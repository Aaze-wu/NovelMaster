"""用 DWM 给原生窗口标题栏上色（Windows 11 22H2 / Build 22000 起支持）。

为什么要单独一个模块：``dwmapi`` 的调用**必须**在窗口 ``show()`` 之后、拿到
真实 ``hwnd``（``int(widget.winId())``）才能生效，而且窗口被重新创建（切换
窗口标志、从最大化还原等极端情况）时得重新应用一次。把这些细节集中在这里，
界面层只要两句话：``apply_titlebar_theme(...)`` / ``reset_titlebar_theme(...)``。

四个必须记住的坑：

* **COLORREF 是 BGR，不是 RGB**。``DwmSetWindowAttribute`` 收的是
  ``0x00BBGGRR``，直接把 ``0xRRGGBB`` 塞进去会得到「红蓝对调」的颜色，
  而且看起来「也能用」，特别容易查不出来。靠 :func:`_to_colorref` 兜住。
* **属性 34/35/36 是只写的**。``DwmGetWindowAttribute`` 读它们返回
  ``E_INVALIDARG``，所以这里**没有**对应的 getter，也别试着写单元测试断言
  「读回来的颜色对不对」——只能断言调用返回 ``S_OK``。
* **老系统不认这些属性**。Win11 22000 以下（Win10、Server）调用会返回失败码，
  但这不影响程序：返回非 0 就静默跳过，标题栏保持系统默认样式。所以这里
  永远不抛异常给上层。
* **颜色得算明暗**。``DWMWA_USE_IMMERSIVE_DARK_MODE`` 决定标题栏上「最小化 /
  最大化 / 关闭」三个按钮画成深色还是浅色，取错了会出现「深底深按钮」糊成
  一片。按标题栏底色的明度自动判断，也可以由调用方显式指定。

整个模块**不依赖 Qt**（只依赖 ctypes），但接口按 Qt 的用法设计，方便
``main_window.py`` 直接把 ``self.winId()`` 丢进来。
"""

import ctypes
import sys

from ..managers.theme import is_dark

#: 边框颜色（DwmSetWindowAttribute 用）
DWMWA_BORDER_COLOR = 34
#: 标题栏底色
DWMWA_CAPTION_COLOR = 35
#: 标题栏文字色
DWMWA_TEXT_COLOR = 36
#: 深色 / 浅色模式标志（决定三个系统按钮的明暗）
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
#: 旧的深色模式标志值，Win10 1809 起可用；新版系统用 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19

#: 特殊值：不画边框（让标题栏与内容区连成一片）
DWMWA_COLOR_NONE = 0xFFFFFFFE
#: 特殊值：恢复系统默认颜色
DWMWA_COLOR_DEFAULT = 0xFFFFFFFF

_S_OK = 0
#: DwmSetWindowAttribute 要求的值大小（DWORD）
_DWORD_SIZE = 4

_is_windows = sys.platform.startswith("win")

try:
    if _is_windows:
        _dwm = ctypes.windll.dwmapi
    else:
        _dwm = None
except OSError:  # pragma: no cover - 极老的系统上 dwmapi 可能不存在
    _dwm = None

#: 缓存一次「这台机器支不支持标题栏上色」的判断结果
_support_cache = None


def available():
    """本平台是否提供 dwmapi（非 Windows 一律为 False）"""
    return _dwm is not None


def _to_colorref(color):
    """``#rrggbb`` → COLORREF（``0x00BBGGRR``）。

    注意顺序是 **BGR**：``#569CD6`` → ``0x00D69C56``。
    """
    if not isinstance(color, str):
        return None
    text = color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        return None
    try:
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
    except ValueError:
        return None
    return (blue << 16) | (green << 8) | red


def _set_attribute(hwnd, attribute, value):
    """调用 ``DwmSetWindowAttribute``，返回是否成功（``S_OK``）。

    任何异常（ctypes 缺失、hwnd 已失效……）都吞掉返回 ``False``：
    标题栏上色是「锦上添花」，绝不能因为它让主窗口起不来。
    """
    if _dwm is None or not hwnd:
        return False
    try:
        data = ctypes.c_uint(value & 0xFFFFFFFF)
        result = _dwm.DwmSetWindowAttribute(
            ctypes.c_void_p(int(hwnd)), int(attribute),
            ctypes.byref(data), ctypes.sizeof(data))
    except (OSError, OverflowError, TypeError, ValueError, AttributeError):
        return False
    return (result & 0xFFFFFFFF) == _S_OK


def supports_caption_color(hwnd=None):
    """这台机器能不能给标题栏上色。

    有 ``hwnd`` 时做一次真实调用（而不是猜版本号）；没给 ``hwnd`` 就按系统
    版本粗判——Win11 Build 22000 起支持，返回 ``False`` 时界面层会退化成
    「只切深浅模式」。

    结果会缓存：这是台机器维度的能力，同一进程里不会变。
    """
    global _support_cache
    if not available():
        return False

    if hwnd:
        # 真实探测：给边框色写一个「恢复默认」，返回 S_OK 就说明属性被认了
        return _set_attribute(hwnd, DWMWA_BORDER_COLOR, DWMWA_COLOR_DEFAULT)

    if _support_cache is not None:
        return _support_cache

    _support_cache = False
    if _is_windows:
        try:
            version = sys.getwindowsversion()
            _support_cache = (version.major, version.build) >= (10, 22000)
        except (AttributeError, OSError):
            _support_cache = False
    return _support_cache


def apply_titlebar_theme(hwnd, theme, dark=None):
    """把主题的标题栏配色应用到 ``hwnd`` 上。

    ``theme`` 用 13 色齐全的主题字典（``ThemeManager.get_theme()`` 的输出）。
    ``dark`` 为 ``None`` 时按 ``titlebar`` 底色的明度自动判断；显式传
    ``True`` / ``False`` 可以强制。

    返回成功应用的属性个数（``0`` 表示这台机器做不到，调用方可以据此决定
    要不要退回「只切深浅」）。窗口还没 ``show()`` 时 ``hwnd`` 是无效的，
    调用会静默失败——请在 ``show()`` 之后调用。
    """
    if not hwnd or not theme:
        return 0

    if dark is None:
        dark = is_dark(theme.get("titlebar") or theme.get("background")
                       or "#FFFFFF")

    applied = 0
    caption = _to_colorref(theme.get("titlebar"))
    text = _to_colorref(theme.get("titlebar_text"))
    border = _to_colorref(theme.get("border"))

    if caption is not None:
        applied += _set_attribute(hwnd, DWMWA_CAPTION_COLOR, caption)
    if text is not None:
        applied += _set_attribute(hwnd, DWMWA_TEXT_COLOR, text)
    if border is not None:
        applied += _set_attribute(hwnd, DWMWA_BORDER_COLOR, border)

    if _set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0):
        applied += 1
    else:
        # Win10 1809~21H2 只认旧标志值，试一次不亏
        applied += _set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                                  1 if dark else 0)

    if _support_cache is None:
        # 第一次调用顺便记下能力判断结果（边框色写成功了 = 支持）
        globals()["_support_cache"] = bool(applied)

    return applied


def apply_dark_mode(hwnd, dark):
    """只切标题栏的深浅模式（老系统降级路径）。

    返回是否成功。
    """
    if not hwnd:
        return False
    if _set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0):
        return True
    return bool(_set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                               1 if dark else 0))


def reset_titlebar_theme(hwnd):
    """恢复系统默认的标题栏样式（切回「跟随系统」时用）"""
    if not hwnd:
        return 0
    applied = 0
    for attribute in (DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
                      DWMWA_BORDER_COLOR):
        applied += _set_attribute(hwnd, attribute, DWMWA_COLOR_DEFAULT)
    applied += _set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                              DWMWA_COLOR_DEFAULT)
    return applied


def hide_border(hwnd):
    """让标题栏不再画那道边框线（``DWMWA_COLOR_NONE``）。

    Windows 11 会在窗口四周画一条 1px 的强调色边框，颜色由系统挑，和我们
    的主题未必搭。想看「融为一体」的效果就调用它。
    """
    return _set_attribute(hwnd, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE)


def apply_to_widget(widget, theme, dark=None):
    """给任意 QWidget（主窗口或对话框）的原生标题栏上色。

    只用到 ``widget.winId()``，所以本模块不需要 import Qt。**必须在窗口
    ``show()`` 之后调用**——``show()`` 之前``winId()`` 拿不到真实的窗口句柄，
    DWM 那边会静默失败。稳妥的做法是在 ``showEvent()`` 里调。

    ``theme`` 为空时什么都不做，返回 ``0``。
    """
    if widget is None or not theme:
        return 0
    try:
        hwnd = int(widget.winId())
    except (AttributeError, TypeError, ValueError):
        return 0
    return apply_titlebar_theme(hwnd, theme, dark=dark)
