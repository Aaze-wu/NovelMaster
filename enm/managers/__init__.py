"""配置、阅读进度、主题与语言管理。"""

from .config import ConfigManager
from .language import LanguageManager
from .progress import (ReadingProgressManager, format_timestamp,
                       split_file_key)
from .theme import (BUILTIN_NAME_KEYS, BUILTIN_THEMES, COLOR_FIELDS,
                    DEFAULT_THEME, THEME_PRESETS, ThemeManager,
                    normalise_color, sanitize_theme_name, validate_theme)

__all__ = ["ConfigManager", "LanguageManager", "ReadingProgressManager",
           "ThemeManager", "format_timestamp", "split_file_key",
           "BUILTIN_NAME_KEYS", "BUILTIN_THEMES", "COLOR_FIELDS",
           "DEFAULT_THEME", "THEME_PRESETS", "normalise_color",
           "sanitize_theme_name", "validate_theme"]
