"""文件夹阅读器：把一个文件夹内的多本电子书串成一本书来读。"""

from pathlib import Path

from ..logger import logger
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
        for reader in self._reader_cache.values():
            if reader is not None and reader.retranslate_titles():
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
