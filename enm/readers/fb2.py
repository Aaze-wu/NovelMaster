"""FB2（FictionBook 2）阅读器。"""

import base64
import xml.etree.ElementTree as ET
from pathlib import Path

from .base import (BaseReader, ReaderError, auto_title, decode_bytes, escape_html,
                   local_name, strip_tags, xml_text)
from .images import (MAX_IMAGE_BYTES, guess_mime, looks_like_image,
                     to_data_uri)


class Fb2Reader(BaseReader):
    """FB2 (FictionBook 2.0) 阅读器，基于标准库 xml.etree"""

    def __init__(self, file_path):
        super().__init__(file_path)
        self._binaries = {}
        self._image_cache = {}
        self.load()

    def load(self):
        try:
            root = ET.parse(self.file_path).getroot()
        except ET.ParseError as e:
            # 有些 FB2 使用非 UTF-8 编码，先做一次编码归一化再解析
            try:
                root = ET.fromstring(decode_bytes(Path(self.file_path).read_bytes()))
            except Exception:
                raise ReaderError(f"无法解析 FB2 文件（XML 格式错误）: {e}") from e
        except Exception as e:
            raise ReaderError(f"无法打开 FB2 文件: {e}") from e

        self._binaries = self._collect_binaries(root)
        self._read_description(root)
        self._read_bodies(root)
        self._finish()

    # ---------------- 内部实现 ----------------

    def _collect_binaries(self, root):
        """收集 <binary> 中的内嵌图片（base64）"""
        binaries = {}
        for element in root:
            if local_name(element.tag) != 'binary':
                continue
            binary_id = element.get('id')
            if not binary_id:
                continue
            # base64 正文常被换行包裹，这里去掉所有空白字符
            payload = ''.join((element.text or '').split())
            if payload:
                binaries[binary_id] = (element.get('content-type', '') or '',
                                       payload)
        return binaries

    def _read_description(self, root):
        """读取书名与作者"""
        description = None
        for element in root:
            if local_name(element.tag) == 'description':
                description = element
                break
        if description is None:
            return

        title_info = None
        for element in description.iter():
            if local_name(element.tag) == 'title-info':
                title_info = element
                break
        if title_info is None:
            return

        authors = []
        for child in title_info:
            name = local_name(child.tag)
            if name == 'book-title':
                self._set_book_info(xml_text(child))
            elif name == 'author':
                parts = [xml_text(grand) for grand in child
                         if local_name(grand.tag) in ('first-name', 'middle-name',
                                                      'last-name', 'nickname')]
                parts = [part for part in parts if part]
                if parts:
                    separator = ' ' if all(part.isascii() for part in parts) else ''
                    authors.append(separator.join(parts))

        self._set_book_info(author=', '.join(authors))

    def _read_bodies(self, root):
        """读取正文；跳过脚注 / 注释等附属 body"""
        for body in root:
            if local_name(body.tag) != 'body':
                continue
            if (body.get('name') or '').strip().lower() in ('notes', 'comments'):
                continue

            for child in body:
                name = local_name(child.tag)
                if name == 'section':
                    self._process_section(child)
                else:
                    html = self._render_element(child)
                    if html:
                        self._add_chapter(
                            None, html,
                            auto_title("book.section_n",
                                       count=len(self.chapters) + 1))

    def _process_section(self, section):
        """递归处理 <section>：自身作为一章，子 section 继续展开"""
        title = ""
        pieces = []
        subsections = []

        for child in section:
            name = local_name(child.tag)
            if name == 'section':
                subsections.append(child)
            elif name == 'title':
                title = xml_text(child)
                pieces.append(self._render_element(child))
            else:
                html = self._render_element(child)
                if html:
                    pieces.append(html)

        content = ''.join(pieces)
        if title or strip_tags(content):
            self._add_chapter(
                title, content,
                auto_title("book.section_n", count=len(self.chapters) + 1))

        for subsection in subsections:
            self._process_section(subsection)

    def _render_element(self, element):
        """把 FB2 元素渲染为 HTML 片段"""
        name = local_name(element.tag)
        if not name:
            return ""

        if name == 'title':
            text = xml_text(element)
            return f"<h3>{escape_html(text)}</h3>" if text else ""
        if name in ('p', 'subtitle'):
            text = xml_text(element)
            return f"<p>{escape_html(text)}</p>" if text else ""
        if name == 'v':
            text = xml_text(element)
            return f"<p>{escape_html(text)}</p>" if text else ""
        if name == 'empty-line':
            return "<p><br/></p>"
        if name == 'image':
            return self._render_image(element)
        if name == 'section':
            return ""

        inner = ''.join(self._render_element(child) for child in element)
        if not inner and name in ('epigraph', 'cite', 'poem', 'stanza', 'annotation',
                                  'text-author', 'date', 'table', 'tr', 'td'):
            text = xml_text(element)
            inner = f"<p>{escape_html(text)}</p>" if text else ""
        if name in ('epigraph', 'cite') and inner:
            inner = f"<blockquote>{inner}</blockquote>"
        return inner

    def _render_image(self, element):
        """把 <image l:href="#xxx"> 渲染为 base64 内嵌图片"""
        href = ""
        for key, value in element.attrib.items():
            if local_name(key) == 'href':
                href = value
                break

        if not href.startswith('#'):
            return ""

        binary = self._binaries.get(href[1:])
        if not binary:
            return ""

        uri = self._image_uri(href[1:], binary[0], binary[1])
        if not uri:
            return ""
        return f'<p><img src="{uri}" /></p>'

    def _image_uri(self, binary_id, content_type, payload):
        """把 base64 图片转成 data URI（带体积与格式校验）"""
        if binary_id in self._image_cache:
            return self._image_cache[binary_id]

        uri = ''
        try:
            data = base64.b64decode(payload)
        except Exception:
            data = b''

        if data and len(data) <= MAX_IMAGE_BYTES:
            declared = (content_type or '').lower().startswith('image/')
            if declared or looks_like_image(data):
                mime = guess_mime('', data[:64],
                                  content_type or 'image/jpeg')
                uri = to_data_uri(data, mime)

        self._image_cache[binary_id] = uri
        return uri
