"""PDF 阅读器，依赖 pypdf（懒加载）。"""

from .base import BaseReader, ReaderError


class PdfReader(BaseReader):
    """PDF 阅读器，依赖 pypdf；优先使用 PDF 书签生成章节"""

    PAGES_PER_CHAPTER = 10

    def __init__(self, file_path):
        super().__init__(file_path)
        self.load()

    def load(self):
        try:
            from pypdf import PdfReader as PypdfReader
        except ImportError as e:
            raise ReaderError("读取 PDF 需要 pypdf 库，请先执行: pip install pypdf") from e

        try:
            pdf = PypdfReader(self.file_path)
        except Exception as e:
            raise ReaderError(f"无法打开 PDF 文件: {e}") from e

        metadata = getattr(pdf, 'metadata', None)
        if metadata is not None:
            self._set_book_info(str(metadata.get('/Title') or ''),
                                str(metadata.get('/Author') or ''))

        try:
            page_texts = [(page.extract_text() or '') for page in pdf.pages]
        except Exception as e:
            raise ReaderError(f"PDF 文本提取失败（可能是扫描版或加密文档）: {e}") from e

        page_count = len(page_texts)
        if page_count == 0:
            raise ReaderError("PDF 文件中没有任何页面")

        outline = self._outline_ranges(pdf, page_count)
        if outline:
            for title, start, end in outline:
                self._add_text_chapter(title, '\n'.join(page_texts[start:end]),
                                       f'第 {start + 1} 页')
        else:
            step = self.PAGES_PER_CHAPTER
            for start in range(0, page_count, step):
                end = min(start + step, page_count)
                if end - start == 1:
                    title = f"第 {start + 1} 页"
                else:
                    title = f"第 {start + 1} - {end} 页"
                self._add_text_chapter(title, '\n'.join(page_texts[start:end]))

        self._finish()

    # ---------------- 内部实现 ----------------

    def _outline_ranges(self, pdf, page_count):
        """根据 PDF 书签计算章节页码范围，返回 [(标题, 起始页, 结束页), ...]"""
        try:
            outline = pdf.outline
        except Exception:
            return []
        if not outline:
            return []

        entries = []
        pending = [outline]
        while pending:
            node = pending.pop(0)
            if not isinstance(node, list):
                continue
            for item in node:
                if isinstance(item, list):
                    pending.append(item)
                    continue
                try:
                    page_number = pdf.get_destination_page_number(item)
                except Exception:
                    page_number = None
                if page_number is None or not 0 <= page_number < page_count:
                    continue
                title = (getattr(item, 'title', '') or '').strip()
                entries.append((page_number, title))

        if len(entries) < 2:
            return []

        entries.sort(key=lambda entry: entry[0])
        unique = []
        seen = set()
        for page_number, title in entries:
            if page_number in seen:
                continue
            seen.add(page_number)
            unique.append((page_number, title))

        ranges = []
        if unique[0][0] > 0:
            ranges.append(('封面 / 前言', 0, unique[0][0]))

        for position, (page_number, title) in enumerate(unique):
            end = unique[position + 1][0] if position + 1 < len(unique) else page_count
            if end <= page_number:
                continue
            ranges.append((title or f'第 {page_number + 1} 页', page_number, end))

        return ranges
