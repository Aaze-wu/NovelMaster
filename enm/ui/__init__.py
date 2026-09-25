"""界面层：主窗口与对话框。"""

from .book_merge_dialog import BookMergeDialog
from .chapter_tree import ChapterTree
from .continue_dialog import ContinueReadingDialog
from .main_window import NovelMaster
from .shortcut_dialog import ShortcutSettingsDialog
from .theme_dialog import ThemeEditorDialog, ThemePreviewWidget
from .theme_manager_dialog import ThemeManagerDialog
from .theme_qss import (SPLITTER_HANDLE_WIDTH, build_palette,
                        build_style_sheet, color_on_accent)
from .titlebar import (apply_dark_mode, apply_titlebar_theme, available,
                       hide_border, reset_titlebar_theme,
                       supports_caption_color)
from .typography_dialog import TypographySettingsDialog

__all__ = ["BookMergeDialog", "ChapterTree", "ContinueReadingDialog",
           "NovelMaster",
           "ShortcutSettingsDialog", "ThemeEditorDialog", "ThemePreviewWidget",
           "ThemeManagerDialog", "TypographySettingsDialog",
           "build_style_sheet", "build_palette", "color_on_accent",
           "SPLITTER_HANDLE_WIDTH", "apply_titlebar_theme",
           "apply_dark_mode", "reset_titlebar_theme",
           "supports_caption_color", "hide_border", "available"]
