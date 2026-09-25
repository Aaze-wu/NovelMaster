"""文件夹阅读器：把一个文件夹内的多本电子书串成一本书来读。"""

from pathlib import Path

from ..logger import logger
from ..managers.book_identity import is_generic_title, strip_extension
from .base import BaseReader, ReaderError
from .factory import SUPPORTED_EXTENSIONS, create_reader


class FolderReader(BaseReader):
    """文件夹阅读器：以文件为单位，内部复用各格式的阅读器"""

    def __init__(self, folder_path):
        super().__init__(folder_path)
        self.folder_path = Path(folder_path)
        self.files = []
        self.current_file_index = 0
        self._reader_cache = {}     # 文件索引 -> 阅读器实例（避免重复解析同一文件）
        self.scan_folder()
    
    def scan_folder(self):
        """扫描文件夹中的支持文件"""
        supported_extensions = SUPPORTED_EXTENSIONS

        for file_path in self.folder_path.rglob('*'):
            if not file_path.is_file():
                continue

            extension = file_path.suffix.lower()
            if extension not in supported_extensions:
                continue
            if extension == '.jad' and self._jar_beside(file_path):
                continue        # .jad 只是描述文件，正文在同名 .jar 里，别重复收录

            self.files.append({
                'path': file_path,
                'name': file_path.name,
                'type': extension
            })

        # 按文件名排序
        self.files.sort(key=lambda x: x['name'])

    @staticmethod
    def _jar_beside(file_path):
        """同名 .jar 是否就在旁边（是的话这个 .jad 不用单独收录）"""
        return any(sibling.is_file()
                   for sibling in (file_path.with_suffix('.jar'),
                                   file_path.with_suffix('.JAR')))
    
    def get_file_count(self):
        return len(self.files)

    # ---------------- 与单文件阅读器一致的章节接口 ----------------

    def get_chapter_count(self):
        """当前文件的章节数（文件夹本身不持有章节）"""
        reader = self.get_current_reader()
        return reader.get_chapter_count() if reader else 0

    def get_chapter_title(self, index):
        reader = self.get_current_reader()
        return reader.get_chapter_title(index) if reader else ""

    def get_chapter_content(self, index):
        reader = self.get_current_reader()
        return reader.get_chapter_content(index) if reader else ""

    def retranslate_titles(self):
        """让已缓存的子阅读器重新生成自动编号的章节标题"""
        changed = False
        for index, reader in self._reader_cache.items():
            if reader is not None and reader.retranslate_titles():
                changed = True
            if self._use_file_name_as_title(reader, index):
                changed = True
        return changed

    def get_book_info(self):
        current = self.get_current_file()
        title = current['name'] if current else self.folder_path.name
        return {'title': title, 'author': ''}
    
    def get_current_file(self):
        """获取当前文件信息"""
        if not self.files:
            return None
        return self.files[self.current_file_index]
    
    def display_name(self, index=None):
        """某个文件的展示名（文件名去掉扩展名）；``index`` 省略时用当前文件"""
        if not self.files:
            return self.folder_path.name
        if index is None:
            index = self.current_file_index
        if not 0 <= index < len(self.files):
            return self.folder_path.name
        name = self.files[index]['name']
        return strip_extension(name) or name

    def _use_file_name_as_title(self, reader, index=None):
        """整篇只有一章且标题是占位词时，改用文件名当章节名。

        文件夹模式下这一层的「章节」本来就是一个文件，而 TXT（没有章节标记）、
        DOCX、HTML、MOBI、UMD 这类整篇一章的格式，标题只能是程序生成的占位词
        （``全文`` / ``正文`` / ``Full Text``……），在列表里既没有区分度、看着
        又像坏掉的标题。真书自带的章节名不受影响：能给出章节名的文件都不止一章，
        所以这里只在只有一章时才动手。返回是否改动了标题。
        """
        if reader is None or len(reader.chapters) != 1:
            return False

        chapter = reader.chapters[0]
        title = str(chapter.get('title') or '')
        if title.strip() and not is_generic_title(title):
            return False

        chapter['title'] = self.display_name(index)
        # 占位标题已经换掉了，别让切换语言时再按 title_spec 生成回去
        chapter.pop('title_spec', None)
        return True

    def get_current_reader(self):
        """获取当前文件的阅读器（带缓存，保证章节位置不会因为重复解析而丢失）"""
        if not self.files:
            return None
        
        if self.current_file_index in self._reader_cache:
            return self._reader_cache[self.current_file_index]
        
        current_file = self.files[self.current_file_index]
        reader = None
        try:
            reader = create_reader(str(current_file['path']))
        except ReaderError as e:
            logger.log(f"无法打开 {current_file['name']}: {e}", "ERROR")
        except Exception as e:
            logger.log(f"打开 {current_file['name']} 失败: {e}", "ERROR")
        
        self._reader_cache[self.current_file_index] = reader
        self._use_file_name_as_title(reader, self.current_file_index)
        return reader
    
    def close(self):
        """释放所有已缓存的阅读器（清理临时文件等）"""
        super().close()
        for reader in self._reader_cache.values():
            if reader is not None:
                try:
                    reader.close()
                except Exception as e:
                    logger.log(f"释放阅读器失败: {e}", "ERROR")
        self._reader_cache.clear()

    # 兼容旧调用名
    release = close
