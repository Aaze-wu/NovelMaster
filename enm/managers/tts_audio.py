# -*- coding: utf-8 -*-
"""朗读的音频播放层（离线神经音色 / 在线神经音色的公共底座）。

系统引擎（SAPI）自己就会出声，不需要这一层；但神经音色的流程是
「文本 → 合成出音频 → 播放」，中间那段音频得由我们推进声卡，所以单独拆出
这个模块。它只管音频，**不认 sherpa-onnx / edge-tts**，方便单独测试。

三块内容：

* :class:`AudioClip` —— 一小段音频。采样率 + 声道 + 编码（``pcm`` / ``mp3``）；
* :class:`PcmPlayer` —— 推模式播放原始 PCM（``QAudioOutput``）。用推模式而不是
  把 ``QBuffer`` 丢给 Qt 拉，是为了能精确控制「写进去多少」——暂停（``suspend``）
  时缓冲里那点余量不会白放掉，恢复后从断点接着写，不会重读一小截；
* :class:`Mp3Player` —— 播放 MP3（``QMediaPlayer``）。edge-tts 只肯给 MP3
  （实测把输出格式改成 raw PCM 会被服务端拒掉），所以在线音色走这条支路；
* :class:`ClipWorker` —— 后台合成线程。合成很吃 CPU（Kokoro 实测 RTF≈0.7），
  放主线程上界面会卡死，所以统一丢给它；带一个「按文本缓存」，这样
  「预合成下一句」在真正轮到它时能立刻出声。

关于**采样率**：声卡不一定认 22050 / 24000 这种非标准采样率，遇到不认的时候
我们只做整数倍上采样（22050 → 44100、24000 → 48000，每个采样点复制一份）。
这比丢给系统重采样更可控，也免得引入外部依赖。
"""

import os
import tempfile
import threading
import time
from collections import OrderedDict

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtMultimedia import (QAudio, QAudioDeviceInfo, QAudioFormat,
                                QAudioOutput, QMediaContent, QMediaPlayer)

from ..logger import logger

#: 原始 PCM（16 位有符号小端）
CODEC_PCM = "pcm"

#: MP3 压缩音频
CODEC_MP3 = "mp3"


class AudioClip(object):
    """一小段音频（不可变）"""

    __slots__ = ("data", "sample_rate", "channels", "codec")

    def __init__(self, data, sample_rate, channels=1, codec=CODEC_PCM):
        self.data = data or b""
        self.sample_rate = int(sample_rate or 0)
        self.channels = int(channels or 1)
        self.codec = codec or CODEC_PCM

    @property
    def is_empty(self):
        return not self.data or self.sample_rate <= 0

    @property
    def duration_ms(self):
        """时长（毫秒）。MP3 是压缩数据，算不出准确值，返回 0"""
        if self.codec != CODEC_PCM or self.is_empty:
            return 0
        return int(len(self.data) / 2 / self.channels / self.sample_rate * 1000)

    def __repr__(self):  # pragma: no cover - 调试用
        return (f"AudioClip({self.codec}, {len(self.data)}B, "
                f"{self.sample_rate}Hz, {self.channels}ch)")


class _PlayerBase(QObject):
    """播放器的公共接口（界面与后端都按这个用，不关心底下是 PCM 还是 MP3）"""

    #: 这段音频正常放完了（不是因为调了 :meth:`stop`）
    finished = pyqtSignal()
    #: 真正出声了（推模式里要等第一块数据被声卡取走才算）
    started = pyqtSignal()
    #: 放不出来，参数是给用户看的说明
    failed = pyqtSignal(str)

    def play(self, clip):
        return False

    def pause(self):
        return False

    def resume(self):
        return False

    def stop(self):
        """停止并丢弃当前音频"""

    def set_volume(self, volume):
        """音量（``0.0`` ~ ``1.0``）"""

    @property
    def playing(self):
        """是否正在出声（暂停中算 ``False``）"""
        return False

    def position_ms(self):
        """已经放到哪儿了（算不出来返回 0）"""
        return 0

    def duration_ms(self):
        return 0

    def shutdown(self):
        """释放资源（关窗口时调用）"""


class PcmPlayer(_PlayerBase):
    """原始 PCM 播放器（推模式）

    工作方式：定时器每 :data:`TICK_MS` 毫秒往里塞一小块数据，塞多少看声卡还剩
    多少空闲（``bytesFree``），一次不超过 :data:`MAX_CHUNK_MS` —— 一次塞太多会
    让暂停 / 停下来的反应变迟钝。
    """

    #: 喂数据的间隔
    TICK_MS = 40
    #: 单次最多塞多少毫秒的音频
    MAX_CHUNK_MS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self._output = None
        self._device_io = None
        self._data = b""
        self._pos = 0
        self._chunk_bytes = 0
        self._frame_bytes = 2
        self._rate = 0
        self._volume = 1.0
        self._started = False
        self._finished = False
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ---------------- 播放控制 ----------------

    def play(self, clip):
        self.stop()
        if clip is None or clip.is_empty:
            return False
        if clip.codec != CODEC_PCM:
            self.failed.emit("unsupported codec")
            return False

        prepared = self._prepare(clip)
        if prepared is None:
            return False
        fmt, data, rate = prepared

        self._output = QAudioOutput(fmt, self)
        self._output.setVolume(self._volume)
        self._output.stateChanged.connect(self._on_state_changed)

        self._data = data
        self._pos = 0
        self._started = False
        self._finished = False
        self._frame_bytes = 2 * clip.channels
        self._rate = rate
        self._chunk_bytes = max(self._frame_bytes,
                                int(rate * self._frame_bytes
                                    * self.MAX_CHUNK_MS / 1000))
        self._device_io = self._output.start()
        if self._device_io is None:
            self._cleanup()
            self.failed.emit("no audio device")
            return False
        self._timer.start()
        return True

    def _prepare(self, clip):
        """按声卡能力拼出播放格式；必要时做整数倍上采样

        返回 ``(格式, 要播的数据, 实际采样率)``，搞不定返回 ``None``。
        """
        fmt = QAudioFormat()
        fmt.setSampleRate(clip.sample_rate)
        fmt.setChannelCount(clip.channels)
        fmt.setSampleSize(16)
        fmt.setCodec("audio/pcm")
        fmt.setByteOrder(QAudioFormat.LittleEndian)
        fmt.setSampleType(QAudioFormat.SignedInt)

        device = QAudioDeviceInfo.defaultOutputDevice()
        if device.isNull():
            logger.log("找不到音频输出设备，神经音色无法播放", "ERROR")
            return None
        if device.isFormatSupported(fmt):
            return fmt, clip.data, clip.sample_rate

        # 声卡不认这个采样率：试试整数倍上采样（22050→44100 / 24000→48000）
        for factor in (2, 4):
            target = clip.sample_rate * factor
            up = QAudioFormat(fmt)
            up.setSampleRate(target)
            if device.isFormatSupported(up):
                if clip.channels > 1:
                    stretched = b"".join(frame * factor
                                         for frame in _split_frames(clip.data,
                                                                    clip.channels))
                else:
                    stretched = clip.data * factor
                logger.log(f"声卡不支持 {clip.sample_rate}Hz，上采样到 "
                           f"{target}Hz 播放", "WARN")
                return up, stretched, target

        nearest = device.nearestFormat(fmt)
        logger.log(f"音频格式不受支持：{clip.sample_rate}Hz/{clip.channels}ch，"
                   f"声卡最近的是 {nearest.sampleRate()}Hz/"
                   f"{nearest.channelCount()}ch", "ERROR")
        return None

    def pause(self):
        if self._output is None or self._finished:
            return False
        self._timer.stop()
        try:
            self._output.suspend()
            return True
        except Exception as exc:  # pragma: no cover - 极少见
            logger.log(f"暂停音频失败: {exc}", "WARN")
            return False

    def resume(self):
        if self._output is None or self._finished:
            return False
        try:
            self._output.resume()
        except Exception as exc:  # pragma: no cover - 极少见
            logger.log(f"继续播放音频失败: {exc}", "WARN")
            return False
        self._timer.start()
        return True

    def stop(self):
        self._timer.stop()
        if self._output is not None:
            try:
                self._output.stop()
            except Exception:
                pass
        self._cleanup()
        self._data = b""
        self._pos = 0

    def set_volume(self, volume):
        self._volume = max(0.0, min(1.0, float(volume)))
        if self._output is not None:
            self._output.setVolume(self._volume)

    @property
    def playing(self):
        if self._output is None or not self._started or self._finished:
            return False
        return self._output.state() == QAudio.ActiveState

    def position_ms(self):
        if self._output is None:
            return 0
        try:
            return int(self._output.processedUSecs() / 1000)
        except Exception:  # pragma: no cover
            return 0

    def duration_ms(self):
        if not self._data or not self._rate:
            return 0
        return int(len(self._data) / self._frame_bytes / self._rate * 1000)

    def shutdown(self):
        self.stop()

    # ---------------- 内部 ----------------

    def _tick(self):
        if self._output is None or self._device_io is None:
            return
        total = len(self._data)
        if self._pos < total:
            free = self._output.bytesFree()
            if free > 0:
                want = min(free, total - self._pos, self._chunk_bytes)
                written = self._device_io.write(self._data[self._pos:self._pos + want])
                if written and written > 0:
                    self._pos += written
        if self._pos >= total and self._started and not self._finished:
            if self._output.state() == QAudio.IdleState:
                self._finish()

    def _on_state_changed(self, state):
        if state == QAudio.ActiveState and not self._started:
            self._started = True
            self.started.emit()
        elif state == QAudio.IdleState and self._started and not self._finished:
            # 数据全部喂完并且声卡空了：这一句放完了
            if self._pos >= len(self._data):
                self._finish()

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self.finished.emit()

    def _cleanup(self):
        output = self._output
        self._output = None
        self._device_io = None
        if output is not None:
            try:
                output.stateChanged.disconnect(self._on_state_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                output.deleteLater()
            except RuntimeError:
                pass


def _split_frames(data, channels):
    """把交错的 PCM 切成一个个「帧」（每个声道各一份采样）"""
    step = 2 * channels
    for start in range(0, len(data) - step + 1, step):
        yield data[start:start + step]


class Mp3Player(_PlayerBase):
    """MP3 播放器（``QMediaPlayer``）

    只用于在线音色（edge-tts 的输出格式写死是 MP3，服务端不接受 raw PCM）。
    数据先落到临时文件再交给 ``QMediaPlayer`` —— Windows 后端起播流式数据不可靠，
    落个文件最稳；文件在换句 / 停止 / 关窗口时删掉。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.error.connect(self._on_error)
        self._volume = 1.0
        self._active = False
        self._tmpdir = ""
        self._path = ""
        self._counter = 0
        self._duration = 0

    # ---------------- 播放控制 ----------------

    def play(self, clip):
        self.stop()
        if clip is None or not clip.data:
            return False
        if clip.codec != CODEC_MP3:
            self.failed.emit("unsupported codec")
            return False
        path = self._write_temp(clip.data)
        if not path:
            self.failed.emit("temp file")
            return False
        self._active = True
        self._player.setVolume(int(round(self._volume * 100)))
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self._player.play()
        return True

    def _write_temp(self, data):
        try:
            if not self._tmpdir:
                self._tmpdir = tempfile.mkdtemp(prefix="NovelMaster_tts_")
            self._counter += 1
            path = os.path.join(self._tmpdir, f"clip_{self._counter}.mp3")
            with open(path, "wb") as fh:
                fh.write(data)
            self._drop_temp()
            self._path = path
            return path
        except OSError as exc:
            logger.log(f"写临时音频文件失败: {exc}", "ERROR")
            return ""

    def _drop_temp(self):
        path, self._path = self._path, ""
        self._remove_file(path)

    @staticmethod
    def _remove_file(path):
        """删掉一个临时音频文件（后端还占着就留着，关窗口时统一清）"""
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def pause(self):
        if not self._active:
            return False
        self._player.pause()
        return True

    def resume(self):
        if not self._active:
            return False
        self._player.play()
        return True

    def stop(self):
        self._active = False
        try:
            self._player.stop()
        except RuntimeError:
            pass
        # 这里**不能**再 setMedia(QMediaContent())：清空媒体会让 Windows 后端
        # 回一个异步的 ResourceError，而它常常在下一句已经开播之后才到，正好
        # 把「上一句的错」算到新一句头上（用户看到的就是莫名其妙的播放失败）。
        # 媒体留着不管，下一次 play() 反正会换掉。
        self._drop_temp()
        self._duration = 0

    def set_volume(self, volume):
        self._volume = max(0.0, min(1.0, float(volume)))
        self._player.setVolume(int(round(self._volume * 100)))

    @property
    def playing(self):
        return self._active and self._player.state() == QMediaPlayer.PlayingState

    def position_ms(self):
        return self._player.position()

    def duration_ms(self):
        return self._player.duration() or self._duration

    def shutdown(self):
        self.stop()
        try:
            self._player.deleteLater()
        except RuntimeError:
            pass
        if self._tmpdir and os.path.isdir(self._tmpdir):
            for name in os.listdir(self._tmpdir):
                try:
                    os.remove(os.path.join(self._tmpdir, name))
                except OSError:
                    pass
            try:
                os.rmdir(self._tmpdir)
            except OSError:
                pass
        self._tmpdir = ""

    # ---------------- 回调 ----------------

    def _on_status(self, status):
        if not self._active:
            return
        if status == QMediaPlayer.BufferedMedia and not self._duration:
            self._duration = self._player.duration()
            self.started.emit()
        elif status == QMediaPlayer.EndOfMedia:
            self._active = False
            # 先把自己这句话的临时文件摘出来删掉，**再**通知上级换下一句。
            # 顺序反过来会出事：finished 是同步回调，下一句立刻就 setMedia 了，
            # 那时候 self._path 已经指向**新**文件，收尾的 _drop_temp() 会把
            # 正在播的新文件删掉，后端随即报 InvalidMedia，播放当场断掉。
            done, self._path = self._path, ""
            self._remove_file(done)
            self.finished.emit()

    def _on_error(self, error):
        if not self._active or error == QMediaPlayer.NoError:
            return
        # 换句时后端会为「上一段媒体」补一个异步错误回来（errorString() 常常
        # 是空的）。报错的媒体已经不是正在放的这一句了，扔掉，别误伤。
        media = self._player.currentMedia().canonicalUrl().toLocalFile()
        if media and self._path \
                and os.path.normcase(media) != os.path.normcase(self._path):
            return
        self._active = False
        logger.log(f"MP3 播放失败: {self._player.errorString()}", "ERROR")
        self.failed.emit(self._player.errorString() or "mp3 error")


class ClipWorker(QObject):
    """后台合成线程：把文本变成 :class:`AudioClip`

    * 串行合成（一次一句），带的缓存按**合成任务**索引，所以「预合成下一句」在真正
      轮到它时是直接命中的，不需要等；
    * ``generation`` 计数器负责作废：停止 / 换音色 / 改语速之后，上一轮还在跑的
      合成结果会被丢掉，不会突然冒出来；
    * 合成函数 ``synth(task) -> AudioClip | None`` 由调用方提供，跑在子线程里，
      **绝对不能碰界面对象**。

    ``key`` 与 ``task`` 都是「什么都可以」的对象（用元组传「模型 + 说话人 + 语速 +
    文本」这种组合最方便），所以信号参数类型是 ``object``。
    """

    #: 合成好了（key, AudioClip）
    clip_ready = pyqtSignal(object, object)
    #: 合成失败（key, 说明）
    clip_failed = pyqtSignal(object, str)

    #: 缓存多少段（一段最多十几秒，8 段撑死几 MB）
    CACHE_SIZE = 8

    def __init__(self, synth, parent=None, cache_size=None):
        super().__init__(parent)
        self._synth = synth
        self._cache_size = int(cache_size or self.CACHE_SIZE)
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self._jobs = []
        self._generation = 0
        self._pending = set()
        self._wake = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._loop,
                                        name="NovelMaster-tts-synth",
                                        daemon=True)
        self._thread.start()

    # ---------------- 提交 / 作废 ----------------

    def submit(self, key, text=None):
        """提交一次合成（``key`` 同时也是缓存键；``text`` 省略时就是 ``key``）"""
        if not key or not self._running:
            return False
        text = key if text is None else text
        generation = self._generation
        with self._lock:
            clip = self._cache.pop(key, None)
            if clip is not None:
                self._cache[key] = clip
        if clip is not None:
            # 缓存命中：走一遍事件循环再发信号，别在调用栈里同步回调
            clip = (generation, clip)
            QTimer.singleShot(0, lambda: self._emit_ready(key, clip))
            return True
        with self._lock:
            if key in self._pending:
                return True
            self._pending.add(key)
            self._jobs.append((generation, key, text))
        self._wake.set()
        return True

    def _emit_ready(self, key, payload):
        generation, clip = payload
        if generation != self._generation:
            return
        self.clip_ready.emit(key, clip)

    def cancel(self, clear_cache=True):
        """作废：丢掉排队中的、正在跑的、以及缓存里的合成结果"""
        self._generation += 1
        with self._lock:
            self._jobs = []
            self._pending.clear()
            if clear_cache:
                self._cache.clear()
        self._wake.set()

    def cached(self, key):
        """取缓存里的合成结果（没有返回 ``None``）"""
        with self._lock:
            clip = self._cache.get(key)
            if clip is not None:
                self._cache.move_to_end(key)
            return clip

    def has_pending(self):
        with self._lock:
            return bool(self._jobs) or bool(self._pending)

    def shutdown(self):
        self._running = False
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    # ---------------- 子线程 ----------------

    def _loop(self):
        while True:
            self._wake.wait(0.2)
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._jobs:
                        break
                    generation, key, text = self._jobs.pop(0)
                if generation != self._generation:
                    with self._lock:
                        self._pending.discard(key)
                    continue
                started = time.time()
                clip = None
                error = ""
                try:
                    clip = self._synth(text)
                except Exception as exc:  # noqa: BLE001 - 合成库抛什么都得兜住
                    error = str(exc) or exc.__class__.__name__
                    logger.log(f"合成失败: {error}", "ERROR")
                if generation != self._generation:
                    with self._lock:
                        self._pending.discard(key)
                    continue
                if clip is not None and not clip.is_empty:
                    with self._lock:
                        self._cache[key] = clip
                        while len(self._cache) > self._cache_size:
                            self._cache.popitem(last=False)
                        self._pending.discard(key)
                    logger.log(f"合成完成: {len(clip.data)}B / "
                               f"{clip.duration_ms}ms / {time.time() - started:.2f}s",
                               "DEBUG")
                    self.clip_ready.emit(key, clip)
                else:
                    with self._lock:
                        self._pending.discard(key)
                    self.clip_failed.emit(key, error or "empty audio")
            if not self._running:
                return
