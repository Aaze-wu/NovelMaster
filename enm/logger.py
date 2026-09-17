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

_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _drop_handlers(target):
    """移除并关闭 target 上已有的处理器，避免重复输出与文件句柄泄漏。"""
    for handler in list(target.handlers):
        target.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _bind(handler, level, formatter):
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


class Logger:
    """单例日志封装。

    同名 logger 重复构造不会叠加处理器：早期 ``Logger()`` 在多处被实例化，
    每构造一次就在同一个 ``PROJECT_NAME`` logger 上再挂一套控制台 / 文件
    处理器，导致同一条日志被重复打印。现在重复调用只会拿到同一个实例。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._initialised = False
            cls._instance = instance
        return cls._instance

    def __init__(self):
        if self._initialised:
            return
        self._initialised = True

        self.logger = logging.getLogger(PROJECT_NAME)
        level = logging.DEBUG if DEBUG_MODE else logging.INFO
        self.logger.setLevel(level)
        # 已自带控制台与文件处理器，禁止向 root 传播，否则可能被 root 处理器再打一遍
        self.logger.propagate = False
        # 兜底：同名 logger 上已有处理器时先清干净（重复导入本模块等）
        _drop_handlers(self.logger)

        formatter = logging.Formatter(_LOG_FORMAT)

        # 控制台处理器
        ch = _bind(logging.StreamHandler(), level, formatter)
        self.logger.addHandler(ch)

        # 文件处理器
        if DEBUG_MODE:      # 调试模式下，日志文件保存在当前目录
            log_dir = Path(".") / "logs"
        else:       # 非调试模式下，日志文件保存在DATA_PATH/logs目录
            log_dir = DATA_PATH / "logs"

        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{PROJECT_NAME}_{time.strftime('%Y%m%d%H')}.log"
        fh = _bind(logging.FileHandler(log_file, encoding='utf-8'), level, formatter)
        self.logger.addHandler(fh)

        # 记录启动信息（单例，只会写一次）
        self.logger.info(f"EpubNovelMaster 启动 - 版本: {VERSION}")
        self.logger.info(f"调试模式: {DEBUG_MODE}")
        self.logger.info(f"数据目录: {DATA_PATH}")
        self.logger.info(f"保存目录: {SAVE_PATH}")

    def log(self, message, level="INFO"):
        self.logger.log(_LEVELS.get(str(level).upper(), logging.INFO), message)

    def debug(self, message):
        """DEBUG级别日志"""
        self.logger.debug(message)

    def info(self, message):
        """INFO级别日志"""
        self.logger.info(message)

    def warning(self, message):
        """WARNING级别日志"""
        self.logger.warning(message)

    def error(self, message):
        """ERROR级别日志"""
        self.logger.error(message)


logger = Logger()
