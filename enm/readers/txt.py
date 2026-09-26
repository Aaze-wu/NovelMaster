"""纯文本（TXT）阅读器，自动检测编码并启发式分章。"""

from pathlib import Path

import chardet

from ..logger import logger
from .base import BaseReader, auto_title


class TxtReader(BaseReader):
    """TXT 阅读器：按行启发式识别章节标题"""

    # 形如 “第 12 章 …” / “第十二节 …” / “Chapter 3 …” 的行视为章节标题
    TITLE_PREFIXES = ('Chapter', 'CHAPTER', 'chapter')

    # 第一个标题行之前的内容短于这个长度时，当作站点广告 / 页眉之类的噪声，
    # 并进后面那一章；更长才单独留作序章（免得把真正的序文并进第一章）
    PROLOGUE_MIN_CHARS = 200

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
        """分割章节（标题行由 <h3> 显示，不再重复写进正文）

        第一个标题行**之前**的内容不再单独切成「序章」：不少书（尤其是按
        章节抓成一个个 txt 的站点合集）每个文件开头都有一行站点广告 / 页眉，
        它在真标题之前，以前会被切成一个只含广告的「序章」，于是每个文件都
        凭空多出一章。现在短于 :data:`PROLOGUE_MIN_CHARS` 就直接并进后面那
        一章，只有内容足够长（真正的序文）时才保留为独立的序章。
        """
        blocks = []                 # [(标题, [正文行…]), …]
        pending = []                # 第一个标题行之前的内容
        chapter_title = None
        current_chapter = []

        for raw_line in self.content.split('\n'):
            line = raw_line.strip()
            if not line:
                continue

            if not self.is_chapter_title(line):
                if chapter_title is None:
                    pending.append(line)
                else:
                    current_chapter.append(line)
                continue

            if chapter_title is not None:
                blocks.append((chapter_title, current_chapter))
            chapter_title = line
            current_chapter = []

        if chapter_title is None:
            # 通篇没有可识别的标题：整篇当一章
            self._add_text_chapter(None, '\n'.join(pending) or self.content,
                                   auto_title("book.full_text", default='全文'))
        else:
            blocks.append((chapter_title, current_chapter))

            # 标题之前的内容：短的并进第一章，长的留作序章
            if pending:
                if len('\n'.join(pending)) < self.PROLOGUE_MIN_CHARS:
                    blocks[0] = (blocks[0][0], pending + blocks[0][1])
                else:
                    blocks.insert(0, (None, list(pending)))

            for title, lines in blocks:
                fallback = (auto_title("book.prologue", default='序章')
                            if title is None else None)
                self._add_text_chapter(title, '\n'.join(lines), fallback)

        # 如果没有检测到章节，将整个内容作为一章
        if not self.chapters:
            self._add_text_chapter(None, self.content,
                                   auto_title("book.full_text", default='全文'))

