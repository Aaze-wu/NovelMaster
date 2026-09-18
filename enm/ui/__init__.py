"""界面层：主窗口与对话框。"""

from .continue_dialog import ContinueReadingDialog
from .main_window import NovelMaster
from .shortcut_dialog import ShortcutSettingsDialog
from .theme_dialog import ThemeEditorDialog, ThemePreviewWidget
from .theme_manager_dialog import ThemeManagerDialog
from .theme_qss import build_style_sheet, color_on_accent

__all__ = ["ContinueReadingDialog", "NovelMaster", "ShortcutSettingsDialog",
           "ThemeEditorDialog", "ThemePreviewWidget", "ThemeManagerDialog",
           "build_style_sheet", "color_on_accent"]
