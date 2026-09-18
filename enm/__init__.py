"""NovelMaster 应用包。

模块划分::

    enm.constants   全局常量与资源路径
    enm.logger      日志
    enm.managers    配置 / 阅读进度 / 主题 / 语言
    enm.readers     各格式阅读器、格式注册表与工厂
    enm.ui          主窗口与对话框
"""

from .constants import AUTHOR_NAME, PROJECT_NAME, VERSION

__all__ = ["AUTHOR_NAME", "PROJECT_NAME", "VERSION"]
__version__ = VERSION
