"""配置、阅读进度、主题与语言管理。"""

from .book_identity import (build_identity, chapter_index_in, match_strength,
                            normalise_title, record_identity)
from .config import ConfigManager
from .language import LanguageManager
from .progress import (BOOK_KEY_PREFIX, ReadingProgressManager,
                       format_timestamp, merge_records, record_covers_file,
                       record_file_key, split_file_key)
from .theme import (BUILTIN_NAME_KEYS, BUILTIN_THEMES, COLOR_FIELDS,
                    DEFAULT_LINE_SPACING, DEFAULT_PARAGRAPH_SPACING,
                    DEFAULT_THEME, FIELD_GROUPS,
                    FONT_SIZE_RANGE, LINE_SPACING_RANGE, OPTIONAL_COLOR_FIELDS,
                    PARAGRAPH_SPACING_RANGE, REQUIRED_COLOR_FIELDS,
                    THEME_PRESETS, TYPO_FIELDS, ThemeManager, contrast_ratio,
                    contrast_text, derive_missing, derive_palette, is_dark,
                    lightness, mix, normalise_color, normalise_font_family,
                    normalise_font_size, normalise_line_spacing,
                    normalise_paragraph_spacing, preset_colors,
                    sanitize_theme_name, shift_lightness, theme_to_json,
                    validate_theme)

__all__ = ["ConfigManager", "LanguageManager", "ReadingProgressManager",
           "ThemeManager", "format_timestamp", "split_file_key",
           "record_file_key", "record_covers_file", "BOOK_KEY_PREFIX",
           "build_identity",
           "chapter_index_in", "match_strength", "merge_records",
           "normalise_title", "record_identity",
           "BUILTIN_NAME_KEYS", "BUILTIN_THEMES", "COLOR_FIELDS",
           "DEFAULT_LINE_SPACING", "DEFAULT_PARAGRAPH_SPACING",
           "DEFAULT_THEME", "FIELD_GROUPS",
           "FONT_SIZE_RANGE", "LINE_SPACING_RANGE", "OPTIONAL_COLOR_FIELDS",
           "PARAGRAPH_SPACING_RANGE", "REQUIRED_COLOR_FIELDS",
           "THEME_PRESETS", "TYPO_FIELDS",
           "contrast_ratio", "contrast_text", "derive_missing",
           "derive_palette", "is_dark", "lightness", "mix",
           "normalise_color", "normalise_font_family", "normalise_font_size",
           "normalise_line_spacing", "normalise_paragraph_spacing",
           "preset_colors", "sanitize_theme_name",
           "shift_lightness", "theme_to_json", "validate_theme"]
