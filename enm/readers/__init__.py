"""阅读器实现、格式注册表与工厂。

所有阅读器都继承 :class:`BaseReader`，遵循同一套接口::

    get_chapter_count() -> int
    get_chapter_title(index) -> str
    get_chapter_content(index) -> str          # HTML 片段
    get_book_info() -> {'title': str, 'author': str}
    close()                                    # 释放临时资源
    current_chapter: int
"""

from .base import BaseReader, ReaderError, format_chapter_html
from .factory import (EXTENSION_READERS, FORMAT_GROUPS, SUPPORTED_EXTENSIONS,
                      build_open_file_filter, create_reader, get_reader_class,
                      supported_extensions_text)
from .folder import FolderReader

__all__ = ["BaseReader", "ReaderError", "format_chapter_html",
           "EXTENSION_READERS", "FORMAT_GROUPS", "SUPPORTED_EXTENSIONS",
           "build_open_file_filter", "create_reader", "get_reader_class",
           "supported_extensions_text", "FolderReader"]
