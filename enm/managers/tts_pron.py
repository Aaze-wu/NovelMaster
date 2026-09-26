# -*- coding: utf-8 -*-
"""朗读读音纠正（多音字 / 异读字）。

在线与离线引擎都会读错一部分多音字（银行 xíng、重新 zhòng、单薄 báo……）。
免费引擎基本不给「喂读音」的口子，所以这里换一条路：**同音字替换**。把读错的
字换成读音相同、而且只有这一个读音的常用字——

    银行 → 银航    重新 → 崇新    单薄 → 单博    秘鲁 → 必鲁

对合成器来说这只是换了个字，读音完全一样（实测 MFCC+DTW 声学距离 0，见
``tools/audit_pronunciation.py``），但它绕开了「引擎得过 SSML」这个前提，
四个引擎一视同仁。为什么不做 SSML：

* 在线引擎 ``edge`` 的免费接口**只收纯文本**。把 ``<speak>`` / ``<prosody>`` /
  ``<phoneme>`` / ``<sub>`` / 内联发音词典 12 种写法挨个试过，全部返回
  ``NoAudioReceived``；对照组的 ``&amp;`` 转义实体和纯文本都能正常出声，合法
  的 ``<s>`` 也照样失败 —— 不是转义问题，是服务端直接拒绝；
* ``SapiComBackend`` 那边其实可以拼 SSML（``Speak`` 的第二参数加
  ``SVSFIsXML``），但同一套替换文本在四个引擎上都能用，没有必要为它单独开分支。

三层，优先级从高到低，同一段文本里**各层只对原文算一次**，最后按
「用户词典 > 内置规则 > 自动推断」解决重叠，不存在「替换完再被替换」的连锁：

1. **用户词典** —— ``%APPDATA%/NovelMaster/pronunciation.json``，设置里有可视化
   编辑页。每条形如「词 → 改成什么」，也可以把「改成什么」写成原词本身，表示
   「这个词别动」（同时挡住自动层）；
2. **内置规则** —— :data:`BUILTIN_RULES`，实测确认过的高频词，开箱即用。用户
   词典里的同名条目会覆盖它；
3. **自动推断** —— 用 ``pypinyin`` 做上下文注音，只在读错读音时才动手。
   **默认关闭**，原因见下。

自动层有两条规则，缺一不可：

1. **安全规则**：只有「上下文读音 ≠ 这个字的默认读音」时才替换。pypinyin 的
   默认读音就是引擎自己也能读对的那个音，而 pypinyin 恰好会在「慢慢地 /
   高兴地说 / 跑得快」这类结构助词上判错（它给 ``di4`` / ``de2``，应该是轻声
   ``de``）—— 这些错判全都落在「等于默认读音」这一侧，于是被直接跳过；
2. **词表确认规则**：如果这个字在这个位置上的读音，被 pypinyin 词表
   （``phrases_dict``，四万七千个词）里的某个词确认过，就不动它。
   这条是实测逼出来的：只有安全规则时，光界面文案那五千多字里自动层就会
   提出 46 处改动，而且全都不像话 —— ``一→宜``（14 次）、``不→醭``、
   ``的→帝``、``为→维``（把 wèi 强行改成 wéi，读音都错了）。它们都是
   「字典认得的词里的字」，引擎自己的词库同样认得，根本不用插手。加上这条
   规则后同一份语料改动数为 **0**。

实测结论（``tools/audit_pronunciation.py``）： ``edge`` 这类神经引擎本身就能
按上下文读对多音字 —— 6 条对照组全对，18 条自然语料里 7 条替换前后
MFCC+DTW 距离为 **0.00**（就是一个字都没读错的铁证）。真正容易读错的是
老式 SAPI / Qt 系统语音。所以主力是**用户词典**（自己听着不对就加一条）和
**内置规则**（实测确认过的高频词），自动层当个需要手动打开的兜底开关。

这个模块是纯函数式的：不碰 Qt、不改文档文本。``SentenceSpan.start/end`` 是文档
字符位置，逐句高亮和自动滚动都靠它，所以替换**只能在 ``speak()`` 那一刻做**，
绝不能写回正文。
"""

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from ..constants import DATA_PATH
from ..logger import logger

try:                                        # 自动层用；缺了就当没有（不影响其它层）
    from pypinyin import Style as _PyStyle
    from pypinyin import pinyin as _pypinyin
    from pypinyin.style import convert as _pinyin_convert
except Exception:                           # pragma: no cover - 环境缺依赖
    _PyStyle = None
    _pypinyin = None
    _pinyin_convert = None

try:                                        # 自动层的「词典确认」判据要用
    from pypinyin.phrases_dict import phrases_dict as _PHRASES
    if not _PHRASES:                        # 极少数情况下得手动催一次
        from pypinyin.phrases_dict import load_phrases_dict as _load_phrases
        _load_phrases()
except Exception:                           # pragma: no cover - 环境缺依赖
    _PHRASES = {}

from .tts_pron_data import HOMOPHONES

# ---------------------------------------------------------------- 常量

#: 用户词典文件（放在数据目录里，跟 config.json 作伴，卸载时可一并保留）
DICT_PATH = DATA_PATH / "pronunciation.json"

#: 词典文件格式版本，将来结构变了好做迁移
DICT_VERSION = 1

LAYER_USER = "user"
LAYER_RULE = "rule"
LAYER_AUTO = "auto"

#: 层优先级：数字小的赢
_LAYER_RANK = {LAYER_USER: 0, LAYER_RULE: 1, LAYER_AUTO: 2}

_LAYER_LABEL = {LAYER_USER: "用户词典", LAYER_RULE: "内置规则", LAYER_AUTO: "自动"}

#: pypinyin 拼音样式（数字声调，如 ``yin2``）
_TONE_RE = re.compile(r"^[a-z]+[1-5]$")

#: 汉字连续段。pypinyin 会把标点/西文原样合并成一段返回，逐个字对不上号，
#: 所以自动层只对「纯汉字段」注音，长度天然 1:1。
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

#: 词典里「改成什么」填原词本身 = 不许动
KEEP_SENTINEL = ""

#: ``correct()`` 的记忆化容量（同一句 speak + preload 会各调一次）
_CACHE_SIZE = 128

# ---------------------------------------------------------------- 内置规则

#: 内置规则：``(原词, 改成, 改动字的新读音, 说明)``。
#:
#: 每条都过 ``tools/audit_pronunciation.py --static``：字数相等、没改到的字读音
#: 不变、改到的字读的就是第三个字段里声明的音。
#:
#: 为什么自动层已经能推断，这里还要手写一份：
#:
#: * **不装 pypinyin 也能用** —— 自动层靠它，内置规则不靠；
#: * **有 pypinyin 也会丢的地方** —— ``重来`` / ``弹奏`` 这类词 pypinyin 会判成
#:   默认读音，安全规则一卡就不动了，只有手写规则能补；
#: * **候选字挑得比自动层自然** —— 自动层只按常用度取第一个（``宁可`` 会拿
#:   到 ``佞``），手写能选更常见的同音字，韵律更稳。
#:
#: 用户词典里的同名条目覆盖这里。
BUILTIN_RULES: Tuple[Tuple[str, str, str, str], ...] = (
    # ---- 行 háng ----
    ("银行", "银航", "hang2", "行 háng，不是 xíng"),
    # ---- 重 chóng ----
    ("重新", "崇新", "chong2", "重 chóng，不是 zhòng"),
    ("重复", "崇复", "chong2", "重 chóng"),
    ("重叠", "崇叠", "chong2", "重 chóng"),
    ("重逢", "崇逢", "chong2", "重 chóng"),
    ("重庆", "崇庆", "chong2", "重 chóng"),
    ("重来", "崇来", "chong2", "重 chóng（pypinyin 也读错的一类）"),
    ("重申", "崇申", "chong2", "重 chóng"),
    # ---- 薄 bó / báo ----
    ("单薄", "单博", "bo2", "薄 bó，不是 báo"),
    ("薄弱", "博弱", "bo2", "薄 bó"),
    ("淡薄", "淡博", "bo2", "薄 bó"),
    ("稀薄", "稀博", "bo2", "薄 bó"),
    ("微薄", "微博", "bo2", "薄 bó"),
    ("薄雾", "博雾", "bo2", "薄 bó"),
    ("薄饼", "雹饼", "bao2", "薄 báo"),
    ("薄脆", "雹脆", "bao2", "薄 báo"),
    # ---- 秘 bì ----
    ("秘鲁", "必鲁", "bi4", "秘 bì，不是 mì"),
    # ---- 乐 yuè ----
    ("音乐", "音岳", "yue4", "乐 yuè，不是 lè"),
    ("乐器", "岳器", "yue4", "乐 yuè"),
    ("乐曲", "岳曲", "yue4", "乐 yuè"),
    ("乐章", "岳章", "yue4", "乐 yuè"),
    ("交响乐", "交响岳", "yue4", "乐 yuè"),
    # ---- 参 shēn ----
    ("人参", "人深", "shen1", "参 shēn，不是 cān"),
    ("海参", "海深", "shen1", "参 shēn"),
    # ---- 数 shǔ ----
    ("数落", "暑落", "shu3", "数 shǔ，不是 shù"),
    ("数不清", "暑不清", "shu3", "数 shǔ"),
    # ---- 畜 chù / xù ----
    ("畜生", "触生", "chu4", "畜 chù，不是 xù"),
    ("畜牧", "序牧", "xu4", "畜 xù，不是 chù"),
    # ---- 相 xiàng ----
    ("相片", "像片", "xiang4", "相 xiàng，不是 xiāng"),
    ("长相", "长像", "xiang4", "相 xiàng"),
    ("相机", "像机", "xiang4", "相 xiàng"),
    ("相册", "像册", "xiang4", "相 xiàng"),
    ("照相", "照像", "xiang4", "相 xiàng"),
    ("相貌", "像貌", "xiang4", "相 xiàng"),
    # ---- 弹 tán ----
    ("弹琴", "谈琴", "tan2", "弹 tán，不是 dàn"),
    ("弹奏", "谈奏", "tan2", "弹 tán（pypinyin 也读错的一类）"),
    ("弹射", "谈射", "tan2", "弹 tán"),
    ("弹性", "谈性", "tan2", "弹 tán"),
    ("反弹", "反谈", "tan2", "弹 tán"),
    # ---- 教 jiāo ----
    ("教书", "交书", "jiao1", "教 jiāo，不是 jiào"),
    ("教课", "交课", "jiao1", "教 jiāo"),
    # ---- 扇 shān / shàn ----
    ("扇风", "山风", "shan1", "扇 shān"),
    ("扇动", "山动", "shan1", "扇 shān"),
    ("扇子", "善子", "shan4", "扇 shàn"),
    # ---- 处 chǔ / chù ----
    ("处理", "楚理", "chu3", "处 chǔ"),
    ("相处", "相楚", "chu3", "处 chǔ"),
    ("处分", "楚分", "chu3", "处 chǔ"),
    ("处方", "楚方", "chu3", "处 chǔ"),
    ("到处", "到触", "chu4", "处 chù"),
    ("长处", "长触", "chu4", "处 chù"),
    ("好处", "好触", "chu4", "处 chù"),
    ("益处", "益触", "chu4", "处 chù"),
    # ---- 给 jǐ ----
    ("给予", "挤予", "ji3", "给 jǐ，不是 gěi"),
    ("供给", "供挤", "ji3", "给 jǐ"),
    # ---- 系 jì ----
    ("系鞋带", "计鞋带", "ji4", "系 jì，不是 xì"),
    # ---- 落 lào ----
    ("落枕", "涝枕", "lao4", "落 lào，不是 luò"),
)

# ---------------------------------------------------------------- 数据结构


@dataclass
class PronEntry:
    """用户词典里的一条。"""

    source: str
    target: str = KEEP_SENTINEL     # 空 = 保持原样（同时挡住自动层）
    note: str = ""
    enabled: bool = True

    def to_json(self) -> dict:
        data = {"source": self.source, "target": self.target}
        if self.note:
            data["note"] = self.note
        if not self.enabled:
            data["enabled"] = False
        return data

    @classmethod
    def from_json(cls, data: dict) -> "PronEntry":
        return cls(
            source=str(data.get("source", "")),
            target=str(data.get("target", "") or ""),
            note=str(data.get("note", "") or ""),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class PronFix:
    """一处替换（两个位置都是**原文**下标，改不到正文）。"""

    start: int
    end: int
    source: str
    target: str
    layer: str
    reading: str = ""

    @property
    def layer_label(self) -> str:
        return _LAYER_LABEL.get(self.layer, self.layer)


# ---------------------------------------------------------------- 小工具

_DEFAULT_READING_CACHE: dict = {}


def _default_reading(char: str) -> Optional[str]:
    """pypinyin 认定的「默认读音」= 异读表第一个。没有则 None。"""
    if char in _DEFAULT_READING_CACHE:
        return _DEFAULT_READING_CACHE[char]
    reading = None
    if _pypinyin is not None:
        try:
            got = _pypinyin(char, style=_PyStyle.TONE3, heteronym=True)
            if got and got[0]:
                reading = got[0][0]
        except Exception:                   # noqa: BLE001 - 生僻字
            reading = None
    _DEFAULT_READING_CACHE[char] = reading
    return reading


def auto_available() -> bool:
    """自动推断层能不能用（装了 pypinyin 才行）。设置界面拿它决定开关是否置灰。"""
    return _pypinyin is not None


#: ``词 → 逐字读音（数字声调）`` 的缓存，查过就留着（词量不大，只查句子里的词）
_WORD_TONE3: dict = {}


def _word_readings(word):
    """pypinyin 词表里这个词的逐字读音（每个字是元组，可能不止一个音）。

    查不到返回 ``None``。结果缓存在 :data:`_WORD_TONE3` 里。
    """
    if word in _WORD_TONE3:
        return _WORD_TONE3[word]
    result = None
    entry = _PHRASES.get(word) if _PHRASES else None
    if entry:
        try:
            result = tuple(
                tuple(_pinyin_convert(item, _PyStyle.TONE3, strict=False)
                      for item in per_char)
                for per_char in entry
            )
        except Exception:                   # noqa: BLE001 - 生僻注音串
            result = None
    _WORD_TONE3[word] = result
    return result


def _word_confirms(segment: str, offset: int, reading: str) -> bool:
    """这段里有没有 pypinyin 认得的词，正好也把这个字注成这个音。

    有的话说明这是个连词典都认得的常用词读音，引擎自己的词库多半也认得，
    不用我们插手。

    ``高兴`` 的 ``兴`` 就是这样：pypinyin 上下文注音给 ``xing4``，而
    ``heteronym`` 里排第一的是 ``xing1``，看上去“不一致”，安全规则放它过去，
    于是以前会把「高兴」改成「高性」——读音一模一样、白改。这条规则把它拦住。
    """
    length = len(segment)
    for size in (4, 3, 2):
        if size > length:
            continue
        low = max(0, offset - size + 1)
        high = min(offset, length - size)
        for start in range(low, high + 1):
            readings = _word_readings(segment[start:start + size])
            if not readings:
                continue
            if reading in readings[offset - start]:
                return True
    return False


# ---------------------------------------------------------------- 主体


class Pronouncer:
    """读音纠正器。一次 ``correct()`` = 三层替换一起算完。"""

    def __init__(self, path=None):
        self.path = path or DICT_PATH
        self._entries: List[PronEntry] = []
        self._cache: dict = {}
        self._enabled = True            # 总开关
        self._auto = False              # 自动层开关（默认关，见模块说明）
        self._warned_alignment = False
        self.load()

    # ---- 总开关 ----

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        value = bool(value)
        if value != self._enabled:
            self._enabled = value
            self._cache.clear()

    @property
    def auto_enabled(self) -> bool:
        return self._auto

    @auto_enabled.setter
    def auto_enabled(self, value: bool):
        value = bool(value)
        if value != self._auto:
            self._auto = value
            self._cache.clear()

    # ---- 词典读写 ----

    def entries(self) -> List[PronEntry]:
        """用户词典（返回副本，改它不会影响内部状态）。"""
        return [PronEntry(e.source, e.target, e.note, e.enabled)
                for e in self._entries]

    def set_entries(self, entries: Sequence[PronEntry]):
        """整表替换（设置界面的「确定」走这里）。"""
        cleaned: List[PronEntry] = []
        seen = set()
        for entry in entries:
            source = (entry.source or "").strip()
            if not source or source in seen:
                continue
            # 目标里带空格/换行会把句子读断，直接去掉
            target = re.sub(r"\s+", "", entry.target or "")
            cleaned.append(PronEntry(source, target, entry.note or "",
                                     bool(entry.enabled)))
            seen.add(source)
        # 长的排前面：同一起点上优先匹配更长的词（正则配 alternation 也按这个序）
        cleaned.sort(key=lambda e: (-len(e.source), e.source))
        self._entries = cleaned
        self._cache.clear()

    def load(self):
        """读词典；文件不存在或坏掉都退回空表（不能用坏词典卡住朗读）。

        两个开关也在这个文件里，跟词典一起走 —— 词典到哪、行为就到哪。
        """
        entries: List[PronEntry] = []
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    raw = data.get("entries", [])
                    if isinstance(raw, list):
                        entries = [PronEntry.from_json(item)
                                   for item in raw if isinstance(item, dict)]
                    self._enabled = bool(data.get("enabled", True))
                    self._auto = bool(data.get("auto", False))
                elif isinstance(data, list):       # 早期只有一个纯数组的写法
                    entries = [PronEntry.from_json(item)
                               for item in data if isinstance(item, dict)]
        except Exception as exc:            # noqa: BLE001
            logger.log(f"读音纠正词典读取失败: {exc}", "ERROR")
            entries = []
        self.set_entries(entries)

    def save(self) -> bool:
        """写词典（含两个开关）。返回是否成功。"""
        payload = {
            "version": DICT_VERSION,
            "enabled": self._enabled,
            "auto": self._auto,
            "entries": [e.to_json() for e in self._entries],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:            # noqa: BLE001
            logger.log(f"读音纠正词典保存失败: {exc}", "ERROR")
            return False

    def add_entry(self, source, target, note="") -> bool:
        source = (source or "").strip()
        if not source:
            return False
        entries = self.entries()
        target = re.sub(r"\s+", "", target or "")
        for entry in entries:
            if entry.source == source:
                entry.target = target
                if note:
                    entry.note = note
                entry.enabled = True
                self.set_entries(entries)
                return True
        entries.append(PronEntry(source, target, note))
        self.set_entries(entries)
        return True

    def remove_entry(self, source) -> bool:
        entries = [e for e in self.entries() if e.source != source]
        if len(entries) == len(self._entries):
            return False
        self.set_entries(entries)
        return True

    def revert_builtin(self, source) -> Optional[str]:
        """把某个词退回内置规则；返回内置规则的目标（没有则 None）。"""
        self.remove_entry(source)
        for word, target, _expect, _note in BUILTIN_RULES:
            if word == source:
                return target
        return None

    def user_overrides(self) -> dict:
        """内置规则里被用户词典改了目标 / 关掉的词，供设置界面标出来。"""
        result = {}
        for entry in self._entries:
            for word, target, _expect, _note in BUILTIN_RULES:
                if word == entry.source and (entry.target != target
                                             or not entry.enabled):
                    result[word] = entry
        return result

    # ---- 三层规划 ----

    def _word_map(self) -> dict:
        """``词 → (目标, 层)``。用户词典覆盖内置规则；目标为空 = 挡住不动。"""
        mapping = {}
        for word, target, _expect, _note in BUILTIN_RULES:
            mapping[word] = (target, LAYER_RULE)
        for entry in self._entries:
            if not entry.enabled:
                continue
            # target 为空 = 「保持原样」：记成 None，只用来挡住自动层
            mapping[entry.source] = (entry.target or None, LAYER_USER)
        return mapping

    def _word_plan(self, text: str) -> List[PronFix]:
        mapping = self._word_map()
        if not mapping:
            return []
        words = sorted(mapping, key=lambda w: (-len(w), w))
        pattern = re.compile("|".join(re.escape(w) for w in words))
        plan: List[PronFix] = []
        for match in pattern.finditer(text):
            word = match.group(0)
            target, layer = mapping[word]
            if target is None or target == word:
                # 挡住：保留原位（target 用原文，只为了把区间占住）
                plan.append(PronFix(match.start(), match.end(), word, word,
                                    layer))
            else:
                plan.append(PronFix(match.start(), match.end(), word, target,
                                    layer))
        return plan

    def _auto_plan(self, text: str, blocked) -> List[PronFix]:
        if not self._auto or _pypinyin is None:
            return []
        plan: List[PronFix] = []
        for run in _HAN_RE.finditer(text):
            segment = run.group(0)
            try:
                got = _pypinyin(segment, style=_PyStyle.TONE3,
                                heteronym=False, errors="default")
            except Exception as exc:        # noqa: BLE001
                logger.log(f"读音纠正注音失败: {exc}", "ERROR")
                continue
            readings = [item[0] if item else "" for item in got]
            if len(readings) != len(segment):
                # 理论上不会发生；真发生了就整段跳过，绝不能错位替换
                if not self._warned_alignment:
                    self._warned_alignment = True
                    logger.log("读音纠正：注音结果与原文长度不一致，已跳过自动层",
                               "WARNING")
                continue

            base = run.start()
            for offset, char in enumerate(segment):
                pos = base + offset
                if pos in blocked:
                    continue
                reading = readings[offset]
                if not _TONE_RE.match(reading):
                    continue
                # ★ 安全规则：跟默认读音一样就说明引擎本来就读得对，不动它
                if reading == _default_reading(char):
                    continue
                # ★ 词表确认：这个音被 pypinyin 词表里的词确认过，引擎也认得，
                #   别去改它（否则「高兴」会被改成「高性」这种白改）
                if _word_confirms(segment, offset, reading):
                    continue
                candidates = HOMOPHONES.get(reading)
                if not candidates:
                    continue
                pick = next((c for c in candidates if c != char), None)
                if pick is None:
                    continue
                plan.append(PronFix(pos, pos + 1, char, pick, LAYER_AUTO,
                                    reading))
        return plan

    def _resolve(self, plan: Sequence[PronFix]) -> List[PronFix]:
        """按层优先级解决重叠：高优先级先占位，剩下的丢掉。"""
        ordered = sorted(plan, key=lambda f: (_LAYER_RANK.get(f.layer, 9),
                                              f.start))
        chosen: List[PronFix] = []
        taken: List[Tuple[int, int]] = []
        for fix in ordered:
            if any(fix.start < end and start < fix.end
                   for start, end in taken):
                continue
            if fix.target == fix.source:
                # 「保持原样」：占住区间但不产生替换
                taken.append((fix.start, fix.end))
                continue
            taken.append((fix.start, fix.end))
            chosen.append(fix)
        chosen.sort(key=lambda f: f.start)
        return chosen

    def plan(self, text: str) -> List[PronFix]:
        """算出这段文本要改哪些地方（``correct()`` 和界面预览都用它）。"""
        if not self._enabled or not text:
            return []
        word_plan = self._word_plan(text)
        blocked = set()
        for fix in word_plan:
            blocked.update(range(fix.start, fix.end))
        auto_plan = self._auto_plan(text, blocked)
        return self._resolve(list(word_plan) + list(auto_plan))

    def correct(self, text: str) -> str:
        """把文本改成「引擎能读对」的样子。空文本 / 关掉开关都原样返回。"""
        if not self._enabled or not text:
            return text
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        plan = self.plan(text)
        if not plan:
            result = text
        else:
            pieces = []
            cursor = 0
            for fix in plan:
                pieces.append(text[cursor:fix.start])
                pieces.append(fix.target)
                cursor = fix.end
            pieces.append(text[cursor:])
            result = "".join(pieces)
        if len(self._cache) >= _CACHE_SIZE:
            self._cache.clear()
        self._cache[text] = result
        return result

    def explain(self, text: str) -> List[PronFix]:
        """``plan()`` 的别名，语义更贴设置界面的「预览」按钮。"""
        return self.plan(text)

    def diff_summary(self, text: str) -> str:
        """给界面用的一行摘要，例如 ``银行→银航；处理→处里``。"""
        fixes = self.plan(text)
        if not fixes:
            return ""
        seen = []
        for fix in fixes:
            item = f"{fix.source}→{fix.target}"
            if item not in seen:
                seen.append(item)
        return "；".join(seen)


# ---------------------------------------------------------------- 单例

_INSTANCE: Optional[Pronouncer] = None


def get_pronouncer() -> Pronouncer:
    """全局单例：朗读队列和设置界面共用同一份词典。"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Pronouncer()
    return _INSTANCE


def reset_pronouncer():
    """丢掉单例（换词典路径、测试用）。"""
    global _INSTANCE
    _INSTANCE = None


__all__ = [
    "Pronouncer", "PronEntry", "PronFix", "get_pronouncer",
    "reset_pronouncer", "BUILTIN_RULES", "DICT_PATH", "DICT_VERSION",
    "auto_available", "LAYER_USER", "LAYER_RULE", "LAYER_AUTO",
    "KEEP_SENTINEL",
]
