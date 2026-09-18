"""DOCX（Word 文档）阅读器，依赖 python-docx（懒加载）。"""

from .base import (BaseReader, ReaderError, auto_title, escape_html,
                   is_docx_heading,
                   local_name)
from .images import MAX_IMAGE_BYTES, guess_mime, to_data_uri


class DocxReader(BaseReader):
    """DOCX (Word) 阅读器，依赖 python-docx"""

    def __init__(self, file_path):
        super().__init__(file_path)
        self._image_cache = {}
        self.load()

    def load(self):
        try:
            import docx
        except ImportError as e:
            raise ReaderError("读取 DOCX 需要 python-docx 库，请先执行: pip install python-docx") from e

        try:
            document = docx.Document(self.file_path)
        except Exception as e:
            raise ReaderError(f"无法打开 DOCX 文件: {e}") from e

        properties = getattr(document, 'core_properties', None)
        if properties is not None:
            self._set_book_info(getattr(properties, 'title', ''),
                                getattr(properties, 'author', ''))

        paragraphs = list(document.paragraphs)
        heading_indices = [i for i, para in enumerate(paragraphs) if is_docx_heading(para)]

        if not heading_indices:
            self._add_chapter(None, self._paragraphs_to_html(paragraphs),
                              auto_title("book.full_text", default='全文'))
        else:
            if heading_indices[0] > 0:
                self._add_chapter(auto_title("book.preface", default='前言'),
                                  self._paragraphs_to_html(paragraphs[:heading_indices[0]]))

            for position, start in enumerate(heading_indices):
                end = heading_indices[position + 1] if position + 1 < len(heading_indices) \
                    else len(paragraphs)
                title = paragraphs[start].text.strip()
                content = self._paragraphs_to_html(paragraphs[start + 1:end])
                self._add_chapter(title, content,
                                  auto_title("book.chapter_n", count=position + 1))

        tables_html = self._tables_to_html(document)
        if tables_html:
            self._append_html(tables_html)

        self._finish()

    # ---------------- 内部实现 ----------------

    def _paragraphs_to_html(self, paragraphs):
        """把段落列表渲染为 HTML（标题样式渲染为 h3，内嵌图片内联为 data URI）"""
        blocks = []
        for paragraph in paragraphs:
            html = self._paragraph_to_html(paragraph)
            if html:
                blocks.append(html)
        return ''.join(blocks)

    def _paragraph_to_html(self, paragraph):
        """渲染单个段落，保留文本与图片的先后顺序"""
        text = (paragraph.text or '').strip()
        if is_docx_heading(paragraph):
            return f"<h3>{escape_html(text)}</h3>" if text else ""

        inner = self._paragraph_inner_html(paragraph)
        if not inner:
            return ''
        return f"<p>{inner}</p>"

    def _paragraph_inner_html(self, paragraph):
        """按文档顺序拼接段落内的文本与图片"""
        try:
            nodes = list(paragraph._p.iter())
        except Exception:
            return escape_html((paragraph.text or '').strip())

        pieces = []
        for node in nodes:
            name = local_name(getattr(node, 'tag', ''))
            if name == 't':
                pieces.append(escape_html(node.text or ''))
            elif name == 'tab':
                pieces.append('&emsp;')
            elif name == 'br':
                pieces.append('<br/>')
            elif name in ('blip', 'imagedata'):
                uri = self._image_uri(node, paragraph)
                if uri:
                    pieces.append(f'<img src="{uri}" />')

        return ''.join(pieces).strip()

    def _image_uri(self, node, paragraph):
        """把 ``a:blip`` / ``v:imagedata`` 引用的图片转成 data URI"""
        relation_id = self._relation_id(node)
        if not relation_id:
            return ''

        if relation_id in self._image_cache:
            return self._image_cache[relation_id]

        uri = ''
        part = getattr(paragraph, 'part', None)
        related = getattr(part, 'related_parts', None) or {}
        image_part = related.get(relation_id)
        if image_part is not None:
            try:
                blob = image_part.blob
            except Exception:
                blob = b''
            if blob and len(blob) <= MAX_IMAGE_BYTES:
                mime = getattr(image_part, 'content_type', '') or guess_mime(data=blob)
                uri = to_data_uri(blob, mime)

        self._image_cache[relation_id] = uri
        return uri

    @staticmethod
    def _relation_id(node):
        """读取节点上的图片关系 ID（兼容 r:embed / r:id 两种写法）"""
        try:
            from docx.oxml.ns import qn
            attributes = (qn('r:embed'), qn('r:id'))
        except Exception:
            attributes = ()

        for attribute in attributes + ('r:embed', 'r:id'):
            value = node.get(attribute)
            if value:
                return value
        return ''

    def _tables_to_html(self, document):
        """把文档中的表格渲染为 HTML 表格"""
        blocks = []
        for table in getattr(document, 'tables', []) or []:
            rows = []
            for row in table.rows:
                cells = [self._cell_html(cell) for cell in row.cells]
                rows.append('<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>')
            if rows:
                blocks.append('<table border="1" cellspacing="0" cellpadding="4">'
                              + ''.join(rows) + '</table>')
        return ''.join(blocks)

    def _cell_html(self, cell):
        """渲染表格单元格（文本 + 内嵌图片）"""
        pieces = []
        for paragraph in getattr(cell, 'paragraphs', []) or []:
            inner = self._paragraph_inner_html(paragraph)
            if inner:
                pieces.append(inner)
        if pieces:
            return '<br/>'.join(pieces)
        return escape_html((cell.text or '').strip())
