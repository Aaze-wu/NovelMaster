# -*- coding: utf-8 -*-
"""朗读（文字转语音）。

这个模块只管「把一段文本读出来」，不碰任何界面控件，分三层：

* :class:`TtsBackend` —— 引擎接口。本机有两个实现，都**离线可用**：

  - :class:`SapiComBackend` —— 用 ``pywin32`` 直接驱动 SAPI5 的 ``SpVoice``。
    能同时看到**经典语音库和 OneCore 语音库**，所以中文音色比 Qt 多
    （Kangkang 男声 / Yaoyao 女声）。装不了 pywin32 时自动降级；
  - :class:`QtSapiBackend` —— 走 ``PyQt5.QtTextToSpeech``，**零额外依赖**，
    但只认经典语音库。

  以后要接在线神经音色，照着同一套信号实现一个子类、在
  :func:`create_backend` 里登记即可，上层界面代码一行都不用改；
* :class:`SpeechQueue` —— 句子队列，负责「一句读完接着读下一句」、暂停 / 继续 /
  上下一句，以及换章时的状态保持；
* :func:`split_sentences` / :func:`sentences_for_blocks` —— 断句与「句子 →
  文档位置」映射，主窗口拿它做逐句高亮与自动滚动。这两个是纯函数，不依赖 Qt，
  方便直接跑测试。

关于 PyQt5 自带的 ``QtTextToSpeech``（Qt 5.15）有几处实测出来的坑，都写在
实现里了，这里先列一下：

* 绑定里**没有** ``enqueue()``，也**没有** ``aboutToFinish`` / ``sayingWord``
  这类逐词回调（那些是 Qt 6 才有的），所以只能一句一句喂，并且**做不到逐字高亮**，
  最高精度就是「句」；
* ``stop()`` 是异步的（调用后状态可能还会短暂停留在 ``Speaking``，再回 ``Ready``），
  必须把这次 ``Ready`` 吞掉，否则上层会把「停止」当成「读完」而继续往下读；
* ``availableVoices()`` 只列**当前 locale** 的语音，要枚举全部语音得先
  ``availableLocales()`` 再逐个 ``setLocale()`` 问；
* 给一个没有语音的 locale 时 Qt 只会往 stderr 打一行
  ``No voice found for given locale``，然后**沿用上一个语音**，但 ``locale()``
  会报告成上一个匹配成功的语言（例如设 ``de_DE`` 后读回来是 ``ja``）。所以
  界面上的语言 → 语音映射必须拿真实枚举结果去挑，不能想当然。
"""

import re
from collections import namedtuple

from PyQt5.QtCore import QElapsedTimer, QLocale, QObject, QTimer, pyqtSignal

try:  # 只在 Windows 上有；别的平台朗读走 Qt 自己的引擎
    import winreg
except ImportError:  # pragma: no cover - 非 Windows
    winreg = None

try:
    from locale import windows_locale as _WINDOWS_LOCALE
except ImportError:  # pragma: no cover - 非 Windows
    _WINDOWS_LOCALE = {}

from .. import i18n
from ..logger import logger

# ---------------- 断句 ----------------

#: 一句话的结束标点（中文句号、问号、感叹号、省略号、分号与英文对应符号）
SENTENCE_ENDINGS = "。！？!?…；;"

#: 结束标点后面允许跟的收尾符号（引号、括号），它们算在上一句里
CLOSING_CHARS = "」』】》〕］）”’\"'）)]"

#: 长句二次切分用的停顿符号（比句号弱，但比硬切自然）
SOFT_BREAKS = "，、,：:—–"

#: 单句最长字符数（超过就按 :data:`SOFT_BREAKS` 切，再不行硬切）
DEFAULT_MAX_CHARS = 120

MIN_MAX_CHARS = 20
MAX_MAX_CHARS = 600

#: 出现这些字符才算「有内容可读」：中日韩文字、英数字母
SPEAKABLE_RE = re.compile(
    "[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af]")

#: 行内图片之类的占位符（读不出声，也不该念出来）
OBJECT_CHAR = "\ufffc"

WHITESPACE_RE = re.compile(r"\s+")

#: 一句的朗读内容与它在文档里的位置
#: （``start`` / ``end`` 是 **文档字符位置**，主窗口用它选中高亮）
SentenceSpan = namedtuple("SentenceSpan", "text start end")


def is_speakable(text):
    """文本里是否有可读内容（纯标点、分隔线、图片占位符都算没有）"""
    return bool(SPEAKABLE_RE.search(text or ""))


def clean_speech_text(text):
    """整理成适合朗读的文本：去掉行内图片占位符、合并空白"""
    text = (text or "").replace(OBJECT_CHAR, " ")
    return WHITESPACE_RE.sub(" ", text).strip()


def split_sentences(text, max_chars=DEFAULT_MAX_CHARS, base=0):
    """把一段文本切成适合朗读的句子。

    :param text: 原始文本（一般是一个段落 / 标题块的文本）
    :param max_chars: 单句长度上限，超长句会按停顿符号二次切分
    :param base: 这段文本首字符在文档里的位置（用于把结果映射回文档）
    :return: :class:`SentenceSpan` 列表；读不出内容的片段会被丢掉

    断句规则：遇到 :data:`SENTENCE_ENDINGS` 里的标点收尾，连着后面的
    :data:`CLOSING_CHARS`（例如 ``」``）一起算作一句；换行同样收尾。这样
    ``他说：「走吧。」`` 不会被切成两半。
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []

    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_CHARS
    limit = max(MIN_MAX_CHARS, min(MAX_MAX_CHARS, limit))

    spans = []
    length = len(text)
    start = 0
    index = 0
    while index < length:
        char = text[index]
        if char in SENTENCE_ENDINGS:
            # 连着的省略号 / 感叹号一起收（「……」「！！」）
            end = index + 1
            while end < length and text[end] in SENTENCE_ENDINGS:
                end += 1
            while end < length and text[end] in CLOSING_CHARS:
                end += 1
            spans.extend(_split_long(text, start, end, limit, base))
            start = end
            index = end
            continue
        if char == "\n":
            spans.extend(_split_long(text, start, index, limit, base))
            start = index + 1
        index += 1

    spans.extend(_split_long(text, start, length, limit, base))
    return spans


def _split_long(text, start, end, limit, base):
    """切出 ``[start, end)`` 这一句；超长时按停顿符号再切几刀"""
    pieces = []
    while end - start > limit:
        cut = _soft_cut(text, start, end, limit)
        pieces.append((start, cut))
        start = cut
    pieces.append((start, end))
    return [span for span in (_make_span(text, s, e, base) for s, e in pieces)
            if span is not None]


def _soft_cut(text, start, end, limit):
    """在 ``[start, start+limit)`` 里找一个尽量靠后的停顿点作为切点"""
    best = -1
    for index in range(start + limit - 1, start + limit // 2 - 1, -1):
        if index <= start:
            break
        if text[index - 1] in SOFT_BREAKS:
            best = index
            break
    if best > start:
        return best
    # 找不到停顿点：英文尽量切在空格上，中文就硬切
    for index in range(start + limit, start + limit // 2, -1):
        if index < end and text[index - 1] == " ":
            return index
    return start + limit


def _make_span(text, start, end, base):
    """把一段区间变成 :class:`SentenceSpan`（读不出内容的返回 ``None``）"""
    if end <= start:
        return None
    raw = text[start:end]
    # 首尾空白不计入高亮范围，读起来也不会多停顿
    left = 0
    while left < len(raw) and raw[left].isspace():
        left += 1
    right = len(raw)
    while right > left and raw[right - 1].isspace():
        right -= 1
    if left >= right:
        return None
    spoken = clean_speech_text(raw[left:right])
    if not is_speakable(spoken):
        return None
    return SentenceSpan(spoken, base + start + left, base + start + right)


def sentences_for_blocks(blocks, max_chars=DEFAULT_MAX_CHARS, char_range=None):
    """把 ``[(文档位置, 文本), ...]`` 变成整章的句子表。

    主窗口按 ``QTextBlock`` 逐个取文本（``block.position()`` 就是它的文档
    位置），这里逐块断句并保留绝对位置，因此高亮时可以直接拿
    ``span.start`` / ``span.end`` 去建 ``QTextCursor``，不用再拼一遍全文——
    含图片、表格的章节也能对得上。

    :param char_range: 只要 ``(start, end)`` 这段区间内的句子（``end`` 为
        ``None`` 表示直到章末）。「只读选中内容」「从光标处开始」都靠它：
        区间外的块整块跳过，压在边界上的块只取落在区间里的那一截，位置
        仍然按它在文档里的绝对偏移算，所以高亮范围不会错位。

    注意这是**字符**区间，和 ``QTextCursor.position()`` 是同一套坐标
    （Qt 里段末换行符也算一个字符，所以块的位置 + 块文本长度 = 块末，
    区间的右边界含不含换行符都不影响断句结果）。
    """
    if char_range is None:
        start, end = None, None
    else:
        start, end = char_range
        start = 0 if start is None else int(start)
        end = None if end is None else int(end)

    sentences = []
    for position, text in blocks:
        position = int(position)
        if start is None:
            sentences.extend(split_sentences(text, max_chars=max_chars,
                                             base=position))
            continue
        block_end = position + len(text)
        if block_end <= start or (end is not None and position >= end):
            continue
        left = max(0, start - position)
        right = len(text) if end is None else min(len(text), end - position)
        if right <= left:
            continue
        sentences.extend(split_sentences(text[left:right], max_chars=max_chars,
                                         base=position + left))
    return sentences


# ---------------- 语音枚举与挑选 ----------------

#: 一个可用语音：``voice_id`` 形如 ``zh_CN|Microsoft Huihui Desktop``
VoiceInfo = namedtuple("VoiceInfo", "voice_id name locale gender")


def language_prefix(lang_code):
    """界面语言代码 → 语言前缀（``zh_TW`` → ``zh``）"""
    text = str(lang_code or "").replace("-", "_")
    return text.split("_")[0].lower()


#: 语音性别 → 语言键。两套后端的 ``gender`` 取值不一样，在这里统一收口：
#: 注册表里读出来的是 ``male`` / ``female`` 字符串，而 PyQt5 的
#: ``QVoice.Gender`` **只是个整数**（``Male=0`` / ``Female=1`` / ``Unknown=2``，
#: ``QVoice.Female.name`` 实测取不到名字），所以整数也得认。
GENDER_KEYS = {"male": "tts.voice.male", "female": "tts.voice.female"}

#: ``QVoice.Gender`` 的整数值 → 上面那套名字
GENDER_VALUES = {0: "male", 1: "female"}


def voice_gender_key(gender):
    """语音性别的语言键（认不出来返回空串，调用方跳过即可）

    先按名字试、再按整数试，所以 ``"female"`` / ``1`` / ``QVoice.Female``
    三种写法都能对上。
    """
    if gender is None or isinstance(gender, bool):
        return ""
    text = getattr(gender, "name", gender)
    text = str(text).strip().lower().rsplit(".", 1)[-1]
    if text in GENDER_KEYS:
        return GENDER_KEYS[text]
    return GENDER_KEYS.get(GENDER_VALUES.get(gender, ""), "")


def voice_label(voice, show_gender=False):
    """语音在界面上的显示名（``Microsoft Huihui Desktop`` → ``Huihui (zh_CN)``）

    ``show_gender=True`` 时补上性别（``Kangkang 男声 (zh_CN)``）。中文音色里
    Kangkang 是男声、Huihui 和 Yaoyao 都是女声，光看名字根本分不出来，
    所以语音菜单要带上它。
    """
    name = voice.name or ""
    for prefix in ("Microsoft ",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in (" Desktop",):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    key = voice_gender_key(voice.gender) if show_gender else ""
    if key:
        name = f"{name} {i18n.t(key)}"
    return f"{name} ({voice.locale})" if voice.locale else name


def pick_voice(voices, lang_code, preferred=None):
    """按界面语言挑一个语音，返回 :class:`VoiceInfo`（挑不到返回 ``None``）。

    顺序：用户上次选的 ``preferred`` → 语言完全匹配（``zh_CN``）→ 同语系
    匹配（``zh_TW`` 落到 ``zh_CN`` 的普通话语音）→ 兜底列表里的第一个。
    """
    voices = list(voices or ())
    if not voices:
        return None

    if preferred:
        for voice in voices:
            if voice.voice_id == preferred:
                return voice

    code = str(lang_code or "").replace("-", "_")
    for voice in voices:
        if voice.locale.lower() == code.lower():
            return voice

    prefix = language_prefix(lang_code)
    if prefix:
        for voice in voices:
            if voice.locale.lower().startswith(prefix):
                return voice

    return voices[0]


def order_voices(voices, lang_code):
    """按「当前界面语言优先」给语音排序，供下拉框使用"""
    prefix = language_prefix(lang_code)
    exact = str(lang_code or "").replace("-", "_").lower()
    return sorted(
        voices,
        key=lambda voice: (
            0 if voice.locale.lower() == exact
            else 1 if prefix and voice.locale.lower().startswith(prefix)
            else 2,
            voice.locale.lower(),
            voice.name,
        ))


# ---------------- 系统语音注册表（SAPI） ----------------

#: SAPI 语音的两个「语音库」（注册表位置）。
#:
#: * ``classic`` —— 经典 SAPI，``PyQt5.QtTextToSpeech`` 走的就是这一套，
#:   本机只有 David / Zira / Haruka / Huihui 四个；
#: * ``onecore`` —— Windows 10/11 的新语音库（讲述人、Cortana 用的那批），
#:   **Qt 完全看不到**（``availableEngines()`` 里只有 ``sapi``），但里面的中文
#:   音色比经典库多：除了 Huihui 还有 **Kangkang（男）** 和 **Yaoyao（女）**。
#:
#: 想拿到这批语音，只能自己按注册表路径拿 token、再用 ``SpVoice`` 直接驱动。
#: 每组是 ``(库名, 注册表子键, COM 用的完整路径)``，顺序即优先级（后面的覆盖前面的）。
SAPI_VOICE_HIVES = (
    ("classic", r"SOFTWARE\Microsoft\Speech\Voices",
     r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices"),
    ("onecore", r"SOFTWARE\Microsoft\Speech_OneCore\Voices",
     r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"),
)

#: 每个语音的 ``Attributes`` 子键里要读的值
SAPI_VOICE_ATTRS = ("Name", "Language", "Gender", "Age", "Vendor")

#: 注册表扫描结果缓存（一次进程只扫一遍；扫描只要 1ms 左右，但没必要重复）
_sapi_voice_cache = None


def _locale_from_lcid(value):
    """注册表里 ``Language`` 是十六进制 LCID（``804``）→ ``zh_CN``"""
    try:
        return _WINDOWS_LOCALE.get(int(str(value), 16), "")
    except (TypeError, ValueError):
        return ""


def sapi_base_name(name):
    """``Microsoft Huihui Desktop`` → ``huihui``（跨语音库去重用的同一个 key）"""
    text = (name or "").strip().lower()
    if text.startswith("microsoft "):
        text = text[len("microsoft "):]
    if text.endswith(" desktop"):
        text = text[:-len(" desktop")]
    return text


def sapi_registry_voices(refresh=False):
    """列出注册表里全部 SAPI 语音（经典库 + OneCore）。

    :return: ``[(voice_id, name, locale, gender, hive, token_path), ...]``，
        按注册表顺序；``voice_id`` 沿用 ``zh_CN|Microsoft Kangkang`` 这种
        「语言|名字」格式，其余字段供 :class:`VoiceInfo` 使用。

    同名语音在两个库里都有时**保留 OneCore 的那份**：OneCore 是新语音库，
    音质更好，而且这样一来 ``Microsoft Huihui Desktop`` 会被
    ``Microsoft Huihui`` 顶掉，中文列表里就只剩 Huihui / Kangkang / Yaoyao
    三个真正不同的音色，不会出现两个看起来一样的「Huihui」。
    """
    global _sapi_voice_cache
    if _sapi_voice_cache is not None and not refresh:
        return _sapi_voice_cache

    result = []
    if winreg is None:
        _sapi_voice_cache = result
        return result

    for hive, subkey, com_path in SAPI_VOICE_HIVES:
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                  subkey + r"\Tokens")
        except OSError:
            continue
        index = 0
        while True:
            try:
                child = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            info = {}
            try:
                key = winreg.OpenKey(root, child)
            except OSError:
                continue
            try:
                key_name = winreg.QueryValueEx(key, "")[0]
            except OSError:
                key_name = child
            try:
                attrs = winreg.OpenKey(key, "Attributes")
            except OSError:
                attrs = None
            if attrs is not None:
                for attr in SAPI_VOICE_ATTRS:
                    try:
                        info[attr] = winreg.QueryValueEx(attrs, attr)[0]
                    except OSError:
                        pass
            name = str(info.get("Name") or key_name)
            locale_name = _locale_from_lcid(info.get("Language"))
            voice_id = f"{locale_name}|{name}" if locale_name else name
            result.append((voice_id, name, locale_name,
                           str(info.get("Gender") or "").lower(), hive,
                           f"{com_path}\\Tokens\\{child}"))

    # 去重：同一个「语言 + 基础名」只留一个，后出现的（OneCore）覆盖先出现的
    deduped = {}
    for item in result:
        deduped[(item[2], sapi_base_name(item[1]))] = item
    _sapi_voice_cache = list(deduped.values())
    return _sapi_voice_cache


def sapi_com_available():
    """能不能用 COM 直接驱动 SAPI（需要 pywin32，且注册表里得有语音）

    只做「轻量检查」（``find_spec`` + 扫注册表，合计约 1ms），**不 import
    win32com** —— 那个要 100ms 左右，不能压在启动路径上。
    """
    if winreg is None:
        return False
    try:
        import importlib.util
        if importlib.util.find_spec("win32com") is None:
            return False
    except (ImportError, ValueError):
        return False
    return bool(sapi_registry_voices())


# ---------------- 引擎接口 ----------------


class TtsBackend(QObject):
    """朗读引擎接口。

    上层只依赖这三个信号，换引擎时界面代码不需要改：

    * ``finished`` —— 当前这句读完了（引擎自己停下来的，不是因为调了
      :meth:`stop`）；
    * ``failed`` —— 引擎出错，参数是给用户看的说明；
    * ``state_changed`` —— 引擎状态变化，取值 ``idle`` / ``speaking`` / ``paused``。
    """

    finished = pyqtSignal()
    failed = pyqtSignal(str)
    state_changed = pyqtSignal(str)

    #: 引擎标识（只用于日志）
    name = "base"

    #: 超时倍率：系统引擎是「开口就读」，神经引擎要先合成，所以它的
    #: 超时（:func:`estimate_speech_ms`）得相应放宽，否则会误判成卡死。
    timeout_factor = 1.0

    def available(self):
        """引擎是否可用"""
        return False

    def voices(self):
        """可用语音列表（:class:`VoiceInfo`）"""
        return []

    def current_voice_id(self):
        """当前语音的 id（没有语音时返回空字符串）"""
        return ""

    def set_voice(self, voice_id):
        """选中某个语音，成功返回 ``True``"""
        return False

    def set_rate(self, rate):
        """设置语速（``-1.0`` ~ ``1.0``），成功返回 ``True``"""
        return False

    def set_volume(self, volume):
        """设置音量（``0.0`` ~ ``1.0``），成功返回 ``True``"""
        return False

    def speak(self, text):
        """读一句，成功受理返回 ``True``"""
        return False

    def preload(self, text):
        """预先把下一句合成好（只有离线神经引擎用得上）

        系统引擎是「喂一句读一句」，不需要预合成，所以默认什么都不做。
        """
        return False

    def pause(self):
        """暂停（读不完的句子留在原地，继续时会接着读）"""
        return False

    def resume(self):
        """继续"""
        return False

    def stop(self):
        """停止当前朗读"""
        return False

    def shutdown(self):
        """释放引擎资源（关窗口时调用）"""


class QtSapiBackend(TtsBackend):
    """本机引擎：``PyQt5.QtTextToSpeech``（Windows 上即系统 SAPI5）。

    引擎是**懒创建**的：窗口启动时不碰它，第一次点播放才真正加载，避免给
    启动速度添负担；引擎加载失败时 :meth:`available` 返回 ``False``，界面
    据此把朗读入口置灰，而不是崩掉。
    """

    name = "sapi"

    #: 创建引擎失败时的说明（给日志用）
    def __init__(self, engine="", parent=None):
        super().__init__(parent)
        self._engine_name = engine or "sapi"
        self._speech = None
        self._engine_failed = False
        self._voices = []
        self._qvoices = {}
        self._current_voice = ""
        #: 本次 ``say()`` 之后是否见过 ``Speaking``（用来识别迟到的 ``Ready``）
        self._speaking_seen = False
        #: 是否正在执行「停止」，用于吞掉 stop 引发的那次 ``Ready``
        self._stop_requested = False
        self._state = "idle"

    # ---------------- 引擎生命周期 ----------------

    def _ensure_engine(self):
        """按需创建引擎，失败返回 ``None``（只提示一次）"""
        if self._speech is not None or self._engine_failed:
            return self._speech
        try:
            from PyQt5.QtTextToSpeech import QTextToSpeech
        except ImportError as exc:  # 打包时漏了 QtTextToSpeech 模块
            logger.log(f"朗读引擎不可用（缺少 QtTextToSpeech）: {exc}", "WARN")
            self._engine_failed = True
            return None
        try:
            self._speech = QTextToSpeech(self._engine_name)
            self._speech.stateChanged.connect(self._on_state_changed)
        except Exception as exc:
            logger.log(f"创建朗读引擎失败: {exc}", "ERROR")
            self._speech = None
            self._engine_failed = True
            return None
        self._scan_voices()
        return self._speech

    def _scan_voices(self):
        """枚举所有语音。

        Qt 的 ``availableVoices()`` 只列当前 locale 的语音，所以得遍历
        ``availableLocales()`` 逐个问；问完把 locale 还原，免得顺手改掉
        用户正在用的语音。
        """
        speech = self._speech
        self._voices = []
        self._qvoices = {}
        if speech is None:
            return
        try:
            saved = speech.locale()
            for locale in speech.availableLocales():
                speech.setLocale(locale)
                label = self._locale_label(locale)
                for voice in speech.availableVoices():
                    voice_id = f"{label}|{voice.name()}"
                    if voice_id in self._qvoices:
                        continue
                    info = VoiceInfo(voice_id=voice_id, name=voice.name(),
                                     locale=label,
                                     gender=voice.gender())
                    self._voices.append(info)
                    self._qvoices[voice_id] = voice
            try:
                speech.setLocale(saved)
            except Exception:
                pass
        except Exception as exc:
            logger.log(f"枚举朗读语音失败: {exc}", "WARN")
        if self._voices:
            logger.log(f"可用朗读语音: "
                       f"{', '.join(v.voice_id for v in self._voices)}")

    @staticmethod
    def _locale_label(locale):
        """QLocale → ``zh_CN`` 这样的标签"""
        try:
            text = locale.name()
        except Exception:
            text = ""
        if text:
            return text
        try:
            return locale.languageToString(locale.language())
        except Exception:
            return ""

    # ---------------- 引擎接口实现 ----------------

    def available(self):
        return self._ensure_engine() is not None

    def voices(self):
        self._ensure_engine()
        return list(self._voices)

    def current_voice_id(self):
        return self._current_voice

    def set_voice(self, voice_id):
        speech = self._ensure_engine()
        if speech is None or not voice_id:
            return False
        voice = self._qvoices.get(voice_id)
        if voice is None:
            logger.log(f"找不到朗读语音: {voice_id}", "WARN")
            return False
        try:
            speech.stop()
            speech.setLocale(QLocale(self._locale_of(voice_id)))
            # setLocale 会重置语音，所以必须在它之后再 setVoice
            for candidate in speech.availableVoices():
                if candidate.name() == voice.name():
                    speech.setVoice(candidate)
                    self._current_voice = voice_id
                    logger.log(f"朗读语音已切换为: {voice_label_by_id(self._voices, voice_id)}")
                    return True
        except Exception as exc:
            logger.log(f"切换朗读语音失败: {exc}", "ERROR")
        return False

    @staticmethod
    def _locale_of(voice_id):
        """``zh_CN|Microsoft Huihui Desktop`` → ``zh_CN``"""
        return voice_id.split("|", 1)[0] if "|" in voice_id else ""

    def set_rate(self, rate):
        speech = self._ensure_engine()
        if speech is None:
            return False
        try:
            speech.setRate(max(-1.0, min(1.0, float(rate))))
            return True
        except Exception as exc:
            logger.log(f"设置朗读语速失败: {exc}", "WARN")
            return False

    def set_volume(self, volume):
        speech = self._ensure_engine()
        if speech is None:
            return False
        try:
            speech.setVolume(max(0.0, min(1.0, float(volume))))
            return True
        except Exception as exc:
            logger.log(f"设置朗读音量失败: {exc}", "WARN")
            return False

    def speak(self, text):
        speech = self._ensure_engine()
        if speech is None:
            return False
        try:
            # 新的一句开口之前，把上一句的「停止」状态清掉
            self._stop_requested = False
            self._speaking_seen = False
            speech.say(text or "")
            return True
        except Exception as exc:
            logger.log(f"朗读失败: {exc}", "ERROR")
            return False

    def pause(self):
        if self._speech is None:
            return False
        try:
            self._speech.pause()
            return True
        except Exception as exc:
            logger.log(f"暂停朗读失败: {exc}", "WARN")
            return False

    def resume(self):
        if self._speech is None:
            return False
        try:
            self._speech.resume()
            return True
        except Exception as exc:
            logger.log(f"继续朗读失败: {exc}", "WARN")
            return False

    def stop(self):
        speech = self._speech
        if speech is None:
            return False
        try:
            # 只有真的在读的时候才需要吞掉后面那次 Ready，否则会把「读完了」
            # 的合法回调误吞（下一次 say 就再也收不到 finished 了）
            if self._speaking_seen:
                self._stop_requested = True
            speech.stop()
            return True
        except Exception as exc:
            logger.log(f"停止朗读失败: {exc}", "WARN")
            return False

    def shutdown(self):
        speech = self._speech
        self._speech = None
        if speech is None:
            return
        try:
            speech.stateChanged.disconnect(self._on_state_changed)
        except Exception:
            pass
        try:
            speech.stop()
        except Exception:
            pass
        try:
            speech.deleteLater()
        except Exception:
            pass

    # ---------------- 状态回调 ----------------

    def _on_state_changed(self, state):
        try:
            from PyQt5.QtTextToSpeech import QTextToSpeech
        except ImportError:
            return

        if state == QTextToSpeech.Speaking:
            self._speaking_seen = True
            self._emit_state("speaking")
            return

        if state == QTextToSpeech.Paused:
            self._emit_state("paused")
            return

        if state == QTextToSpeech.BackendError:
            self._speaking_seen = False
            self._stop_requested = False
            self._emit_state("idle")
            logger.log("朗读引擎报错", "ERROR")
            self.failed.emit(i18n.t("tts.error.engine_failed",
                                    default="朗读引擎出错，请稍后重试。"))
            return

        # Ready：可能是读完了，也可能是 stop() 之后的那一声
        if self._stop_requested:
            self._stop_requested = False
            self._speaking_seen = False
            self._emit_state("idle")
            return
        if self._speaking_seen:
            self._speaking_seen = False
            self._emit_state("idle")
            self.finished.emit()
            return
        # 什么都没读时收到的 Ready，忽略
        self._emit_state("idle")

    def _emit_state(self, state):
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)


class SapiComBackend(TtsBackend):
    """本机引擎（进阶版）：用 ``pywin32`` 直接驱动 SAPI5 的 ``SpVoice``。

    相比 :class:`QtSapiBackend`（走 ``QTextToSpeech``），它多看到一批语音 ——
    ``QTextToSpeech`` 只认经典语音库，看不到 **OneCore** 里的音色，
    而中文恰恰是 OneCore 里更全（多出 Kangkang 男声 / Yaoyao 女声）。
    所以本程序优先用这个后端，装不了 pywin32 时再退回 Qt。

    和 Qt 后端的几处关键差异（都是实测出来的）：

    * ``SpVoice.Speak()`` **默认阻塞**，必须传 ``SVSF_ASYNC`` 才会立刻返回；
      读没读完要自己轮询 ``Status.RunningState``（``0`` 未起播 / ``2`` 正在读 /
      ``1`` 读完了），所以这里挂了个 :data:`POLL_MS` 的定时器；
    * 调用 ``Speak()`` 会**同步**把 ``RunningState`` 重置掉，但 ``stop()``
      之后的残留值是 ``1``，所以「第一次轮询读到的 ``1`` 不算数」——用
      :attr:`_fresh` 标记必须见过 ``0`` / ``2`` 才认「读完了」，否则会跳句；
    * **暂停时 ``RunningState`` 仍然是 ``2``**，光看状态分不出「在读」还是
      「暂停中」，得自己记 :attr:`_paused`；
    * ``Rate`` 是整数 ``-10 ~ 10``、``Volume`` 是整数 ``0 ~ 100``（Qt 那套是
      浮点 ``-1.0 ~ 1.0``），这里做换算，界面上的档位两个后端保持一致；
    * 停止 = ``Speak("", SVSF_ASYNC | SVSF_PURGE)``（清空待读队列），没有
      单独的 ``stop()``。
    """

    name = "sapi-com"

    #: 多久查一次「读完了没」（毫秒）。轮询只是读一个属性，40ms 足够便宜，
    #: 而且比「等引擎回调」多出来的延迟远小于人耳能分辨的句间停顿。
    POLL_MS = 40

    #: ``SpeechVoiceSpeakFlags``：1 = 异步返回，2 = 读之前先清空待读队列
    SVSF_ASYNC = 1
    SVSF_PURGE = 2

    #: SAPI 的语速 / 音量是整数，界面用的是浮点档位
    RATE_SCALE = 10
    VOLUME_SCALE = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._com = None
        self._voice = None
        self._engine_failed = False
        self._voices = []
        #: ``voice_id`` → 注册表 token 路径（COM 指派时要按路径构造）
        self._token_paths = {}
        self._current_voice = ""
        #: 是否已经开口、正等着读完之后的那次 ``RunningState == 1``
        self._awaiting = False
        #: 本次开口之后有没有见过 ``0`` / ``2``（用来屏蔽上一次 purge 的残留值）
        self._fresh = False
        self._paused = False
        self._state = "idle"
        self._poll = QTimer(self)
        self._poll.setInterval(self.POLL_MS)
        self._poll.timeout.connect(self._on_poll)

    # ---------------- 引擎生命周期 ----------------

    def _ensure_engine(self):
        """按需创建 ``SpVoice``，失败返回 ``None``（只提示一次）"""
        if self._voice is not None or self._engine_failed:
            return self._voice
        try:
            import win32com.client
        except ImportError as exc:  # 没装 pywin32
            logger.log(f"朗读引擎不可用（缺少 pywin32）: {exc}", "WARN")
            self._engine_failed = True
            return None
        try:
            self._com = win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as exc:
            logger.log(f"创建 SAPI 语音对象失败: {exc}", "ERROR")
            self._voice = None
            self._engine_failed = True
            return None
        self._scan_voices()
        return self._voice

    def _scan_voices(self):
        """按注册表列出语音（经典库 + OneCore，同名只留 OneCore 那份）"""
        self._voices = []
        self._token_paths = {}
        for voice_id, name, locale_name, gender, _hive, path in \
                sapi_registry_voices():
            if voice_id in self._token_paths:
                continue
            self._voices.append(VoiceInfo(voice_id=voice_id, name=name,
                                          locale=locale_name, gender=gender))
            self._token_paths[voice_id] = path
        if self._voices:
            logger.log(f"可用朗读语音: "
                       f"{', '.join(v.voice_id for v in self._voices)}")

    # ---------------- 引擎接口实现 ----------------

    def available(self):
        return self._ensure_engine() is not None and bool(self._voices)

    def voices(self):
        self._ensure_engine()
        return list(self._voices)

    def current_voice_id(self):
        return self._current_voice

    def set_voice(self, voice_id):
        voice = self._ensure_engine()
        if voice is None or not voice_id:
            return False
        path = self._token_paths.get(voice_id)
        if path is None:
            logger.log(f"找不到朗读语音: {voice_id}", "WARN")
            return False
        try:
            self._cancel()
            token = self._com.Dispatch("SAPI.SpObjectToken")
            token.SetId(path)
            voice.Voice = token
            self._current_voice = voice_id
            logger.log(f"朗读语音已切换为: "
                       f"{voice_label_by_id(self._voices, voice_id)}")
            return True
        except Exception as exc:
            logger.log(f"切换朗读语音失败: {exc}", "ERROR")
            return False

    def set_rate(self, rate):
        voice = self._ensure_engine()
        if voice is None:
            return False
        try:
            value = max(-1.0, min(1.0, float(rate or 0.0)))
            voice.Rate = int(round(value * self.RATE_SCALE))
            return True
        except Exception as exc:
            logger.log(f"设置朗读语速失败: {exc}", "WARN")
            return False

    def set_volume(self, volume):
        voice = self._ensure_engine()
        if voice is None:
            return False
        try:
            value = max(0.0, min(1.0, float(volume)))
            voice.Volume = int(round(value * self.VOLUME_SCALE))
            return True
        except Exception as exc:
            logger.log(f"设置朗读音量失败: {exc}", "WARN")
            return False

    def speak(self, text):
        voice = self._ensure_engine()
        if voice is None:
            return False
        try:
            # 这里刻意不带 SVSF_PURGE：队列保证开口前一定先 stop() 过，
            # 而 purge 之后 RunningState 会留一个 1，反而要多一层消歧
            self._awaiting = False
            self._fresh = False
            self._paused = False
            voice.Speak(text or "", self.SVSF_ASYNC)
            self._awaiting = True
            self._poll.start()
            return True
        except Exception as exc:
            logger.log(f"朗读失败: {exc}", "ERROR")
            return False

    def pause(self):
        voice = self._voice
        if voice is None:
            return False
        try:
            voice.Pause()
            self._paused = True
            self._emit_state("paused")
            return True
        except Exception as exc:
            logger.log(f"暂停朗读失败: {exc}", "WARN")
            return False

    def resume(self):
        voice = self._voice
        if voice is None:
            return False
        try:
            voice.Resume()
            self._paused = False
            self._emit_state("speaking")
            return True
        except Exception as exc:
            logger.log(f"继续朗读失败: {exc}", "WARN")
            return False

    def stop(self):
        """停止：清空待读队列，并掐掉轮询（不留任何残留回调）"""
        self._cancel()
        self._emit_state("idle")
        return True

    def shutdown(self):
        self._cancel()
        self._voice = None
        self._com = None

    # ---------------- 内部 ----------------

    def _cancel(self):
        """停掉当前朗读与轮询，清掉「等着读完」的标记"""
        self._poll.stop()
        self._awaiting = False
        self._fresh = False
        self._paused = False
        voice = self._voice
        if voice is None:
            return
        try:
            voice.Speak("", self.SVSF_ASYNC | self.SVSF_PURGE)
        except Exception:
            pass

    def _on_poll(self):
        """轮询 ``RunningState``：0 未起播 / 2 正在读 / 1 读完了"""
        if not self._awaiting:
            self._poll.stop()
            return
        voice = self._voice
        if voice is None:
            self._awaiting = False
            self._poll.stop()
            return
        try:
            state = voice.Status.RunningState
        except Exception as exc:
            logger.log(f"查询朗读状态失败: {exc}", "ERROR")
            self._awaiting = False
            self._poll.stop()
            self._emit_state("idle")
            self.failed.emit(i18n.t("tts.error.engine_failed",
                                    default="朗读引擎出错，请稍后重试。"))
            return

        if state == 0:                      # 还没起播
            self._fresh = True
            return
        if state == 2:                      # 正在读（暂停时同样是 2）
            self._fresh = True
            self._emit_state("paused" if self._paused else "speaking")
            return

        # state == 1：读完了。但 stop() 留下的残留值也是 1，所以必须见过
        # 0 / 2 才认，否则新的一句刚开口就会被判「读完」而跳句
        if not self._fresh:
            return
        self._awaiting = False
        self._poll.stop()
        self._emit_state("idle")
        self.finished.emit()

    def _emit_state(self, state):
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)


def voice_label_by_id(voices, voice_id):
    """按 id 取语音显示名（日志 / 界面共用）"""
    for voice in voices or ():
        if voice.voice_id == voice_id:
            return voice_label(voice)
    return voice_id


# ---------------- 队列 ----------------


def estimate_speech_ms(text, rate=0.0):
    """估算读一句话大概要多久（毫秒），只用于「引擎不吭声」时的兜底超时。

    取值刻意给得宽松：SAPI 默认语速读中文大约每秒 4~5 个字，这里按每秒
    3.8 个字算，再加上固定的等待余量；语速调快时（``rate > 0``）超时同步缩短。
    最慢档（``rate = -1.0``）会让 ``1 + rate`` 归零，所以分母压了个下限 ——
    宁可多等一会儿，也不能在切档位时抛异常。
    """
    chars = len(text or "")
    rate = max(-1.0, min(1.0, float(rate or 0.0)))
    factor = 1.0 / max(0.35, 1.0 + rate)
    return int(min(180000, 4000 + chars * 260 * factor))


class SpeechQueue(QObject):
    """句子队列：一句读完接着读下一句，并负责暂停 / 继续 / 上下句。

    状态只有三个：``idle``（没在读）、``playing``、``paused``。队列自己不管
    界面，但会发信号告诉外面「现在读的是第几句」，主窗口据此高亮与滚动。

    换章时的规矩（由 :meth:`load` 实现）：正在读就把新的一章从指定句接着读，
    暂停中就把位置挪过去但不开口，空闲时只换句子表。
    """

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"

    #: 当前句变化（-1 表示没有句子）
    sentence_changed = pyqtSignal(int)
    state_changed = pyqtSignal(str)
    #: 整段读完（自动翻章靠它）
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    #: 「上一句」在这句读了这么久之后，改为重读当前句（跟播放器一个手感）
    RESTART_AFTER_MS = 3000

    def __init__(self, backend=None, parent=None):
        super().__init__(parent)
        self._backend = None
        self._spans = []
        self._index = -1
        self._state = self.IDLE
        #: 是否已经开口、正等着引擎报「读完」
        self._awaiting = False
        self._current_text = ""
        self._rate = 0.0
        self._volume = 1.0
        self._elapsed = QElapsedTimer()
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)
        if backend is not None:
            self.set_backend(backend)

    # ---------------- 装配 ----------------

    def set_backend(self, backend):
        """换引擎（会断开旧引擎的信号）"""
        if self._backend is not None:
            for signal, slot in self._connections(self._backend):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._backend = backend
        if backend is not None:
            for signal, slot in self._connections(backend):
                signal.connect(slot)
            # 换引擎后语速 / 音量得重新灌一遍，新引擎不知道旧引擎的设定
            backend.set_rate(self._rate)
            backend.set_volume(self._volume)

    def _connections(self, backend):
        """引擎信号 → 队列槽（换引擎时按同一份清单断开）"""
        return ((backend.finished, self._on_backend_finished),
                (backend.failed, self._on_backend_failed))

    # ---------------- 只读状态 ----------------

    @property
    def state(self):
        return self._state

    @property
    def active(self):
        """是否处于朗读中（播放或暂停）"""
        return self._state in (self.PLAYING, self.PAUSED)

    @property
    def current_index(self):
        return self._index

    @property
    def sentence_count(self):
        return len(self._spans)

    @property
    def spans(self):
        return list(self._spans)

    @property
    def rate(self):
        return self._rate

    @property
    def volume(self):
        return self._volume

    def current_span(self):
        """当前句（没有则返回 ``None``）"""
        if 0 <= self._index < len(self._spans):
            return self._spans[self._index]
        return None

    # ---------------- 句子表 ----------------

    def load(self, spans, index=0):
        """换一份句子表（换章 / 重新渲染），并保持当前的播放状态。

        正在播放：从 ``index`` 句接着读；暂停中：位置挪过去但不开口；
        空闲：只换句子表。
        """
        previous = self._state
        self._cancel_utterance()
        self._spans = list(spans or ())
        self._index = self._clamp(index if self._spans else -1)

        if not self._spans:
            self.sentence_changed.emit(-1)
            self._set_state(self.IDLE)
            return

        if previous == self.PLAYING:
            self._set_state(self.PLAYING)
            self._speak_current()
        elif previous == self.PAUSED:
            self._set_state(self.PAUSED)
            self.sentence_changed.emit(self._index)
        else:
            self._set_state(self.IDLE)
            self.sentence_changed.emit(self._index)

    # ---------------- 播放控制 ----------------

    def start(self, index=None):
        """开始朗读；暂停中调用就是「继续」"""
        if not self._spans:
            return False
        if self._state == self.PLAYING and index is None:
            return False

        if index is not None:
            self._index = self._clamp(index)
        elif self._index < 0:
            self._index = 0

        if self._state == self.PAUSED and index is None:
            return self.resume()

        if self._state != self.PLAYING:
            self._set_state(self.PLAYING)
        self._speak_current()
        return True

    def resume(self):
        """从暂停处继续（接着读完被打断的那一句）"""
        if self._state != self.PAUSED:
            return False
        self._set_state(self.PLAYING)
        self._awaiting = True
        self._elapsed.restart()
        if self._backend is None or not self._backend.resume():
            # 引擎不认「继续」就退回重读当前句
            self._speak_current()
            return True
        self._watchdog.start(self._timeout_ms(self._current_text))
        return True

    def pause(self):
        """暂停（当前句留在原地，继续时接着读）"""
        if self._state != self.PLAYING:
            return False
        self._watchdog.stop()
        self._set_state(self.PAUSED)
        if self._backend is not None:
            self._backend.pause()
        return True

    def toggle(self):
        """播放 / 暂停切换"""
        if self._state == self.PLAYING:
            return self.pause()
        if self._state == self.PAUSED:
            return self.resume()
        return self.start()

    def stop(self):
        """停止朗读（保留当前句位置，下次从这句继续）"""
        if not self.active and not self._awaiting:
            self._cancel_utterance()
            self._set_state(self.IDLE)
            return False
        self._cancel_utterance()
        self._set_state(self.IDLE)
        return True

    def next_sentence(self):
        """下一句：播放中立即切过去，暂停 / 空闲时只挪位置"""
        if not self._spans:
            return False
        if self._index >= len(self._spans) - 1:
            return False
        return self._seek(self._index + 1)

    def previous_sentence(self):
        """上一句：刚开始读的话会先重读当前句，读了 3 秒以上才真往后退"""
        if not self._spans:
            return False
        if (self._state == self.PLAYING and self._index >= 0
                and self._elapsed.isValid()
                and self._elapsed.elapsed() >= self.RESTART_AFTER_MS):
            return self._seek(self._index)
        return self._seek(max(0, self._index - 1))

    def seek(self, index):
        """跳到第 ``index`` 句（保持当前的播放 / 暂停状态）"""
        return self._seek(index)

    def _seek(self, index):
        if not self._spans:
            return False
        index = self._clamp(index)
        if index == self._index and self._state == self.PLAYING:
            # 同一句：重新开口（用户按了「重读」）
            self._cancel_utterance()
            self._speak_current()
            return True
        self._index = index
        if self._state == self.PLAYING:
            self._cancel_utterance()
            self._speak_current()
        else:
            self.sentence_changed.emit(self._index)
        return True

    def set_rate(self, rate, restart=False):
        """设置语速。

        已经开口的那一句不会中途变速，所以 ``restart=True`` 时会从当前句
        重读一遍——拖完语速滑块松手时用得上，拖的过程中不要用。
        """
        self._rate = max(-1.0, min(1.0, float(rate or 0.0)))
        if self._backend is not None:
            self._backend.set_rate(self._rate)
        if restart and self._state == self.PLAYING:
            self._cancel_utterance()
            self._speak_current()

    def set_volume(self, volume):
        """设置音量（``0.0`` ~ ``1.0``），立即生效

        音量跟语速不一样：已经开口的那一句也能中途变大变小，不用重读；
        所以这里不需要 ``restart`` 参数。
        """
        try:
            self._volume = max(0.0, min(1.0, float(volume)))
        except (TypeError, ValueError):
            self._volume = 1.0
        if self._backend is None:
            return False
        return self._backend.set_volume(self._volume)

    def shutdown(self):
        """停掉朗读并释放引擎"""
        self._watchdog.stop()
        self._spans = []
        self._index = -1
        self._awaiting = False
        backend = self._backend
        self._backend = None
        if backend is not None:
            try:
                backend.stop()
            except Exception:
                pass
            backend.shutdown()
        self._set_state(self.IDLE)

    # ---------------- 内部 ----------------

    def _clamp(self, index):
        if not self._spans:
            return -1
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 0
        return max(0, min(len(self._spans) - 1, index))

    def _timeout_ms(self, text):
        """这句的兜底超时（按引擎的 ``timeout_factor`` 放宽）"""
        factor = 1.0
        if self._backend is not None:
            try:
                factor = max(1.0, float(self._backend.timeout_factor))
            except (AttributeError, TypeError, ValueError):
                factor = 1.0
        return int(estimate_speech_ms(text, self._rate) * factor)

    def _cancel_utterance(self):
        """掐掉当前这句：停引擎、取消超时、清掉「等着读完」的标记"""
        self._watchdog.stop()
        self._awaiting = False
        self._current_text = ""
        if self._backend is not None:
            self._backend.stop()

    def _speak_current(self):
        """把当前句喂给引擎"""
        self._watchdog.stop()
        span = self.current_span()
        if span is None:
            self._finish()
            return

        self._current_text = span.text
        self._awaiting = True
        self._elapsed.restart()
        self.sentence_changed.emit(self._index)

        if self._backend is None or not self._backend.speak(span.text):
            self._awaiting = False
            self._set_state(self.IDLE)
            message = i18n.t("tts.error.speak_failed",
                             default="无法朗读，系统语音引擎不可用。")
            logger.log("朗读失败：引擎未受理", "ERROR")
            self.failed.emit(message)
            return

        self._watchdog.start(self._timeout_ms(span.text))
        self._preload_next()

    def _preload_next(self):
        """让引擎先把下一句合成好（神经引擎才有意义，系统引擎是空实现）

        当前句还在播的时候算下一句，轮到它时直接出声，中间不会出现空档。
        合成失败无所谓（顶多回到「先算再播」），不要打断朗读。
        """
        if self._backend is None or not self._spans:
            return
        nxt = self._index + 1
        if nxt < 0 or nxt >= len(self._spans):
            return
        try:
            self._backend.preload(self._spans[nxt].text)
        except Exception as exc:  # noqa: BLE001 - 预合成失败不影响主流程
            logger.log(f"预合成下一句失败: {exc}", "DEBUG")

    def _on_backend_finished(self):
        """引擎读完一句"""
        if not self._awaiting:
            # 已经停止 / 换章了，这次回调是旧的
            return
        self._awaiting = False
        self._watchdog.stop()
        if self._index >= len(self._spans) - 1:
            self._finish()
            return
        self._index += 1
        self._speak_current()

    def _on_backend_failed(self, message):
        self._awaiting = False
        self._watchdog.stop()
        self._set_state(self.IDLE)
        logger.log(f"朗读引擎报错: {message}", "ERROR")
        self.failed.emit(message or i18n.t("tts.error.engine_failed",
                                           default="朗读引擎出错，请稍后重试。"))

    def _on_watchdog(self):
        """引擎一直没报「读完」时的兜底：当作读完了往下走，别卡死"""
        if not self._awaiting:
            return
        span = self.current_span()
        logger.log(f"朗读超时（{self._timeout_ms(self._current_text)}ms "
                   f"未收到完成回调），跳过: {self._current_text[:20]}", "WARN")
        self._awaiting = False
        if span is None or self._index >= len(self._spans) - 1:
            self._finish()
            return
        self._index += 1
        self._speak_current()

    def _finish(self):
        """整段读完"""
        self._watchdog.stop()
        self._awaiting = False
        self._current_text = ""
        self._set_state(self.IDLE)
        self.finished.emit()

    def _set_state(self, state):
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)


# ---------------- 工厂 ----------------

#: 离线神经音色引擎名（与 :class:`enm.managers.tts_neural.SherpaBackend` 一致）
NEURAL_ENGINE = "sherpa"

#: 在线音色引擎名（与 :class:`enm.managers.tts_edge.EdgeBackend` 一致）
EDGE_ENGINE = "edge"


def _has_neural():
    """装没装 ``sherpa-onnx``（缺库 / 缺 DLL 都算没装）"""
    try:
        from .tts_neural import sherpa_available
    except Exception as exc:  # noqa: BLE001 - 语音库缺失也得照常跑
        logger.log(f"没装 sherpa-onnx，离线神经音色不可用: {exc}", "INFO")
        return False
    try:
        return bool(sherpa_available())
    except Exception as exc:  # noqa: BLE001
        logger.log(f"检查离线神经音色失败: {exc}", "WARN")
        return False


def _has_edge():
    """装没装 ``edge-tts``"""
    try:
        from .tts_edge import edge_available
    except Exception as exc:  # noqa: BLE001 - 语音库缺失也得照常跑
        logger.log(f"没装 edge-tts，在线音色不可用: {exc}", "INFO")
        return False
    try:
        return bool(edge_available())
    except Exception as exc:  # noqa: BLE001
        logger.log(f"检查在线音色失败: {exc}", "WARN")
        return False


def available_engines():
    """本机可用的朗读引擎名，**第一项是本程序会优先用的那个**

    顺序是「离线神经 → 系统 SAPI → 在线」，优先能离线出声的：神经音色
    （Piper / Kokoro）最好听且不联网；它没装 / 没下模型就退回系统引擎；
    在线音色（edge-tts）要联网，只在用户主动选它的时候才用，所以排最后。
    ``sapi-com``（pywin32 直接驱动 SAPI，能看到 OneCore 语音）优于
    ``sapi``（``QTextToSpeech``，只能看到经典语音库）。取不到时返回空列表。
    """
    names = []
    if _has_neural():
        names.append(NEURAL_ENGINE)
    if sapi_com_available():
        names.append(SapiComBackend.name)
    try:
        from PyQt5.QtTextToSpeech import QTextToSpeech
        qt_engines = list(QTextToSpeech.availableEngines())
    except ImportError:
        qt_engines = []
    except Exception as exc:
        logger.log(f"枚举朗读引擎失败: {exc}", "WARN")
        qt_engines = []
    for name in qt_engines:
        if name not in names:
            names.append(name)
    if _has_edge():
        names.append(EDGE_ENGINE)
    return names


def _create_sapi_com():
    backend = SapiComBackend()
    return backend if backend.available() else None


def _create_neural(require_voices=True):
    """建离线神经后端；``require_voices`` 为真时「一个音色都没有」算建不出来

    自动挑引擎时要求有音色（不然会挑中一个没声音的引擎，用户点朗读只能
    听到一句「模型还没下载」）；用户**明确**点了「离线神经音色」时不拦 ——
    否则没下模型的人连「音色管理」的入口都进不去，模型永远下不了。
    """
    try:
        from .tts_neural import SherpaBackend
    except Exception as exc:  # noqa: BLE001 - 缺 sherpa-onnx 就退回系统引擎
        logger.log(f"离线神经音色不可用: {exc}", "WARN")
        return None
    backend = SherpaBackend()
    if not backend.available():
        backend.shutdown()
        return None
    if require_voices and not backend.voices():
        logger.log("离线神经音色还没下载模型，自动选择时跳过它", "INFO")
        backend.shutdown()
        return None
    return backend


def _create_edge():
    try:
        from .tts_edge import EdgeBackend
    except Exception as exc:  # noqa: BLE001 - 缺 edge-tts 就退回系统引擎
        logger.log(f"在线音色不可用: {exc}", "WARN")
        return None
    backend = EdgeBackend()
    return backend if backend.available() else None


def _create_qt_sapi(engine_name):
    # 名字校验：``QTextToSpeech("没这个引擎")`` 会**悄悄用默认引擎**建成功，
    # 于是「用户点了 A 却听到 B」——所以先对一遍本机引擎名单。
    if engine_name:
        try:
            from PyQt5.QtTextToSpeech import QTextToSpeech
            known = list(QTextToSpeech.availableEngines())
        except Exception as exc:  # noqa: BLE001
            logger.log(f"枚举朗读引擎失败: {exc}", "WARN")
            known = []
        if known and engine_name not in known:
            logger.log(f"本机没有朗读引擎 {engine_name}", "WARN")
            return None
    backend = QtSapiBackend(engine_name)
    return backend if backend.available() else None


def create_backend(engine=None):
    """创建一个可用的朗读引擎。

    ``engine`` 为空时按 :func:`available_engines` 的顺序依次尝试，**第一个
    能用的胜出** —— 也就是优先 ``sapi-com``（能多看到 Kangkang / Yaoyao
    这些 OneCore 音色），失败才退回 ``QTextToSpeech``。指定了 ``engine``
    却创建不出来时返回 ``None``，不悄悄换成别的引擎（用户明确点过名的东西
    不能背着他换掉）。
    """
    if engine:
        if engine == SapiComBackend.name:
            return _create_sapi_com()
        if engine == NEURAL_ENGINE:
            # 用户明确点名的引擎不要求「已经有音色」：空着也让他进去下模型
            return _create_neural(require_voices=False)
        if engine == EDGE_ENGINE:
            return _create_edge()
        return _create_qt_sapi(engine)

    for name in available_engines():
        if name == SapiComBackend.name:
            backend = _create_sapi_com()
        elif name == NEURAL_ENGINE:
            backend = _create_neural()
        elif name == EDGE_ENGINE:
            backend = _create_edge()
        else:
            backend = _create_qt_sapi(name)
        if backend is not None:
            return backend
    logger.log("系统没有可用的朗读引擎，朗读功能不可用", "WARN")
    return None


__all__ = ["DEFAULT_MAX_CHARS", "EDGE_ENGINE", "GENDER_KEYS",
           "NEURAL_ENGINE", "SentenceSpan",
           "SapiComBackend", "SpeechQueue", "TtsBackend", "QtSapiBackend",
           "VoiceInfo", "available_engines", "clean_speech_text",
           "create_backend", "estimate_speech_ms", "is_speakable",
           "language_prefix", "order_voices", "pick_voice",
           "sapi_com_available", "sapi_registry_voices", "sentences_for_blocks",
           "split_sentences", "voice_gender_key", "voice_label",
           "voice_label_by_id"]
