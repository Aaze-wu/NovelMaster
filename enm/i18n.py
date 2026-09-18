"""全局翻译入口（模块级单例）。

界面和阅读器统一通过这里的 :func:`t` 取文案，主窗口启动时用
:func:`set_language` 把 ``config.json`` 里的语言设置应用进来；用户切换语言时
再调一次，之后所有新取到的文案（菜单、按钮、对话框、生成的章节标题）都会
立即变成新语言，不需要重启。

之所以做成模块级单例，是因为阅读器要生成「第 N 章」这类占位文案，它们不应该
知道主窗口的存在；同时语言文件只需要加载一次。

用法::

    from ..i18n import t

    title = t("book.chapter_n", n=3)
"""

from .managers.language import DEFAULT_LANG, LANGUAGES, LanguageManager

# 全局唯一的语言管理器
_manager = LanguageManager()


def manager():
    """返回全局语言管理器"""
    return _manager


def t(key, default=None, **kwargs):
    """按键取当前语言的文案（可带 ``{name}`` 占位符）"""
    return _manager.tr(key, default=default, **kwargs)


def has(key):
    """当前语言（或默认语言）里是否存在该键"""
    return _manager.has(key)


def set_language(lang_code):
    """切换当前语言，返回是否成功"""
    return _manager.set_language(lang_code)


def current_language():
    """当前语言代码，如 ``"zh_CN"``"""
    return _manager.language


def language_name(lang_code):
    """语言代码对应的显示名"""
    return _manager.language_name(lang_code)


def available_languages():
    """``{语言代码: 显示名}``"""
    return _manager.available_languages()


__all__ = ["DEFAULT_LANG", "LANGUAGES", "LanguageManager", "manager", "t", "has",
           "set_language", "current_language", "language_name",
           "available_languages"]
