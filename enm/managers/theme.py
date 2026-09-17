"""主题管理：内置主题 + themes 目录下的自定义主题。"""

import json

from ..constants import THEMES_PATH
from ..logger import logger


class ThemeManager:
    def __init__(self):
        self.themes_path = THEMES_PATH
        self.builtin_themes = {
            "light": {
                "name": "浅色主题",
                "background": "#FFFFFF",
                "foreground": "#000000",
                "accent": "#007ACC",
                "highlight": "#E3F2FD",
                "border": "#CCCCCC"
            },
            "dark": {
                "name": "深色主题",
                "background": "#2B2B2B",
                "foreground": "#FFFFFF",
                "accent": "#569CD6",
                "highlight": "#3C3C3C",
                "border": "#555555"
            }
        }
        self.custom_themes = {}
        self.load_custom_themes()
    
    def load_custom_themes(self):
        """加载自定义主题"""
        try:
            for theme_file in self.themes_path.glob("*.json"):
                with open(theme_file, 'r', encoding='utf-8') as f:
                    theme_data = json.load(f)
                    theme_name = theme_file.stem
                    self.custom_themes[theme_name] = theme_data
        except Exception as e:
            logger.log(f"加载自定义主题失败: {e}", "ERROR")
    
    def get_theme(self, theme_name):
        """获取主题配置"""
        if theme_name in self.builtin_themes:
            return self.builtin_themes[theme_name]
        elif theme_name in self.custom_themes:
            return self.custom_themes[theme_name]
        else:
            return self.builtin_themes["light"]
    
    def save_theme(self, theme_name, theme_data):
        """保存自定义主题"""
        try:
            theme_file = self.themes_path / f"{theme_name}.json"
            with open(theme_file, 'w', encoding='utf-8') as f:
                json.dump(theme_data, f, ensure_ascii=False, indent=2)
            self.custom_themes[theme_name] = theme_data
            return True
        except Exception as e:
            logger.log(f"保存主题失败: {e}", "ERROR")
            return False
    
    def delete_theme(self, theme_name):
        """删除自定义主题"""
        try:
            if theme_name in self.custom_themes:
                theme_file = self.themes_path / f"{theme_name}.json"
                if theme_file.exists():
                    theme_file.unlink()
                del self.custom_themes[theme_name]
                return True
        except Exception as e:
            logger.log(f"删除主题失败: {e}", "ERROR")
        return False
