"""配置、阅读进度、主题与语言管理。"""

from .config import ConfigManager
from .language import LanguageManager
from .progress import (ReadingProgressManager, format_timestamp,
                       split_file_key)
from .theme import (BUILTIN_NAME_KEYS, BUILTIN_THEMES, COLOR_FIELDS,
                    DEFAULT_THEME, FIELD_GROUPS, FONT_SIZE_RANGE,
                    LINE_SPACING_RANGE, OPTIONAL_COLOR_FIELDS,
                    REQUIRED_COLOR_FIELDS, THEME_PRESETS, TYPO_FIELDS,
                    ThemeManager, contrast_ratio, contrast_text,
                    derive_missing, derive_palette, is_dark, lightness, mix,
                    normalise_color, normalise_font_family,
                    normalise_font_size, normalise_line_spacing, preset_colors,
                    sanitize_theme_name, shift_lightness, theme_to_json,
                    validate_theme)

__all__ = ["ConfigManager", "LanguageManager", "ReadingProgressManager",
           "ThemeManager", "format_timestamp", "split_file_key",
           "BUILTIN_NAME_KEYS", "BUILTIN_THEMES", "COLOR_FIELDS",
           "DEFAULT_THEME", "FIELD_GROUPS", "FONT_SIZE_RANGE",
           "LINE_SPACING_RANGE", "OPTIONAL_COLOR_FIELDS",
           "REQUIRED_COLOR_FIELDS", "THEME_PRESETS", "TYPO_FIELDS",
           "contrast_ratio", "contrast_text", "derive_missing",
           "derive_palette", "is_dark", "lightness", "mix",
           "normalise_color", "normalise_font_family", "normalise_font_size",
           "normalise_line_spacing", "preset_colors", "sanitize_theme_name",
           "shift_lightness", "theme_to_json", "validate_theme"]
