"""MOBI / AZW / AZW3 / PRC 阅读器。

优先使用可选的 ``mobi`` 库（GPL-3.0，非必需依赖），
未安装时退回到内置的 PalmDB + PalmDOC 解析器。
"""

import importlib.util
import re
import shutil
import struct
from pathlib import Path

from ..logger import logger
from .base import (BaseReader, ReaderError, auto_title, clean_html_content,
                   palmdoc_decompress, split_html_by_headings, strip_tags)
from .images import (MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES, guess_mime,
                     looks_like_image, to_data_uri)

_MOBI_IMG_RE = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
_MOBI_RECINDEX_RE = re.compile(
    r'\b(?:recindex|lorecindex|hirecindex)\s*=\s*["\']?\s*(\d+)', re.IGNORECASE)
_PAGEBREAK_RE = re.compile(r'<mbp:pagebreak[^>]*/?>', re.IGNORECASE)


class MobiReader(BaseReader):
    """MOBI / AZW / AZW3 / PRC 阅读器

    解析策略：
      1. 如果环境中安装了可选的 `mobi` 库（KindleUnpack 分支，GPL-3.0），
         优先使用它，可获得 AZW3/KF8、HUFF/CDIC 压缩以及更完整的排版；
      2. 否则使用内置的 PalmDB + PalmDOC 解析器（纯标准库实现，无额外依赖），
         支持未压缩与 PalmDOC 压缩的 .mobi / .prc / .azw。
    """

    def __init__(self, file_path):
        super().__init__(file_path)
        self._temp_dir = None
        self._image_records = []
        self._fallback_images = []
        self._image_uris = {}
        self._image_budget = MAX_TOTAL_IMAGE_BYTES
        self.load()

    def load(self):
        if self._load_with_mobi_library():
            return

        try:
            self._load_with_builtin_parser()
        except ReaderError as e:
            if importlib.util.find_spec('mobi') is None:
                raise ReaderError(
                    f"{e}\n\n提示：安装可选依赖 `mobi`（pip install mobi）"
                    "可获得 AZW3/KF8、HUFF/CDIC 压缩格式的完整支持。"
                ) from e
            raise

    # ---------------- 可选依赖：mobi 库 ----------------

    def _load_with_mobi_library(self):
        """尝试使用可选的 mobi 库解析（支持 KF8 / HUFF-CDIC）"""
        if importlib.util.find_spec('mobi') is None:
            return False

        try:
            import mobi as mobi_library
        except Exception as e:
            logger.log(f"导入 mobi 库失败，改用内置解析器: {e}", "ERROR")
            return False

        temp_dir = None
        try:
            temp_dir, extracted_path = mobi_library.extract(self.file_path)
            inner_path = Path(extracted_path)
            if not inner_path.exists():
                raise ReaderError("mobi 库未能从文件中提取出内容")

            inner_reader = create_reader(str(inner_path))
            chapters = list(inner_reader.chapters)
            if not chapters:
                raise ReaderError("mobi 库提取的内容为空")

            self.chapters = chapters
            self._set_book_info(getattr(inner_reader, 'book_title', ''),
                                getattr(inner_reader, 'book_author', ''))
            self._temp_dir = temp_dir
            self._finish()
            return True

        except Exception as e:
            logger.log(f"使用 mobi 库解析失败，改用内置解析器: {e}", "ERROR")
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    # ---------------- 内置解析器：PalmDB + PalmDOC ----------------

    def _load_with_builtin_parser(self):
        raw = Path(self.file_path).read_bytes()
        if len(raw) < 90:
            raise ReaderError("文件太小，不是有效的 MOBI 文件")

        record_count = struct.unpack_from('>H', raw, 76)[0]
        offsets = []
        for i in range(record_count):
            position = 78 + i * 8
            if position + 4 > len(raw):
                break
            offsets.append(struct.unpack_from('>I', raw, position)[0])
        offsets.append(len(raw))

        if len(offsets) < 3:
            raise ReaderError("MOBI 文件记录表损坏，无法解析")

        record0 = raw[offsets[0]:offsets[1]]
        if len(record0) < 16:
            raise ReaderError("MOBI 文件头损坏")

        (compression, _unused, text_length,
         text_records, _record_size, encryption) = struct.unpack_from('>HHIHHH', record0, 0)

        if encryption:
            raise ReaderError("该 MOBI 文件受 DRM 保护，无法解析")

        if compression == 1:
            decoder = None
        elif compression == 2:
            decoder = palmdoc_decompress
        else:
            raise ReaderError(f"暂不支持该 MOBI 压缩方式（代码 {compression}）")

        if not text_records:
            text_records = max(0, len(offsets) - 2)

        self._collect_image_records(raw, offsets, text_records)

        buffer = bytearray()
        for i in range(1, min(1 + text_records, len(offsets) - 1)):
            chunk = raw[offsets[i]:offsets[i + 1]]
            buffer.extend(decoder(chunk) if decoder else chunk)

        if not buffer:
            raise ReaderError("MOBI 文件中没有找到正文内容")

        if text_length:
            buffer = buffer[:text_length]

        encoding = self._text_encoding(record0)
        body = self._decode_body(buffer, encoding)
        if self._image_records:
            body = self._inline_mobi_images(body)

        self._read_exth(record0, encoding)
        if not self.book_title:
            self._set_book_info(
                raw[0:32].split(b'\x00')[0].decode('cp1252', errors='replace'))

        self._split_mobi_body(body)
        self._finish()

    def _collect_image_records(self, raw, offsets, text_records):
        """收集正文记录之后的图片记录

        MOBI 正文里的 ``<img recindex="00001">`` 按下标引用正文记录之后的
        图片记录。不同工具生成的文件在是否夹带索引记录上略有差异，因此同时
        记录“全部记录”与“仅图片记录”两套下标。
        """
        records = []
        images = []
        for index in range(text_records + 1, len(offsets) - 1):
            chunk = raw[offsets[index]:offsets[index + 1]]
            records.append(chunk)
            if looks_like_image(chunk):
                images.append(chunk)

        # 部分文件前几条记录为封面缩略图以外的辅助记录，跳过非图片项
        while records and not looks_like_image(records[0]):
            records.pop(0)

        self._image_records = records
        self._fallback_images = images

    def _inline_mobi_images(self, html):
        """把 ``<img recindex="N">`` 替换成内联的 data URI 图片"""
        if not html or '<img' not in html.lower():
            return html

        dropped = 0

        def replace(match):
            nonlocal dropped
            tag = match.group(0)
            for number in _MOBI_RECINDEX_RE.findall(tag):
                uri = self._mobi_image_uri(number)
                if uri:
                    return f'<img src="{uri}" />'
            dropped += 1
            return ''

        result = _MOBI_IMG_RE.sub(replace, html)
        if dropped:
            logger.log(f"MOBI 中有 {dropped} 张图片无法定位，已跳过", "WARN")
        return result

    def _mobi_image_uri(self, number):
        """按下标找到图片记录并转成 data URI"""
        if number in self._image_uris:
            return self._image_uris[number]

        uri = ''
        data = self._image_record(int(number)) if number.isdigit() else None
        if data:
            if len(data) > MAX_IMAGE_BYTES:
                logger.log(f"MOBI 内嵌图片过大已跳过（{len(data)} 字节）", "WARN")
            elif len(data) <= self._image_budget:
                self._image_budget -= len(data)
                uri = to_data_uri(data, guess_mime('', data[:64]))

        self._image_uris[number] = uri
        return uri

    def _image_record(self, index):
        """按 1 起始下标取图片记录（两套下标逐级尝试）"""
        for records in (self._image_records, self._fallback_images):
            if 1 <= index <= len(records):
                candidate = records[index - 1]
                if looks_like_image(candidate):
                    return candidate
        return None

    def _text_encoding(self, record0):
        """根据 MOBI 头判断正文编码（65001 = UTF-8，其余按 cp1252）"""
        if len(record0) >= 32 and record0[16:20] == b'MOBI':
            code = struct.unpack_from('>I', record0, 28)[0]
            return 'utf-8' if code == 65001 else 'cp1252'
        return 'cp1252'

    def _decode_body(self, buffer, encoding):
        """解码正文；对声明为 cp1252 但实际是 UTF-8 的文件做兼容"""
        if encoding == 'cp1252':
            try:
                candidate = buffer.decode('utf-8')
                if any(ord(char) > 127 for char in candidate):
                    return candidate
            except UnicodeDecodeError:
                pass
        return buffer.decode(encoding, errors='replace')

    def _read_exth(self, record0, encoding):
        """读取 EXTH 元数据（书名 / 作者）"""
        if len(record0) < 16 + 0x74 or record0[16:20] != b'MOBI':
            return

        exth_flags = struct.unpack_from('>I', record0, 16 + 0x70)[0]
        if not exth_flags & 0x40:
            return

        mobi_length = struct.unpack_from('>I', record0, 20)[0]
        start = 16 + mobi_length
        if record0[start:start + 4] != b'EXTH':
            start = record0.find(b'EXTH', start, start + 32)
            if start < 0:
                return

        record_total = struct.unpack_from('>I', record0, start + 8)[0]
        position = start + 12

        for _ in range(record_total):
            if position + 8 > len(record0):
                break
            record_type, record_length = struct.unpack_from('>II', record0, position)
            if record_length < 8 or position + record_length > len(record0):
                break
            value = record0[position + 8:position + record_length].decode(encoding,
                                                                         errors='replace')
            value = value.strip()
            if record_type == 100:
                self._set_book_info(author=value)
            elif record_type in (503, 501):
                self._set_book_info(title=value)
            position += record_length

    def _split_mobi_body(self, body):
        """把 MOBI 正文 HTML 切分为章节"""
        fragments = [fragment for fragment in _PAGEBREAK_RE.split(body)
                     if strip_tags(fragment)]

        if len(fragments) > 1:
            for i, fragment in enumerate(fragments):
                html = clean_html_content(fragment)
                sub_chapters = split_html_by_headings(html)
                fallback = auto_title("book.section_n", count=i + 1)
                if sub_chapters:
                    for title, piece in sub_chapters:
                        self._add_chapter(title, piece, fallback)
                else:
                    self._add_chapter(None, html, fallback)
            return

        html = clean_html_content(body)
        sub_chapters = split_html_by_headings(html)
        if sub_chapters:
            for title, piece in sub_chapters:
                self._add_chapter(title, piece,
                                  auto_title("book.body", default='正文'))
        else:
            self._add_chapter(None, html,
                              auto_title("book.full_text", default='全文'))
