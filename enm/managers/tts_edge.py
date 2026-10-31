# -*- coding: utf-8 -*-
"""在线音色后端（``edge-tts``，微软 Edge 的在线朗读）。

和离线神经音色（:mod:`enm.managers.tts_neural`）走的是同一套流程：

    文本 → 在线合成出 MP3 → :class:`Mp3Player` 放出来 → 放完报告

三个和离线不一样的坑：

* **只能出 MP3**：输出格式在 ``edge_tts/communicate.py`` 里写死成
  ``audio-24khz-48kbitrate-mono-mp3``，改成 raw PCM 服务端直接不给音频
  （抛 ``NoAudioReceived``）。所以这里必须用 :class:`Mp3Player`（落临时文件再放）；
* **必须联网**：断网 / 超时会抛异常，这里把它变成一句人话提示，不静默换引擎；
* **音色列表要联网才拿得到**：所以列表缓存到 ``<数据目录>/tts_voices_edge.json``，
  开机先用缓存（离线也能把菜单列出来），后台线程再去刷新。
* **库版本不能太旧**：微软给朗读接口加了 ``Sec-MS-GEC`` **v2** 令牌校验，
  ``edge-tts`` 从 7.3.0 才开始带（见 :data:`MIN_EDGE_TTS`）。老版本取音色列表**照样
  成功**（那走的是另一个 HTTP 接口，不校验令牌），可一开始合成就被 **403** 拒掉，
  表现成「音色能选，一读就失败」。所以下面把 403 单独翻译成「升级 edge-tts」的提示，
  而不是笼统地说「请检查网络」。
"""

import asyncio
import json
import threading
import time

from PyQt5.QtCore import QMetaObject, Qt, QTimer, pyqtSignal, pyqtSlot

from .. import i18n
from ..constants import DATA_PATH
from ..logger import logger
from .tts import TtsBackend, VoiceInfo
from .tts_audio import CODEC_MP3, AudioClip, ClipWorker, Mp3Player

#: 音色列表的缓存文件（放在数据目录里，跟着程序一起被卸载 / 迁移）
VOICE_CACHE_PATH = DATA_PATH / "tts_voices_edge.json"

#: 语速映射：界面的 ``rate``（``-1`` ~ ``1``）→ edge-tts 的百分比。
#: ``+60%`` 大概就是「快得能听清」的上限，再快就糊了。
RATE_PERCENT_SPAN = 60

#: 音色列表多久刷新一次（秒）—— 7 天
VOICE_CACHE_TTL = 7 * 24 * 3600

#: 单次合成的总超时（秒）
SYNTH_TIMEOUT = 60

#: 第一个会带 ``Sec-MS-GEC`` v2 令牌的 ``edge-tts`` 版本。
#: 比它更老的版本合成一律被服务端 403 拒绝（``WSServerHandshakeError``）。
MIN_EDGE_TTS = (7, 3, 1)

#: :data:`MIN_EDGE_TTS` 的可读写法（给提示文案用）
MIN_EDGE_TTS_TEXT = ".".join(str(part) for part in MIN_EDGE_TTS)

#: 服务端「拒绝握手」时出现过的字样（403 在 aiohttp 里就这几种说法 + 时钟偏移）。
#: 只认文本，不认数字：``ConnectionId`` 之类的十六进制串里随时会出现 "403"。
_REJECT_MARKERS = (
    "handshakestatuserror",
    "invalid response status",
    "403 forbidden",
    "server rejected websocket",
    "skewadjustment",
)


def edge_version():
    """本机 ``edge-tts`` 的版本，形如 ``(7, 3, 1)``；取不到就给 ``()``"""
    try:
        import edge_tts
    except Exception:  # noqa: BLE001 - 没装 / 装坏了都算「不知道」
        return ()
    info = getattr(edge_tts, "__version_info__", None)
    if isinstance(info, tuple) and info:
        try:
            return tuple(int(part) for part in info[:3])
        except (TypeError, ValueError):
            pass
    try:
        text = str(getattr(edge_tts, "__version__", "") or "")
    except Exception:  # noqa: BLE001 - 元数据坏了也不该让朗读炸掉
        return ()
    parts = []
    for chunk in text.split(".")[:3]:
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def edge_version_text():
    """本机 ``edge-tts`` 版本的可读写法；不知道就给 ``"-"``"""
    version = edge_version()
    return ".".join(str(part) for part in version) if version else "-"


def edge_outdated():
    """版本老到会被服务端拒绝（老版本不带 v2 令牌）"""
    version = edge_version()
    return bool(version) and version < MIN_EDGE_TTS


def is_rejected(error):
    """这次失败是不是「服务端拒绝握手」（版本旧 / 系统时间偏），而不是网络不通"""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__} {error}"
    else:
        text = str(error or "")
    text = text.lower()
    return any(marker in text for marker in _REJECT_MARKERS)


def edge_available():
    """本机装没装 ``edge-tts``"""
    try:
        import edge_tts  # noqa: F401
    except ImportError as exc:
        logger.log(f"没装 edge-tts，在线音色不可用: {exc}", "INFO")
        return False
    except Exception as exc:  # noqa: BLE001 - 装了但加载不了（缺依赖等）
        logger.log(f"加载 edge-tts 失败，在线音色不可用: {exc}", "ERROR")
        return False
    if edge_outdated():
        # 不拦着用户用（万一服务端放宽了），但日志里先留一条线索：
        # 这个版本合成必然 403，看见这条就不用再怀疑网络了。
        logger.log(f"在线音色库 edge-tts {edge_version_text()} 过旧，"
                   f"合成本会失败，请升级到 {MIN_EDGE_TTS_TEXT} 或更新版本", "WARN")
    return True


def rate_to_percent(rate):
    """界面语速 → 百分比整数（``-60`` ~ ``60``）"""
    try:
        value = max(-1.0, min(1.0, float(rate or 0.0)))
    except (TypeError, ValueError):
        value = 0.0
    return int(round(value * RATE_PERCENT_SPAN))


def rate_text(rate):
    """界面语速 → edge-tts 要的 ``"+20%"`` 这种字符串"""
    return f"{rate_to_percent(rate):+d}%"


def friendly_name(raw, short):
    """``"Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)"`` → ``"Xiaoxiao"``

    名字太长的就退回 ``ShortName``（``zh-CN-XiaoxiaoNeural``），至少能区分开。
    """
    text = str(raw or "").strip()
    if text.startswith("Microsoft "):
        text = text[len("Microsoft "):]
    for marker in (" Online", " (", " - "):
        if marker in text:
            text = text.split(marker)[0]
    text = text.strip()
    return text or str(short or "").strip()


def parse_voices(raw):
    """``edge_tts.list_voices()`` 的原始结果 → :class:`VoiceInfo` 列表"""
    voices = []
    seen = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        voice_id = str(item.get("ShortName") or "").strip()
        if not voice_id or voice_id in seen:
            continue
        seen.add(voice_id)
        gender = str(item.get("Gender") or "").strip().lower()
        if gender not in ("male", "female"):
            gender = ""
        voices.append(VoiceInfo(voice_id,
                                friendly_name(item.get("FriendlyName"), voice_id),
                                str(item.get("Locale") or "").strip(),
                                gender))
    voices.sort(key=lambda voice: (voice.locale, voice.gender, voice.name))
    return voices


def load_cached_voices():
    """读本地缓存的音色列表，返回 ``(voices, 时间戳)``"""
    try:
        with open(VOICE_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return [], 0.0
    if not isinstance(data, dict):
        return [], 0.0
    voices = parse_voices(data.get("voices"))
    try:
        stamp = float(data.get("time") or 0.0)
    except (TypeError, ValueError):
        stamp = 0.0
    return voices, stamp


def save_cached_voices(raw):
    """把 ``list_voices()`` 的原始结果写进缓存（原子替换，别写坏）"""
    try:
        payload = {"time": time.time(), "voices": raw}
        tmp = VOICE_CACHE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        tmp.replace(VOICE_CACHE_PATH)
        return True
    except OSError as exc:
        logger.log(f"写在线音色缓存失败: {exc}", "WARN")
        return False


def fetch_voices():
    """联网取音色列表（同步接口，供后台线程调用）"""
    import edge_tts
    return asyncio.run(asyncio.wait_for(edge_tts.list_voices(),
                                        timeout=SYNTH_TIMEOUT))


def synthesize(text, voice_id, percent):
    """联网合成一句，返回 MP3 字节（同步接口，**跑在后台线程**）"""
    import edge_tts

    async def collect():
        communicate = edge_tts.Communicate(text, voice=voice_id,
                                           rate=f"{int(percent):+d}%",
                                           volume="+0%")
        chunks = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return b"".join(chunks)

    return asyncio.run(asyncio.wait_for(collect(), timeout=SYNTH_TIMEOUT))


class EdgeBackend(TtsBackend):
    """在线音色（edge-tts），要联网，但音色多、听着自然"""

    name = "edge"

    #: 联网 + 合成都要时间，超时给宽一点
    timeout_factor = 2.0

    #: 音色列表变了（联网刷新回来 / 换过缓存）
    voices_changed = pyqtSignal()

    def __init__(self, parent=None, cache_size=8):
        super().__init__(parent)
        self._voices, self._stamp = load_cached_voices()
        self._current_voice = ""
        self._rate = 0.0
        self._volume = 1.0
        self._state = "idle"
        #: 每次说话 / 停止都会 +1，用来丢掉过期的合成结果
        self._generation = 0
        self._pending = None
        self._paused = False
        #: 合成线程记下的失败原因（给用户看的提示里带上）
        self._last_error = ""
        #: 上次失败是不是服务端拒绝握手（→ 该提示升级 edge-tts，而不是查网络）
        self._last_rejected = False
        self._fetching = False
        self._fetch_thread = None
        self._player = Mp3Player(self)
        self._player.started.connect(self._on_player_started)
        self._player.finished.connect(self._on_player_finished)
        self._player.failed.connect(self._on_player_failed)
        self._worker = ClipWorker(self._synth, self, cache_size=cache_size)
        self._worker.clip_ready.connect(self._on_clip_ready)
        self._worker.clip_failed.connect(self._on_clip_failed)

    # ---------------- 引擎接口 ----------------

    def available(self):
        return edge_available()

    def voices(self):
        return list(self._voices)

    def current_voice_id(self):
        return self._current_voice

    def voices_ready(self):
        """音色列表是不是已经拿到了（没有的话菜单里要先显示「正在获取」）"""
        return bool(self._voices)

    def refresh(self):
        """按需刷新音色列表：有缓存先用缓存，过期或为空再联网（后台线程）"""
        if not self._voices:
            self._voices, self._stamp = load_cached_voices()
        stale = (not self._voices) or (time.time() - self._stamp > VOICE_CACHE_TTL)
        if stale:
            self.refresh_async()
        return self._voices

    def refresh_async(self):
        """后台线程去联网取音色列表（不阻塞界面）"""
        if self._fetching or not edge_available():
            return False
        self._fetching = True
        self._fetch_thread = threading.Thread(target=self._fetch_worker,
                                              name="NovelMaster-edge-voices",
                                              daemon=True)
        self._fetch_thread.start()
        return True

    def set_voice(self, voice_id):
        voice_id = str(voice_id or "").strip()
        if not voice_id:
            return False
        self._current_voice = voice_id
        self._worker.cancel(clear_cache=False)
        logger.log(f"在线音色切换到 {voice_id}", "INFO")
        return True

    def set_rate(self, rate):
        try:
            self._rate = max(-1.0, min(1.0, float(rate or 0.0)))
        except (TypeError, ValueError):
            self._rate = 0.0
        return True

    def set_volume(self, volume):
        try:
            self._volume = max(0.0, min(1.0, float(volume)))
        except (TypeError, ValueError):
            self._volume = 1.0
        self._player.set_volume(self._volume)
        return True

    def speak(self, text):
        """读一句：先从缓存里找，没有就丢给后台合成"""
        if not edge_available():
            return self._refuse(i18n.t(
                "tts.error.edge_missing",
                default="在线音色需要 edge-tts，本机没有装上。"))
        if not self._current_voice:
            return self._refuse(i18n.t("tts.error.voice_missing",
                                       default="还没选音色，请先挑一个。"))

        spec = (self._current_voice, rate_to_percent(self._rate), text)
        self._generation += 1
        self._pending = spec
        self._paused = False
        self._player.stop()
        self._emit_state("speaking")

        cached = self._worker.cached(spec)
        if cached is not None:
            self._play(cached)
            return True
        self._worker.submit(spec)
        return True

    def preload(self, text):
        """预合成下一句（边放边下，轮到它时直接出声）"""
        if not text or not self._current_voice:
            return False
        spec = (self._current_voice, rate_to_percent(self._rate), text)
        if self._worker.cached(spec) is not None:
            return True
        return self._worker.submit(spec)

    def pause(self):
        self._paused = True
        if self._player.playing or self._player.position_ms() > 0:
            self._player.pause()
        self._emit_state("paused")
        return True

    def resume(self):
        self._paused = False
        if self._player.position_ms() > 0 or self._player.playing:
            self._player.resume()
        self._emit_state("speaking")
        return True

    def stop(self):
        self._generation += 1
        self._pending = None
        self._paused = False
        self._worker.cancel(clear_cache=False)
        self._player.stop()
        self._emit_state("idle")
        return True

    def shutdown(self):
        self.stop()
        self._worker.shutdown()
        self._player.shutdown()
        thread = self._fetch_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._fetch_thread = None
        self._voices = []

    # ---------------- 内部：音色列表 ----------------

    def _fetch_worker(self):
        try:
            raw = fetch_voices()
        except Exception as exc:  # noqa: BLE001 - 断网 / 超时 / 接口变了都算
            logger.log(f"获取在线音色列表失败（不影响朗读）：{exc}", "WARN")
        else:
            voices = parse_voices(raw)
            if voices:
                save_cached_voices(raw)
                self._voices = voices
                self._stamp = time.time()
                logger.log(f"在线音色列表已更新：{len(voices)} 个", "INFO")
                # 本函数跑在子线程里，不能直接发信号（监听方是界面对象），
                # 用 QueuedConnection 把「通知」投回自己的线程（主线程）
                QMetaObject.invokeMethod(self, "_notify_voices",
                                         Qt.QueuedConnection)
        self._fetching = False

    @pyqtSlot()
    def _notify_voices(self):
        """在引擎自己的线程里发 ``voices_changed``（不要在子线程里直接发）"""
        self.voices_changed.emit()

    # ---------------- 内部：合成 ----------------

    def _refuse(self, message):
        """受理但立刻报错，让上层用**具体**的原因提示用户"""
        logger.log(f"在线音色无法朗读：{message}", "WARN")
        QTimer.singleShot(0, lambda: self.failed.emit(message))
        return True

    def _synth(self, spec):
        """合成一句（**跑在后台线程**）：``spec`` → :class:`AudioClip`"""
        voice_id, percent, text = spec
        try:
            data = synthesize(text, voice_id, percent)
        except Exception as exc:  # noqa: BLE001 - 断网 / 超时 / 服务端不给音频
            logger.log(f"在线合成失败（{voice_id}）: {exc}", "ERROR")
            self._last_error = str(exc)
            self._last_rejected = is_rejected(exc)
            if self._last_rejected:
                logger.log(f"服务端拒绝握手，本机 edge-tts {edge_version_text()}，"
                           f"需要 {MIN_EDGE_TTS_TEXT} 或更新版本", "WARN")
            return None
        if not data:
            logger.log(f"在线合成没有音频（{voice_id}）: {text[:20]}", "WARN")
            self._last_error = "服务端没有返回音频"
            return None
        return AudioClip(data, 24000, 1, CODEC_MP3)

    # ---------------- 内部：播放 ----------------

    def _on_clip_ready(self, spec, clip):
        if spec != self._pending:
            return                        # 上一句的结果，丢掉
        if clip is None or clip.is_empty:
            self._pending = None
            self._emit_state("idle")
            self.failed.emit(self._synth_message(""))
            return
        self._play(clip)

    def _on_clip_failed(self, spec, message):
        if spec != self._pending:
            return
        self._pending = None
        self._emit_state("idle")
        self.failed.emit(self._synth_message(message))

    def _synth_message(self, message):
        """合成失败 → 一句用户能照着做的提示"""
        reason = self._last_error or message
        rejected, self._last_rejected = self._last_rejected, False
        self._last_error = ""
        if rejected or is_rejected(reason):
            # 这**不是**网络问题：说「请检查网络」只会让人白折腾
            return i18n.t("tts.error.edge_rejected",
                          default="在线音色服务拒绝连接：本机 edge-tts 是 {current}，"
                                  "微软现在的校验需要 {required} 或更新版本，"
                                  "请运行 pip install -U edge-tts 后重试。",
                          current=edge_version_text(),
                          required=MIN_EDGE_TTS_TEXT)
        text = i18n.t("tts.error.edge_failed",
                      default="在线音色合成失败，请检查网络后重试。")
        return text + (f"（{reason}）" if reason else "")

    def _play(self, clip):
        if not self._player.play(clip):
            self._pending = None
            self._emit_state("idle")
            self.failed.emit(i18n.t("tts.error.audio_failed",
                                    default="音频播放失败，请检查系统声音设置。"))
            return
        if self._paused:
            self._player.pause()

    def _on_player_started(self):
        self._emit_state("paused" if self._paused else "speaking")

    def _on_player_finished(self):
        self._pending = None
        self._emit_state("idle")
        self.finished.emit()

    def _on_player_failed(self, message):
        self._pending = None
        self._emit_state("idle")
        self.failed.emit(i18n.t("tts.error.audio_failed",
                                default="音频播放失败，请检查系统声音设置。")
                         + (f"（{message}）" if message else ""))

    def _emit_state(self, state):
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)


__all__ = ["MIN_EDGE_TTS", "MIN_EDGE_TTS_TEXT", "RATE_PERCENT_SPAN",
           "SYNTH_TIMEOUT", "VOICE_CACHE_PATH", "VOICE_CACHE_TTL", "EdgeBackend",
           "edge_available", "edge_outdated", "edge_version", "edge_version_text",
           "fetch_voices", "friendly_name", "is_rejected", "load_cached_voices",
           "parse_voices", "rate_text", "rate_to_percent", "save_cached_voices",
           "synthesize"]
