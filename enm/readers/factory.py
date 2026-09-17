"""格式注册表与阅读器工厂。

新增格式只需：

1. 在 ``readers/`` 下实现一个新的阅读器类（继承 :class:`BaseReader`）；
2. 在本文件的 ``EXTENSION_READERS`` 中登记扩展名。
"""

from pathlib import Path

from ..constants import DEBUG_MODE
from ..logger import logger
from .archive import JarReader, ZipReader
from .base import ReaderError
from .docx import DocxReader
from .epub import EpubReader
from .fb2 import Fb2Reader
from .html import HtmlReader
from .mobi import MobiReader
from .pdf import PdfReader
from .txt import TxtReader
from .umd import UmdReader


# 扩展名 -> 阅读器类
EXTENSION_READERS = {
    '.epub': EpubReader,
    '.txt': TxtReader,
    '.pdf': PdfReader,
    '.mobi': MobiReader,
    '.azw': MobiReader,
    '.azw3': MobiReader,
    '.prc': MobiReader,
    '.docx': DocxReader,
    '.fb2': Fb2Reader,
    '.umd': UmdReader,
    '.html': HtmlReader,
    '.htm': HtmlReader,
    '.xhtml': HtmlReader,
    '.jar': JarReader,
    '.zip': ZipReader,
}

# 全部受支持的扩展名
SUPPORTED_EXTENSIONS = frozenset(EXTENSION_READERS)


def get_reader_class(extension):
    """按扩展名（可带点、大小写不限）获取阅读器类，未登记时返回 None"""
    if not extension:
        return None
    if not extension.startswith('.'):
        extension = '.' + extension
    return EXTENSION_READERS.get(extension.lower())


# 文件对话框中的分组过滤器
FORMAT_GROUPS = (
    ("电子书文件", ('.epub', '.mobi', '.azw', '.azw3', '.prc', '.umd', '.fb2')),
    ("文档文件", ('.pdf', '.docx', '.txt', '.html', '.htm', '.xhtml')),
    ("压缩包", ('.jar', '.zip')),
)


def supported_extensions_text():
    """返回可读格式的展示文本，例如 'EPUB、TXT、PDF'"""
    names = []
    for extension in EXTENSION_READERS:
        name = extension.lstrip('.').upper()
        if name not in names:
            names.append(name)
    return '、'.join(names)


def build_open_file_filter():
    """构建 QFileDialog 使用的过滤器字符串"""
    all_patterns = ' '.join(f'*{extension}' for extension in EXTENSION_READERS)
    parts = [f"支持的文件 ({all_patterns})"]
    for group_name, extensions in FORMAT_GROUPS:
        parts.append(f"{group_name} ({' '.join('*' + ext for ext in extensions)})")
    parts.append("所有文件 (*)")
    return ";;".join(parts)


def create_reader(file_path):
    """根据扩展名创建对应的阅读器"""
    extension = Path(file_path).suffix.lower()
    reader_class = EXTENSION_READERS.get(extension)
    if reader_class is None:
        raise ReaderError(f"不支持的文件格式: {extension or '未知'}"
                          f"（支持: {supported_extensions_text()}）")

    if DEBUG_MODE:
        logger.debug(f"创建阅读器: {reader_class.__name__} -> {file_path}")

    return reader_class(str(file_path))
