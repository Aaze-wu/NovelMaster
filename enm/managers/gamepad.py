# -*- coding: utf-8 -*-
"""手柄支持（Windows XInput）。

为什么直接拿 ``ctypes`` 调 XInput、而不装第三方手柄库：``XInput1_4.dll`` 是
Windows 8 以上**系统自带**的（Win10 / Win11 一定在），所以这块功能
**不需要任何新依赖**，requirements.txt 一行都不用改。这一点和全局媒体键
（:mod:`enm.managers.media_keys` 走 winrt）的取舍不同：winrt 不是系统自带的，
那边必须做成可选依赖；这边只需要判断「能不能加载 DLL」。

设计要点
--------

* 手柄是**状态**而不是**事件**：要自己保存上一帧的按键位图做 0→1 边沿检测，
  否则按住一次会连发几十次（这一条是这类代码最常见的坑）。
* **左摇杆上下 = 滚动阅读区**，是固定行为、不参与改键。理由和鼠标一样：
  摇杆是模拟量（推得越深滚得越快），而绑定槽里存的是「按一下 = 执行一次」
  的离散命令，两者混在一起没法表达。手柄的离散按键才进
  :mod:`enm.shortcuts` 的第三个绑定槽（``shortcuts_pad``）。
* 手柄**没有「焦点」概念**，也不像媒体键那样是全局的：本模块只负责发信号，
  要不要响应由主窗口决定（见 ``NovelMaster.on_gamepad_token``，只在主窗口
  是前台窗口时才响应）。
* 线程模型照抄 :class:`enm.managers.media_keys.MediaKeysController`：
  ``QObject`` + 信号 + 守护线程 + ``threading.Event`` 收工。信号从工作线程
  发出，接收方（主窗口）在 GUI 线程，Qt 会自动排成队列连接，不需要自己加锁。

改代码前先看一眼这几条踩过的坑
------------------------------

1. 想读 **Xbox 键（Guide）** 只能用序号导出的 ``XInputGetStateEx``
   （``dll[100]``）——``XInputGetState`` 里那一位永远是 0。
   序号 100 在 ``XInput9_1_0.dll`` 上不存在，所以**按序号取**，
   取不到就退回普通版（退回去只是读不到 Guide 键，别的都正常）。
2. 空槽位返回 ``ERROR_DEVICE_NOT_CONNECTED``（1167），**不是**返回 0。
   返回码要判等，不然「没插手柄」会被当成「手柄一个键都没按」而白忙。
3. 左摇杆 Y 轴**向上是正数**，跟屏幕坐标相反，滚动时要取负号。
4. ``XINPUT_STATE`` 是 16 字节、``XINPUT_GAMEPAD`` 是 12 字节，结构体写错
   会静默读出垃圾值（不会报错），所以模块里带一个 ``self_check()``。
5. 没有手柄时不要按 60 Hz 空转：找不到手柄就退到 2 Hz 慢慢问，
   插上之后再升回 60 Hz（见 :data:`POLL_IDLE` / :data:`POLL_ACTIVE`）。
6. 退出时一定要把震动关掉，否则最后一下震动会一直转到拔电源。
7. **「关震动」这一下必须写得住**：震动是「记住最后一次设置」，但第三方手柄
   的 XInput 模拟层会吞掉紧跟在脉冲之后的那次 0（也可能因为那一刻跑到别的
   槽位上而写丢），马达就会一直转到下次按键 —— 也就是用户报上来的
   「手柄一直震，再按一下才停」。所以关震动要**反复写、四个槽位都写**，
   还要看 ``XInputSetState`` 的返回码（见 :data:`RUMBLE_RELEASE_MS`）。
"""

import ctypes
import sys
import threading
import time
from collections import namedtuple

from PyQt5.QtCore import QObject, pyqtSignal

from ..logger import logger
from ..shortcuts import (PAD_A, PAD_B, PAD_BACK, PAD_DOWN, PAD_GUIDE,
                         PAD_LB, PAD_LEFT, PAD_LSTICK, PAD_RB, PAD_RIGHT,
                         PAD_RSTICK, PAD_RT, PAD_START, PAD_LT, PAD_UP, PAD_X,
                         PAD_Y)

# 一次轮询读到的内容（只保留用得到的字段）
PadState = namedtuple("PadState", "buttons left_trigger right_trigger thumb_ly")

# XInput 返回码
ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167

# 按钮位（前 14 个是文档里的；Xbox 键那一位不在文档里）
BUTTON_MASKS = (
    (0x0001, PAD_UP),
    (0x0002, PAD_DOWN),
    (0x0004, PAD_LEFT),
    (0x0008, PAD_RIGHT),
    (0x0010, PAD_START),
    (0x0020, PAD_BACK),
    (0x0040, PAD_LSTICK),
    (0x0080, PAD_RSTICK),
    (0x0100, PAD_LB),
    (0x0200, PAD_RB),
    (0x1000, PAD_A),
    (0x2000, PAD_B),
    (0x4000, PAD_X),
    (0x8000, PAD_Y),
)
#: 只有 ``XInputGetStateEx`` 会报这一位（XINPUT_GAMEPAD_GUIDE）
GUIDE_MASK = 0x0400

# 扳机是 0~255 的模拟量，超过这个值就当「按下」
TRIGGER_THRESHOLD = 30
# 摇杆死区。XInput 1.4 会自己套一遍，1.3 不会，所以这里自己再判一次，
# 两个版本行为就一致了（重复判死区没有副作用）
LEFT_THUMB_DEADZONE = 7849
#: 摇杆满推时每一帧滚多少像素（按推力平方缩放，轻推慢滚、推满快滚）
STICK_SCROLL_MAX_PX = 42.0
#: 刚出死区时的最低速度。平方曲线在死区边缘几乎等于 0，光靠它要十几秒
#: 才滚一个像素，用户会以为摇杆坏了；这里给一个下限保证「推了就有反应」
STICK_SCROLL_MIN_PX = 2.0

# 按住不放会连发的键：翻章、上/下一句、语速这类「按住了就想一直走」的键。
# A / B 这种开关型按键**故意不连发** —— 连发会把朗读开开关关几十次。
# 只按记号判定，不看它绑到了哪个动作：用户把 A 改绑成下一章时按住 A 不会连发，
# 这只是少个便利；反过来（开关型动作被连发）是会出乱子的。
REPEAT_TOKENS = frozenset((PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT,
                           PAD_LB, PAD_RB, PAD_LT, PAD_RT, PAD_X, PAD_Y))
#: 按住后隔多久开始连发、之后每次间隔多少秒
REPEAT_DELAY = 0.35
REPEAT_INTERVAL = 0.09

# 轮询间隔：有手柄时快、没有时慢（别为了一个没插的硬件一直 60 Hz 空转）
POLL_ACTIVE = 0.016
POLL_IDLE = 0.5

# 震动反馈：很短的一下，表示「命令收到了」
RUMBLE_MS = 70
RUMBLE_STRENGTH = 0.32
#: 单次震动的时间上限（调用方传得再大也砍到这里，防呆）
RUMBLE_MAX_MS = 500
# 脉冲结束之后还要**反复**写 0 多久 —— 这一段叫「消磁窗口」。
# 为什么要反复写：XInput 的震动是「记住最后一次设置」，理论上写一次 0 就够，
# 但**第三方手柄**（8BitDo / 北通 / 飞智这类走 XInput 模拟层的）会吞掉紧跟在
# 脉冲后面的那一次 0，于是马达一直转到「下一次有非 0 写入再写 0」才停 —— 正是
# 用户报上来的「手柄一直震，再按一下手柄才停」。窗口里多写几次、四个槽位都写，
# 被吞掉几次也无所谓。
RUMBLE_RELEASE_MS = 600
#: 消磁窗口里每隔多久写一遍 0（600 ms / 100 ms ≈ 6 次）
RUMBLE_RELEASE_INTERVAL = 0.1
#: 消磁窗口**至少**要写够几次 0。界面在忙着做耗时动作（开朗读、换章）时
#: 工作线程可能被饿上好几秒，光靠「窗口内才写」会一次都没写就被跳过，
#: 所以次数是硬下限，跟时间窗口哪个宽就按哪个来。
RUMBLE_RELEASE_WRITES = 6

#: 候选 DLL（1.4 支持手柄插拔热插拔，9_1_0 只认老版驱动，放最后兜底）
DLL_NAMES = ("XInput1_4.dll", "XInput1_3.dll", "XInput9_1_0.dll")
#: 最多认几号槽位（XInput 固定 0~3）
MAX_SLOTS = 4


class _XInputState(ctypes.Structure):
    """XINPUT_STATE（16 字节）"""

    _fields_ = [("dwPacketNumber", ctypes.c_uint32),
                ("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _XInputVibration(ctypes.Structure):
    """XINPUT_VIBRATION（4 字节，两个马达各 0~65535）"""

    _fields_ = [("wLeftMotorSpeed", ctypes.c_ushort),
                ("wRightMotorSpeed", ctypes.c_ushort)]


class _Api:
    """XInput 的最小封装：函数指针 + 读状态 + 设震动

    每次读都新建一个状态结构体（16 字节，开销可以忽略），这样 GUI 线程
    偶尔调 :meth:`read` 时不会和工作线程抢同一块缓冲区。
    """

    def __init__(self, name, get_state, set_state, guide):
        self.dll_name = name
        self.guide = bool(guide)
        self._get_state = get_state
        self._set_state = set_state

    def read(self, slot):
        """读一个槽位的状态；没手柄或读失败时返回 ``None``"""
        state = _XInputState()
        code = self._get_state(slot, ctypes.byref(state))
        if code != ERROR_SUCCESS:
            return None
        return PadState(state.wButtons, int(state.bLeftTrigger),
                        int(state.bRightTrigger), int(state.sThumbLY))

    def set_vibration(self, slot, strength):
        """设震动强度（0~1）；返回 XInput 的错误码（``None`` = 这个 DLL 没这接口）

        返回码要往外传：``XInputSetState`` 在「手柄刚拔掉」「槽位没手柄」等情况
        下会失败，调用方得知道这一下 0 到底写进去没有 —— 写丢了马达就会一直转。
        """
        if self._set_state is None:
            return None
        value = int(max(0.0, min(1.0, strength)) * 65535)
        vibration = _XInputVibration(value, value)
        try:
            return int(self._set_state(slot, ctypes.byref(vibration)))
        except OSError as e:
            logger.log(f"XInputSetState 调用失败（槽位 {slot}）: {e}", "WARN")
            return ERROR_DEVICE_NOT_CONNECTED

    def any_connected(self):
        """有没有任何一台手柄连着"""
        return any(self.read(slot) is not None for slot in range(MAX_SLOTS))


def _load_api():
    """加载 XInput，返回 ``(api, 原因)``；加载不了时 ``api`` 为 ``None``"""
    if sys.platform != "win32":
        return None, "手柄支持只在 Windows 上可用"
    reason = "找不到 XInput"
    for name in DLL_NAMES:
        try:
            dll = ctypes.WinDLL(name)
        except OSError as e:
            reason = f"加载 {name} 失败: {e}"
            continue
        get_state = getattr(dll, "XInputGetState", None)
        if get_state is None:
            reason = f"{name} 里没有 XInputGetState"
            continue
        # 序号 100 的 XInputGetStateEx 才报 Xbox 键；取不到就退回普通版
        get_state_ex = None
        try:
            get_state_ex = dll[100]
        except (OSError, IndexError, ValueError):
            get_state_ex = None
        getter = get_state_ex or get_state
        getter.argtypes = [ctypes.c_uint32, ctypes.POINTER(_XInputState)]
        getter.restype = ctypes.c_uint32
        set_state = getattr(dll, "XInputSetState", None)
        if set_state is not None:
            set_state.argtypes = [ctypes.c_uint32,
                                  ctypes.POINTER(_XInputVibration)]
            set_state.restype = ctypes.c_uint32
        return _Api(name, getter, set_state, get_state_ex is not None), ""
    return None, reason


# 探测结果只做一次（反复加载 DLL 没必要，而且 menu 勾选状态要查它）
_PROBE_LOCK = threading.Lock()
_PROBED = False
_API = None
_REASON = ""


def _ensure_api():
    """懒加载 XInput（返回 ``_Api`` 或 ``None``）"""
    global _PROBED, _API, _REASON
    with _PROBE_LOCK:
        if not _PROBED:
            _API, _REASON = _load_api()
            _PROBED = True
        return _API


def gamepad_importable():
    """手柄支持在这台机器上能不能用（只看系统组件在不在）

    对应 media_keys 那边的 ``media_keys_importable()``：判断的是「功能理论上
    能不能跑」，跟「现在有没有插手柄」无关。
    """
    return _ensure_api() is not None


def gamepad_unavailable_reason():
    """手柄支持不可用的原因（可用时返回空字符串）"""
    _ensure_api()
    return _REASON


def gamepad_connected():
    """现在有没有手柄插着（每次都真去问一次系统）"""
    api = _ensure_api()
    if api is None:
        return False
    return api.any_connected()


def gamepad_guide_supported():
    """能不能读到 Xbox 键（只有序号导出的 XInputGetStateEx 报得出来）"""
    api = _ensure_api()
    return bool(api is not None and api.guide)


def gamepad_available():
    """手柄功能现在能不能派上用场：系统组件在 + 至少有一台手柄连着"""
    return gamepad_importable() and gamepad_connected()


def self_check():
    """启动自检：结构体大小不对就直接报出来（写错了会读出垃圾值而不报错）"""
    problems = []
    if ctypes.sizeof(_XInputState) != 16:
        problems.append(f"XINPUT_STATE 大小 {ctypes.sizeof(_XInputState)} != 16")
    if ctypes.sizeof(_XInputVibration) != 4:
        problems.append(
            f"XINPUT_VIBRATION 大小 {ctypes.sizeof(_XInputVibration)} != 4")
    return problems


class GamepadController(QObject):
    """手柄轮询器：把 XInput 的「状态」翻成「按下了哪个键」

    信号
    ----

    * :attr:`token` —— 按下了一个手柄键，带的是 ``enm.shortcuts`` 里的手柄记号
      （``PadA`` / ``PadLB``…），外加一个「是不是长按连发」的标志，由主窗口
      查绑定表后派发（连发的那几次不震动，否则按住不放会一直嗡嗡）
      ；
    * :attr:`scroll` —— 左摇杆要让阅读区滚多少像素（正数往下）；
    * :attr:`connection` —— 手柄插上 / 拔掉（主窗口只记日志，用于排查）。

    用法（照 media_keys 的样子）：``start()`` 起线程，退出前 ``stop()``。
    """

    token = pyqtSignal(str, bool)
    scroll = pyqtSignal(int)
    connection = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._error = ""
        self._api = None
        #: 当前认的是哪个槽位（-1 = 没有手柄）
        self._slot = -1
        self._rumble_until = 0.0
        self._rumble_strength = 0.0
        #: 消磁窗口的截止时刻（脉冲结束后还要反复写一会儿 0，见 RUMBLE_RELEASE_MS）
        self._rumble_release_until = 0.0
        #: 消磁窗口里上一次写 0 的时刻（用来限流，不用每帧都写）
        self._last_release_write = 0.0
        #: 本次消磁已经写了几次 0（脉冲时归零，写够 RUMBLE_RELEASE_WRITES 为止）
        self._release_writes = 0

    # ---------------- 生命周期 ----------------

    def start(self):
        """起轮询线程（已经在跑或起不来时返回 ``False``）"""
        if self._running:
            return True
        api = _ensure_api()
        if api is None:
            self._error = gamepad_unavailable_reason() or "XInput 不可用"
            return False
        self._api = api
        self._error = ""
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="gamepad",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """停轮询线程并关掉震动（不关的话最后一下震动会一直转下去）"""
        self._stop_event.set()
        self._running = False
        self._clear_vibration()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._slot = -1

    def is_running(self):
        """轮询线程在不在跑"""
        return self._running

    def is_connected(self):
        """当前有没有认到手柄"""
        return self._slot >= 0

    def error(self):
        """出错原因（正常时是空字符串）"""
        return self._error

    def rumble(self, strength=RUMBLE_STRENGTH, ms=RUMBLE_MS):
        """短震一下（可在设置里关掉）。

        这里只记下「震到什么时候」，真正调 DLL 的是轮询线程：GUI 线程里
        别做这种小动作，免得手柄突然被拔掉时卡住界面。
        """
        ms = max(0.0, min(float(RUMBLE_MAX_MS), float(ms)))
        with self._lock:
            now = time.monotonic()
            self._rumble_strength = max(0.0, min(1.0, float(strength)))
            self._rumble_until = now + ms / 1000.0
            # 消磁窗口必须**盖住**脉冲之后的一段：脉冲本身只有几十毫秒，
            # 紧跟着写的那一次 0 有可能被手柄的 XInput 模拟层吞掉
            self._rumble_release_until = (self._rumble_until
                                          + RUMBLE_RELEASE_MS / 1000.0)
            self._last_release_write = 0.0
            self._release_writes = 0

    def stop_rumble(self):
        """立刻停下正在震的这一下（并进入消磁窗口）

        留给「手柄一直震」的手动出口：设置里把「手柄震动反馈」取消勾选就会
        调到这里，比「再按一下手柄」直接些。
        """
        self._clear_vibration()

    # ---------------- 轮询线程 ----------------

    def _loop(self):
        """轮询主循环（跑在工作线程里，别在这里碰任何 Qt 界面对象）"""
        previous_buttons = 0
        previous_triggers = (False, False)
        last_held = ""
        next_repeat = 0.0
        scroll_carry = 0.0
        rumble_on = False
        was_connected = False
        try:
            while not self._stop_event.is_set():
                slot, state = self._scan()
                connected = state is not None
                if connected != was_connected:
                    was_connected = connected
                    self._slot = slot if connected else -1
                    # 插拔之后上一帧的按键状态全部作废，否则会误判成一直按着
                    previous_buttons = 0
                    previous_triggers = (False, False)
                    last_held = ""
                    scroll_carry = 0.0
                    # 拔掉的那一帧一定要补写一次「关震动」：XInput 只会记住最后一次
                    # 设置，漏掉这一下有概率让马达一直转到下次按键（就是这么被用户
                    # 报上来的）。消磁窗口会把四个槽位都写一遍 0，插/拔两个方向都
                    # 顺手清一次，免得手柄带着上一次的残留状态回来。
                    self._clear_vibration()
                    self._announce(connected)
                if not connected:
                    self._stop_event.wait(POLL_IDLE)
                    continue
                self._slot = slot

                now = time.monotonic()
                buttons = state.buttons
                if self._api.guide and buttons & GUIDE_MASK:
                    buttons |= GUIDE_MASK

                # ---- 按键：0→1 的边沿才算「按下」，按住不放走下面的连发 ----
                pressed = buttons & ~previous_buttons
                for mask, token in BUTTON_MASKS:
                    if pressed & mask:
                        self.token.emit(token, False)
                if pressed & GUIDE_MASK and self._api.guide:
                    self.token.emit(PAD_GUIDE, False)
                previous_buttons = buttons

                # ---- 扳机（0~255 的模拟量，按阈值当按键）----
                left = state.left_trigger >= TRIGGER_THRESHOLD
                right = state.right_trigger >= TRIGGER_THRESHOLD
                if left and not previous_triggers[0]:
                    self.token.emit(PAD_LT, False)
                if right and not previous_triggers[1]:
                    self.token.emit(PAD_RT, False)
                previous_triggers = (left, right)

                # ---- 长按连发 ----
                held = [token for mask, token in BUTTON_MASKS
                        if buttons & mask and token in REPEAT_TOKENS]
                if left:
                    held.append(PAD_LT)
                if right:
                    held.append(PAD_RT)
                if held:
                    token = held[0]
                    if token != last_held:
                        # 换了个键按住：重新计时（连发不跨键继承）
                        last_held = token
                        next_repeat = now + REPEAT_DELAY
                    elif now >= next_repeat:
                        self.token.emit(token, True)
                        next_repeat = now + REPEAT_INTERVAL
                else:
                    last_held = ""

                # ---- 左摇杆上下 = 滚动（模拟量，推得越深滚得越快）----
                scroll_carry = self._feed_scroll(state, scroll_carry)

                # ---- 震动反馈 ----
                rumble_on = self._update_rumble(slot, now, rumble_on)

                self._stop_event.wait(POLL_ACTIVE)
        except Exception as e:  # noqa: BLE001
            self._error = f"手柄轮询线程异常退出: {e}"
            self._running = False
            logger.log(self._error, "ERROR")
        finally:
            self._clear_vibration()

    def _scan(self):
        """找一台连着的手柄，返回 ``(槽位, 状态)``；没有就 ``(-1, None)``

        认到哪台就一直用哪台（只用第一台，避免两台手柄各按一下变成两下）；
        它拔了才重新扫一遍找下一台。
        """
        if self._slot >= 0:
            state = self._api.read(self._slot)
            if state is not None:
                return self._slot, state
        for slot in range(MAX_SLOTS):
            state = self._api.read(slot)
            if state is not None:
                return slot, state
        return -1, None

    def _feed_scroll(self, state, carry):
        """把左摇杆的纵向偏移换算成滚动像素（返回新的余量）"""
        deviation = state.thumb_ly
        if abs(deviation) <= LEFT_THUMB_DEADZONE:
            return 0.0
        # 归一化到 0~1：不减去死区的话刚过阈值就会跳到很快
        span = 32767 - LEFT_THUMB_DEADZONE
        ratio = min(1.0, (abs(deviation) - LEFT_THUMB_DEADZONE) / span)
        # 速度 = 下限 + (上限 - 下限) * ratio²：刚出死区也有 STICK_SCROLL_MIN_PX
        # 那么快，推满时到 STICK_SCROLL_MAX_PX
        speed = (STICK_SCROLL_MIN_PX
                 + (STICK_SCROLL_MAX_PX - STICK_SCROLL_MIN_PX)
                 * ratio * ratio)
        # Y 轴向上是正数、滚动条向下才是变大，所以方向取反
        direction = -1.0 if deviation > 0 else 1.0
        carry += direction * speed
        # 一帧滚不到一个像素时把零头留着，不然轻推会完全不动
        whole = int(carry)
        if whole:
            carry -= whole
            self.scroll.emit(whole)
        return carry

    def _update_rumble(self, slot, now, rumble_on):
        """按需开关震动（返回这一帧结束后震动是不是开着的）

        关震动时是**反复写** 0（消磁窗口，见 :data:`RUMBLE_RELEASE_MS`），而且
        四个槽位都写：XInput 只「记住最后一次设置」，一次 0 被第三方手柄吞掉、
        或者那一帧恰好跑到别的槽位上，马达就会一直转到下次按键才停。
        """
        with self._lock:
            strength = self._rumble_strength
            until = self._rumble_until
            release = self._rumble_release_until
            writes = self._release_writes
        if strength > 0 and now < until:
            self._api.set_vibration(slot, strength)
            return True
        if now < release or writes < RUMBLE_RELEASE_WRITES:
            # 消磁窗口：每 RUMBLE_RELEASE_INTERVAL 写一遍 0；即便窗口已经过完，
            # 只要还没写够 RUMBLE_RELEASE_WRITES 次就继续补（工作线程被饿住时
            # 靠这一条兜底）
            if now - self._last_release_write >= RUMBLE_RELEASE_INTERVAL:
                with self._lock:
                    self._last_release_write = now
                    self._release_writes = writes + 1
                self._write_off_all()
            return True
        if rumble_on:
            self._write_off_all()
        return False

    def _write_off_all(self):
        """给四个槽位都写一遍 0（只关震动，不动「震到什么时候」的记录）

        写 0 到没有手柄的槽位是无害的（``XInputSetState`` 返回 1167 而已），
        但能兜住「脉冲和 0 写到了不同槽位」这种把马达留在震动上的情况。
        """
        api = self._api
        if api is None:
            return
        for slot in range(MAX_SLOTS):
            try:
                api.set_vibration(slot, 0.0)
            except OSError:  # 理论上 set_vibration 自己吞了，这里再兜一层
                pass

    def _clear_vibration(self):
        """把马达关掉并清掉「正在震」的记录（退出 / 拔手柄 / 手动停时调）

        注意这里**不只是「写一次 0」**：写完之后还要把消磁窗口重新武装一遍
        （见 :data:`RUMBLE_RELEASE_MS`），因为要压住的恰恰就是「一次 0 被手柄
        吞掉」这种情况 —— 所有「停震」路径都走这一个函数，语义就不会分叉。
        """
        self._write_off_all()
        with self._lock:
            now = time.monotonic()
            self._rumble_strength = 0.0
            self._rumble_until = 0.0
            self._rumble_release_until = now + RUMBLE_RELEASE_MS / 1000.0
            self._last_release_write = now
            self._release_writes = 0

    def _announce(self, connected):
        """手柄插拔时写一条日志并通知主窗口"""
        logger.log(f"手柄{'已连接' if connected else '已断开'}")
        self.connection.emit(connected)
