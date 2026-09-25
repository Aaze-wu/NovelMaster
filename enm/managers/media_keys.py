"""全局媒体键与系统媒体面板（v1.3.9，Windows 10/11）。

键盘上的播放 / 暂停、上一首 / 下一首在 Windows 里不是「按了就给当前窗口」，
而是先交给**当前媒体会话**（SMTC，System Media Transport Controls）——也就是
任务栏音量条旁边那个媒体浮层背后的东西。想让 NovelMaster 变成那个会话，得照
下面这套来（每一条都是实测出来的，少一条就一个事件都收不到）：

1. 进程要设 AppUserModelID（见 :func:`_set_app_user_model_id`），而且这个 ID 得
   **由一个带 ``AppUserModelID`` 属性的开始菜单快捷方式承载**——在安装程序里配
   （``InstallerMakerScript/NovelMaster-Release.iss`` 的 ``[Icons]``）。Windows
   是把「AUMID → 应用名」记在快捷方式上的：shell 的 ``AppsFolder`` 里查不到这个
   ID 时，媒体浮层标题只会写「未知应用」。只往注册表 ``HKCU\\Software\\Classes\\
   AppUserModelId\\<AUMID>`` 写 ``DisplayName``（:func:`_register_app_user_model_id`）
   **不够**，那份登记只影响提示类界面；也因此，直接跑 ``dist`` 里的绿色版（没有
   快捷方式）时浮层仍会显示「未知应用」；
2. ``MediaPlayer`` 与它的 SMTC 必须建在**自己跑消息泵的线程**上，而且该线程要以
   **STA** 初始化——建在 Qt 主线程上、或者用 MTA，都收不到任何事件（Qt 自己的
   事件循环不会派发 WinRT 事件）；
3. 先关掉 ``command_manager``，**再**打开 ``smtc.is_enabled``；顺序反了会静默把
   会话关掉（``is_enabled`` 读回来还是 True，但按键不会再送到我们这边）；
4. 会话背后要有音源在播，这里用一段程序生成的静音 WAV 循环播放（代价是音量
   合成器里会多一个 NovelMaster 的静音会话）；
5. 送 PLAY 还是 PAUSE 由我们上报的 ``playback_status`` 决定：朗读中报 PLAYING，
   其余报 PAUSED（报 PAUSED 时系统才送 PLAY，否则「暂停后接着听」收不到键）。

实测结论：按键是**全局**派发的，不需要窗口在前台，甚至不需要窗口可见——只要
进程里有个真实存在的顶层窗口、并且上面这套会话开着。

``winrt`` 是可选依赖：没装时 :func:`media_keys_available` 返回 False，整块功能
自动关掉（设置里的开关会置灰），主窗口完全不受影响。
"""

import ctypes
import importlib.util
import queue
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

from ..constants import AUTHOR_NAME, ICON_PATH, PROJECT_NAME
from ..logger import logger

#: 进程的 AppUserModelID（没有它，系统不会把我们当成一个媒体应用）
APP_USER_MODEL_ID = "{}.{}.MediaKeys".format(AUTHOR_NAME, PROJECT_NAME)

#: 登记「AUMID → 显示名 / 图标」的注册表位置（在 HKCU 下，不需要管理员）
USER_MODEL_ID_PATH = r"Software\Classes\AppUserModelId"

#: 静音音源：循环播放，只为让 SMTC 会话有音源撑着
SILENCE_FILE_NAME = "{}_silence.wav".format(PROJECT_NAME)
SILENCE_SECONDS = 10
SILENCE_RATE = 22050

#: 按钮 → 我们的动作名
BUTTON_ACTIONS = {
    "PLAY": "toggle",
    "PAUSE": "toggle",
    "STOP": "stop",
    "NEXT": "next",
    "PREVIOUS": "previous",
}

#: 消息泵每轮之间的歇息（秒）：0.005 时按键延迟约 5ms 上下
PUMP_SLEEP = 0.005

#: 缓存 winrt 投影（成功是对象，失败是原因字符串）
_PROJECTIONS = None
_IMPORT_ERROR = None


class _Projections:
    """懒加载的 winrt 符号集合。

    放在一个类里只是为了少写一堆模块级 import —— winrt 是可选依赖，主窗口没开
    这个功能时不该为它付出导入开销。
    """

    def __init__(self):
        from winrt import runtime
        from winrt.windows.foundation import Uri
        from winrt.windows.media import (MediaPlaybackStatus, MediaPlaybackType)
        from winrt.windows.media.core import MediaSource
        from winrt.windows.media.playback import MediaPlayer

        self.runtime = runtime
        self.Uri = Uri
        self.MediaPlaybackStatus = MediaPlaybackStatus
        self.MediaPlaybackType = MediaPlaybackType
        self.MediaSource = MediaSource
        self.MediaPlayer = MediaPlayer


def _load_projections():
    """导入 winrt 投影；不可用时抛 ImportError（原因会被缓存）"""
    global _PROJECTIONS, _IMPORT_ERROR
    if _PROJECTIONS is not None:
        return _PROJECTIONS
    if _IMPORT_ERROR is not None:
        raise ImportError(_IMPORT_ERROR)
    try:
        _PROJECTIONS = _Projections()
    except Exception as e:  # noqa: BLE001 - 缺包 / 平台不支持都算「不可用」
        _IMPORT_ERROR = "{}: {}".format(type(e).__name__, e)
        raise ImportError(_IMPORT_ERROR)
    return _PROJECTIONS


def media_keys_importable():
    """包里到底有没有 winrt（只翻文件、不导入，供建菜单时快速判断）

    与 :func:`media_keys_available` 的区别只在于**不触发导入**：winrt 是可选的，
    没开这个功能的用户不该为一次探测付出导入开销。
    """
    if sys.platform != "win32":
        return False
    try:
        return importlib.util.find_spec("winrt") is not None
    except Exception:  # noqa: BLE001
        return False


def media_keys_available():
    """本机能不能用全局媒体键（Windows + 装了 winrt 投影组件，真的导入一次）"""
    if sys.platform != "win32":
        return False
    try:
        _load_projections()
    except Exception:  # noqa: BLE001
        return False
    return True


def media_keys_unavailable_reason():
    """不可用的原因（给日志 / 设置项提示用）"""
    if sys.platform != "win32":
        return "当前系统不是 Windows"
    try:
        _load_projections()
    except Exception as e:  # noqa: BLE001
        return str(e)
    return ""


def _ensure_silence_file():
    """准备（并复用）静音 WAV，返回路径；失败返回 None"""
    path = Path(tempfile.gettempdir()) / SILENCE_FILE_NAME
    try:
        if path.exists() and path.stat().st_size > 44:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SILENCE_RATE)
            handle.writeframes(b"\x00\x00" * SILENCE_RATE * SILENCE_SECONDS)
        return path
    except Exception as e:  # noqa: BLE001
        logger.log("媒体键：静音音源准备失败（{}）".format(e), "WARN")
        return None


def _app_display_name():
    """媒体浮层上要显示的应用名（跟随界面语言，取不到就退回项目名）"""
    try:
        from ..i18n import t

        name = t("app.name")
        if name:
            return str(name)
    except Exception:  # noqa: BLE001 - 语言没起来也不该拖累媒体键
        pass
    return PROJECT_NAME


def _register_app_user_model_id(name):
    """在 HKCU 里登记 AUMID 的显示名与图标（只影响提示类界面）

    真正让媒体浮层叫出应用名的是**带 ``AppUserModelID`` 属性的开始菜单快捷方式**
    （安装程序里配的），不是这里：实测只写注册表时，shell 的 ``AppsFolder`` 依然
    查不到这个 AUMID，浮层标题照旧是「未知应用」。这份登记是照 MuseHub、Watt
    Toolkit 那类桌面应用的做法补的，给提示类界面一个 ``DisplayName`` / ``IconUri``，
    并且**不需要管理员权限**。

    幂等：值一样就不碰注册表；失败只影响显示名，不影响按键。
    """
    try:
        import winreg
    except ImportError:  # noqa: BLE001 - 非 Windows 上走不到这里
        return False

    values = [("DisplayName", name)]
    try:
        if ICON_PATH.is_file():
            values.append(("IconUri", str(ICON_PATH)))
    except OSError:
        pass

    path = "{}\\{}".format(USER_MODEL_ID_PATH, APP_USER_MODEL_ID)
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            for value_name, value in values:
                try:
                    current = winreg.QueryValueEx(key, value_name)[0]
                except OSError:  # 值还不存在
                    current = None
                if current != value:
                    winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)
        return True
    except Exception as e:  # noqa: BLE001
        logger.log("媒体键：应用名登记失败（{}）".format(e), "WARN")
        return False


def _set_app_user_model_id():
    """给进程设 AppUserModelID，并登记它的显示名（失败只影响显示名，不影响按键）"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(APP_USER_MODEL_ID))
    except Exception as e:  # noqa: BLE001
        logger.log("媒体键：AppUserModelID 设置失败（{}）".format(e), "WARN")
        return False
    _register_app_user_model_id(_app_display_name())
    return True


class _Msg(ctypes.Structure):
    """Win32 ``MSG``（只用到 hwnd / message，其余字段对齐用）"""

    _fields_ = [("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]


class MediaKeysController(QObject):
    """把系统媒体键翻译成 Qt 信号。

    用法：``start()`` 之后用 :meth:`set_track` / :meth:`set_playing` 上报当前在
    放什么、放没放；按键回来时发出 :attr:`action`。

    所有 WinRT 对象都只活在自己的 STA 线程里（主线程碰不到，也不该碰），主线程
    与它的往来只有两样东西：一个命令队列（往下传状态）和一个信号（往上回按键）。
    """

    #: 媒体键动作：``toggle``（播放 / 暂停）、``stop``、``next``、``previous``
    action = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._commands = queue.Queue()
        self._stopping = threading.Event()
        self._thread = None
        self._running = False
        self._ready = False
        self._silence_file = None
        self._error = ""
        #: 期望状态（会话还没起来时先存着，起来时一次性套上）
        self._desired = {"playing": False, "title": "", "subtitle": ""}

    # ---------------- 对外接口 ----------------

    def is_running(self):
        """会话线程是否已经起来（起来了才值得往队列里塞状态）"""
        return self._running

    def error(self):
        """最近一次启动失败的原因（没失败时是空字符串）"""
        return self._error

    def start(self, playing=False, title="", subtitle=""):
        """启动会话；返回是否成功（失败时 :meth:`error` 里有原因）"""
        if self._running:
            return True
        if not media_keys_available():
            self._error = media_keys_unavailable_reason()
            return False
        self._silence_file = _ensure_silence_file()
        if self._silence_file is None:
            self._error = "静音音源不可用"
            return False

        self._desired = {"playing": bool(playing),
                         "title": title or "",
                         "subtitle": subtitle or ""}
        # 清掉上一轮剩下的命令，避免复用时把旧状态又套一遍
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                break
        self._stopping.clear()
        self._error = ""
        self._running = True
        self._ready = False
        self._thread = threading.Thread(target=self._worker, name="media-keys",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """停掉会话（等线程收尾，最多 2 秒）"""
        if not self._running:
            return
        self._stopping.set()
        thread, self._thread = self._thread, None
        self._running = False
        self._ready = False
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=2.0)

    def set_track(self, title, subtitle=""):
        """更新媒体面板上的「书名 / 章节名」（标题与副标题都用音乐属性）"""
        title, subtitle = title or "", subtitle or ""
        if (self._desired.get("title") == title
                and self._desired.get("subtitle") == subtitle):
            return
        self._desired["title"] = title
        self._desired["subtitle"] = subtitle
        self._post(("track", (title, subtitle)))

    def set_playing(self, playing):
        """上报「是不是正在出声」：决定系统送 PLAY 还是 PAUSE 键"""
        playing = bool(playing)
        if self._desired.get("playing") == playing:
            return
        self._desired["playing"] = playing
        self._post(("playing", playing))

    def _post(self, command):
        """往会话线程塞一条命令

        会话刚启动、还没建好那几毫秒里也照样塞：命令会等在队列里，线程建好会话
        后的第一轮循环就会把它套上，不会丢状态。
        """
        if self._running:
            self._commands.put(command)

    # ---------------- 会话线程 ----------------

    def _worker(self):
        runtime = None
        projections = None
        player = smtc = updater = None
        try:
            try:
                projections = _load_projections()
            except Exception as e:  # noqa: BLE001
                self._error = str(e)
                logger.log("媒体键不可用：{}".format(e), "WARN")
                return
            runtime = projections.runtime

            try:
                # 线程套间：必须是 STA，MTA 收不到 SMTC 事件
                runtime.init_apartment(runtime.STA)
            except Exception as e:  # noqa: BLE001 - 已经初始化过也算正常
                logger.log("媒体键：套间初始化提示（{}）".format(e), "WARN")

            try:
                player, smtc, updater = self._open_session(projections)
            except Exception as e:  # noqa: BLE001
                self._error = "{}: {}".format(type(e).__name__, e)
                logger.log("媒体键启动失败：{}".format(self._error), "WARN")
                return

            self._ready = True
            logger.log("全局媒体键已启用（媒体面板显示书名与章节）")
            while not self._stopping.is_set():
                self._apply_commands(projections, smtc, updater)
                self._pump_messages()
        except Exception as e:  # noqa: BLE001 - 线程里出了什么都没法往上抛
            logger.log("媒体键线程异常：{}".format(e), "ERROR")
        finally:
            self._ready = False
            self._close_session(player, smtc)
            try:
                if runtime is not None:
                    runtime.uninit_apartment()
            except Exception:  # noqa: BLE001
                pass

    def _open_session(self, projections):
        """建好播放器与 SMTC 会话，返回 ``(player, smtc, display_updater)``"""
        _set_app_user_model_id()

        player = projections.MediaPlayer()
        player.is_looping_enabled = True
        uri = projections.Uri(Path(self._silence_file).as_uri())
        player.source = projections.MediaSource.create_from_uri(uri)
        smtc = player.system_media_transport_controls
        # 回调是 WinRT 调进这个线程的，qt 信号会在主线程那边排队送达
        smtc.add_button_pressed(self._on_button_pressed)

        # 顺序不能换：先关命令管理器，再开会话
        player.command_manager.is_enabled = False
        smtc.is_enabled = True
        for name in ("is_play_enabled", "is_pause_enabled", "is_next_enabled",
                     "is_previous_enabled", "is_stop_enabled"):
            try:
                setattr(smtc, name, True)
            except Exception:  # noqa: BLE001 - 个别属性不支持就当没有
                pass

        updater = smtc.display_updater
        updater.type = projections.MediaPlaybackType.MUSIC
        self._write_track(updater, self._desired.get("title"),
                          self._desired.get("subtitle"))
        player.play()
        self._write_playing(projections, smtc, self._desired.get("playing"))
        return player, smtc, updater

    def _close_session(self, player, smtc):
        """收尾：关会话、停播放（都要容错，退出路径上不能再抛）"""
        if smtc is not None:
            try:
                smtc.is_enabled = False
            except Exception:  # noqa: BLE001
                pass
        if player is not None:
            for method in ("pause", "close"):
                try:
                    getattr(player, method)()
                except Exception:  # noqa: BLE001
                    pass

    def _pump_messages(self):
        """自己跑消息泵：WinRT 的事件回调靠它派发"""
        user32 = ctypes.windll.user32
        message = _Msg()
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        time.sleep(PUMP_SLEEP)

    def _apply_commands(self, projections, smtc, updater):
        """把主线程塞进来的状态改动落到会话上"""
        while True:
            try:
                name, value = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                if name == "playing":
                    self._write_playing(projections, smtc, value)
                elif name == "track":
                    title, subtitle = value
                    self._write_track(updater, title, subtitle)
            except Exception as e:  # noqa: BLE001
                logger.log("媒体键状态更新失败（{}）".format(e), "WARN")

    def _write_track(self, updater, title, subtitle):
        """写媒体面板的标题 / 副标题（副标题借音乐属性的「专辑艺术家」）"""
        properties = updater.music_properties
        properties.title = (title or PROJECT_NAME)[:128]
        properties.artist = (subtitle or "")[:128]
        updater.update()

    def _write_playing(self, projections, smtc, playing):
        """上报播放状态：决定系统送 PLAY 还是 PAUSE"""
        status = projections.MediaPlaybackStatus
        smtc.playback_status = status.PLAYING if playing else status.PAUSED

    def _on_button_pressed(self, _sender, args):
        """SMTC 按钮回调（跑在会话线程上）"""
        try:
            name = args.button.name
        except Exception:  # noqa: BLE001
            return
        action = BUTTON_ACTIONS.get(name)
        if action:
            self.action.emit(action)
