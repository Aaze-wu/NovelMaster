"""主题管理：内置主题 + ``themes`` 目录下的自定义主题。

一套主题 = **13 个颜色** + 可选的排版信息。

必需色（旧主题文件里只有这 5 个，也是其余配色的推导起点）::

    background / foreground / accent / highlight / border

扩展色（缺省时按必需色自动推导，见 :func:`derive_missing`）::

    titlebar        窗口标题栏底色（走 DWM，见 :mod:`enm.ui.titlebar`）
    titlebar_text   标题栏文字色
    selection       选中项 / 选中文本的底色（原来硬绑 accent）
    disabled        禁用态文字色（原来硬绑 border）
    scrollbar       滚动条滑块色（原来硬绑 border）
    tooltip         工具提示底色
    sidebar         左侧章节列表底色
    reader          阅读区底色（沉浸阅读的米黄 / 护眼绿就靠它）

排版字段（可选，主题带不带都行）::

    font_family / font_size / line_spacing / paragraph_spacing

注意 ``line_spacing`` / ``paragraph_spacing`` 不能靠样式表生效（Qt 的
``line-height`` 是无效属性），真正落地靠 :mod:`enm.ui.reader_typography`
里的块格式，本模块只负责把值存对、校验住。

本模块只管数据（校验、推导、读写 ``themes/*.json``、增删改查），颜色怎么用由
:mod:`enm.ui.theme_qss` 决定。校验失败时返回的是「语言键 + 参数」，翻译交给
界面层，这样管理器本身不依赖 i18n，也**不依赖 Qt**：颜色换算全在这里自己算，
所以每个换算函数的数值语义都必须与 ``QColor`` 对齐（见 :func:`lightness`）。

有三个坑必须在这里兜住：

* :meth:`ThemeManager.get_theme` **永远返回字段齐全的主题**。``apply_theme()``
  是按 ``theme['background']`` 直接取值的，缺字段会直接把主窗口的构造打崩，
  而主题名已经写进 ``config.json``，重启依旧崩——等于程序再也起不来。
* 内置主题名（``light`` / ``dark``）不允许被自定义主题占用。``get_theme()``
  先查内置，同名的自定义主题永远取不到，却又删不掉（列表里看不见），是纯粹的坑。
* :data:`FIELD_GROUPS` 必须**完整覆盖** :data:`COLOR_FIELDS`，否则主题编辑器
  里会少几个颜色项——用户看不见就永远改不了。界面层还会兜一层「没归组的
  字段自动补到最后一组」，双保险。
"""

import json
import re
from pathlib import Path

from ..constants import THEMES_PATH
from ..logger import logger

#: 必需色：旧主题文件里就这 5 个，也是推导其余颜色的起点
REQUIRED_COLOR_FIELDS = ("background", "foreground", "accent", "highlight", "border")

#: 扩展色：缺省时按必需色推导，不写进文件也能用
OPTIONAL_COLOR_FIELDS = ("titlebar", "titlebar_text", "selection", "disabled",
                         "scrollbar", "tooltip", "sidebar", "reader")

#: 全部颜色字段（顺序即界面里的排列顺序）
COLOR_FIELDS = REQUIRED_COLOR_FIELDS + OPTIONAL_COLOR_FIELDS

#: 主题编辑器里的分组：(语言键, 字段元组)
FIELD_GROUPS = (
    ("theme_editor.group_base", REQUIRED_COLOR_FIELDS),
    ("theme_editor.group_window", ("titlebar", "titlebar_text", "sidebar", "tooltip")),
    ("theme_editor.group_state", ("selection", "disabled", "scrollbar")),
    ("theme_editor.group_reader", ("reader",)),
)

#: 可选的排版字段
TYPO_FIELDS = ("font_family", "font_size", "line_spacing", "paragraph_spacing")

#: 主题数据里除颜色 / 排版外的字段
NAME_FIELD = "name"

#: 取不到主题时的兜底主题
DEFAULT_THEME = "light"

#: 只认 ``#RGB`` / ``#RRGGBB``：颜色值一律走十六进制，不接受颜色名（严格校验）
_COLOR_RE = re.compile(r"\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")

#: 文件名（Windows）里不能出现的字符
_INVALID_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: 文件名（Windows）里不能独立使用的保留名
_RESERVED_FILENAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

_MAX_NAME_LENGTH = 60
_MAX_FONT_FAMILY_LENGTH = 100

#: 阅读区字号范围（与 main_window 的 FONT_SIZE_MIN / FONT_SIZE_MAX 一致）
FONT_SIZE_RANGE = (8, 48)

#: 行距范围
LINE_SPACING_RANGE = (1.0, 3.0)

#: 段间距范围（像素）。Qt 给 ``<p>`` 的默认上下边距各 12px，
#: 也就是相邻两段之间默认就是 24px，所以默认值取 24 = 不改动外观
PARAGRAPH_SPACING_RANGE = (0, 80)

#: 段间距默认值（与 :data:`enm.managers.config.default_config` 一致）
DEFAULT_PARAGRAPH_SPACING = 24

#: 行距默认值（与 :data:`enm.managers.config.default_config` 一致）
DEFAULT_LINE_SPACING = 1.8

#: 黑白文字的分界点：在这个相对亮度上黑字与白字的对比度相等
#: （(L+0.05)/0.05 == 1.05/(L+0.05) ⇒ L ≈ 0.179）
_CONTRAST_PIVOT = 0.179

#: 内置主题；显示名走 ``BUILTIN_NAME_KEYS`` 里的语言键
BUILTIN_THEMES = {
    "light": {
        "name": "浅色主题",
        "background": "#FFFFFF",
        "foreground": "#000000",
        "accent": "#007ACC",
        "highlight": "#E3F2FD",
        "border": "#CCCCCC",
        "titlebar": "#F3F3F3",
        "titlebar_text": "#000000",
        "selection": "#007ACC",
        "disabled": "#9A9A9A",
        "scrollbar": "#C4C4C4",
        "tooltip": "#F7F7F7",
        "sidebar": "#F7F7F7",
        "reader": "#FFFFFF",
    },
    "dark": {
        "name": "深色主题",
        "background": "#2B2B2B",
        "foreground": "#FFFFFF",
        "accent": "#569CD6",
        "highlight": "#3C3C3C",
        "border": "#555555",
        "titlebar": "#202020",
        "titlebar_text": "#FFFFFF",
        "selection": "#569CD6",
        "disabled": "#7A7A7A",
        "scrollbar": "#4E4E4E",
        "tooltip": "#3A3A3A",
        "sidebar": "#262626",
        "reader": "#2B2B2B",
    },
}

#: 内置主题键 → 语言键（界面上的显示名）
BUILTIN_NAME_KEYS = {
    "light": "menu.theme_light",
    "dark": "menu.theme_dark",
}

#: 配色预设：只写 5 个必需色，其余 8 个由 :func:`preset_colors` 推导
THEME_PRESETS = (
    ("Visual Studio Dark", {
        "background": "#1E1E1E", "foreground": "#D4D4D4", "accent": "#0E639C",
        "highlight": "#3A3D41", "border": "#3F3F46",
    }),
    ("Solarized Light", {
        "background": "#FDF6E3", "foreground": "#657B83", "accent": "#268BD2",
        "highlight": "#EEE8D5", "border": "#93A1A1",
    }),
    ("Solarized Dark", {
        "background": "#002B36", "foreground": "#93A1A1", "accent": "#268BD2",
        "highlight": "#073642", "border": "#586E75",
    }),
    ("GitHub Light", {
        "background": "#FFFFFF", "foreground": "#24292F", "accent": "#0969DA",
        "highlight": "#DDF4FF", "border": "#D0D7DE",
    }),
    ("Nord", {
        "background": "#2E3440", "foreground": "#D8DEE9", "accent": "#5E81AC",
        "highlight": "#434C5E", "border": "#4C566A",
    }),
    ("Gruvbox Dark", {
        "background": "#282828", "foreground": "#EBDBB2", "accent": "#D79921",
        "highlight": "#504945", "border": "#665C54",
    }),
    ("Sepia", {
        "background": "#F5ECD9", "foreground": "#4B3B2A", "accent": "#A67C52",
        "highlight": "#E8DCC2", "border": "#D6C4A8",
    }),
    ("High Contrast", {
        "background": "#000000", "foreground": "#FFFFFF", "accent": "#FFFF00",
        "highlight": "#333333", "border": "#808080",
    }),
    ("One Dark", {
        "background": "#282C34", "foreground": "#ABB2BF", "accent": "#61AFEF",
        "highlight": "#3E4451", "border": "#3E4451",
    }),
    ("Dracula", {
        "background": "#282A36", "foreground": "#F8F8F2", "accent": "#BD93F9",
        "highlight": "#44475A", "border": "#44475A",
    }),
    ("Tokyo Night", {
        "background": "#1A1B26", "foreground": "#C0CAF5", "accent": "#7AA2F7",
        "highlight": "#292E42", "border": "#2F334D",
    }),
    ("Rose Pine", {
        "background": "#191724", "foreground": "#E0DEF4", "accent": "#C4A7E7",
        "highlight": "#26233A", "border": "#403D52",
    }),
    ("Everforest Dark", {
        "background": "#2D353B", "foreground": "#D3C6AA", "accent": "#A7C080",
        "highlight": "#3D484D", "border": "#475258",
    }),
    ("Midnight Blue", {
        "background": "#0F172A", "foreground": "#E2E8F0", "accent": "#38BDF8",
        "highlight": "#1E293B", "border": "#334155",
    }),
    ("Catppuccin Latte", {
        "background": "#EFF1F5", "foreground": "#4C4F69", "accent": "#1E66F5",
        "highlight": "#DCE0E8", "border": "#BCC0CC",
    }),
    ("Ayu Light", {
        "background": "#FAFAFA", "foreground": "#5C6166", "accent": "#FF8F40",
        "highlight": "#F0F0F0", "border": "#D0D0D0",
    }),
)


def normalise_color(value):
    """把颜色值规范化成 ``#rrggbb``；不合法返回 ``None``"""
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not _COLOR_RE.match(text):
        return None

    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return "#" + digits.lower()


# ---------------------------------------------------------------- 颜色基础运算
# 这些函数刻意不依赖 Qt：theme.py 属于数据层，界面层才需要 QColor。
# 数值语义与 QColor 对齐（例如 lightness() 取 HSL 明度并缩放到 0~255），
# 这样 theme_qss.color_on_accent() 与这里的 contrast_text() 不会打架。


def hex_to_rgb(color):
    """``#rrggbb`` → ``(r, g, b)``；不合法返回 ``None``"""
    text = normalise_color(color)
    if text is None:
        return None
    return tuple(int(text[index:index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(rgb):
    """``(r, g, b)`` → ``#rrggbb``（自动夹到 0~255）"""
    return "#" + "".join(
        f"{max(0, min(255, int(round(channel)))):02x}" for channel in rgb)


def _linear(channel):
    """sRGB 分量 → 线性光强度（WCAG 对比度公式用）"""
    value = channel / 255.0
    if value <= 0.03928:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color):
    """WCAG 相对亮度，取值 0~1；颜色非法时按全黑算"""
    rgb = hex_to_rgb(color)
    if rgb is None:
        return 0.0
    red, green, blue = (_linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(color_a, color_b):
    """两个颜色的 WCAG 对比度，取值 1~21"""
    first = relative_luminance(color_a)
    second = relative_luminance(color_b)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def contrast_text(background, dark="#000000", light="#ffffff"):
    """在 ``background`` 上该用黑字还是白字（取对比度更高的那个）"""
    if relative_luminance(background) > _CONTRAST_PIVOT:
        return normalise_color(dark) or "#000000"
    return normalise_color(light) or "#ffffff"


def rgb_to_hsl(rgb):
    """``(r, g, b)`` → ``(h, s, l)``，三个分量都归一化到 0~1"""
    red, green, blue = (channel / 255.0 for channel in rgb)
    high, low = max(red, green, blue), min(red, green, blue)
    lightness_value = (high + low) / 2.0
    if high == low:
        return 0.0, 0.0, lightness_value

    span = high - low
    saturation = (span / (2.0 - high - low) if lightness_value > 0.5
                  else span / (high + low))
    if high == red:
        hue = ((green - blue) / span) % 6.0
    elif high == green:
        hue = (blue - red) / span + 2.0
    else:
        hue = (red - green) / span + 4.0
    return hue / 6.0, saturation, lightness_value


def hsl_to_rgb(hue, saturation, lightness_value):
    """``(h, s, l)``（0~1）→ ``(r, g, b)``（0~255）"""
    hue = hue % 1.0
    saturation = max(0.0, min(1.0, saturation))
    lightness_value = max(0.0, min(1.0, lightness_value))

    if saturation == 0.0:
        channel = int(round(lightness_value * 255))
        return channel, channel, channel

    second = (lightness_value * (1.0 + saturation)
              if lightness_value < 0.5
              else lightness_value + saturation - lightness_value * saturation)
    first = 2.0 * lightness_value - second

    def _channel(offset):
        position = (hue + offset) % 1.0
        if position < 1 / 6:
            return first + (second - first) * 6.0 * position
        if position < 1 / 2:
            return second
        if position < 2 / 3:
            return first + (second - first) * (2 / 3 - position) * 6.0
        return first

    return tuple(int(round(_channel(offset) * 255))
                 for offset in (1 / 3, 0.0, -1 / 3))


def hsl_hex(hue, saturation, lightness_value):
    """``(h, s, l)``（0~1）→ ``#rrggbb``"""
    return rgb_to_hex(hsl_to_rgb(hue, saturation, lightness_value))


def lightness(color):
    """HSL 明度，取值 0~255（与 Qt 的 ``QColor.lightness()`` 一致）"""
    rgb = hex_to_rgb(color)
    if rgb is None:
        return 0
    return int(round(rgb_to_hsl(rgb)[2] * 255))


def is_dark(color):
    """颜色是否偏暗（按 HSL 明度，分界与 ``QColor`` 的 128 一致）"""
    return lightness(color) < 128


def shift_lightness(color, delta):
    """整体提亮 / 压暗 ``delta``（0~1 的 HSL 明度增量），色相与饱和度保持"""
    rgb = hex_to_rgb(color)
    if rgb is None:
        return normalise_color(color) or "#000000"
    hue, saturation, value = rgb_to_hsl(rgb)
    return hsl_hex(hue, saturation, value + delta)


def mix(color_a, color_b, ratio):
    """按 ``ratio`` 把 ``color_a`` 混向 ``color_b``（0 = 全 a，1 = 全 b）"""
    first = hex_to_rgb(color_a)
    second = hex_to_rgb(color_b)
    if first is None:
        return normalise_color(color_b) or "#000000"
    if second is None:
        return normalise_color(color_a) or "#000000"
    ratio = max(0.0, min(1.0, ratio))
    return rgb_to_hex(tuple(a + (b - a) * ratio for a, b in zip(first, second)))


# ---------------------------------------------------------------- 排版字段校验


def normalise_font_size(value):
    """字号 → 整数（8~48）；不合法返回 ``None``，需要区分「非法」与「没填」

    注意这是「校验」而不是「带兜底的读取」：``None`` 一律表示值不合法，
    调用方想给默认值自己用 ``or`` 接。段间距同理（见下）。
    """
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip()) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None
    low, high = FONT_SIZE_RANGE
    return number if low <= number <= high else None


def normalise_line_spacing(value):
    """行距 → 两位小数（1.0~3.0）；不合法返回 ``None``"""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    low, high = LINE_SPACING_RANGE
    if not low <= number <= high:
        return None
    return round(number, 2)


def normalise_paragraph_spacing(value):
    """段间距 → 整数像素（0~80）；不合法返回 ``None``

    ``0`` 是合法值（段落紧贴），所以调用方**不能**用 ``or`` 接默认值，
    必须显式判断 ``is None``。
    """
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip()) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None
    low, high = PARAGRAPH_SPACING_RANGE
    return number if low <= number <= high else None


def normalise_font_family(value):
    """字体名 → 去空白的字符串；空、超长或含控制字符返回 ``None``"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_FONT_FAMILY_LENGTH:
        return None
    if any(ord(char) < 32 for char in text):
        return None
    return text


# ---------------------------------------------------------------- 配色推导


def derive_missing(theme):
    """补齐缺失的扩展色，返回**新**字典（不修改入参）。

    推导规则（``dark`` 由底色明度决定，所以深浅主题都成立）：

    * ``titlebar``      底色微微提亮（深色主题）/ 压暗（浅色主题），像一条独立色带
    * ``titlebar_text`` 标题栏底色上的高对比文字色
    * ``selection``     直接跟随强调色（选中项最显眼）
    * ``disabled``      文字色向底色淡出 58%，能看出「不可用」又不至于看不见
    * ``scrollbar``     文字色向底色淡出 70%，比禁用态更轻
    * ``tooltip``       底色再提亮 / 压暗一档，和主窗口拉开层次
    * ``sidebar``       底色微调一档，和阅读区区分开
    * ``reader``        跟随底色（想要米黄 / 护眼绿时在主题里显式给值）
    """
    result = dict(theme)
    background = normalise_color(result.get("background")) or "#FFFFFF"
    foreground = normalise_color(result.get("foreground")) or "#000000"
    accent = normalise_color(result.get("accent")) or "#007ACC"
    dark = is_dark(background)

    derived = {
        "titlebar": shift_lightness(background, 0.05 if dark else -0.06),
        "selection": accent,
        "disabled": mix(foreground, background, 0.58),
        "scrollbar": mix(foreground, background, 0.70),
        "tooltip": shift_lightness(background, 0.08 if dark else -0.05),
        "sidebar": shift_lightness(background, 0.035 if dark else -0.03),
        "reader": background,
    }
    for field, value in derived.items():
        if not normalise_color(result.get(field)):
            result[field] = value

    # 标题栏文字色要等标题栏底色定下来才算得准
    if not normalise_color(result.get("titlebar_text")):
        result["titlebar_text"] = contrast_text(result["titlebar"])
    return result


def derive_palette(seed):
    """从一个**主色**派生一整套配色（自动决定走深色向还是浅色向）。

    深浅判断用的是主色自己的明度：亮主色配浅底，暗主色配深底。底色带着主色
    的色相（饱和度压到很低，避免刺眼），文字色取高对比，强调色在底色上对比度
    不足时自动拉开明度——保证派生出来的主题**一定是能看的**，而不是一堆随机色。
    """
    accent = normalise_color(seed) or "#007acc"
    hue, saturation, _value = rgb_to_hsl(hex_to_rgb(accent))
    dark = is_dark(accent)

    if dark:
        background = hsl_hex(hue, min(saturation * 0.32, 0.22), 0.13)
        foreground = hsl_hex(hue, min(saturation * 0.18, 0.14), 0.92)
        highlight = hsl_hex(hue, min(saturation * 0.30, 0.20), 0.20)
        border = hsl_hex(hue, min(saturation * 0.22, 0.16), 0.30)
    else:
        background = hsl_hex(hue, min(saturation * 0.35, 0.24), 0.972)
        foreground = hsl_hex(hue, min(saturation * 0.30, 0.22), 0.12)
        highlight = hsl_hex(hue, min(saturation * 0.45, 0.30), 0.92)
        border = hsl_hex(hue, min(saturation * 0.28, 0.20), 0.78)

    # 强调色跳不出底色就拉开明度，否则按钮和选中项会糊在背景里
    if contrast_ratio(accent, background) < 2.0:
        accent = shift_lightness(accent, 0.22 if dark else -0.22)

    return derive_missing({
        "background": background,
        "foreground": foreground,
        "accent": accent,
        "highlight": highlight,
        "border": border,
    })


def preset_colors(preset):
    """预设的 5 个基础色 + 推导出的其余 8 个字段（返回完整配色）"""
    base = {}
    for field in REQUIRED_COLOR_FIELDS:
        color = normalise_color(preset.get(field))
        if color:
            base[field] = color
    return derive_missing(base)


def theme_to_json(theme):
    """把主题字典整理成写盘用的结构（13 色齐全；排版字段没有就省略）。

    导出的文件是**自包含**的：扩展色即使原来没写，也会按必需色推导出来一起
    写进去。这样换台机器导入时看到的配色和导出时完全一致，不受导入方版本、
    推导算法的影响。
    """
    filled = derive_missing(theme)
    data = {NAME_FIELD: theme.get(NAME_FIELD, "")}
    for field in COLOR_FIELDS:
        data[field] = filled.get(field)
    for field in TYPO_FIELDS:
        # 段间距 0 也是有效值，不能靠真假判断决定写不写
        if theme.get(field) is not None:
            data[field] = theme[field]
    return data


def sanitize_theme_name(name):
    """把用户输入收拾成能当文件名用的主题键（非法字符直接去掉）"""
    text = _INVALID_NAME_RE.sub("", str(name or "")).strip()
    text = text.strip(".").strip()
    text = text[:_MAX_NAME_LENGTH].strip()
    if text.upper() in _RESERVED_FILENAMES:
        text += "_"
    return text


def validate_theme(data):
    """严格校验主题数据。

    返回 ``(theme, errors, warnings)``：

    * ``theme``：规范化后的**完整**主题字典（13 个颜色字段齐全 + 可选的排版），
      失败为 ``None``
    * ``errors`` / ``warnings``：``(语言键, 参数)`` 列表，由界面层翻译

    必需色缺失或颜色非法一律算错误：宁可拒绝导入，也不要写进一份会让程序
    起不来的配置。扩展色与排版字段是**可选**的——没给就按必需色推导，给了
    就必须合法（写错了不如不写）。多出来的字段不算错误，只在 ``warnings``
    里提示一句。
    """
    if not isinstance(data, dict):
        return None, [("theme_error.not_object", {})], []

    errors = []
    warnings = []
    theme = {}

    for field in REQUIRED_COLOR_FIELDS:
        raw = data.get(field)
        if raw is None:
            errors.append(("theme_error.missing_field", {"field": field}))
            continue
        color = normalise_color(raw)
        if color is None:
            errors.append(("theme_error.invalid_color",
                           {"field": field, "value": str(raw)}))
            continue
        theme[field] = color

    for field in OPTIONAL_COLOR_FIELDS:
        raw = data.get(field)
        if raw is None:
            continue
        color = normalise_color(raw)
        if color is None:
            errors.append(("theme_error.invalid_color",
                           {"field": field, "value": str(raw)}))
            continue
        theme[field] = color

    if data.get("font_family") is not None:
        family = normalise_font_family(data.get("font_family"))
        if family is None:
            errors.append(("theme_error.invalid_font_family",
                           {"value": str(data.get("font_family"))}))
        else:
            theme["font_family"] = family

    if data.get("font_size") is not None:
        size = normalise_font_size(data.get("font_size"))
        if size is None:
            errors.append(("theme_error.invalid_font_size",
                           {"value": str(data.get("font_size")),
                            "min": FONT_SIZE_RANGE[0],
                            "max": FONT_SIZE_RANGE[1]}))
        else:
            theme["font_size"] = size

    if data.get("line_spacing") is not None:
        spacing = normalise_line_spacing(data.get("line_spacing"))
        if spacing is None:
            errors.append(("theme_error.invalid_line_spacing",
                           {"value": str(data.get("line_spacing")),
                            "min": LINE_SPACING_RANGE[0],
                            "max": LINE_SPACING_RANGE[1]}))
        else:
            theme["line_spacing"] = spacing

    if data.get("paragraph_spacing") is not None:
        paragraph = normalise_paragraph_spacing(data.get("paragraph_spacing"))
        if paragraph is None:
            errors.append(("theme_error.invalid_paragraph_spacing",
                           {"value": str(data.get("paragraph_spacing")),
                            "min": PARAGRAPH_SPACING_RANGE[0],
                            "max": PARAGRAPH_SPACING_RANGE[1]}))
        else:
            theme["paragraph_spacing"] = paragraph

    known = set(COLOR_FIELDS) | set(TYPO_FIELDS) | {NAME_FIELD}
    unknown = sorted(key for key in data if key not in known)
    if unknown:
        warnings.append(("theme_error.unknown_fields",
                         {"fields": ", ".join(unknown)}))

    if errors:
        return None, errors, warnings

    name = str(data.get(NAME_FIELD) or "").strip()
    theme = derive_missing(theme)
    if name:
        theme[NAME_FIELD] = name
    return theme, [], warnings


def describe_errors(errors):
    """把校验错误拼成一句日志（日志固定中文，不进语言文件）"""
    parts = []
    for code, params in errors:
        if code.endswith("not_object"):
            parts.append("内容不是主题对象")
        elif code.endswith("missing_field"):
            parts.append(f"缺少字段 {params.get('field')}")
        elif code.endswith("invalid_color"):
            parts.append(f"颜色非法 {params.get('field')}={params.get('value')}")
        elif code.endswith("invalid_font_family"):
            parts.append(f"字体名非法 {params.get('value')}")
        elif code.endswith("invalid_font_size"):
            parts.append(f"字号非法 {params.get('value')}")
        elif code.endswith("invalid_line_spacing"):
            parts.append(f"行距非法 {params.get('value')}")
        elif code.endswith("invalid_paragraph_spacing"):
            parts.append(f"段间距非法 {params.get('value')}")
        else:
            parts.append(code)
    return "；".join(parts) or "未知错误"


class ThemeManager:
    """内置主题 + 自定义主题的读写与增删改查"""

    color_fields = COLOR_FIELDS
    required_color_fields = REQUIRED_COLOR_FIELDS
    optional_color_fields = OPTIONAL_COLOR_FIELDS
    typo_fields = TYPO_FIELDS
    field_groups = FIELD_GROUPS
    presets = THEME_PRESETS
    name_keys = BUILTIN_NAME_KEYS

    def __init__(self, themes_path=None):
        self.themes_path = Path(themes_path) if themes_path else THEMES_PATH
        self.builtin_themes = BUILTIN_THEMES
        self.custom_themes = {}
        self.load_custom_themes()

    # ------------------------------------------------------------------ 读取

    def load_custom_themes(self):
        """加载自定义主题，返回成功加载的数量。

        逐个文件容错：某个 JSON 坏了只跳过它自己，不会连带后面的主题一起丢掉。
        """
        self.custom_themes = {}
        try:
            theme_files = sorted(self.themes_path.glob("*.json"))
        except OSError as error:
            logger.log(f"读取主题目录失败: {error}", "ERROR")
            return 0

        for theme_file in theme_files:
            theme = self._read_theme_file(theme_file)
            if theme is not None:
                self.custom_themes[theme_file.stem] = theme
        return len(self.custom_themes)

    def reload(self):
        """重新扫描主题目录"""
        return self.load_custom_themes()

    def _read_theme_file(self, path):
        """读取并校验一个主题文件；坏文件记日志后返回 ``None``"""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            logger.log(f"跳过损坏的主题文件 {path.name}: {error}", "WARN")
            return None

        theme, errors, _ = validate_theme(data)
        if theme is None:
            logger.log(f"跳过无效的主题文件 {path.name}: {describe_errors(errors)}",
                       "WARN")
            return None

        theme.setdefault(NAME_FIELD, path.stem)
        return theme

    # ------------------------------------------------------------------ 查询

    def is_builtin(self, theme_name):
        """是否是内置主题"""
        return theme_name in self.builtin_themes

    def is_custom(self, theme_name):
        """是否是自定义主题"""
        return theme_name in self.custom_themes

    def exists(self, theme_name):
        """主题是否存在"""
        return self.is_builtin(theme_name) or self.is_custom(theme_name)

    def custom_theme_names(self):
        """自定义主题键，按名称排序"""
        return sorted(self.custom_themes)

    def theme_names(self):
        """全部主题键，内置在前"""
        return list(self.builtin_themes) + self.custom_theme_names()

    def entries(self):
        """按显示顺序返回 ``[(主题键, 是否内置, 主题字典), ...]``"""
        result = [(name, True, dict(theme))
                  for name, theme in self.builtin_themes.items()]
        for name in self.custom_theme_names():
            result.append((name, False, dict(self.custom_themes[name])))
        return result

    def complete(self, theme):
        """补齐主题里缺失的颜色字段（必需色按浅色主题兜底），返回新字典"""
        fallback = self.builtin_themes.get(
            DEFAULT_THEME, next(iter(self.builtin_themes.values())))
        result = {}
        for field in REQUIRED_COLOR_FIELDS:
            result[field] = normalise_color(theme.get(field)) or fallback[field]
        for field in OPTIONAL_COLOR_FIELDS:
            color = normalise_color(theme.get(field))
            if color:
                result[field] = color

        # 必需色齐全了才能推导，扩展色只补缺
        result = derive_missing(result)

        for field in TYPO_FIELDS:
            raw = theme.get(field)
            # 用 ``is None`` 而不是真假判断：段间距 0 是合法值
            if raw is None:
                continue
            if field == "font_family":
                value = normalise_font_family(raw)
            elif field == "font_size":
                value = normalise_font_size(raw)
            elif field == "paragraph_spacing":
                value = normalise_paragraph_spacing(raw)
            else:
                value = normalise_line_spacing(raw)
            if value is not None:
                result[field] = value

        name = str(theme.get(NAME_FIELD) or "").strip()
        result[NAME_FIELD] = name or DEFAULT_THEME
        return result

    def get_theme(self, theme_name, fallback=DEFAULT_THEME):
        """取主题配置，返回的字典保证 13 个颜色字段齐全。

        ``fallback=None`` 表示「找不到就返回 ``None``」，给「这主题还在吗」用。
        """
        theme = self.builtin_themes.get(theme_name)
        if theme is None:
            theme = self.custom_themes.get(theme_name)
        if theme is not None:
            return self.complete(theme)

        if fallback is None:
            return None
        logger.log(f"主题 {theme_name!r} 不存在，改用 {fallback} 主题", "WARN")
        return self.complete(self.builtin_themes.get(fallback) or {})

    def display_name(self, theme_name):
        """主题自己声明的显示名，没有就用主题键"""
        theme = self.get_theme(theme_name, fallback=None)
        if theme and theme.get(NAME_FIELD):
            return theme[NAME_FIELD]
        return theme_name

    def has_typography(self, theme_name):
        """这套主题是否自带排版信息"""
        theme = self.get_theme(theme_name, fallback=None)
        if not theme:
            return False
        return any(theme.get(field) is not None for field in TYPO_FIELDS)

    def next_available_name(self, base):
        """找一个没被占用的主题键：``base``、``base-2``、``base-3``……"""
        key = sanitize_theme_name(base) or "theme"
        if not self.exists(key):
            return key
        index = 2
        while self.exists(f"{key}-{index}"):
            index += 1
        return f"{key}-{index}"

    # ------------------------------------------------------------------ 写入

    def save_theme(self, theme_name, theme_data, overwrite=True):
        """保存自定义主题，返回 ``(是否成功, 错误列表, 警告列表)``"""
        key = sanitize_theme_name(theme_name)
        if not key:
            return False, [("theme_error.empty_name", {})], []
        if self.is_builtin(key):
            return False, [("theme_error.reserved_name", {"name": key})], []
        if key in self.custom_themes and not overwrite:
            return False, [("theme_error.name_exists", {"name": key})], []

        theme, errors, warnings = validate_theme(theme_data)
        if theme is None:
            return False, errors, warnings

        theme[NAME_FIELD] = (str(theme_data.get(NAME_FIELD) or "").strip()
                             or theme.get(NAME_FIELD) or key)
        try:
            self.themes_path.mkdir(parents=True, exist_ok=True)
            with open(self.themes_path / f"{key}.json", "w",
                      encoding="utf-8") as handle:
                json.dump(theme_to_json(theme), handle,
                          ensure_ascii=False, indent=2)
        except OSError as error:
            logger.log(f"保存主题失败: {error}", "ERROR")
            return False, [("theme_error.save_failed", {"error": str(error)})], warnings

        self.custom_themes[key] = theme
        logger.log(f"主题已保存: {key}")
        return True, [], warnings

    def delete_theme(self, theme_name):
        """删除自定义主题（内置主题不理会），返回是否成功"""
        if not self.is_custom(theme_name):
            return False
        try:
            theme_file = self.themes_path / f"{theme_name}.json"
            if theme_file.exists():
                theme_file.unlink()
        except OSError as error:
            logger.log(f"删除主题失败: {error}", "ERROR")
            return False

        self.custom_themes.pop(theme_name, None)
        logger.log(f"主题已删除: {theme_name}")
        return True

    def rename_theme(self, old_name, new_name):
        """重命名自定义主题，返回 ``(是否成功, 新的主题键, 错误列表)``"""
        if not self.is_custom(old_name):
            return False, old_name, [("theme_error.not_custom", {"name": old_name})]

        key = sanitize_theme_name(new_name)
        if not key:
            return False, old_name, [("theme_error.empty_name", {})]
        if self.is_builtin(key) or (key != old_name and self.is_custom(key)):
            return False, old_name, [("theme_error.name_exists", {"name": key})]
        if key == old_name:
            return True, old_name, []

        theme = dict(self.custom_themes[old_name])
        theme[NAME_FIELD] = str(new_name).strip() or key
        ok, errors, _ = self.save_theme(key, theme)
        if not ok:
            return False, old_name, errors

        self.delete_theme(old_name)
        logger.log(f"主题已重命名: {old_name} -> {key}")
        return True, key, []

    def duplicate_theme(self, source_name, new_name=None):
        """复制主题（内置主题也能复制成自定义主题）。

        返回 ``(是否成功, 新的主题键, 错误列表)``。
        """
        theme = self.get_theme(source_name, fallback=None)
        if theme is None:
            return False, None, [("theme_error.not_found", {"name": source_name})]

        key = sanitize_theme_name(new_name) if new_name else ""
        if not key:
            return False, None, [("theme_error.empty_name", {})]
        if self.exists(key):
            return False, key, [("theme_error.name_exists", {"name": key})]

        ok, errors, _ = self.save_theme(key, theme)
        if not ok:
            return False, key, errors
        return True, key, []

    # ------------------------------------------------------------- 导入 / 导出

    def import_theme_file(self, path, name=None, overwrite=False):
        """从文件导入主题，返回 ``(是否成功, 主题键, 错误列表, 警告列表)``。

        主题键优先取调用方给的名字，其次取 JSON 里的 ``name``，最后才用文件名：
        按文件名命名会把用户在 JSON 里写好的名字丢掉。
        """
        source = Path(path)
        try:
            with open(source, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            return False, None, [("theme_error.read_failed",
                                  {"error": str(error)})], []

        theme, errors, warnings = validate_theme(data)
        if theme is None:
            return False, None, errors, warnings

        name_hint = str(name or "").strip()
        key = sanitize_theme_name(name_hint or data.get(NAME_FIELD) or source.stem)
        if not key:
            return False, None, [("theme_error.invalid_name", {})], warnings
        if self.is_builtin(key):
            return False, key, [("theme_error.reserved_name", {"name": key})], warnings
        if self.is_custom(key) and not overwrite:
            return False, key, [("theme_error.name_exists", {"name": key})], warnings

        theme[NAME_FIELD] = (name_hint
                             or str(data.get(NAME_FIELD) or "").strip()
                             or key)
        ok, save_errors, save_warnings = self.save_theme(key, theme)
        if not ok:
            return False, key, save_errors, warnings + save_warnings

        logger.log(f"主题已导入: {key}（来自 {source.name}）")
        return True, key, [], warnings + save_warnings

    def export_theme_file(self, theme_name, path, display_name=None):
        """把主题写到指定文件，返回 ``(是否成功, 错误列表)``"""
        theme = self.get_theme(theme_name, fallback=None)
        if theme is None:
            return False, [("theme_error.not_found", {"name": theme_name})]

        data = theme_to_json(dict(theme, **{
            NAME_FIELD: display_name or theme[NAME_FIELD]}))
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except OSError as error:
            logger.log(f"导出主题失败: {error}", "ERROR")
            return False, [("theme_error.write_failed", {"error": str(error)})]

        logger.log(f"主题已导出: {theme_name} -> {Path(path).name}")
        return True, []
