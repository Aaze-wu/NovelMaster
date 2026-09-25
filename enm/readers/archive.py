"""ZIP / JAR 压缩包阅读器，以及 JAR / JAD 手机电子书入口。

* :class:`ArchiveReader` / :class:`ZipReader` —— 通用压缩包：自动挑选包内最合适
  的电子书再委托给对应阅读器；
* :class:`JarReader` —— ``.jar``：优先按手机 Java 电子书解析（正文是一批纯数字
  名条目，见 :mod:`enm.readers.jarbook`），识别不出来才退回压缩包逻辑；
* :class:`JadReader` —— ``.jad``：只是 MIDlet 描述文件，按它定位正文所在的 JAR。
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

from ..logger import logger
from .base import BaseReader, ReaderError, decode_bytes
from .jarbook import JarBookReader, parse_properties


def _create_reader(file_path):
    """延迟导入工厂函数，避免与 factory 模块形成循环依赖。"""
    from .factory import create_reader
    return create_reader(file_path)


class ArchiveReader(BaseReader):
    """ZIP / JAR 压缩包阅读器

    自动在压缩包内挑选最合适的电子书文件（EPUB / FB2 / DOCX / PDF 优先，
    其次选择体积最大的 TXT / HTML），解压到临时目录后交给对应的阅读器处理。
    手机 Java 电子书（``.jar``）由 :class:`JarReader` 另行处理，不会走到这里。
    """

    STRONG_FORMATS = ('.epub', '.fb2', '.docx', '.pdf')
    WEAK_FORMATS = ('.txt', '.html', '.htm', '.xhtml')
    MIN_INNER_SIZE = 512
    # 解压保护：避免恶意 / 异常的压缩包占满磁盘
    MAX_TOTAL_SIZE = 512 * 1024 * 1024
    MAX_ENTRIES = 20000

    def __init__(self, file_path):
        super().__init__(file_path)
        self._temp_dir = None
        self.load()

    def load(self):
        try:
            archive = zipfile.ZipFile(self.file_path)
        except (zipfile.BadZipFile, OSError) as e:
            raise ReaderError(f"无法打开压缩包（仅支持 ZIP/JAR）: {e}") from e

        with archive:
            candidates = self._collect_candidates(archive)
            if not candidates:
                raise ReaderError("压缩包中没有找到可阅读的内容"
                                  "（支持内部包含 EPUB/TXT/HTML/FB2/DOCX/PDF）")

            inner_name = candidates[0]
            jar_title = self._read_jar_title(archive)

            temp_dir = Path(tempfile.mkdtemp(prefix='enm_archive_'))
            self._temp_dir = str(temp_dir)
            try:
                # 完整解压包内结构，使内部 HTML 的相对图片引用可以解析
                self._extract_all(archive, temp_dir)
            except Exception as e:
                self.close()
                raise ReaderError(f"读取压缩包内容失败: {e}") from e

            target = temp_dir / inner_name
            if not target.is_file():
                target = self._find_extracted(temp_dir, inner_name)
            if target is None:
                self.close()
                raise ReaderError("压缩包内容解压失败，无法读取内部电子书")

        try:
            inner_reader = _create_reader(str(target))
        except Exception:
            self.close()
            raise

        self.chapters = list(inner_reader.chapters)
        self._set_book_info(
            jar_title or getattr(inner_reader, 'book_title', ''),
            getattr(inner_reader, 'book_author', ''))
        self._finish()

    # ---------------- 内部实现 ----------------

    @staticmethod
    def _safe_member_name(name):
        """把压缩包内条目名规整成安全的相对路径；可疑条目返回空串"""
        text = (name or '').replace('\\', '/')
        if not text or text.endswith('/'):
            return ''
        if text.startswith('/') or re.match(r'^[A-Za-z]:', text):
            return ''

        parts = []
        for part in text.split('/'):
            if part in ('', '.'):
                continue
            if part == '..':                # 拒绝目录穿越
                return ''
            parts.append(part)
        return '/'.join(parts)

    def _extract_all(self, archive, temp_dir):
        """把压缩包内所有文件解压到临时目录（保留相对结构）"""
        total = 0
        count = 0

        for info in archive.infolist():
            if info.is_dir():
                continue
            name = self._safe_member_name(info.filename)
            if not name:
                continue
            if count >= self.MAX_ENTRIES or total + info.file_size > self.MAX_TOTAL_SIZE:
                break

            target = temp_dir / name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, 'wb') as destination:
                    shutil.copyfileobj(source, destination)
            except OSError:
                continue

            total += info.file_size
            count += 1

    @staticmethod
    def _find_extracted(temp_dir, inner_name):
        """按文件名回查解压结果（防止个别文件名被规整后不一致）"""
        basename = Path(inner_name).name.lower()
        for path in temp_dir.rglob('*'):
            if path.is_file() and path.name.lower() == basename:
                return path
        return None

    def _collect_candidates(self, archive):
        """收集压缩包内可作为电子书的文件，按优先级排序"""
        strong = []
        weak = []

        for info in archive.infolist():
            if info.is_dir():
                continue

            name = self._safe_member_name(info.filename)
            if not name:
                continue

            lower = name.lower()

            if lower.startswith('meta-inf/') or '/meta-inf/' in lower:
                continue
            if lower.startswith('__macosx/') or '/__macosx/' in lower:
                continue
            if info.file_size < self.MIN_INNER_SIZE:
                continue

            extension = Path(lower).suffix
            if extension in self.STRONG_FORMATS:
                strong.append((self.STRONG_FORMATS.index(extension),
                               -info.file_size, name))
            elif extension in self.WEAK_FORMATS:
                weak.append((-info.file_size, name))

        strong.sort()
        weak.sort()
        return [name for _, _, name in strong] + [name for _, name in weak]

    def _read_jar_title(self, archive):
        """从 JAR 清单中读取电子书标题"""
        for name in ('META-INF/MANIFEST.MF', 'META-INF/manifest.mf'):
            try:
                content = archive.read(name)
            except KeyError:
                continue
            except Exception:
                return ""

            text = content.decode('utf-8', errors='replace')
            for line in text.splitlines():
                if ':' not in line:
                    continue
                key, _, value = line.partition(':')
                if key.strip().lower() in ('midlet-name', 'implementation-title',
                                           'bundle-name'):
                    value = value.strip()
                    if value:
                        return value
        return ""


class ZipReader(ArchiveReader):
    """ZIP 压缩包阅读器"""


class JarReader(ArchiveReader):
    """JAR 阅读器：优先手机 Java 电子书，其次压缩包

    手机 Java 电子书（JavaBook / 杰奇 CMS）把正文切成一堆**纯数字名**的条目塞进
    JAR，章节表在目录条目 ``0`` 里，按扩展名挑文件的话一条正文也找不到。所以先让
    :class:`~enm.readers.jarbook.JarBookReader` 试解析，成功就用它；识别不出来再
    退回压缩包逻辑（包内装着 EPUB / TXT 的 ``.jar`` 照样能读）。
    """

    def load(self):
        if JarBookReader.detect(self.file_path):
            try:
                book = JarBookReader(self.file_path)
            except ReaderError as e:
                logger.log(f"按手机电子书解析 JAR 失败，改按压缩包处理: {e}", "ERROR")
            else:
                if book.get_chapter_count():
                    self.chapters = book.chapters
                    self._set_book_info(book.book_title, book.book_author)
                    self._finish()
                    return

        super().load()


class JadReader(BaseReader):
    """JAD（MIDlet 描述文件）阅读器

    ``.jad`` 本身没有正文，只是 Java ME 应用的描述文件，里面用
    ``MIDlet-Jar-URL`` 指明正文所在的 JAR。这里按它定位同目录的 JAR，再交给
    对应的阅读器；窗口标题、最近文件记录仍沿用用户打开的 ``.jad``。
    """

    def __init__(self, file_path):
        super().__init__(file_path)
        self.jar_path = ""
        self._inner_reader = None
        self.load()

    def load(self):
        try:
            raw = Path(self.file_path).read_bytes()
        except OSError as e:
            raise ReaderError(f"无法读取 JAD 文件: {e}") from e

        properties = parse_properties(decode_bytes(raw))
        target = self._resolve_jar(properties.get('midlet-jar-url', ''))

        try:
            inner_reader = _create_reader(str(target))
        except Exception:
            self.close()
            raise

        self._inner_reader = inner_reader
        self.jar_path = str(target)
        self.chapters = list(inner_reader.chapters)
        self._set_book_info(
            properties.get('midlet-name') or getattr(inner_reader, 'book_title', ''),
            getattr(inner_reader, 'book_author', ''))
        self._finish()

    def close(self):
        super().close()
        if self._inner_reader is not None:
            try:
                self._inner_reader.close()
            except Exception as e:
                logger.log(f"释放阅读器失败: {e}", "ERROR")
            self._inner_reader = None

    def _resolve_jar(self, url):
        """把 ``MIDlet-Jar-URL`` 解析成实际存在的 JAR 路径

        描述文件里的名字常常还是下载站的原始文件名（例如 ``2441.jar``），而本地
        文件早被改成了书名，所以按 URL 找不到时，再按「同名 .jar」找一次
        （``X.jad`` 配 ``X.jar``，这是最常见的存放方式）。
        """
        value = (url or '').strip()
        if '://' in value:
            raise ReaderError(f"JAD 指向的是网络地址，无法离线阅读:\n{value}\n\n"
                              "请改开同目录的 JAR 文件。")

        jad_path = Path(self.file_path)
        folder = jad_path.parent

        if value:
            wanted = unquote(value).replace('\\', '/')
            for candidate in (folder / wanted, folder / Path(wanted).name):
                if candidate.is_file():
                    return candidate

        stem = jad_path.stem.lower()
        for sibling in sorted(folder.glob('*')):
            if (sibling.is_file() and sibling.suffix.lower() == '.jar'
                    and sibling.stem.lower() == stem):
                return sibling

        hint = f"（MIDlet-Jar-URL: {value}）" if value else "（描述文件里没有 MIDlet-Jar-URL）"
        raise ReaderError(f"找不到 JAD 对应的 JAR 文件 {hint}\n"
                          f"请把 {jad_path.stem}.jar 放在与 {jad_path.name} "
                          "同一个目录下，或直接打开 JAR 文件。")
