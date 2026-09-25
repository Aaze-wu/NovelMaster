# -*- coding: utf-8 -*-
"""离线神经音色后端（sherpa-onnx 的 Piper / Kokoro 模型）。

和 :mod:`enm.managers.tts` 里的系统引擎相比，流程多了一步「合成」：

    文本 → sherpa-onnx 合成出 PCM → :class:`PcmPlayer` 推到声卡 → 放完报告

所以本模块的职责就是**把这一步串起来**，并且处理两件系统引擎不用操心的事：

* **合成在后台线程**（:class:`ClipWorker`）。Kokoro 实测 RTF≈0.7，也就是说一句
  4 秒的话要算 3 秒，放主线程上界面会卡；
* **预合成下一句**：当前句一开始播，就把下一句丢给后台算（:meth:`preload`），
  轮到它时直接从缓存出声，中间不会出现「读一句停一下」的空档。

模型不在安装包里，第一次用要在程序里下载（见 :mod:`enm.managers.tts_models`）。
没装 ``sherpa-onnx`` 或一个模型都没有时 :meth:`available` 返回 ``False``，
界面据此把入口置灰，程序照常启动。
"""

from PyQt5.QtCore import QTimer

from .. import i18n
from ..logger import logger
from . import tts_models
from .tts import TtsBackend, VoiceInfo
from .tts_audio import CODEC_PCM, AudioClip, ClipWorker, PcmPlayer

#: 语音 id 的分隔符（``piper-chaowen|0``）：前半段是模型目录名，后半段是说话人编号
VOICE_SEP = "|"

#: 语速映射：界面上的 ``rate``（``-1`` ~ ``1``）→ sherpa-onnx 的 ``speed`` 倍数。
#: ``1.0`` 是原始速度，最大 1.6 倍、最小 0.4 倍 —— 再快就开始糊字了。
RATE_SPAN = 0.6


def sherpa_available():
    """本机装没装 ``sherpa-onnx``"""
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError as exc:
        logger.log(f"没装 sherpa-onnx，离线神经音色不可用: {exc}", "INFO")
        return False
    except Exception as exc:  # noqa: BLE001 - 装了但加载不了（缺 DLL 等）
        logger.log(f"加载 sherpa-onnx 失败，离线神经音色不可用: {exc}", "ERROR")
        return False
    return True


def voice_id_for(model_id, sid):
    """拼一个语音 id"""
    return f"{model_id}{VOICE_SEP}{int(sid)}"


def split_voice_id(voice_id):
    """拆语音 id，返回 ``(model_id, sid)``；拆不开返回 ``(None, 0)``"""
    text = str(voice_id or "")
    if VOICE_SEP not in text:
        return None, 0
    model_id, _sep, raw = text.rpartition(VOICE_SEP)
    try:
        return model_id, int(raw)
    except ValueError:
        return None, 0


def rate_to_speed(rate):
    """界面语速 → sherpa-onnx 的 ``speed``"""
    try:
        value = max(-1.0, min(1.0, float(rate or 0.0)))
    except (TypeError, ValueError):
        value = 0.0
    return round(1.0 + value * RATE_SPAN, 3)


def _to_pcm16(samples):
    """sherpa-onnx 给的浮点采样（``-1.0`` ~ ``1.0``）→ 16 位小端 PCM"""
    if not samples:
        return b""
    try:
        import numpy as np
    except ImportError:
        return b"".join(
            int(max(-1.0, min(1.0, value)) * 32767).to_bytes(2, "little",
                                                            signed=True)
            for value in samples)
    array = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    return (array * 32767.0).astype("<i2").tobytes()


class SherpaBackend(TtsBackend):
    """离线神经音色（Piper / Kokoro），走 sherpa-onnx 本地推理"""

    name = "sherpa"

    #: 神经音色要「先合成再播放」，比系统引擎慢，超时给宽一点
    timeout_factor = 3.0

    def __init__(self, parent=None, cache_size=8):
        super().__init__(parent)
        self._voices = []
        self._current_voice = ""
        self._rate = 0.0
        self._volume = 1.0
        self._state = "idle"
        #: 已经建好的 ``OfflineTts`` 对象（**只在合成线程里碰**）
        self._engines = {}
        #: 每次说话 / 停止都会 +1，用来丢掉过期的合成结果
        self._generation = 0
        #: 当前等着的合成任务（``(模型, 说话人, 语速, 文本)``）
        self._pending = None
        self._paused = False
        #: 合成线程记下的失败原因（给用户看的提示里带上）
        self._last_error = ""
        self._player = PcmPlayer(self)
        self._player.started.connect(self._on_player_started)
        self._player.finished.connect(self._on_player_finished)
        self._player.failed.connect(self._on_player_failed)
        self._worker = ClipWorker(self._synth, self, cache_size=cache_size)
        self._worker.clip_ready.connect(self._on_clip_ready)
        self._worker.clip_failed.connect(self._on_clip_failed)
        self.refresh()

    # ---------------- 引擎接口 ----------------

    def available(self):
        """本机装没装 ``sherpa-onnx``（**还没下模型也算能用**）

        没下模型时音色列表是空的，但这正是用户要去「音色管理」下载的时候，
        所以这里不能判死 —— 否则用户永远进不去那个窗口。要不要真的选它由
        调用方决定：自动挑引擎时会跳过没有音色的它（见 ``tts.create_backend``）。
        """
        return sherpa_available()

    def voices(self):
        return list(self._voices)

    def current_voice_id(self):
        return self._current_voice

    def refresh(self):
        """重新扫一遍已下载的模型（装完 / 删完模型后调用）"""
        voices = []
        for info in tts_models.installed_models():
            for sid, name, locale, gender in info.voices:
                voices.append(VoiceInfo(voice_id_for(info.model_id, sid),
                                        name, locale, gender))
        self._voices = voices
        if self._current_voice and not any(
                voice.voice_id == self._current_voice for voice in voices):
            self._current_voice = ""
        if not self._current_voice and voices:
            self._current_voice = voices[0].voice_id
        return voices

    def set_voice(self, voice_id):
        model_id, _sid = split_voice_id(voice_id)
        if not model_id or not tts_models.is_installed(model_id):
            logger.log(f"切换神经音色失败（模型没装）: {voice_id}", "WARN")
            return False
        if voice_id not in [voice.voice_id for voice in self._voices]:
            self.refresh()
        self._current_voice = voice_id
        self._worker.cancel(clear_cache=False)
        logger.log(f"神经音色切换到 {voice_id}", "INFO")
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
        model_id, sid = split_voice_id(self._current_voice)
        if not model_id:
            if tts_models.installed_models():
                return self._refuse(i18n.t("tts.error.voice_missing",
                                           default="还没选音色，请先挑一个。"))
            # 一个模型都没下：真正要做的不是「挑音色」而是「下模型」
            return self._refuse(i18n.t(
                "tts.error.model_missing",
                default="这个音色的模型还没下载，请到「朗读 → 音色管理」里下载。"))
        files = tts_models.model_files(model_id)
        if files is None:
            return self._refuse(i18n.t(
                "tts.error.model_missing",
                default="这个音色的模型还没下载，请到「朗读 → 音色管理」里下载。"))

        spec = (model_id, sid, rate_to_speed(self._rate), text)
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
        """预合成下一句（当前句还在放的时候后台先算出来）"""
        model_id, sid = split_voice_id(self._current_voice)
        if not model_id or not text:
            return False
        spec = (model_id, sid, rate_to_speed(self._rate), text)
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
        """停止：丢掉还没合成的结果，也掐掉正在放的音频"""
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
        self._engines = {}
        self._voices = []

    # ---------------- 内部：合成 ----------------

    def _refuse(self, message):
        """受理但立刻报错：这样队列会用**具体**的原因提示用户

        （直接返回 ``False`` 的话，上层只知道「引擎不受理」，只能给一句
        笼统的「系统语音引擎不可用」。）
        """
        logger.log(f"神经音色无法朗读：{message}", "WARN")
        QTimer.singleShot(0, lambda: self.failed.emit(message))
        return True

    def _load(self, model_id):
        """建 / 取 ``OfflineTts``（只在合成线程里调用）"""
        engine = self._engines.get(model_id)
        if engine is not None:
            return engine
        info = tts_models.model_info(model_id)
        files = tts_models.model_files(model_id)
        if info is None or files is None:
            return None
        try:
            import sherpa_onnx
        except ImportError as exc:
            logger.log(f"没装 sherpa-onnx: {exc}", "ERROR")
            return None

        try:
            if info.engine == "kokoro":
                model = sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=files["model"], tokens=files["tokens"],
                    voices=files["voices"], lexicon=files["lexicon"],
                    data_dir=files["data_dir"], dict_dir=files["dict_dir"],
                    # 别传 "zh"：混排文本里的英文会被吞掉（C++ 侧报
                    # Failed to set eSpeak-ng voice 'zh'），空串是自动判定
                    lang="")
                model_config = sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=model, num_threads=2, provider="cpu")
            else:
                model = sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=files["model"], tokens=files["tokens"],
                    lexicon=files["lexicon"])
                model_config = sherpa_onnx.OfflineTtsModelConfig(
                    vits=model, num_threads=2, provider="cpu")
            config = sherpa_onnx.OfflineTtsConfig(
                model=model_config, rule_fsts=files["rule_fsts"],
                max_num_sentences=1)
            engine = sherpa_onnx.OfflineTts(config)
        except Exception as exc:  # noqa: BLE001
            logger.log(f"加载语音模型 {model_id} 失败: {exc}", "ERROR")
            return None
        logger.log(f"语音模型 {model_id} 已加载"
                   f"（{engine.sample_rate}Hz，{engine.num_speakers} 个说话人）",
                   "INFO")
        self._engines[model_id] = engine
        return engine

    def _synth(self, spec):
        """合成一句（**跑在后台线程**）：``spec`` → :class:`AudioClip`"""
        model_id, sid, speed, text = spec
        engine = self._load(model_id)
        if engine is None:
            self._last_error = "模型加载失败"
            return None
        try:
            audio = engine.generate(text, sid=int(sid), speed=float(speed))
        except Exception as exc:  # noqa: BLE001
            logger.log(f"语音合成失败（{model_id}）: {exc}", "ERROR")
            self._last_error = str(exc)
            return None
        pcm = _to_pcm16(getattr(audio, "samples", None))
        if not pcm:
            logger.log(f"语音合成没有出声（{model_id}）: {text[:20]}", "WARN")
            self._last_error = "合成结果为空"
            return None
        return AudioClip(pcm, getattr(audio, "sample_rate", 0), 1, CODEC_PCM)

    # ---------------- 内部：播放 ----------------

    def _on_clip_ready(self, spec, clip):
        if spec != self._pending:
            return                        # 上一句的结果，丢掉
        if clip is None or clip.is_empty:
            self._pending = None
            self._emit_state("idle")
            self.failed.emit(i18n.t("tts.error.synth_failed",
                                    default="语音合成失败，这句读不出来。")
                             + self._error_suffix())
            return
        self._play(clip)

    def _on_clip_failed(self, spec, message):
        if spec != self._pending:
            return
        self._pending = None
        self._emit_state("idle")
        self.failed.emit(i18n.t("tts.error.synth_failed",
                                default="语音合成失败，这句读不出来。")
                         + self._error_suffix(message))

    def _error_suffix(self, message=""):
        """拼上具体原因（合成线程记下的优先，worker 的 "empty audio" 没什么用）"""
        reason = self._last_error or message
        self._last_error = ""
        return f"（{reason}）" if reason else ""

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


__all__ = ["RATE_SPAN", "VOICE_SEP", "SherpaBackend", "rate_to_speed",
           "sherpa_available", "split_voice_id", "voice_id_for"]
