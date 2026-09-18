# -*- coding: utf-8 -*-
"""去掉 Qt 对话框标题栏上那个没用的「?」按钮。

Windows 上 ``QDialog`` 的默认窗口标志里带着 ``Qt::WindowContextHelpButtonHint``
（实测裸 ``QDialog()`` 的标志是 ``0x08013003``），Qt 把它翻译成窗口扩展样式
``WS_EX_CONTEXTHELP``，于是标题栏最右边多画一个「?」。点它的行为是进入
「这是什么？」模式，鼠标变成带问号的箭头，再点某个控件才会弹说明气泡 ——
而气泡内容来自控件的 ``setWhatsThis()``。本项目从来没给任何控件设过
``whatsThis``，所以这个按钮点下去什么都不会发生，纯粹是 Qt 的默认外观残留。

Qt 自己创建的对话框（``QInputDialog.getText()`` / ``QInputDialog()`` /
直接 ``new`` 出来的 ``QFontDialog`` 等）外层拿不到引用，没法像本项目自己的
对话框那样在 ``__init__`` 里改标志，所以换个思路：在 ``QApplication`` 上装
一个事件过滤器，任何顶层 ``QDialog`` 的原生窗口刚建好时就清掉这个标志。

三个必须记住的点：

* **时机只能是 ``QEvent.WinIdChange``**。这时原生窗口刚建好、**还没显示**
  （实测 ``visible=False``），改标志没有任何副作用；等到 ``Show`` 再改，
  Qt 会把已经可见的窗口藏起来重建，用户能看到窗口「闪一下」甚至直接消失。
* **改标志本身不会立刻生效**。Qt 在标志变化时会销毁原生窗口，下次 ``show()``
  用新标志重建，所以按钮是真的没了，而不是「Qt 标志清了、原生按钮还在」。
* **已经可见的窗口一律不碰**。对可见窗口调 ``setWindowFlags()`` 会把它藏起来
  （Qt 不会自动再显示），那样反而比多一个问号按钮更糟。

``QMessageBox`` 的静态函数（``warning`` / ``question`` / ``about`` ……）建的
实例本来就没带这个标志（实测 ``QMessageBox.warning`` 的窗口标志是
``0x08003103``），不用特意照顾，过滤器顺带覆盖即可。
"""

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QDialog

#: 上下文帮助（「?」）按钮对应的窗口标志
HELP_BUTTON_FLAG = Qt.WindowContextHelpButtonHint


def strip_help_button(widget):
    """清掉 ``widget`` 的问号按钮标志，返回是否真的改动了。

    **必须在窗口 ``show()`` 之前调用**：对已经可见的窗口调用会让它被藏起来
    （Qt 不会替你重新显示），所以只该在构造期或 :class:`HelpButtonFilter`
    那样的「还没显示」时机用。
    """
    if widget is None:
        return False
    flags = widget.windowFlags()
    if not (flags & HELP_BUTTON_FLAG):
        return False
    widget.setWindowFlags(flags & ~HELP_BUTTON_FLAG)
    return True


class HelpButtonFilter(QObject):
    """顶层对话框原生窗口建好的瞬间清掉问号按钮的应用级事件过滤器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        #: 防重入：改标志会销毁原生窗口，可能在事件处理途中再触发一次 WinIdChange
        self._busy = False

    def eventFilter(self, obj, event):
        if self._busy or event.type() != QEvent.WinIdChange:
            return False
        # QInputDialog / QFontDialog / QColorDialog 都是 QDialog 的子类
        if not isinstance(obj, QDialog):
            return False
        # 内嵌（非顶层）的对话框没有自己的标题栏
        if not obj.isWindow():
            return False
        # 已经显示的窗口不能动标志（会被藏起来）
        if obj.isVisible():
            return False

        self._busy = True
        try:
            strip_help_button(obj)
        finally:
            self._busy = False
        return False


def install(app, parent=None):
    """把过滤器装到 ``app`` 上，返回过滤器对象（调用方持有引用即可）。

    ``app`` 为 ``None`` 时什么都不做并返回 ``None``。
    """
    if app is None:
        return None
    event_filter = HelpButtonFilter(parent=parent)
    app.installEventFilter(event_filter)
    return event_filter
