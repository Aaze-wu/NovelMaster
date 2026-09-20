# -*- coding: utf-8 -*-
"""朗读（文字转语音）。

这个模块只管「把一段文本读出来」，不碰任何界面控件，分三层：

* :class:`TtsBackend` —— 引擎接口。:class:`QtSapiBackend` 是本机实现
  （``PyQt5.QtTextToSpeech``，Windows 上走系统 SAPI5，**离线可用、不用装任何
  额外依赖**）。以后要接在线神经音色（或别的系统引擎），照着同一套信号实现一个
  子类、在 :func:`create_backend` 里登记即可，上层界面代码一行都不用改；
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


def sentences_for_blocks(blocks, max_chars=DEFAULT_MAX_CHARS):
    """把 ``[(文档位置, 文本), ...]`` 变成整章的句子表。

    主窗口按 ``QTextBlock`` 逐个取文本（``block.position()`` 就是它的文档
    位置），这里逐块断句并保留绝对位置，因此高亮时可以直接拿
    ``span.start`` / ``span.end`` 去建 ``QTextCursor``，不用再拼一遍全文——
    含图片、表格的章节也能对得上。
    """
    sentences = []
    for position, text in blocks:
        sentences.extend(split_sentences(text, max_chars=max_chars,
                                         base=int(position)))
    return sentences


# ---------------- 语音枚举与挑选 ----------------

#: 一个可用语音：``voice_id`` 形如 ``zh_CN|Microsoft Huihui Desktop``
VoiceInfo = namedtuple("VoiceInfo", "voice_id name locale gender")


def language_prefix(lang_code):
    """界面语言代码 → 语言前缀（``zh_TW`` → ``zh``）"""
    text = str(lang_code or "").replace("-", "_")
    return text.split("_")[0].lower()


def voice_label(voice):
    """语音在界面上的显示名（``Microsoft Huihui Desktop`` → ``Huihui (zh_CN)``）"""
    name = voice.name or ""
    for prefix in ("Microsoft ",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in (" Desktop",):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
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
        self._watchdog.start(estimate_speech_ms(self._current_text, self._rate))
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
        """设置音量（``0.0`` ~ ``1.0``），立即生效"""
        if self._backend is None:
            return False
        return self._backend.set_volume(volume)

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

        self._watchdog.start(estimate_speech_ms(span.text, self._rate))

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
        logger.log(f"朗读超时（{estimate_speech_ms(self._current_text, self._rate)}ms "
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


def available_engines():
    """系统里可用的朗读引擎名（取不到时返回空列表）"""
    try:
        from PyQt5.QtTextToSpeech import QTextToSpeech
    except ImportError:
        return []
    try:
        return list(QTextToSpeech.availableEngines())
    except Exception as exc:
        logger.log(f"枚举朗读引擎失败: {exc}", "WARN")
        return []


def create_backend(engine=None):
    """创建一个可用的朗读引擎。

    目前只有本机 ``sapi`` 一种实现（Windows 系统语音，离线）。将来接在线
    神经音色时，在这里按 ``engine`` 名字返回另一个 :class:`TtsBackend` 子类
    即可，主窗口只认接口。
    """
    engines = available_engines()
    if not engines:
        logger.log("系统没有可用的朗读引擎，朗读功能不可用", "WARN")
        return None
    name = engine or ("sapi" if "sapi" in engines else engines[0])
    backend = QtSapiBackend(name)
    if not backend.available():
        return None
    return backend


__all__ = ["DEFAULT_MAX_CHARS", "SentenceSpan", "SpeechQueue", "TtsBackend",
           "QtSapiBackend", "VoiceInfo", "available_engines", "clean_speech_text",
           "create_backend", "estimate_speech_ms", "is_speakable",
           "language_prefix", "order_voices", "pick_voice", "sentences_for_blocks",
           "split_sentences", "voice_label", "voice_label_by_id"]
