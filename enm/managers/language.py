"""多语言管理（lang/*.json）。"""

import json

from ..constants import LANG_PATH
from ..logger import logger


class LanguageManager:
    def __init__(self):
        self.lang_path = LANG_PATH
        self.languages = {
            "zh_CN": "简体中文",
            "en_US": "English"
        }
        self.translations = {}
        self.load_translations()
    
    def load_translations(self):
        """加载语言文件"""
        for lang_code in self.languages.keys():
            lang_file = self.lang_path / f"{lang_code}.json"
            if lang_file.exists():
                try:
                    with open(lang_file, 'r', encoding='utf-8') as f:
                        self.translations[lang_code] = json.load(f)
                except Exception as e:
                    logger.log(f"加载语言文件 {lang_code} 失败: {e}", "ERROR")
            else:
                # 创建默认语言文件
                self.create_default_language_file(lang_code)
    
    def create_default_language_file(self, lang_code):
        """创建默认语言文件"""
        default_translations = {
            "zh_CN": {
                "file_menu": "文件",
                "open_file": "打开文件",
                "open_folder": "打开文件夹",
                "recent_files": "最近文件",
                "exit": "退出",
                "view_menu": "视图",
                "theme": "主题",
                "font": "字体",
                "language": "语言",
                "help_menu": "帮助",
                "about": "关于",
                "reading_progress": "阅读进度",
                "chapter_list": "章节列表",
                "search": "搜索",
                "settings": "设置"
            },
            "en_US": {
                "file_menu": "File",
                "open_file": "Open File",
                "open_folder": "Open Folder",
                "recent_files": "Recent Files",
                "exit": "Exit",
                "view_menu": "View",
                "theme": "Theme",
                "font": "Font",
                "language": "Language",
                "help_menu": "Help",
                "about": "About",
                "reading_progress": "Reading Progress",
                "chapter_list": "Chapter List",
                "search": "Search",
                "settings": "Settings"
            }
        }
        
        if lang_code in default_translations:
            lang_file = self.lang_path / f"{lang_code}.json"
            try:
                with open(lang_file, 'w', encoding='utf-8') as f:
                    json.dump(default_translations[lang_code], f, ensure_ascii=False, indent=2)
                self.translations[lang_code] = default_translations[lang_code]
            except Exception as e:
                logger.log(f"创建语言文件 {lang_code} 失败: {e}", "ERROR")
    
    def tr(self, key, lang_code="zh_CN"):
        """翻译文本"""
        if lang_code in self.translations and key in self.translations[lang_code]:
            return self.translations[lang_code][key]
        return key
