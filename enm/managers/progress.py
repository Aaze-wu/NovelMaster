"""阅读进度管理。

记录键（``file_key``）的规则：

* 电子书文件 —— 文件**内容**的 MD5（``file:<md5>``），因此文件被移动、改名后
  仍然能接着上次的位置继续读，同一本书的多个副本也共享进度；
* 文件夹 —— 文件夹**路径**的 MD5（``dir:<md5>``），文件夹没有内容哈希可言；
* 计算失败时退回路径哈希（``path:<md5>``），保证功能不会因为权限等问题中断。

记录文件仍然以 ``md5(file_key)`` 命名，避免路径过长。旧版本直接拿文件路径当键，
:meth:`ReadingProgressManager.load_progress` 会自动把旧记录迁移到新键上。

每条记录在位置信息之外还会带上元数据（旧记录在读取时自动补齐，下次保存落盘）：

* ``filename`` —— 文件名（文件夹模式为文件夹名，含扩展名）；
* ``md5`` —— 记录键的摘要，``key_type`` 为 ``file`` 时即整文件**内容** MD5；
* ``novelname`` —— 书名（取书的元数据，缺失时回退文件名）；
* ``author`` —— 作者；
* ``key_type`` —— ``file`` / ``dir`` / ``path``，说明 ``md5`` 的含义；
* ``file_size`` —— 文件字节数（仅普通文件）；
* ``total_chapters`` / ``chapter_title`` —— 总章节数与当前章节标题；
* ``record_version`` / ``saved_at`` —— 记录格式版本与保存时间，由管理器统一写入。
"""

import hashlib
import json
import time
from pathlib import Path

from ..constants import SAVE_PATH
from ..logger import logger

# 计算内容哈希时的读取块大小
_HASH_CHUNK_SIZE = 1024 * 1024

# 阅读记录格式版本：字段结构变化时递增
RECORD_VERSION = 2


def content_hash(path, chunk_size=_HASH_CHUNK_SIZE):
    """按内容计算文件 MD5（分块读取，避免把整本书读进内存）"""
    digest = hashlib.md5()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b''):
            digest.update(chunk)
    return digest.hexdigest()


def path_hash(path):
    """按路径字符串计算 MD5（用于文件夹与兜底场景）"""
    return hashlib.md5(str(path).encode('utf-8')).hexdigest()


def split_file_key(file_key):
    """拆分记录键，返回 ``(key_type, digest)``。

    ``key_type`` 为 ``file``（内容 MD5）/ ``dir``（文件夹路径 MD5）/ ``path``（兜底路径 MD5）；
    键为空或格式意外时按 ``path`` 处理。
    """
    if not file_key:
        return "path", ""

    kind, sep, digest = str(file_key).partition(':')
    if not sep or kind not in ("file", "dir", "path"):
        return "path", path_hash(file_key)
    return kind, digest


class ReadingProgressManager:
    def __init__(self):
        self.save_path = SAVE_PATH
        self.save_path.mkdir(parents=True, exist_ok=True)
        # 路径 -> ((mtime_ns, size), file_key)：避免自动保存时反复读取整本书
        self._key_cache = {}

    # ---------------- 记录键 ----------------

    def build_file_key(self, file_path):
        """把文件路径换算成记录键（文件按内容哈希，文件夹按路径哈希）"""
        path = Path(str(file_path))
        try:
            stat = path.stat()
        except OSError as e:
            logger.log(f"无法读取 {path} 的信息，阅读记录改用路径哈希: {e}", "WARN")
            return f'path:{path_hash(path)}'

        if path.is_dir():
            return f'dir:{path_hash(path)}'

        cached = self._key_cache.get(str(path))
        stamp = (stat.st_mtime_ns, stat.st_size)
        if cached and cached[0] == stamp:
            return cached[1]

        try:
            key = f'file:{content_hash(path)}'
        except OSError as e:
            logger.log(f"计算文件哈希失败，阅读记录改用路径哈希: {e}", "WARN")
            key = f'path:{path_hash(path)}'

        self._key_cache[str(path)] = (stamp, key)
        return key

    def get_progress_file_path(self, file_key):
        """获取阅读记录文件路径"""
        # 使用记录键的MD5哈希作为文件名，避免路径过长问题
        return self.save_path / f"{path_hash(file_key)}.json"

    def key_metadata(self, file_path, file_key=None):
        """由文件路径（或已知记录键）生成记录的元数据。

        返回 ``filename`` / ``md5`` / ``key_type``，普通文件额外带 ``file_size``。
        书名与作者由调用方补充，因为这个管理器不关心书籍内容。
        """
        key = file_key or self.build_file_key(file_path)
        kind, digest = split_file_key(key)
        path = Path(str(file_path))

        metadata = {
            "filename": path.name or str(path),
            "md5": digest,
            "key_type": kind,
        }

        try:
            if path.is_file():
                metadata["file_size"] = path.stat().st_size
        except OSError as e:
            logger.log(f"读取文件大小失败，记录中省略该字段: {e}", "WARN")

        return metadata

    # ---------------- 读写 ----------------

    def load_progress(self, file_key, legacy_key=None):
        """加载阅读进度

        ``legacy_key`` 是旧版本使用的键（直接是文件路径字符串）。新键没有记录时，
        会读一次旧键，把结果写到新键上并删掉旧文件，完成迁移。

        取到的记录会经过 :meth:`_upgrade_record` 补全元数据，但不会额外落盘，
        等下一次自动保存时自然写入。
        """
        progress = self._read(file_key)
        if progress:
            return self._upgrade_record(progress, file_key)

        if legacy_key and legacy_key != file_key:
            legacy = self._read(legacy_key)
            if legacy:
                self.save_progress(file_key, legacy)
                legacy_file = self.get_progress_file_path(legacy_key)
                try:
                    legacy_file.unlink()
                except OSError as e:
                    logger.log(f"删除旧的阅读记录失败: {e}", "WARN")
                logger.log(f"阅读记录已迁移到内容哈希: {legacy.get('file_path', legacy_key)}")
                return self._upgrade_record(legacy, file_key)

        return {}

    def _upgrade_record(self, progress, file_key):
        """补齐旧记录缺少的 ``md5`` / ``key_type`` / ``filename`` 字段"""
        if not isinstance(progress, dict):
            return {}

        kind, digest = split_file_key(file_key)
        if not progress.get("key_type"):
            progress["key_type"] = kind
        if not progress.get("md5"):
            progress["md5"] = digest
        if not progress.get("filename"):
            file_path = progress.get("file_path")
            if file_path:
                progress["filename"] = Path(str(file_path)).name

        return progress

    def save_progress(self, file_key, progress_data):
        """保存阅读进度

        写入前会补全记录信封字段（``key_type`` / ``md5`` / ``filename`` /
        ``record_version`` / ``saved_at``），调用方无需关心。
        """
        progress_file = self.get_progress_file_path(file_key)
        record = dict(progress_data or {})

        kind, digest = split_file_key(file_key)
        record.setdefault("key_type", kind)
        if not record.get("md5"):
            record["md5"] = digest
        file_path = record.get("file_path")
        if not record.get("filename") and file_path:
            record["filename"] = Path(str(file_path)).name
        record["record_version"] = RECORD_VERSION
        record["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        try:
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.log(f"保存阅读记录失败: {e}", "ERROR")
            return False

    def _read(self, file_key):
        """读取记录键对应的 JSON（文件不存在或损坏时返回空字典）"""
        progress_file = self.get_progress_file_path(file_key)
        
        if not progress_file.exists():
            return {}
        
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.log(f"加载阅读记录失败: {e}", "ERROR")
            return {}
    
    def get_all_progress(self):
        """获取所有阅读记录（键为记录文件名，值为记录内容）"""
        progress_data = {}
        
        for progress_file in self.save_path.glob("*.json"):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    # 由于使用哈希文件名，无法直接还原原始文件路径
                    # 这里返回文件内容，主程序需要处理映射关系
                    progress_data[progress_file.stem] = json.load(f)
            except Exception as e:
                logger.log(f"读取阅读记录文件失败: {e}", "ERROR")
        
        return progress_data
