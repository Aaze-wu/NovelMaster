"""界面层：主窗口与对话框。"""

from .continue_dialog import ContinueReadingDialog
from .main_window import NovelMaster
from .shortcut_dialog import ShortcutSettingsDialog
from .theme_dialog import ThemeGeneratorDialog

__all__ = ["ContinueReadingDialog", "NovelMaster", "ShortcutSettingsDialog",
           "ThemeGeneratorDialog"]
