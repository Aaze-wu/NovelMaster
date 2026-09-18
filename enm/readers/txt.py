"""纯文本（TXT）阅读器，自动检测编码并启发式分章。"""

from pathlib import Path

import chardet

from ..logger import logger
from .base import BaseReader, auto_title


class TxtReader(BaseReader):
    """TXT 阅读器：按行启发式识别章节标题"""

    # 形如 “第 12 章 …” / “第十二节 …” / “Chapter 3 …” 的行视为章节标题
    TITLE_PREFIXES = ('Chapter', 'CHAPTER', 'chapter')

    def __init__(self, file_path):
        super().__init__(file_path)
        self.content = ""
        self.load_content()
        self.split_chapters()
        # 纯文本没有元数据，用文件名充当书名
        self._set_book_info(Path(self.file_path).stem)
    
    @classmethod
    def is_chapter_title(cls, line):
        """判断一行是否像章节标题"""
        if not line or len(line) > 60:
            return False
        if line.startswith(cls.TITLE_PREFIXES):
            return True
        return line.startswith('第') and ('章' in line or '节' in line)
    
    def detect_encoding(self):
        """检测文件编码"""
        try:
            with open(self.file_path, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                return result['encoding'] or 'utf-8'
        except Exception as e:
            logger.log(f"检测编码失败: {e}", "ERROR")
            return 'utf-8'
    
    def load_content(self):
        """加载TXT文件内容"""
        try:
            encoding = self.detect_encoding()
            with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
                self.content = f.read()
            return True
        except Exception as e:
            logger.log(f"加载TXT文件失败: {e}", "ERROR")
            return False
    
    def split_chapters(self):
        """分割章节（标题行由 <h3> 显示，不再重复写进正文）"""
        current_chapter = []
        chapter_title = None

        for raw_line in self.content.split('\n'):
            line = raw_line.strip()
            if not line:
                continue

            if self.is_chapter_title(line):
                if current_chapter:
                    self._add_text_chapter(
                        chapter_title, '\n'.join(current_chapter),
                        auto_title("book.prologue", default='序章'))
                    current_chapter = []
                chapter_title = line
                continue

            current_chapter.append(line)

        # 添加最后一章
        if current_chapter:
            if chapter_title is None:
                fallback = auto_title("book.full_text", default='全文')
            else:
                fallback = auto_title("book.prologue", default='序章')
            self._add_text_chapter(chapter_title, '\n'.join(current_chapter), fallback)

        # 如果没有检测到章节，将整个内容作为一章
        if not self.chapters:
            self._add_text_chapter(None, self.content,
                                   auto_title("book.full_text", default='全文'))

