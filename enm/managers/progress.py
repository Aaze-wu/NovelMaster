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
* ``scroll_percent`` —— 章内滚动位置（0~100）；
* ``record_version`` / ``saved_at`` —— 记录格式版本与保存时间，由管理器统一写入。

阅读统计字段（同样由读取时自动补齐）：

* ``open_count`` —— 这本书被打开的次数；
* ``first_opened_at`` / ``last_opened_at`` —— 首次 / 最后打开时间；
* ``total_read_seconds`` —— 累计阅读时长（只统计窗口处于激活状态的时间）；
* ``session_read_seconds`` —— 最近一次会话的阅读时长；
* ``read_chapters`` —— ``{单元名: [已读章节下标]}``，单元名在单文件模式为文件名、
  文件夹模式为内层文件名，因此同一个文件夹里的多个文件互不干扰；
* ``read_chapter_count`` —— ``read_chapters`` 里去重后的章节总数；
* ``max_chapter`` —— **当前单元**读到的最远章节下标（由 ``read_chapters`` 推导）。
"""

import copy
import hashlib
import json
import time
from pathlib import Path

from ..constants import SAVE_PATH
from ..logger import logger

# 计算内容哈希时的读取块大小
_HASH_CHUNK_SIZE = 1024 * 1024

# 阅读记录格式版本：字段结构变化时递增
# 3：新增阅读统计字段（open_count / total_read_seconds / read_chapters 等）
RECORD_VERSION = 3

# 统计字段的默认值，旧记录在读取时按此补齐
DEFAULT_STATS = {
    "open_count": 0,
    "first_opened_at": "",
    "last_opened_at": "",
    "total_read_seconds": 0.0,
    "session_read_seconds": 0.0,
    "read_chapters": {},
    "read_chapter_count": 0,
    "max_chapter": 0,
}


def format_timestamp(value=None):
    """把时间戳格式化成记录里使用的可读时间（缺省取当前时间）"""
    if isinstance(value, (int, float)):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def record_file_key(record):
    """从记录内容反推它的记录键（读不到 ``md5`` / ``key_type`` 时退回路径哈希）"""
    if not isinstance(record, dict):
        return ""

    kind = record.get("key_type")
    digest = record.get("md5")
    if kind in ("file", "dir", "path") and digest:
        return f"{kind}:{digest}"

    file_path = record.get("file_path")
    if file_path:
        return f"path:{path_hash(file_path)}"
    return ""


def normalise_read_chapters(value):
    """把 ``read_chapters`` 规范成 ``{单元名: 升序去重的章节下标}``。

    容忍手工编辑过的记录：允许直接写成章节列表（视为单文件模式），
    非数字或负数下标会被丢弃。
    """
    result = {}
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, (list, tuple, set)):
        items = [("*", value)]
    else:
        return result

    for unit, chapters in items:
        if isinstance(chapters, (str, bytes)) or not isinstance(chapters, (list, tuple, set)):
            continue
        indexes = set()
        for item in chapters:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if index >= 0:
                indexes.add(index)
        if indexes:
            result[str(unit)] = sorted(indexes)

    return result


def _as_int(value, default=0):
    """尽力把记录里的值转成整数"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    """尽力把记录里的值转成浮点数"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        """补齐旧记录缺少的元数据与统计字段

        只改内存里的字典，等下一次保存时自然落盘。
        """
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

        # 统计数据：旧记录没有这些字段，按默认值补齐后再做一次类型规范化
        for field, default in DEFAULT_STATS.items():
            if field not in progress:
                progress[field] = copy.deepcopy(default)

        progress["open_count"] = _as_int(progress.get("open_count"))
        progress["total_read_seconds"] = _as_float(progress.get("total_read_seconds"))
        progress["session_read_seconds"] = _as_float(progress.get("session_read_seconds"))
        progress["read_chapters"] = normalise_read_chapters(progress.get("read_chapters"))
        progress["read_chapter_count"] = sum(len(v) for v in progress["read_chapters"].values())
        progress["max_chapter"] = _as_int(progress.get("max_chapter"))

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
        record["saved_at"] = format_timestamp()

        try:
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.log(f"保存阅读记录失败: {e}", "ERROR")
            return False

    def _read(self, file_key):
        """读取记录键对应的 JSON（文件不存在或损坏时返回空字典）"""
        return self._read_file(self.get_progress_file_path(file_key))

    def _read_file(self, progress_file):
        """读取记录文件（不存在或损坏时返回空字典）"""
        progress_file = Path(progress_file)
        if not progress_file.exists():
            return {}

        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.log(f"加载阅读记录失败: {e}", "ERROR")
            return {}

    # ---------------- 记录列表 ----------------

    def iter_records(self):
        """遍历所有阅读记录，产出 ``(记录文件路径, 记录内容)``

        记录内容已补全元数据与统计字段，可直接用于「继续阅读」列表展示；
        记录文件路径用于删除等操作（记录文件名是记录键的哈希，本身不可读）。
        """
        for progress_file in sorted(self.save_path.glob("*.json")):
            record = self._read_file(progress_file)
            if not isinstance(record, dict) or not record:
                continue
            yield progress_file, self._upgrade_record(record, record_file_key(record))

    def delete_record_file(self, progress_file):
        """删除单个阅读记录文件"""
        try:
            Path(progress_file).unlink()
            return True
        except OSError as e:
            logger.log(f"删除阅读记录失败: {e}", "WARN")
            return False

    def get_all_progress(self):
        """获取所有阅读记录（键为记录文件名，值为记录内容）"""
        return {progress_file.stem: record for progress_file, record in self.iter_records()}
