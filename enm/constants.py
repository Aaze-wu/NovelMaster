# -*- coding: utf-8 -*-
"""全局常量与资源路径。

``LANG_PATH`` / ``ICON_PATH`` 指向随程序分发的资源目录，因此这里会先定位
“应用根目录”：

1. 打包后（Nuitka）优先使用可执行文件所在目录；
2. 其次使用启动脚本所在目录；
3. 最后回退到当前工作目录与源码目录。
"""

import os
import shutil
import sys
from pathlib import Path

# 项目配置
PROJECT_NAME = "NovelMaster"
AUTHOR_NAME = "Aaze_wu"
VERSION = "1.3.11"
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
_DATA_ROOT = Path(os.getenv("APPDATA") or Path.home())
DATA_PATH = _DATA_ROOT / PROJECT_NAME

# 项目曾用名：改名后首次启动时把旧数据目录整体搬过来，避免丢配置与阅读记录
LEGACY_PROJECT_NAMES = ("EpubNovelMaster",)
# 本次启动若发生了迁移，这里记录旧目录路径（供日志显示），否则为 None
MIGRATED_DATA_FROM = None


def _merge_missing_tree(source: Path, target: Path) -> bool:
    """把 ``source`` 里 ``target`` 尚不存在的条目搬过去，返回是否搬动过。

    同名文件一律保留 ``target`` 里的那份，绝不覆盖用户在新目录下已经产生的
    数据；搬空后的子目录会被顺手删掉，好让上层把旧目录整个清掉。
    """
    moved = False
    target.mkdir(parents=True, exist_ok=True)

    for item in list(source.iterdir()):
        dest = target / item.name
        if item.is_dir():
            moved |= _merge_missing_tree(item, dest)
            try:
                item.rmdir()          # 只有搬空了才能删掉
            except OSError:
                pass
        elif dest.exists():
            continue
        else:
            try:
                shutil.move(str(item), str(dest))
            except OSError:
                continue
            moved = True

    return moved


def _migrate_legacy_data_dir():
    """把旧项目名的数据目录合并进 :data:`DATA_PATH`。

    在旧目录存在时逐项搬运；新目录里已有同名文件则以新目录为准。任何一步
    失败（跨盘、被占用、权限不足）都只是跳过，程序照常在当前目录下工作。
    """
    global MIGRATED_DATA_FROM

    for legacy_name in LEGACY_PROJECT_NAMES:
        legacy_path = _DATA_ROOT / legacy_name
        if not legacy_path.is_dir():
            continue

        if _merge_missing_tree(legacy_path, DATA_PATH):
            MIGRATED_DATA_FROM = legacy_path

        try:
            legacy_path.rmdir()       # 搬完且没留下东西时把旧目录删掉
        except OSError:
            pass
        return


_migrate_legacy_data_dir()

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
    "LANG_PATH", "ICON_PATH", "LEGACY_PROJECT_NAMES", "MIGRATED_DATA_FROM",
]
