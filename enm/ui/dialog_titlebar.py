"""让 Qt 自带对话框的原生标题栏也跟随主题。

``QFontDialog.getFont()`` / ``QColorDialog.getColor()`` / ``QInputDialog.getText()`` /
``QMessageBox.about()`` 都是**静态便捷函数**：对话框由 Qt 内部创建，外层拿不到
引用，也就没法像本项目自己的对话框那样在 ``showEvent`` 里调
:func:`enm.ui.titlebar.apply_to_widget`。

于是换个思路：在 ``QApplication`` 上装一个事件过滤器，任何**顶层对话框**第一次
``show()`` 时就按当前主题给它上色；窗口句柄被重建（``QEvent.WinIdChange``）时
再补一次 —— DWM 把颜色写在窗口自己身上，窗口重建就丢了。

为什么不用子类：``QMessageBox.about()`` 建的对话框连 Python 引用都没有，子类化
只能管到我们自己 new 出来的那几个。过滤器不挑对象，凡是 ``QDialog`` 一律照顾；
本项目自己的对话框也会被顺带刷一遍，重复上同一套色没有副作用。

「标题栏跟随主题」关掉时，取主题的钩子返回 ``None``，这里直接跳过 —— 不用
自己判断那个开关。
"""

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QDialog

from .titlebar import apply_to_widget


class DialogTitlebarFilter(QObject):
    """顶层对话框 ``show()`` 时给它们的原生标题栏上色的应用级事件过滤器。"""

    def __init__(self, theme_provider, parent=None):
        super().__init__(parent)
        #: 取当前该用的主题字典的钩子（通常是主窗口的 dialog_titlebar_theme）
        self._theme_provider = theme_provider
        #: 防止 winId() 触发的重入：apply_to_widget 里会调 winId()，
        #: 而 winId() 在某些情况下会补发 WinIdChange
        self._busy = False

    def eventFilter(self, obj, event):
        if self._busy:
            return False
        if event.type() not in (QEvent.Show, QEvent.WinIdChange):
            return False
        # QMessageBox / QFontDialog / QColorDialog / QInputDialog 都是 QDialog 的子类
        if not isinstance(obj, QDialog):
            return False
        # 内嵌（非顶层）的对话框没有自己的标题栏
        if not obj.isWindow():
            return False

        theme = self._theme_provider() if callable(self._theme_provider) else None
        if not theme:
            return False

        self._busy = True
        try:
            apply_to_widget(obj, theme)
        finally:
            self._busy = False
        return False


def install(app, theme_provider, parent=None):
    """把过滤器装到 ``app`` 上，返回过滤器对象（调用方持有引用即可）。

    ``theme_provider`` 是个无参可调用对象，返回当前该用的主题字典或 ``None``。
    ``app`` 为 ``None`` 时什么都不做并返回 ``None``。
    """
    if app is None:
        return None
    event_filter = DialogTitlebarFilter(theme_provider, parent=parent)
    app.installEventFilter(event_filter)
    return event_filter
