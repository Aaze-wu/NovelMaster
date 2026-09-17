"""ZIP / JAR 压缩包阅读器：自动挑选包内最合适的电子书再委托给对应阅读器。"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .base import BaseReader, ReaderError


def _create_reader(file_path):
    """延迟导入工厂函数，避免与 factory 模块形成循环依赖。"""
    from .factory import create_reader
    return create_reader(file_path)


class ArchiveReader(BaseReader):
    """ZIP / JAR 压缩包阅读器

    自动在压缩包内挑选最合适的电子书文件（EPUB / FB2 / DOCX / PDF 优先，
    其次选择体积最大的 TXT / HTML），解压到临时目录后交给对应的阅读器处理。
    手机 Java 电子书（.jar）通常就是内含单个 TXT/HTML 的压缩包。
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
    """JAR（手机 Java 电子书）阅读器"""
