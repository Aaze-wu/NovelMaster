"""应用配置管理（config.json）。"""

import json

from ..constants import CONFIG_PATH
from ..logger import logger


class ConfigManager:
    def __init__(self):
        self.config_file = CONFIG_PATH
        self.default_config = {
            "theme": "light",
            "language": "zh_CN",
            "font_family": "Microsoft YaHei",
            "font_size": 16,
            "line_spacing": 1.8,
            "auto_save": True,
            "auto_save_interval": 30,
            "recent_files": [],
            "window_size": [1200, 800],
            "window_position": [100, 100],
            "sidebar_visible": True
        }
        self.config = self.load_config()
    
    def load_config(self):
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置
                    for key, value in self.default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
        except Exception as e:
            logger.log(f"加载配置失败: {e}", "ERROR")
        
        return self.default_config.copy()
    
    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.log(f"保存配置失败: {e}", "ERROR")
    
    def get(self, key, default=None):
        return self.config.get(key, default)
    
    def set(self, key, value):
        self.config[key] = value
        self.save_config()
