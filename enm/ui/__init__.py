"""界面层：主窗口与对话框。"""

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

__all__ = ["ChapterTree", "ContinueReadingDialog", "NovelMaster",
           "ShortcutSettingsDialog", "ThemeEditorDialog", "ThemePreviewWidget",
           "ThemeManagerDialog", "build_style_sheet", "build_palette",
           "color_on_accent", "SPLITTER_HANDLE_WIDTH", "apply_titlebar_theme",
           "apply_dark_mode", "reset_titlebar_theme",
           "supports_caption_color", "hide_border", "available"]
