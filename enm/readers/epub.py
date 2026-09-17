"""EPUB 阅读器（基于 ebooklib）。"""

import posixpath
from pathlib import Path

import ebooklib
from ebooklib import epub

from ..logger import logger
from .base import BaseReader
from .images import (candidate_paths, guess_mime, inline_images, is_image_name)


class EpubReader(BaseReader):
    """EPUB 阅读器（基于 ebooklib）"""

    def __init__(self, file_path):
        super().__init__(file_path)
        self.book = None
        self._items_by_name = {}
        self._image_index = {}
        self._basename_index = {}
        self.load_book()
    
    def load_book(self):
        """加载EPUB文件"""
        try:
            self.book = epub.read_epub(self.file_path)
            self._set_book_info(*self._read_metadata())
            self._index_items()
            self.extract_chapters()
            return True
        except Exception as e:
            logger.log(f"加载EPUB文件失败: {e}", "ERROR")
            return False

    def _read_metadata(self):
        """读取 EPUB 元数据中的书名与作者，返回 (title, author)"""
        def first(name):
            try:
                values = self.book.get_metadata('DC', name)
            except Exception as e:
                logger.log(f"读取 EPUB 元数据失败（{name}）: {e}", "WARN")
                return ""
            for entry in values or []:
                value = entry[0] if isinstance(entry, (list, tuple)) else entry
                text = str(value or '').strip()
                if text:
                    return text
            return ""

        return first('title'), first('creator')

    def close(self):
        """释放 ebooklib 解析出来的资源（章节内容已经提取到内存中）"""
        super().close()
        self.book = None

    def _index_items(self):
        """建立条目 / 图片索引，用于解析正文里的相对引用"""
        self._items_by_name = {}
        self._image_index = {}
        self._basename_index = {}

        for item in list(self.book.get_items()):
            if item is None:
                continue

            name = (item.get_name() or '').replace('\\', '/')
            if not name:
                continue

            for key in {name, posixpath.normpath(name), name.lstrip('./')}:
                self._items_by_name.setdefault(key, item)
            self._basename_index.setdefault(posixpath.basename(name), item)

            if not self._is_image_item(item, name):
                continue
            try:
                data = item.get_content()
            except Exception as e:
                logger.log(f"读取 EPUB 内嵌图片失败（{name}）: {e}", "WARN")
                continue
            if not data:
                continue

            mime = guess_mime(Path(name).suffix, bytes(data[:64]),
                              getattr(item, 'media_type', '') or 'image/jpeg')
            for key in {name, posixpath.normpath(name), posixpath.basename(name)}:
                self._image_index.setdefault(key, (len(data), mime, data))

    @staticmethod
    def _is_image_item(item, name):
        """判断条目是否为图片（按 ebooklib 类型或扩展名）"""
        try:
            item_type = item.get_type()
        except Exception:
            item_type = None
        if item_type in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER):
            return True
        media_type = getattr(item, 'media_type', '') or ''
        if media_type.startswith('image/'):
            return True
        return is_image_name(name)

    def extract_chapters(self):
        """提取章节"""
        self.chapters = []
        
        # 首先尝试获取书籍的目录结构
        try:
            # 获取书籍的spine（阅读顺序）
            spine = self.book.spine
            
            # 获取书籍的目录
            toc = self.book.toc
            
            # 如果有目录信息，优先使用目录
            if toc:
                self._extract_chapters_from_toc(toc)
            else:
                # 如果没有目录，使用spine顺序
                self._extract_chapters_from_spine(spine)
                
        except Exception as e:
            # 如果上述方法失败，使用备用方法
            self._extract_chapters_fallback()
    
    def _extract_chapters_from_toc(self, toc):
        """从目录提取章节"""
        def process_toc_items(items, level=0):
            for item in items:
                if hasattr(item, 'href'):
                    # 查找对应的文档项
                    doc_item = self._find_document(item.href)
                    if doc_item is not None:
                        content = self._chapter_content(doc_item)
                        title = self._extract_title_from_content(content, item.title)
                        
                        self.chapters.append({
                            'title': title,
                            'content': content,
                            'id': doc_item.get_id()
                        })
                
                # 递归处理子项
                if hasattr(item, 'subitems') and item.subitems:
                    process_toc_items(item.subitems, level + 1)
        
        process_toc_items(toc)
    
    def _extract_chapters_from_spine(self, spine):
        """从spine顺序提取章节"""
        for item_id, linear in spine:
            item = self.book.get_item_with_id(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = self._chapter_content(item)
                title = self._extract_title_from_content(content)
                
                self.chapters.append({
                    'title': title,
                    'content': content,
                    'id': item.get_id()
                })
    
    def _extract_chapters_fallback(self):
        """备用章节提取方法"""
        for item in list(self.book.get_items()):
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = self._chapter_content(item)
                title = self._extract_title_from_content(content)
                
                self.chapters.append({
                    'title': title,
                    'content': content,
                    'id': item.get_id()
                })

    # ---------------- 内嵌图片 ----------------

    def _chapter_content(self, item):
        """读取文档内容，并把其中的图片内联为 data URI"""
        try:
            content = item.get_content().decode('utf-8', errors='ignore')
        except Exception as e:
            logger.log(f"读取 EPUB 章节内容失败（{item.get_name()}）: {e}", "ERROR")
            return ""

        if not self._image_index:
            return content
        return inline_images(content, self._image_resolver(item.get_name()))

    def _image_resolver(self, document_name):
        """返回解析该文档内图片引用的闭包"""
        def resolve(reference):
            for key in candidate_paths(document_name, reference):
                found = self._image_index.get(key)
                if found:
                    return found[2], found[1]
            return None

        return resolve

    def _find_document(self, href):
        """根据目录中的 href 找到对应的文档条目"""
        for key in candidate_paths('', href):
            item = self._items_by_name.get(key)
            if item is not None:
                return item if self._is_document(item) else None

        basename = posixpath.basename((href or '').split('#')[0].split('?')[0])
        item = self._basename_index.get(basename)
        if item is not None and self._is_document(item):
            return item
        return None

    @staticmethod
    def _is_document(item):
        """判断条目是否为可阅读的正文文档"""
        try:
            return item.get_type() == ebooklib.ITEM_DOCUMENT
        except Exception:
            return False

    def _extract_title_from_content(self, content, fallback_title=None):
        """从内容中提取标题"""
        # 方法1: 尝试提取<title>标签
        if '<title>' in content and '</title>' in content:
            start = content.find('<title>') + 7
            end = content.find('</title>')
            title = content[start:end].strip()
            if title and title != "未知章节":
                return title
        
        # 方法2: 尝试提取<h1>到<h6>标签
        for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            if f'<{tag}' in content and f'</{tag}>' in content:
                start = content.find(f'<{tag}')
                end = content.find(f'</{tag}>') + len(tag) + 3
                tag_content = content[start:end]
                
                # 提取标签内的文本
                text_start = tag_content.find('>')
                if text_start != -1:
                    title = tag_content[text_start+1:].replace(f'</{tag}>', '').strip()
                    if title and len(title) < 100:  # 避免提取过长的文本
                        return title
        
        # 方法3: 使用文件名或fallback标题
        if fallback_title:
            return fallback_title
        
        # 方法4: 使用章节序号
        chapter_num = len(self.chapters) + 1
        return f"第{chapter_num}章"
