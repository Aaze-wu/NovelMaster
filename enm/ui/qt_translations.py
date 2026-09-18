"""让 Qt 自己画的对话框也跟着换语言（并补上系统漏翻的标准按钮）。

``QFontDialog`` 的标题默认是 ``Select Font``、内部标签是 ``Font`` / ``Size``…，
``QColorDialog`` 的「基本颜色」，``QMessageBox`` 的按钮 —— 这些文案**不在**
``lang/*.json`` 里，它们来自 Qt 自带的翻译目录（``qt_zh_CN.qm`` 之类）。
不装的话永远是英文：用户报的「字体选择窗口标题一直是英文」就是这个原因。

四个要点：

* **目录要自己找**。PyQt5 的 wheel 里 ``QLibraryInfo.TranslationsPath`` 有可能
  是空串，真正的文件在 ``PyQt5/Qt5/translations`` 下，两处都探一次。
* **不同语言的目录拆法不一样**。``zh_CN`` 只有一个整体目录 ``qt_zh_CN.qm``，
  ``zh_TW`` 则是 ``qtbase_zh_TW.qm`` 加一个 141 字节的 metacatalog
  ``qt_zh_TW.qm``（metacatalog 自己没内容，要靠 ``qtbase_*``）。所以按
  ``qtbase_<code>`` → ``qt_<code>`` 的顺序挨个试，谁在就用谁。
* **英文不能装**。Qt 的源语言就是英文，但它照样带了一套「英文目录」
  （``qtbase_en.qm``）—— 里面把每条文案都**显式标成空串**，而 Qt 的
  ``translate()`` 只在乎返回值是不是 null：拿到空串就直接当文案用，不再
  回退到原文。装上它反而会把字体对话框标题、标准按钮全变成空白（实测
  ``Select Font`` → ``""``）。所以英文只卸载、不加载，切回英文也必须卸。
* **标准按钮另有一条线**。Windows 平台主题取按钮文案走的是 ``QPlatformTheme``
  上下文，而 ``qt_zh_CN.qm`` 里没有这一节（实测字体对话框的按钮始终是
  ``OK`` / ``Cancel``），所以另用 Python 侧的小翻译器
  :class:`_StandardButtonTranslator` 补上。它认不出的条目一定要返回
  ``None``（null）而不是空串，否则同样会把 Qt 自己的文案清空。
"""

from pathlib import Path

from PyQt5.QtCore import QLibraryInfo, QTranslator

from .. import i18n

#: 已经装上的翻译器（换语言时按这份列表逐个卸下）
_installed = []

#: Qt 的源语言。Qt 自带的英文目录（``qtbase_en.qm``）里每条文案都是显式空串，
#: 装上去会把对话框标题和按钮全变成空白，所以英文只能卸载、不能加载。
_SOURCE_LANGUAGES = ("en",)

#: Qt 的「标准按钮」英文原文（去掉助记符 ``&``、转小写之后）→ 语言键
_STANDARD_BUTTON_KEYS = {
    "ok": "common.ok",
    "cancel": "common.cancel",
    "close": "common.close",
    "yes": "common.yes",
    "no": "common.no",
}


class _StandardButtonTranslator(QTranslator):
    """把 Qt 的「标准按钮」文案换成语言文件里的说法。

    Qt 只在 ``QMessageBox`` / ``QDialogButtonBox`` / ``QFontDialog`` 这些地方
    用 ``QCoreApplication::translate("QPlatformTheme", "OK")`` 取按钮文字，
    而中文目录里恰好没有 ``QPlatformTheme`` 这一节，于是永远显示 ``OK``。

    返回 ``None``（null）表示「我这儿没有」——Qt 会自动继续查下一个翻译器。
    千万不要返回空串：空串在 Qt 眼里是「有翻译，翻译成空」，会把按钮文案
    直接抹成空白。也只认语言文件里确实存在的键，别的留给 Qt 自己处理。
    """

    def translate(self, context, source, disambiguation=None, n=-1):
        if context in ("QPlatformTheme", "QDialogButtonBox"):
            word = str(source).replace("&", "").strip().lower()
            key = _STANDARD_BUTTON_KEYS.get(word)
            if key and i18n.has(key):
                return i18n.t(key)
        return None


def translations_dirs():
    """Qt 翻译目录候选（按优先级），只返回真实存在的目录"""
    candidates = []
    try:
        path = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
    except (RuntimeError, AttributeError):  # pragma: no cover - 老版本 PyQt5
        path = ""
    if path:
        candidates.append(Path(path))
    try:
        import PyQt5
        candidates.append(Path(PyQt5.__file__).parent / "Qt5" / "translations")
    except ImportError:  # pragma: no cover - 正常安装时必有
        pass

    unique = []
    for directory in candidates:
        if directory.is_dir() and directory not in unique:
            unique.append(directory)
    return unique


def candidate_names(lang_code):
    """语言代码 → 可能的目录文件名（不含 ``.qm``），按优先级排列。

    ``zh_CN`` → ``["qtbase_zh_CN", "qt_zh_CN", "qtbase_zh", "qt_zh"]``：
    先试分模块的 ``qtbase_*``，再试整体目录 / metacatalog，最后退到不带地区
    的语言代码。
    """
    if not lang_code:
        return []
    names = ["qtbase_%s" % lang_code, "qt_%s" % lang_code]
    base = lang_code.split("_")[0]
    if base and base != lang_code:
        names += ["qtbase_%s" % base, "qt_%s" % base]
    return names


def is_source_language(lang_code):
    """语言代码是不是 Qt 的源语言（英文，不区分地区）"""
    if not lang_code:
        return True
    return lang_code.split("_")[0].lower() in _SOURCE_LANGUAGES


def install(app, lang_code):
    """按语言代码装卸 Qt 自带翻译，返回真正加载成功的目录文件名列表。

    ``app`` 为 ``None``（还没有 QApplication）时什么都不做。语言是英文时
    只卸载、不加载（Qt 的源语言就是英文，英文目录里全是空串）。
    """
    for translator in _installed:
        try:
            app.removeTranslator(translator)
        except (RuntimeError, AttributeError):  # pragma: no cover - app 已销毁
            pass
    del _installed[:]

    if app is None:
        return []

    # 标准按钮的补丁与语言目录是两回事：目录里没有这一节，得自己接上
    translator = _StandardButtonTranslator()
    app.installTranslator(translator)
    _installed.append(translator)

    if is_source_language(lang_code):
        # 英文目录里的条目是显式空串，装了反而清空文案，跳过
        return []

    loaded = []
    for directory in translations_dirs():
        for name in candidate_names(lang_code):
            if not (directory / ("%s.qm" % name)).is_file():
                continue
            candidate = QTranslator()
            if candidate.load(name, str(directory)):
                app.installTranslator(candidate)
                _installed.append(candidate)
                loaded.append(name)
                break
    return loaded
