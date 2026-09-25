"""JAR 手机电子书（JavaBook / 杰奇 CMS）解析 —— 纯标准库实现。

手机 Java 电子书（``.jar``）不是「压缩包里放着一本电子书」，而是一个 Java ME
（MIDP）程序：一个 MIDlet 外壳 + 一整本书的正文。桌面端过去只能把它当压缩包
处理（挑包内的 EPUB/TXT），正文自然一条也读不到（正文条目没有扩展名）。
本模块按格式本身解析：

* ``META-INF/MANIFEST.MF`` —— ``MIDlet-Name`` 是书名，也是识别格式的依据：
  ``MIDlet-1`` 里出现 ``JavaBook``，或 ``MIDlet-Vendor`` 里出现 ``jieqi``；
* 正文是一批**纯数字名**的条目（``1`` … ``N``，没有扩展名），内容为
  无 BOM 的 **UTF-16LE**（``3c 00`` = ``<``），第一行形如 ``<章节标题>``，
  其后是正文；
* 目录条目 ``0`` 是一串 Java ``DataOutputStream.writeUTF`` 字符串
  （2 字节大端长度 + UTF-8）：``"0"``（格式版本）、书名、章节数，随后是
  ``N`` 条 ``"序号,字节数,标题"``，末尾还会跟一段「书名：… 作者：…」制作信息；
* ZIP 内部的条目顺序与章节顺序无关，章节顺序只认目录里的序号。

所以这里把「目录」和「正文」分开解析：目录给出章节顺序、标题、作者，正文按目录
顺序逐条解码；没有目录的变体退化成「按数字升序 + 取正文首行标题」。
"""

import re
import zipfile

from ..logger import logger
from .base import BaseReader, ReaderError, decode_bytes, strip_tags

# 目录条目名。正文条目叫 "1" … "N"，目录固定叫 "0"
CATALOG_NAME = '0'

# 目录里每条记录都写成 "序号,字节数,标题"
_CATALOG_ITEM_RE = re.compile(r'^(\d+),(\d+),([\s\S]*)$')
# 正文条目首行的标题行：<第一卷 序章>
_ENTRY_TITLE_RE = re.compile(r'^<([^<>]+)>$')
# 制作信息里的作者行：作者：森田季节
_AUTHOR_RE = re.compile(r'^[ \t]*(?:作者|著者|原作)[ \t]*[:：][ \t]*([^\r\n]+?)[ \t]*$',
                        re.MULTILINE)
# 正文条目的名字是纯数字
_NUMERIC_NAME_RE = re.compile(r'^\d+$')


def parse_properties(text):
    """解析 ``Key: Value`` 形式的清单 / MIDlet 描述文件，键名统一转小写

    按 JAR 清单规范处理续行：以单个空格开头的行接在上一个值后面
    （清单的值超过 72 字节就会被折行，书名长的电子书很容易触发）。
    """
    properties = {}
    key = None
    for line in (text or '').splitlines():
        if not line.strip():
            key = None
            continue
        if line.startswith(' ') and key:
            properties[key] += line[1:]
            continue

        name, separator, value = line.partition(':')
        if not separator:
            key = None
            continue
        key = name.strip().lower()
        properties[key] = value.strip()
    return properties


def read_manifest(archive):
    """读取 JAR 清单（``META-INF/MANIFEST.MF``），返回小写键字典"""
    for name in archive.namelist():
        normalized = name.replace('\\', '/')
        if normalized.lower() != 'meta-inf/manifest.mf':
            continue
        try:
            raw = archive.read(name)
        except (KeyError, RuntimeError, zipfile.BadZipFile, OSError) as e:
            logger.log(f"读取 JAR 清单失败: {e}", "ERROR")
            return {}
        return parse_properties(decode_bytes(raw))
    return {}


def parse_utf_strings(data):
    """按 Java ``writeUTF`` 规则拆出一串字符串；结构不符时返回 None

    ``writeUTF`` = 2 字节大端长度 + 修改版 UTF-8 内容。目录条目就是这一串字符串
    首尾相接拼起来的，没有额外的文件头。结构对不上（长度越界、非法 UTF-8）
    就返回 None，调用方据此判定「这不是目录」。
    """
    strings = []
    position = 0
    total = len(data)

    while position < total:
        if total - position < 2:
            return None
        size = int.from_bytes(data[position:position + 2], 'big')
        position += 2
        if total - position < size:
            return None
        try:
            strings.append(data[position:position + size].decode('utf-8'))
        except UnicodeDecodeError:
            return None
        position += size

    return strings or None


def parse_catalog(data):
    """解析目录条目，返回 ``{'title', 'count', 'items', 'extra'}``；非目录时 None

    ``items`` 是 ``[(序号, 字节数, 标题), ...]``（保持目录里的先后顺序），
    ``extra`` 是章节表之后剩下的字符串，通常只有一段制作信息。
    """
    strings = parse_utf_strings(data)
    if not strings or len(strings) < 4:
        return None

    items = []
    for text in strings[3:]:
        match = _CATALOG_ITEM_RE.match(text.strip())
        if not match:                       # 章节表结束（后面是制作信息）
            break
        items.append((int(match.group(1)), int(match.group(2)),
                      strip_tags(match.group(3))))
    if not items:
        return None

    try:
        count = int(strings[2].strip())
    except ValueError:
        count = len(items)

    return {'title': strip_tags(strings[1]), 'count': count, 'items': items,
            'extra': strings[3 + len(items):]}


def decode_entry_text(raw):
    """解码正文条目：无 BOM 的 UTF-16 为主，其余交给通用编码探测"""
    if not raw:
        return ""

    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):       # 带 BOM 时按 BOM 走
        return decode_bytes(raw)

    # 无 BOM 的 UTF-16：``<`` ``>`` ``\r`` ``\n`` 这些 ASCII 字符会在固定的一侧
    # 留下 0x00（LE 在奇数位、BE 在偶数位）。纯文本里不会有 0x00，信号很干净。
    low_null = raw[1::2].count(0)
    high_null = raw[0::2].count(0)
    if low_null or high_null:
        if len(raw) % 2:                            # 长度落单时丢掉最后 1 字节
            raw = raw[:-1]
        encoding = 'utf-16-le' if low_null >= high_null else 'utf-16-be'
        return raw.decode(encoding, errors='replace')

    return decode_bytes(raw)


def split_entry_title(text):
    """拆出正文首行的 ``<标题>``，返回 ``(标题, 正文)``

    只认**第一个非空行**：它是 ``<…>`` 才算章节标题，否则整段都是正文
    （少数生成器不写标题行）。
    """
    normalized = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    lines = normalized.split('\n')

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = _ENTRY_TITLE_RE.match(stripped)
        if not match:
            break
        title = strip_tags(match.group(1)).strip()
        return title, '\n'.join(lines[index + 1:]).strip()

    return "", normalized.strip()


def count_numeric_entries(archive):
    """包内根目录下的「纯数字名」条目，返回 ``[(数值, 条目名), ...]``（数值升序）

    第二个元素是 ZIP 里的原始条目名，读内容时要用它。
    """
    entries = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace('\\', '/')
        if name.startswith('./'):
            name = name[2:]
        if not _NUMERIC_NAME_RE.match(name):
            continue
        entries.append((int(name), info.filename))

    entries.sort(key=lambda item: item[0])
    return entries


class JarBookReader(BaseReader):
    """JavaBook / 杰奇 CMS 手机电子书（``.jar``）阅读器

    识别见 :meth:`detect`：有能解析的目录条目 ``0``，或清单里有 JavaBook /
    jieqi 特征，或包内存在多个纯数字名条目。解析不出来时抛
    :class:`ReaderError`，交给调用方退回压缩包逻辑。
    """

    # 与 ArchiveReader 一致的解压保护
    MAX_TOTAL_SIZE = 512 * 1024 * 1024
    MAX_CHAPTERS = 20000

    def __init__(self, file_path):
        super().__init__(file_path)
        self.load()

    # ---------------- 格式识别 ----------------

    @classmethod
    def detect(cls, file_path):
        """判断 ``.jar`` / ``.zip`` 是否为手机 Java 电子书（打不开或不符合返回 False）"""
        try:
            with zipfile.ZipFile(file_path) as archive:
                return cls._looks_like_book(archive)
        except (zipfile.BadZipFile, OSError, RuntimeError) as e:
            logger.log(f"检查 JAR 结构失败: {e}", "ERROR")
            return False

    @classmethod
    def _looks_like_book(cls, archive):
        names = set(archive.namelist())
        if CATALOG_NAME in names:
            try:
                if parse_catalog(archive.read(CATALOG_NAME)):
                    return True
            except (KeyError, RuntimeError, zipfile.BadZipFile, OSError):
                pass

        manifest = read_manifest(archive)
        if 'javabook' in manifest.get('midlet-1', '').lower():
            return True
        if 'jieqi' in manifest.get('midlet-vendor', '').lower():
            return True

        # 没有清单特征也没有目录时的兜底：一堆纯数字名的条目
        return bool(manifest) and len(count_numeric_entries(archive)) >= 3

    # ---------------- 解析 ----------------

    def load(self):
        try:
            archive = zipfile.ZipFile(self.file_path)
        except (zipfile.BadZipFile, OSError) as e:
            raise ReaderError(f"无法打开 JAR（仅支持 ZIP/JAR）: {e}") from e

        with archive:
            manifest = read_manifest(archive)
            catalog = self._read_catalog(archive)
            entries = count_numeric_entries(archive)

            plan = self._chapter_plan(catalog, entries)
            if not plan:
                raise ReaderError("JAR 中没有找到手机电子书正文"
                                  "（既不是 JavaBook 格式，也没有可阅读的文本条目）")

            self._read_chapters(archive, plan)

            title = (manifest.get('midlet-name')
                     or (catalog or {}).get('title', ''))
            self._set_book_info(title, self._catalog_author(catalog))
        self._finish()

    def _read_catalog(self, archive):
        """读取并解析目录条目（没有或不是目录时返回 None）"""
        if CATALOG_NAME not in set(archive.namelist()):
            return None
        try:
            return parse_catalog(archive.read(CATALOG_NAME))
        except (KeyError, RuntimeError, zipfile.BadZipFile, OSError) as e:
            logger.log(f"读取 JAR 目录失败: {e}", "ERROR")
            return None

    def _chapter_plan(self, catalog, entries):
        """算出 ``[(条目名, 目录里的标题), ...]``（章节顺序以目录为准）"""
        by_index = {index: name for index, name in entries}
        plan = []
        used = set()

        if catalog:
            for index, _size, title in catalog['items']:
                name = by_index.get(index)
                if name is None or name in used:
                    continue
                used.add(name)
                plan.append((name, title))
            if not plan:
                logger.log("JAR 目录与条目名对不上，改用数字顺序", "WARNING")

        # 目录缺失、对不上，或目录漏掉的条目：按数字升序补在后面（标题取正文首行）
        for _index, name in entries:
            if name != CATALOG_NAME and name not in used:
                plan.append((name, ""))

        return plan

    def _read_chapters(self, archive, plan):
        """按顺序读正文，解码后登记为章节"""
        total = 0
        for name, catalog_title in plan[:self.MAX_CHAPTERS]:
            try:
                raw = archive.read(name)
            except (KeyError, RuntimeError, zipfile.BadZipFile, OSError) as e:
                logger.log(f"读取 JAR 章节 {name} 失败: {e}", "ERROR")
                continue

            total += len(raw)
            if total > self.MAX_TOTAL_SIZE:
                logger.log("JAR 正文字节数超过上限，已截断", "WARNING")
                break

            title, body = split_entry_title(decode_entry_text(raw))
            # 标题优先用目录里的（目录才是真正的章节表），其次取正文首行；
            # 正文为空的条目（例如只剩标题的插图页）由 _add_chapter 自行跳过
            self._add_text_chapter(title or catalog_title or None, body)

    @staticmethod
    def _catalog_author(catalog):
        """从目录末尾的制作信息里取作者（``作者：森田季节``）

        制作信息是一段 ``\r\n`` 分隔的多行文本，先归一化换行再匹配，
        否则 ``$`` 会卡在 ``\r`` 上匹配不上。
        """
        text = '\n'.join((catalog or {}).get('extra') or ())
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        match = _AUTHOR_RE.search(text)
        return strip_tags(match.group(1)).strip() if match else ""
