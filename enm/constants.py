# -*- coding: utf-8 -*-
"""全局常量与资源路径。

``LANG_PATH`` / ``ICON_PATH`` 指向随程序分发的资源目录，因此这里会先定位
“应用根目录”：

1. 打包后（Nuitka）优先使用可执行文件所在目录；
2. 其次使用启动脚本所在目录；
3. 最后回退到当前工作目录与源码目录。
"""

import os
import sys
from pathlib import Path

# 项目配置
PROJECT_NAME = "EpubNovelMaster"
AUTHOR_NAME = "Aaze_wu"
VERSION = "1.2.0"
DEBUG_MODE = False    # 默认关闭调试模式
# DEBUG_MODE = True   # 开发环境下默认开启调试模式

# 命令行参数处理：包含 --debug 或 -d 时开启调试模式
args = sys.argv[1:]
if "--debug" in args or "-d" in args:
    DEBUG_MODE = True


def _resolve_app_root():
    """定位存放 lang/ 、icon/ 等资源文件的应用根目录。"""
    candidates = []

    # 打包后的可执行文件目录（Nuitka / PyInstaller）
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        candidates.append(Path(sys.executable).resolve().parent)

    # 启动脚本所在目录
    if sys.argv and sys.argv[0] and sys.argv[0] not in ("-c", ""):
        try:
            candidates.append(Path(sys.argv[0]).resolve().parent)
        except OSError:
            pass

    # 当前工作目录与源码目录（开发环境）
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve().parent.parent)

    for candidate in candidates:
        if (candidate / "lang").is_dir() or (candidate / "icon").is_dir():
            return candidate

    return candidates[0] if candidates else Path.cwd()


APP_ROOT = _resolve_app_root()

# 数据路径配置
DATA_PATH = Path(os.getenv("APPDATA") or Path.home()) / PROJECT_NAME
SAVE_PATH = DATA_PATH / "saves"
CONFIG_PATH = DATA_PATH / "config.json"
THEMES_PATH = DATA_PATH / "themes"
LANG_PATH = APP_ROOT / "lang"
ICON_PATH = APP_ROOT / "icon" / "icon.ico"

# 确保目录存在
DATA_PATH.mkdir(parents=True, exist_ok=True)
SAVE_PATH.mkdir(parents=True, exist_ok=True)
THEMES_PATH.mkdir(parents=True, exist_ok=True)
LANG_PATH.mkdir(parents=True, exist_ok=True)

__all__ = [
    "PROJECT_NAME", "AUTHOR_NAME", "VERSION", "DEBUG_MODE", "args",
    "APP_ROOT", "DATA_PATH", "SAVE_PATH", "CONFIG_PATH", "THEMES_PATH",
    "LANG_PATH", "ICON_PATH",
]
