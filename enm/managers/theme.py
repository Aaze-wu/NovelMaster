"""主题管理：内置主题 + ``themes`` 目录下的自定义主题。

一套主题就是 5 个颜色的组合：

``background`` / ``foreground`` / ``accent`` / ``highlight`` / ``border``

本模块只管数据（校验、读写 ``themes/*.json``、增删改查），颜色怎么用由
:mod:`enm.ui.theme_qss` 决定。校验失败时返回的是「语言键 + 参数」，翻译交给
界面层，这样管理器本身不依赖 i18n，也不依赖 Qt。

有两个坑必须在这里兜住：

* :meth:`ThemeManager.get_theme` **永远返回字段齐全的主题**。``apply_theme()``
  是按 ``theme['background']`` 直接取值的，缺字段会直接把主窗口的构造打崩，
  而主题名已经写进 ``config.json``，重启依旧崩——等于程序再也起不来。
* 内置主题名（``light`` / ``dark``）不允许被自定义主题占用。``get_theme()``
  先查内置，同名的自定义主题永远取不到，却又删不掉（列表里看不见），是纯粹的坑。
"""

import json
import re
from pathlib import Path

from ..constants import THEMES_PATH
from ..logger import logger

#: 主题里的颜色字段（顺序即界面里的排列顺序）
COLOR_FIELDS = ("background", "foreground", "accent", "highlight", "border")

#: 主题数据里除颜色外的字段
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

#: 内置主题；显示名走 ``BUILTIN_NAME_KEYS`` 里的语言键
BUILTIN_THEMES = {
    "light": {
        "name": "浅色主题",
        "background": "#FFFFFF",
        "foreground": "#000000",
        "accent": "#007ACC",
        "highlight": "#E3F2FD",
        "border": "#CCCCCC",
    },
    "dark": {
        "name": "深色主题",
        "background": "#2B2B2B",
        "foreground": "#FFFFFF",
        "accent": "#569CD6",
        "highlight": "#3C3C3C",
        "border": "#555555",
    },
}

#: 内置主题键 → 语言键（界面上的显示名）
BUILTIN_NAME_KEYS = {
    "light": "menu.theme_light",
    "dark": "menu.theme_dark",
}

#: 配色预设：一键铺满 5 个颜色，再慢慢微调
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

    * ``theme``：规范化后的主题字典（含 ``name`` 与 5 个颜色字段），失败为 ``None``
    * ``errors`` / ``warnings``：``(语言键, 参数)`` 列表，由界面层翻译

    字段缺失或颜色非法一律算错误：宁可拒绝导入，也不要写进一份会让程序
    起不来的配置。多出来的字段不算错误，只在 ``warnings`` 里提示一句。
    """
    if not isinstance(data, dict):
        return None, [("theme_error.not_object", {})], []

    errors = []
    warnings = []
    theme = {}

    for field in COLOR_FIELDS:
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

    unknown = sorted(key for key in data
                     if key not in COLOR_FIELDS and key != NAME_FIELD)
    if unknown:
        warnings.append(("theme_error.unknown_fields",
                         {"fields": ", ".join(unknown)}))

    if errors:
        return None, errors, warnings

    name = str(data.get(NAME_FIELD) or "").strip()
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
        else:
            parts.append(code)
    return "；".join(parts) or "未知错误"


class ThemeManager:
    """内置主题 + 自定义主题的读写与增删改查"""

    color_fields = COLOR_FIELDS
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
        """补齐主题里缺失的颜色字段（按浅色主题兜底），返回新字典"""
        fallback = self.builtin_themes.get(DEFAULT_THEME,
                                           next(iter(self.builtin_themes.values())))
        result = {}
        for field in COLOR_FIELDS:
            result[field] = normalise_color(theme.get(field)) or fallback[field]
        name = str(theme.get(NAME_FIELD) or "").strip()
        result[NAME_FIELD] = name or DEFAULT_THEME
        return result

    def get_theme(self, theme_name, fallback=DEFAULT_THEME):
        """取主题配置，返回的字典保证 5 个颜色字段齐全。

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
            with open(self.themes_path / f"{key}.json", "w", encoding="utf-8") as handle:
                json.dump({NAME_FIELD: theme[NAME_FIELD],
                           **{field: theme[field] for field in COLOR_FIELDS}},
                          handle, ensure_ascii=False, indent=2)
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

        data = {NAME_FIELD: display_name or theme[NAME_FIELD]}
        data.update({field: theme[field] for field in COLOR_FIELDS})
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except OSError as error:
            logger.log(f"导出主题失败: {error}", "ERROR")
            return False, [("theme_error.write_failed", {"error": str(error)})]

        logger.log(f"主题已导出: {theme_name} -> {Path(path).name}")
        return True, []
