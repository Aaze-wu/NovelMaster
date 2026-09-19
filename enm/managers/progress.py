"""阅读进度管理。

记录键（``file_key``）的规则：

* 电子书文件 —— **书本身份**的 MD5（``book:<book_id>``），同一本书的不同版本、
  不同副本共享同一份阅读记录；
* 文件夹 —— 文件夹**路径**的 MD5（``dir:<md5>``），文件夹没有内容哈希可言；
* 算不出身份时退回文件内容哈希（``file:<md5>``）；
* 计算失败时退回路径哈希（``path:<md5>``），保证功能不会因为权限等问题中断。

内容哈希（``file:``）有个绕不开的短板：同一本书只要重新导出、追加章节、换个格式，
内容 MD5 就变了，阅读位置与统计会从零开始。所以打开书籍时会先用
:mod:`enm.managers.book_identity` 算出**书本身份**，把记录键升级成
``book:<book_id>``（``book_id`` = 归一化书名 + 开头几章的标题指纹）：

* 升级是**惰性**的，由 :meth:`ReadingProgressManager.plan_record_key` 规划、
  :meth:`ReadingProgressManager.apply_record_key` 执行：同一个文件的旧记录直接
  迁移过来，另一个版本（或另一份副本）的记录合并成一份；
* 只在「书名对得上、章节结构对不上」时才回头问用户；问过一次合并后
  （或用户选择不再询问后）不会再打扰；
* 合并掉的记录键会记进 ``aliases``，之后拿任意一个版本打开都能认出这条记录；
* 章节名是程序自动编号的书（UMD 之类很常见）没有章节指纹可用，只有
  **弱身份**（``book_id`` 为空、``weak_id`` 非空，同样落在 ``book:`` 前缀上）。
  弱身份只保证「同名」，不能断定「同书」，因此一律先问用户：用户点头才合并，
  选了「各自独立」就退回这个文件自己的内容键，绝不覆盖同名另一本书的记录；
* 连书名都取不到时沿用 ``file:<md5>``，行为与旧版本一致。

记录文件仍然以 ``md5(file_key)`` 命名，避免路径过长。旧版本直接拿文件路径当键，
:meth:`ReadingProgressManager.load_progress` 会自动把旧记录迁移到新键上。

每条记录在位置信息之外还会带上元数据（旧记录在读取时自动补齐，下次保存落盘）：

* ``filename`` —— 文件名（文件夹模式为文件夹名，含扩展名）；
* ``md5`` —— 记录键的摘要（``key_type`` 为 ``book`` 时即书本身份）；
* ``novelname`` —— 书名（取书的元数据，缺失时回退文件名）；
* ``author`` —— 作者；
* ``key_type`` —— ``book`` / ``file`` / ``dir`` / ``path``，说明 ``md5`` 的含义；
* ``file_md5`` —— 文件**内容** MD5（与记录键无关，用于区分同一本书的不同版本）；
* ``file_size`` —— 文件字节数（仅普通文件）；
* ``total_chapters`` / ``chapter_title`` —— 总章节数与当前章节标题；
* ``title_key`` / ``author_key`` —— 归一化后的书名 / 作者，判断「同一本书」用；
* ``chapter_fingerprint`` / ``fingerprint_titles`` —— 章节标题指纹与取样到的标题；
* ``book_id`` —— 书本身份（章节名是自动编号时为空串，此时只能按 ``title_key``
  与用户确认来共用记录）；
* ``aliases`` —— 已经合并进本记录的其它记录键，避免以后反复询问；
* ``versions`` —— 这本书见过的各个文件（文件名 / 路径 / 内容 MD5 / 大小 / 章节数）；
* ``scroll_percent`` —— 章内滚动位置（0~100）；
* ``record_version`` / ``saved_at`` —— 记录格式版本与保存时间，由管理器统一写入。

阅读统计字段（同样由读取时自动补齐）：

* ``open_count`` —— 这本书被打开的次数；
* ``first_opened_at`` / ``last_opened_at`` —— 首次 / 最后打开时间；
* ``total_read_seconds`` —— 累计阅读时长（只统计窗口处于激活状态的时间）；
* ``session_read_seconds`` —— 最近一次会话的阅读时长；
* ``read_chapters`` —— ``{单元名: [已读章节下标]}``，单文件模式的单元名固定为
  ``"*"``（整条记录就是这一本书，改了文件名也要能合并统计），
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
from .book_identity import (match_strength, normalise_author, normalise_title,
                            record_identity)

# 计算内容哈希时的读取块大小
_HASH_CHUNK_SIZE = 1024 * 1024

# 书本身份键的前缀
BOOK_KEY_PREFIX = "book:"

# 记录键的种类
VALID_KEY_TYPES = ("book", "file", "dir", "path")

# 记录里最多留几个版本的足迹
MAX_VERSIONS = 8

# 阅读记录格式版本：字段结构变化时递增
# 3：新增阅读统计字段（open_count / total_read_seconds / read_chapters 等）
# 4：新增书本身份字段（title_key / chapter_fingerprint / book_id / aliases / versions），
#    记录键可以是 book:<book_id>，单文件模式的统计单元统一成 "*"
RECORD_VERSION = 4

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
    if kind in VALID_KEY_TYPES and digest:
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

    ``key_type`` 为 ``book``（书本身份）/ ``file``（内容 MD5）/ ``dir``（文件夹路径 MD5）
    / ``path``（兜底路径 MD5）；键为空或格式意外时按 ``path`` 处理。
    """
    if not file_key:
        return "path", ""

    kind, sep, digest = str(file_key).partition(':')
    if not sep or kind not in VALID_KEY_TYPES:
        return "path", path_hash(file_key)
    return kind, digest


def _first_time(*values):
    """取最早的一个时间文本（时间格式定宽，字典序就是时间序）"""
    texts = [str(value) for value in values if value]
    return min(texts) if texts else ""


def _last_time(*values):
    """取最晚的一个时间文本"""
    texts = [str(value) for value in values if value]
    return max(texts) if texts else ""


def _record_time(record):
    """记录的最后活跃时间（用于判断两份记录哪份更新）"""
    if not isinstance(record, dict):
        return ""

    for field in ("last_opened_at", "saved_at"):
        text = str(record.get(field) or "").strip()
        if text:
            return text

    timestamp = record.get("timestamp")
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        return format_timestamp(timestamp)
    return ""


def normalise_versions(value):
    """把 ``versions`` 规范成版本足迹列表。

    每项形如 ``{filename, file_path, file_md5, file_size, total_chapters,
    last_seen_at}``；没有文件名也没有路径的条目会被丢弃。容许记录里直接写成一个
    字典（只有一份的情况），也容许缺字段。
    """
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []

    result = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        item = {
            "filename": str(entry.get("filename") or ""),
            "file_path": str(entry.get("file_path") or ""),
            "file_md5": str(entry.get("file_md5") or ""),
            "file_size": _as_int(entry.get("file_size")),
            "total_chapters": _as_int(entry.get("total_chapters")),
            "last_seen_at": str(entry.get("last_seen_at") or entry.get("saved_at") or ""),
        }
        if item["filename"] or item["file_path"]:
            result.append(item)
    return result


def _version_key(entry):
    """版本足迹的去重键：优先内容 MD5（同一本书的不同副本算一版）"""
    return str(entry.get("file_md5") or entry.get("file_path") or entry.get("filename") or "")


def upsert_version(versions, entry, limit=MAX_VERSIONS):
    """把一条版本足迹写进列表（同一个文件就地更新，并挪到最前面）。

    每次保存阅读进度时调用，因此 ``versions`` 总是“这本书见过哪些文件”。
    """
    normalised = normalise_versions([entry])
    if not normalised:
        return normalise_versions(versions)

    entry = normalised[0]
    key = _version_key(entry)
    result = [item for item in normalise_versions(versions) if _version_key(item) != key]
    result.insert(0, entry)
    return result[:max(1, _as_int(limit, MAX_VERSIONS))]


def merge_versions(*sources):
    """合并多份 ``versions``（按内容 MD5 去重，后给的覆盖先给的）"""
    result = []
    for source in sources:
        for entry in normalise_versions(source):
            key = _version_key(entry)
            for position, existing in enumerate(result):
                if _version_key(existing) == key:
                    result[position] = entry
                    break
            else:
                result.append(entry)
    result.sort(key=lambda item: item.get("last_seen_at") or "", reverse=True)
    return result[:max(1, _as_int(MAX_VERSIONS))]


def merge_records(base, other):
    """把 ``other`` 合并进 ``base``（``base`` 是较新的那份，位置以它为准）。

    返回新字典，不改动入参。位置、书名、文件信息一律保留 ``base`` 的；
    统计字段累加 / 取并集，``versions`` 与 ``aliases`` 取并集。
    合并的只是同一本书的不同版本，所以已读章节取并集不会算错，
    而阅读时长、打开次数这些计数则是真的累加。
    """
    if not isinstance(base, dict) or not base:
        return dict(other) if isinstance(other, dict) else {}
    if not isinstance(other, dict) or not other:
        return dict(base)

    merged = dict(base)
    merged["open_count"] = _as_int(base.get("open_count")) + _as_int(other.get("open_count"))
    merged["total_read_seconds"] = round(
        _as_float(base.get("total_read_seconds")) + _as_float(other.get("total_read_seconds")), 1)
    merged["session_read_seconds"] = _as_float(base.get("session_read_seconds"))
    merged["first_opened_at"] = _first_time(base.get("first_opened_at"),
                                             other.get("first_opened_at"))
    merged["last_opened_at"] = _last_time(base.get("last_opened_at"),
                                           other.get("last_opened_at"))

    read_chapters = normalise_read_chapters(base.get("read_chapters"))
    for unit, indexes in normalise_read_chapters(other.get("read_chapters")).items():
        read_chapters[unit] = sorted(set(read_chapters.get(unit, [])) | set(indexes))
    merged["read_chapters"] = read_chapters
    merged["read_chapter_count"] = sum(len(items) for items in read_chapters.values())
    merged["max_chapter"] = max(_as_int(base.get("max_chapter")),
                                 _as_int(other.get("max_chapter")))

    aliases = {str(item) for item in (base.get("aliases") or []) if item}
    aliases.update(str(item) for item in (other.get("aliases") or []) if item)
    merged["aliases"] = sorted(aliases)
    merged["versions"] = merge_versions(base.get("versions"), other.get("versions"))

    # 身份与书籍信息：以 base 为主，base 缺失时才拿 other 补上。
    # 老记录没有指纹，而它合并的对象往往带着指纹，顺手接过来就不用再问用户一次。
    for field in ("title_key", "author_key", "chapter_fingerprint", "book_id",
                  "novelname", "author", "file_md5", "filename"):
        if not merged.get(field):
            merged[field] = other.get(field) or ""
    if not merged.get("fingerprint_titles"):
        merged["fingerprint_titles"] = list(other.get("fingerprint_titles") or [])
    if not _as_int(merged.get("total_chapters")):
        merged["total_chapters"] = _as_int(other.get("total_chapters"))
    return merged


def record_covers_file(record, content_key, file_path=""):
    """这条记录是不是就是这个文件自己留下的（弱身份识别用）

    弱身份（只按书名认出来的那份）没有「这就是同一本书」的铁证，只能反过来看
    一条记录里有没有当前这个文件的记号：记录自己的路径、别名里的记录键
    （合并过的记录会把源记录的键记下来）、版本足迹里的内容哈希与路径。
    """
    if not isinstance(record, dict) or not record:
        return False

    path_text = str(file_path or "")
    if path_text and str(record.get("file_path") or "") == path_text:
        return True

    content_key = str(content_key or "")
    if content_key:
        if content_key in {str(item) for item in (record.get("aliases") or [])}:
            return True

    _kind, digest = split_file_key(content_key)
    if not digest:
        return False
    if str(record.get("md5") or "") == digest:
        return True
    for item in record.get("versions") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("file_md5") or "") == digest:
            return True
        if path_text and str(item.get("file_path") or "") == path_text:
            return True
    return False


def _is_single_file_record(record, kind):
    """这份记录是不是「一个文件 = 一本书」（决定统计单元要不要归一成 ``"*"``）"""
    if kind == "dir":
        return False
    # 文件夹模式的记录一定带内层文件名与内层文件序号
    if record.get("inner_filename") or "file_index" in record:
        return False
    if kind in ("book", "file"):
        return True
    # kind == "path"：老记录直接拿路径当键，文件夹也可能长这样。
    # 先看路径本身是不是目录，再用有没有扩展名兜底（目录名带点的情况极少）
    file_path = str(record.get("file_path") or "")
    try:
        if file_path and Path(file_path).is_dir():
            return False
    except OSError:
        pass
    return bool(Path(file_path).suffix)


def _collapse_units(read_chapters):
    """把多个统计单元合并成单个 ``"*"``。

    单文件模式的记录整条就对应这本书，单元名其实不参与展示（只是为了统计
    去重），而文件改名、装过不同版本时会在同一个记录里留下好几个单元名，
    每个名字都会把同一批章节再数一遍。归一成 ``"*"`` 之后已读章节数才不会翻倍。
    """
    indexes = set()
    for items in (read_chapters or {}).values():
        indexes.update(items)
    if not indexes:
        return dict(read_chapters or {})
    return {"*": sorted(indexes)}


class ReadingProgressManager:
    def __init__(self):
        self.save_path = SAVE_PATH
        self.save_path.mkdir(parents=True, exist_ok=True)
        # 路径 -> ((mtime_ns, size), file_key)：避免自动保存时反复读取整本书
        self._key_cache = {}
        # 路径 -> ((mtime_ns, size), 内容 MD5)：记录里的 file_md5 用，同样要缓存
        self._digest_cache = {}

    # ---------------- 记录键 ----------------

    def content_digest(self, file_path):
        """文件内容的 MD5（带缓存；读不到时返回空串）

        与记录键无关，只用来标记「这是这本书的哪一版」。自动保存会频繁调用，
        所以按 ``(mtime, size)`` 缓存，文件没动过就不重复读整本书。
        """
        path = Path(str(file_path))
        try:
            stat = path.stat()
        except OSError as e:
            logger.log(f"无法读取 {path} 的信息，记录中省略内容哈希: {e}", "WARN")
            return ""

        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._digest_cache.get(str(path))
        if cached and cached[0] == stamp:
            return cached[1]

        try:
            digest = content_hash(path)
        except OSError as e:
            logger.log(f"计算文件内容哈希失败，记录中省略该字段: {e}", "WARN")
            return ""

        self._digest_cache[str(path)] = (stamp, digest)
        return digest

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
                logger.log(f"阅读记录已迁移到新记录键: {legacy.get('file_path', legacy_key)}")
                return self._upgrade_record(legacy, file_key)

        return {}

    # ---------------- 书本身份 ----------------

    def _record_covers_file(self, record, content_key, file_path=""):
        """这条记录里有没有当前这个文件（弱身份识别用，见 :func:`record_covers_file`）"""
        return record_covers_file(record, content_key, file_path)

    def plan_record_key(self, content_key, identity, file_path=""):
        """规划这次打开书籍该用哪个记录键（只读，不落盘）。

        ``content_key`` 是按内容（或文件夹路径）算出的键，``identity`` 是
        :func:`enm.managers.book_identity.build_identity` 算出的身份签名，
        ``file_path`` 是当前文件路径（弱身份时用来判断记录是不是就是这个文件的）。
        返回的规划交给 :meth:`apply_record_key` 执行：

        * ``key`` —— 最终要用的记录键（身份可用时是 ``book:<book_id>``）；
        * ``sources`` —— 可以直接合并进来的记录 ``[(记录文件, 记录, 原因)]``；
        * ``candidates`` —— 需要用户点头才能合并的候选记录；
        * ``weak`` —— 身份是弱身份（只按书名），此时任何合并都必须用户点头；
        * ``match`` —— ``identity`` / ``content`` / ``title`` / ``""``，
          说明这次是靠什么认出来的（写日志、给提示用）。
        """
        plan = {"content_key": content_key, "key": content_key, "weak": False,
                "sources": [], "candidates": [], "match": ""}

        book_id = str((identity or {}).get("book_id") or "")
        weak_id = str((identity or {}).get("weak_id") or "")
        if not book_id and not weak_id:
            return plan

        # 弱身份（只按书名算出来的）只保证「同名」，不能保证「同书」：
        # 除了明确是当前这个文件自己的记录，其余一律走「问用户」那条路
        weak = not book_id
        plan["weak"] = weak
        target_key = f"{BOOK_KEY_PREFIX}{book_id or weak_id}"
        target_file = self.get_progress_file_path(target_key)
        plan["key"] = target_key

        for progress_file, record in self.iter_records():
            aliases = [str(item) for item in (record.get("aliases") or [])]
            record_key = record_file_key(record)

            if progress_file == target_file:
                # 记录本来就落在身份键上：强身份直接认；弱身份得先看这条记录里
                # 有没有当前这个文件，否则它可能是同名另一本书留下的
                if weak:
                    if self._record_covers_file(record, content_key, file_path):
                        plan["match"] = "content"
                    else:
                        plan["candidates"].append((progress_file, record, "title"))
                else:
                    plan["match"] = "identity"
                continue

            if record_key == target_key or target_key in aliases:
                # 别的版本已经把进度合并到这把身份键上过。强身份要沿用**那条记录
                # 的键**，否则另一个版本每次打开都会把记录在两把键之间搬来搬去
                # （还会连带删掉对方的文件）。弱身份不敢替用户认这个账
                if weak:
                    plan["candidates"].append((progress_file, record, "title"))
                    continue
                if record_key != target_key and record_key.startswith(BOOK_KEY_PREFIX):
                    plan["key"] = record_key
                plan["sources"].append((progress_file, record, "identity"))
            elif content_key and (record_key == content_key or content_key in aliases):
                # 就是这个文件（副本）以前留下的记录，直接迁过来
                plan["sources"].append((progress_file, record, "content"))
            elif weak and self._record_covers_file(record, content_key, file_path):
                # 弱身份：记录键虽然对不上，但记录里记着当前这个文件
                plan["sources"].append((progress_file, record, "content"))
            else:
                strength = match_strength(record, identity)
                if strength == "strong" and not weak:
                    plan["sources"].append((progress_file, record, "identity"))
                elif strength:
                    # 书名对得上、章节结构对不上（或记录太老没有指纹、身份本身就
                    # 只有书名）：交给用户点头，绝不静默合并
                    plan["candidates"].append((progress_file, record, "title"))

        reasons = [reason for _file, _record, reason in plan["sources"]]
        if "identity" in reasons:
            plan["match"] = "identity"
        elif "content" in reasons:
            plan["match"] = "content"
        elif plan["candidates"]:
            plan["match"] = "title"
        if not plan["match"] and not weak and target_file.exists():
            # 记录本来就落在书本身份键上（以前已经共用过），也算认出了身份
            plan["match"] = "identity"
        return plan

    def apply_record_key(self, plan, confirmed=()):
        """执行 :meth:`plan_record_key` 的规划，返回最终使用的记录键。

        ``confirmed`` 是需要用户点头之后才合并的候选记录文件路径（可迭代）。
        没在里面的候选原样留在磁盘上（用户选了「保持独立」）。
        合并完成后源记录文件会被删掉，它们的记录键会记进新记录的 ``aliases``，
        这样以后拿任意一个版本打开都能直接认出这条记录。

        弱身份（``plan["weak"]``）额外守一道：连身份键上的那条记录都可能是同名
        另一本书的，用户没点头时绝不碰它，直接让这本书继续用自己的内容键。
        """
        target_key = str((plan or {}).get("key") or "")
        if not target_key:
            return ""

        confirmed = {str(Path(item)) for item in (confirmed or ())}
        target_file = self.get_progress_file_path(target_key)

        if plan.get("weak"):
            rejected = {str(Path(item[0])) for item in (plan.get("candidates") or [])
                        if str(Path(item[0])) not in confirmed}
            if str(target_file) in rejected:
                # 身份键上那条记录不是这个文件的，用户又选了「各自独立」：
                # 写进去就把别人的进度覆盖了
                return str(plan.get("content_key") or target_key)

        entries = []
        seen = set()

        def _add(progress_file, record):
            """把一份记录加进待合并列表（同一个文件只算一份）"""
            path = Path(progress_file)
            if str(path) in seen:
                return
            seen.add(str(path))
            entries.append((path, record))

        if target_file.exists():
            existing = self._read_file(target_file)
            if existing:
                _add(target_file, existing)
        for progress_file, record, _reason in (plan.get("sources") or []):
            _add(progress_file, record)
        for progress_file, record, _reason in (plan.get("candidates") or []):
            if str(Path(progress_file)) in confirmed:
                _add(progress_file, record)

        if not entries:
            return target_key

        # 最新的一份做底（位置信息以它为准），其余按时间从新到旧合并进来；
        # 排序是稳定的，时间一样时目标记录留最前面
        entries.sort(key=lambda item: _record_time(item[1]), reverse=True)
        merged = entries[0][1]
        for _progress_file, record in entries[1:]:
            merged = merge_records(merged, record)

        aliases = {str(item) for item in (merged.get("aliases") or []) if item}
        for progress_file, record in entries:
            if progress_file == target_file:
                continue
            record_key = record_file_key(record)
            if record_key and record_key != target_key:
                aliases.add(record_key)
            aliases.update(str(item) for item in (record.get("aliases") or []) if item)
        aliases.discard(target_key)
        merged["aliases"] = sorted(aliases)

        if not self.save_progress(target_key, merged):
            return target_key

        for progress_file, _record in entries:
            if progress_file != target_file:
                self.delete_record_file(progress_file)
        logger.log(f"阅读记录已合并到书本身份（{len(entries)} 份记录）")
        return target_key

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

        # 身份字段：老记录只有 novelname / author，这里现算一份归一化键补上，
        # 不用等下次保存就能参与「是不是同一本书」的比对
        if not progress.get("title_key"):
            progress["title_key"] = normalise_title(progress.get("novelname"))
        if not progress.get("author_key"):
            progress["author_key"] = normalise_author(progress.get("author"))
        progress["chapter_fingerprint"] = str(progress.get("chapter_fingerprint") or "")
        progress["book_id"] = str(progress.get("book_id") or "")
        titles = progress.get("fingerprint_titles")
        if isinstance(titles, (list, tuple)):
            progress["fingerprint_titles"] = [str(item) for item in titles]
        else:
            progress["fingerprint_titles"] = []
        progress["aliases"] = sorted({str(item) for item in (progress.get("aliases") or []) if item})
        progress["versions"] = normalise_versions(progress.get("versions"))

        # 统计数据：旧记录没有这些字段，按默认值补齐后再做一次类型规范化
        for field, default in DEFAULT_STATS.items():
            if field not in progress:
                progress[field] = copy.deepcopy(default)

        progress["open_count"] = _as_int(progress.get("open_count"))
        progress["total_read_seconds"] = _as_float(progress.get("total_read_seconds"))
        progress["session_read_seconds"] = _as_float(progress.get("session_read_seconds"))
        progress["read_chapters"] = normalise_read_chapters(progress.get("read_chapters"))
        if _is_single_file_record(progress, kind):
            progress["read_chapters"] = _collapse_units(progress["read_chapters"])
        progress["read_chapter_count"] = sum(len(v) for v in progress["read_chapters"].values())
        progress["max_chapter"] = _as_int(progress.get("max_chapter"))

        return progress

    def save_progress(self, file_key, progress_data):
        """保存阅读进度

        写入前会补全记录信封字段（``key_type`` / ``md5`` / ``filename`` /
        ``record_version`` / ``saved_at``），调用方无需关心。

        ``aliases`` 与 ``versions`` 是管理器自己维护的“累积状态”（调用方每次都
        只提供当前位置与统计），因此写盘前会先读一次旧记录把它们接上，
        免得每次保存都把它们冲掉。
        """
        progress_file = self.get_progress_file_path(file_key)
        record = dict(progress_data or {})
        previous = self._read_file(progress_file)
        if not isinstance(previous, dict):
            previous = {}

        kind, digest = split_file_key(file_key)
        # 键与摘要必须一致（record_file_key() 靠它反推记录键），旧记录里可能带着
        # 另一个键算出来的摘要，这里一律以实际使用的键为准
        record["key_type"] = kind
        record["md5"] = digest
        file_path = record.get("file_path")
        if not record.get("filename") and file_path:
            record["filename"] = Path(str(file_path)).name
        record["record_version"] = RECORD_VERSION
        record["saved_at"] = format_timestamp()

        # 单文件模式：多份记录（改过名 / 不同版本）合并后可能留下好几个统计单元，
        # 归一到 "*" 才不会把同一批章节数好几遍
        if _is_single_file_record(record, kind):
            record["read_chapters"] = _collapse_units(
                normalise_read_chapters(record.get("read_chapters")))
            record["read_chapter_count"] = sum(
                len(items) for items in record["read_chapters"].values())
            record["max_chapter"] = _as_int(record.get("max_chapter"))

        aliases = {str(item) for item in (record.get("aliases") or []) if item}
        aliases.update(str(item) for item in (previous.get("aliases") or []) if item)
        record["aliases"] = sorted(aliases)
        record["versions"] = upsert_version(
            merge_versions(previous.get("versions"), record.get("versions")),
            {
                "filename": record.get("filename"),
                "file_path": file_path,
                "file_md5": record.get("file_md5"),
                "file_size": record.get("file_size"),
                "total_chapters": record.get("total_chapters"),
                "last_seen_at": record["saved_at"],
            })

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
