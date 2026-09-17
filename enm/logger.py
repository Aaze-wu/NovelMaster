"""日志工具：同时输出到控制台与文件（统一使用 UTF-8）。"""

import logging
import sys
import time
from pathlib import Path

from .constants import DATA_PATH, DEBUG_MODE, PROJECT_NAME, SAVE_PATH, VERSION

# 重定向输出时，避免个别字符无法编码导致 logging 报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass


class Logger:
    def __init__(self):
        self.logger = logging.getLogger(PROJECT_NAME)
        
        # 设置日志级别
        if DEBUG_MODE:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        
        # 控制台处理器
        ch = logging.StreamHandler()
        if DEBUG_MODE:
            ch.setLevel(logging.DEBUG)
        else:
            ch.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)
        
        # 文件处理器
        if DEBUG_MODE:      # 调试模式下，日志文件保存在当前目录
            log_dir = Path(".") / "logs"
        else:       # 非调试模式下，日志文件保存在DATA_PATH/logs目录
            log_dir = DATA_PATH / "logs"
        
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{PROJECT_NAME}_{time.strftime('%Y%m%d%H')}.log"
        fh = logging.FileHandler(log_file, encoding='utf-8')
        if DEBUG_MODE:
            fh.setLevel(logging.DEBUG)
        else:
            fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        
        # 记录启动信息
        self.logger.info(f"EpubNovelMaster 启动 - 版本: {VERSION}")
        self.logger.info(f"调试模式: {DEBUG_MODE}")
        self.logger.info(f"数据目录: {DATA_PATH}")
        self.logger.info(f"保存目录: {SAVE_PATH}")
    
    def log(self, message, level="INFO"):
        if level == "DEBUG":
            self.logger.debug(message)
        elif level == "INFO":
            self.logger.info(message)
        elif level == "WARNING":
            self.logger.warning(message)
        elif level == "ERROR":
            self.logger.error(message)
        elif level == "CRITICAL":
            self.logger.critical(message)
        else:
            self.logger.info(message)
    
    def debug(self, message):
        """DEBUG级别日志"""
        self.logger.debug(message)

logger = Logger()
