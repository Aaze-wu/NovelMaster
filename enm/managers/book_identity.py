# -*- coding: utf-8 -*-
"""同一本书的「身份」识别。

阅读记录过去以**整文件内容**的 MD5 为键，于是同一本书只要重新导出、追加了新
章节、换了文件格式，就会被当成一本新书：阅读位置、统计、已读章节全部从零开始。
本模块负责算出一个稳定的「书本身份」，让这些版本落到同一份阅读记录上。

身份由两部分共同决定（**双重校验**）：

* **书名** —— :func:`normalise_title` 归一化：全角转半角、去掉电子书扩展名、
  拆掉书名号、丢掉括号注释、去掉空白、转小写。于是 ``[作者]书名(全本).epub``、
  ``《书名》``、元数据里的 ``书名`` 会落到同一个键上；
* **章节标题指纹** —— :func:`chapter_fingerprint` 取**开头几章**的标题归一化后
  做 MD5。追加新章节、重新排版都不会改动前几章的标题，所以「更新版」照样认得出来。

章节标题指纹有个必须防住的退化场景：书的章节名是程序自动编号的
（``第 1 章`` / ``第 3 节`` / ``Page 2`` / ``Chapter One``），此时**任何两本书的
前三章标题都长得一样**，指纹完全没有区分度；而且这类标题还是按界面语言临时生成的
（见 :func:`enm.readers.base.auto_title`），换个语言就变。
:func:`chapter_fingerprint` 认得出这类标题并返回空串，
:func:`build_identity` 随之给出空的 ``book_id``，但会给出一个**弱身份**
``weak_id``（只由书名算出）。弱身份只保证「同名」，不能保证「同书」
（两本叫《小说》的书完全可能），所以调用方**绝不能**用它静默合并，
只能拿去请用户确认（见 :meth:`enm.managers.ReadingProgressManager.plan_record_key`）。

本模块是纯 Python（不导入 Qt、不碰文件系统），可以单独测试。
"""

import hashlib
import re
import unicodedata

# 与 readers.factory.EXTENSION_READERS 一一对应的扩展名，只用于把「书名.epub」
# 还原成书名。漏掉几个只会让归一化少剥一层后缀（书名字典里多一个键），不会出错；
# 验证脚本里有一条断言盯着它别跟注册表漂移。
EBOOK_EXTENSIONS = frozenset((
    ".epub", ".txt", ".pdf", ".mobi", ".azw", ".azw3", ".prc", ".docx",
    ".fb2", ".umd", ".html", ".htm", ".xhtml", ".jar", ".zip",
))

# 书名号：只是包裹，不算注释，直接去掉
_WRAP_CHARS = "《》〈〉「」『』"
_WRAP_DELETE = {ord(char): None for char in _WRAP_CHARS}

# 括号注释：连同内容一起丢掉（``书名（全本）`` -> ``书名``），支持嵌套
_GROUP_OPEN = "([{【〈（［｛"
_GROUP_CLOSE = ")]}】〉）］｝"

# 归一化后剪掉的收尾符号（文件名里常见的分隔符）
_TRIM_CHARS = "-_—–.·、,，;；:：!！?？~～"

# 取样章节数：够区分「同一本书的不同版本」，又不会被后面新增的章节影响到
FINGERPRINT_SAMPLE = 3
# 少于这么多样本就当不了指纹（只有一两章的短篇会让所有书撞在一起）
MIN_FINGERPRINT_SAMPLE = 2

# 程序自动编号出来的章节名（在归一化后的文本上匹配）
_AUTO_TITLE_PATTERNS = (
    # 第12章 / 三回 / 第 3 节 / 第1卷 / 十五頁
    re.compile(r"^第?[0-9一二三四五六七八九十百千零两]+[章节節回卷篇集话話頁页]$"),
    # 第 1 - 3 页
    re.compile(r"^第?[0-9]+[-~至][0-9]+[頁页]$"),
    # 光秃秃的序号
    re.compile(r"^[0-9]+$"),
    # Chapter 1 / Chapter One / Section 2 / Page 3
    re.compile(
        r"^(chapter|section|part|page|volume|vol|book|ch|episode|ep)"
        r"\.?[-_]?(\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty)$"
    ),
)

# 整本书只有一章时常见的通用标题（对应语言文件里的 book.full_text / body /
# prologue / preface，各语言版本都会产出这几个词），同样没有区分度
_GENERIC_TITLES = frozenset((
    "全文", "正文", "序章", "前言", "后记", "尾声",
    "fulltext", "body", "text", "prologue", "preface", "foreword", "epilogue",
))


def _as_int(value, default=0):
    """尽力把值转成整数"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------- 归一化 ----------------

def normalise_chapter_title(value):
    """章节标题的轻量归一化：全角转半角 + 去掉所有空白 + 转小写。

    只做这几步是因为章节标题要用来**逐字比对**：``第1章 觉醒`` 与 ``第1章 苏醒``
    必须区分得开，所以不能像书名那样丢括号、去标点。
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(text.split()).lower()


def normalise_author(value):
    """作者的归一化形式（全角转半角 + 去空白 + 转小写）"""
    return normalise_chapter_title(value)


def strip_extension(text):
    """去掉末尾的电子书扩展名（``书名.epub`` -> ``书名``）"""
    text = str(text or "")
    lowered = text.lower()
    for extension in EBOOK_EXTENSIONS:
        if lowered.endswith(extension):
            return text[: -len(extension)]
    return text


def drop_bracket_groups(text):
    """丢掉括号注释（``书名（全本）`` -> ``书名``），支持嵌套"""
    result = []
    depth = 0
    for char in text:
        if char in _GROUP_OPEN:
            depth += 1
        elif char in _GROUP_CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0:
            result.append(char)
    return "".join(result)


def normalise_title(value):
    """书名的归一化形式，用于判断「是不是同一本书」。

    ``[作者]书名(全本).epub`` / ``《书名》`` / ``书名（完结）`` 都会落到同一个键上。
    取不到书名时返回空串。
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return ""

    text = drop_bracket_groups(strip_extension(text))
    text = text.translate(_WRAP_DELETE)
    text = "".join(text.split()).lower()
    return text.strip(_TRIM_CHARS)


# ---------------- 指纹 ----------------

def is_auto_title(value):
    """标题是不是程序自动编号出来的（``第 1 章`` / ``Page 2`` / ``Chapter One``）。

    空标题也算「认不出」（没有信息量），一并返回 ``True``。
    """
    key = normalise_chapter_title(value)
    if not key:
        return True
    return any(pattern.match(key) for pattern in _AUTO_TITLE_PATTERNS)


def is_generic_title(value):
    """标题是不是「全文」「正文」这类整本书通用的占位标题"""
    return normalise_chapter_title(value) in _GENERIC_TITLES


def chapter_fingerprint(titles, sample=FINGERPRINT_SAMPLE):
    """算出章节标题指纹，返回 ``(指纹, 参与计算的标题列表)``。

    取开头 ``sample`` 个标题归一化后拼起来做 MD5。出现下面任一情况说明这份书的
    结构**当不了身份**，返回 ``("", [])``：

    * 取到自动编号的标题或「全文」这类通用标题 —— 任何两本书都会撞在一起，
      而且这些标题还会随界面语言变化；
    * 取到的标题不足 :data:`MIN_FINGERPRINT_SAMPLE` 个；
    * 取到的标题互相重复。
    """
    try:
        sample = max(1, int(sample))
    except (TypeError, ValueError):
        sample = FINGERPRINT_SAMPLE

    picked = []
    for title in titles or ():
        text = normalise_chapter_title(title)
        if is_auto_title(text) or text in _GENERIC_TITLES:
            return "", []
        picked.append(text)
        if len(picked) >= sample:
            break

    if len(picked) < MIN_FINGERPRINT_SAMPLE:
        return "", []
    if len(set(picked)) != len(picked):
        return "", []

    digest = hashlib.md5("\x1f".join(picked).encode("utf-8")).hexdigest()
    return digest, picked


def build_identity(title, titles, author="", total_chapters=0):
    """算出书本身份签名。

    ``titles`` 只需要开头的几个章节标题（多了也无妨）。返回的字典里：

    * ``book_id`` —— 书名与章节指纹都算得出来时的**强身份**，可以静默共用进度；
    * ``weak_id`` —— 只有书名算得出来（章节名是自动编号的、章节太少、开头几章
      重名……）时的**弱身份**。它只保证「同名」，因此调用方只能拿它去问用户，
      用户点头才合并。两个字段不会同时有值，也都可能为空（连书名都空 ⇒ 连
      弱身份都算不出来，只能退回按内容哈希的老行为）。
    """
    title_key = normalise_title(title)
    author_key = normalise_author(author)
    fingerprint, sampled = chapter_fingerprint(titles)

    book_id = ""
    weak_id = ""
    if title_key:
        if fingerprint:
            seed = f"{title_key}\x1f{fingerprint}".encode("utf-8")
            book_id = hashlib.md5(seed).hexdigest()
        else:
            weak_id = hashlib.md5(title_key.encode("utf-8")).hexdigest()

    return {
        "title": str(title or "").strip(),
        "title_key": title_key,
        "author_key": author_key,
        "chapter_fingerprint": fingerprint,
        "fingerprint_titles": sampled,
        "book_id": book_id,
        "weak_id": weak_id,
        "total_chapters": _as_int(total_chapters),
    }


# ---------------- 记录之间的比对 ----------------

def record_identity(record):
    """从阅读记录里取出身份字段。

    老记录没有 ``title_key`` / ``author_key``，就地用 ``novelname`` / ``author``
    现算一份，这样不用等重写记录也能参与比对。
    """
    if not isinstance(record, dict):
        return {}

    title_key = str(record.get("title_key") or "") or normalise_title(record.get("novelname"))
    author_key = str(record.get("author_key") or "") or normalise_author(record.get("author"))
    return {
        "title_key": title_key,
        "author_key": author_key,
        "chapter_fingerprint": str(record.get("chapter_fingerprint") or ""),
        "book_id": str(record.get("book_id") or ""),
    }


def match_strength(record, identity):
    """判断一条记录与当前书有多像。

    * ``"strong"`` —— 书名、作者、章节指纹全对上，可以**静默**共用进度；
    * ``"weak"`` —— 书名对上了，但作者冲突、或章节指纹对不上（记录太老没有指纹、
      新版本开头被重排过、同名不同书……），**必须问过用户**再合并；
    * ``""`` —— 不是同一本书。
    """
    record_id = record_identity(record)
    if not record_id or not identity:
        return ""

    title_key = str(identity.get("title_key") or "")
    if not title_key or not record_id["title_key"] or record_id["title_key"] != title_key:
        return ""

    # 作者只在两边都有值时才参与判断（TXT 常常没有作者，同一本书的 EPUB 有）
    author_key = str(identity.get("author_key") or "")
    if record_id["author_key"] and author_key and record_id["author_key"] != author_key:
        return "weak"

    fingerprint = str(identity.get("chapter_fingerprint") or "")
    if record_id["chapter_fingerprint"] and fingerprint and \
            record_id["chapter_fingerprint"] == fingerprint:
        return "strong"
    return "weak"


def chapter_index_in(titles, index, title=""):
    """在新版本里定位原来读到的那一章。

    先按章节标题找（同名章节取离原下标最近的那个），找不到再退回**夹到有效范围**
    的下标 —— 新版本基本都是往后追加章节，原下标本身往往就是对的。
    """
    count = len(titles or ())
    if count <= 0:
        return 0

    index = max(0, min(count - 1, _as_int(index)))

    wanted = normalise_chapter_title(title)
    if not wanted:
        return index
    if normalise_chapter_title(titles[index]) == wanted:
        return index

    best = None
    for position, item in enumerate(titles):
        if normalise_chapter_title(item) == wanted:
            if best is None or abs(position - index) < abs(best - index):
                best = position
    return index if best is None else best


__all__ = [
    "EBOOK_EXTENSIONS", "FINGERPRINT_SAMPLE", "MIN_FINGERPRINT_SAMPLE",
    "normalise_title", "normalise_author", "normalise_chapter_title",
    "strip_extension", "drop_bracket_groups",
    "is_auto_title", "is_generic_title", "chapter_fingerprint",
    "build_identity", "record_identity", "match_strength", "chapter_index_in",
]
