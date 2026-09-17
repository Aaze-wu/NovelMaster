"""UMD（手机电子书）阅读器 —— 纯标准库实现。

文件格式参考：
    - 0x23 功能块 / 0x24 数据块
    - PalmDOC 风格的分块存储 + zlib 压缩
"""

import struct
import zlib
from pathlib import Path

from .base import BaseReader, ReaderError
from .images import (MAX_IMAGE_BYTES, guess_mime, looks_like_image,
                     to_data_uri)


class UmdReader(BaseReader):
    """UMD (掌上书院) 阅读器，纯 Python 实现，不依赖第三方库

    文件结构（参考公开的 UMD 格式说明与 linpinger/golib 的 UMDReader 实现）：
      - 文件魔数: 89 9B 9A DE
      - 循环读取块:
          * '#(0x23)' 功能块: 长度在块头第 5 字节（含 5 字节块头）
          * '$(0x24)' 数据块: ID(4, LE) + 长度(4, LE, 含 9 字节块头) + 数据
      - 正文数据块为 zlib 压缩；章节偏移表 / 章节标题表为原始数据
    """

    MAGIC = b'\x89\x9b\x9a\xde'
    FUNC_FILE_HEADER = 1
    FUNC_BOOK_NAME = 2
    FUNC_AUTHOR = 3
    FUNC_YEAR = 4
    FUNC_MONTH = 5
    FUNC_DAY = 6
    FUNC_PUBLISHER = 8
    FUNC_CONTENT_LEN = 11
    FUNC_CONTENT_BLOCKS = 129
    FUNC_COVER = 130
    FUNC_CHAPTER_OFFSETS = 131
    FUNC_CHAPTER_TITLES = 132

    def __init__(self, file_path):
        super().__init__(file_path)
        self.publisher = ""
        self.publish_date = ""
        self.cover_bytes = None
        self.load()

    def load(self):
        raw = Path(self.file_path).read_bytes()
        if len(raw) < 20 or not raw.startswith(self.MAGIC):
            raise ReaderError("不是有效的 UMD 文件（文件魔数不匹配）")

        functions, blocks, order = self._parse_blocks(raw)

        if functions.get(self.FUNC_FILE_HEADER, b'\x01')[:1] != b'\x01':
            raise ReaderError("该 UMD 文件是漫画/图片类型，暂不支持阅读")

        self._set_book_info(self._decode_utf16(functions.get(self.FUNC_BOOK_NAME)),
                            self._decode_utf16(functions.get(self.FUNC_AUTHOR)))
        self.publisher = self._decode_utf16(functions.get(self.FUNC_PUBLISHER))

        year = self._decode_utf16(functions.get(self.FUNC_YEAR))
        month = self._decode_utf16(functions.get(self.FUNC_MONTH))
        day = self._decode_utf16(functions.get(self.FUNC_DAY))
        self.publish_date = '-'.join(part for part in (year, month, day) if part)

        content_length = self._read_u32(functions.get(self.FUNC_CONTENT_LEN))
        content_block_id = self._read_u32(functions.get(self.FUNC_CONTENT_BLOCKS))
        chapter_offset_id = self._read_u32(functions.get(self.FUNC_CHAPTER_OFFSETS))
        chapter_title_id = self._read_u32(functions.get(self.FUNC_CHAPTER_TITLES))

        cover_bytes, cover_id = self._read_cover(functions, blocks)
        self.cover_bytes = cover_bytes

        content_block_ids = self._u32_list(self._block_data(blocks, content_block_id))
        if not content_block_ids:
            excluded = {block_id for block_id in
                        (content_block_id, chapter_offset_id, chapter_title_id, cover_id)
                        if block_id is not None}
            content_block_ids = [block_id for block_id in order if block_id not in excluded]

        content = self._assemble_content(blocks, order, content_block_ids, content_length)

        titles = self._parse_titles(self._block_data(blocks, chapter_title_id))
        offsets = self._u32_list(self._block_data(blocks, chapter_offset_id))

        self._add_cover_chapter()

        if not offsets:
            self._add_text_chapter(titles[0] if titles else None,
                                   self._decode_utf16(content), '全文')
        else:
            count = min(len(offsets), len(titles) if titles else len(offsets))
            for i in range(count):
                start = offsets[i]
                end = offsets[i + 1] if i + 1 < len(offsets) else len(content)
                if end <= start:
                    continue
                text = self._decode_utf16(content[start:end])
                self._add_text_chapter(titles[i] if i < len(titles) else None, text,
                                       f'第{i + 1}章')

        self._finish()

    def get_cover_bytes(self):
        """返回封面图片的原始字节（如果没有封面则返回 None）"""
        return self.cover_bytes

    def _add_cover_chapter(self):
        """把内嵌封面显示为第一章（文字类 UMD 的图片支持）"""
        data = self.cover_bytes
        if not data or len(data) > MAX_IMAGE_BYTES:
            return
        if not looks_like_image(data):
            return

        uri = to_data_uri(data, guess_mime('', data[:64], 'image/jpeg'))
        if uri:
            self._add_chapter('封面', f'<p><img src="{uri}" /></p>')

    # ---------------- 内部实现 ----------------

    def _parse_blocks(self, raw):
        """遍历文件，分离功能块与数据块"""
        functions = {}
        blocks = {}
        order = []
        offset = len(self.MAGIC)
        total = len(raw)

        while offset + 9 <= total:
            marker = raw[offset]

            if marker == 0x23:                      # 功能块
                func_id = raw[offset + 1]
                func_len = raw[offset + 4]
                if func_len < 5 or offset + func_len > total:
                    break
                functions[func_id] = raw[offset + 5:offset + func_len]
                offset += func_len

            elif marker == 0x24:                    # 数据块
                data_id = struct.unpack_from('<I', raw, offset + 1)[0]
                data_len = struct.unpack_from('<I', raw, offset + 5)[0]
                if data_len < 9 or offset + data_len > total:
                    break
                blocks[data_id] = raw[offset + 9:offset + data_len]
                order.append(data_id)
                offset += data_len

            else:                                   # 未知块，停止解析
                break

        if not blocks and not functions:
            raise ReaderError("UMD 文件结构损坏，未解析到任何数据块")

        return functions, blocks, order

    def _inflate(self, data):
        """解压数据块（UMD 正文使用 zlib 压缩）"""
        if not data:
            return b""
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                return zlib.decompress(data, -15)   # 无 zlib 头的 raw deflate
            except zlib.error:
                return data

    def _block_data(self, blocks, block_id):
        """读取索引类数据块；少数文件会把索引块也压缩，这里做兼容"""
        if block_id is None:
            return b""
        data = blocks.get(block_id)
        if not data:
            return b""
        if data[:1] == b'\x78':
            return self._inflate(data)
        return data

    def _assemble_content(self, blocks, order, content_block_ids, content_length):
        """按数据块在文件中的出现顺序拼接正文"""
        wanted = {}
        for block_id in content_block_ids:
            wanted[block_id] = wanted.get(block_id, 0) + 1

        buffer = bytearray()
        for data_id in order:
            times = wanted.get(data_id, 0)
            if not times:
                continue
            chunk = self._inflate(blocks.get(data_id, b''))
            for _ in range(times):
                buffer.extend(chunk)

        # UMD 使用 U+2029 (0x29 0x20) 作为段落分隔符，统一替换为换行
        content = bytes(buffer).replace(b'\x29\x20', b'\x0a\x00')
        if content_length and len(content) > content_length:
            content = content[:content_length]
        return content

    def _parse_titles(self, data):
        """章节标题表：[1 字节长度][UTF-16LE 标题]，重复直到结束"""
        titles = []
        position = 0
        total = len(data)

        while position < total:
            length = data[position]
            position += 1
            if length == 0:
                continue
            if position + length > total:
                break
            title = self._decode_utf16(data[position:position + length])
            position += length
            titles.append(title or f'第{len(titles) + 1}章')

        return titles

    def _read_cover(self, functions, blocks):
        """读取封面：功能块 0x82，内容首字节 1 表示 JPEG"""
        payload = functions.get(self.FUNC_COVER)
        if not payload or len(payload) < 5 or payload[0] != 1:
            return None, None

        cover_id = struct.unpack_from('<I', payload, 1)[0]
        return blocks.get(cover_id), cover_id

    def _u32_list(self, data):
        """把字节串解析为 little-endian uint32 数组"""
        if not data or len(data) < 4:
            return []
        count = len(data) // 4
        return list(struct.unpack_from(f'<{count}I', data, 0))

    def _read_u32(self, data):
        """读取 little-endian uint32（不足 4 字节返回 None）"""
        if not data or len(data) < 4:
            return None
        return struct.unpack_from('<I', data, 0)[0]

    def _decode_utf16(self, data):
        """解码 UTF-16LE 字符串并清理结尾的 NUL"""
        if not data:
            return ""
        text = data.decode('utf-16-le', errors='replace')
        return text.replace('\x00', '').strip()
