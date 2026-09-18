"""章节列表控件（左侧章节树）。

侧边栏宽度有限（默认 300px），网络小说的章节名又长，列表里多数条目都被
``Qt.ElideRight`` 截成「第1234章 我打造了末日安…」。这里给章节树补上
「悬停看全名」，并且**只在真正被截断时才弹提示**——短名字悬停时保持安静。

Qt 自带的 ``setToolTip()`` 做不到「只在截断时弹」：它是对每个条目无条件
生效的，于是「第1章 开局」这种一眼能看全的名字也会弹出提示，很吵。所以
这里改成在 ``viewportEvent`` 里拦下 ``QEvent.ToolTip``，自己量一下这一行
的文字是不是画得下，再决定弹不弹。
"""

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QToolTip, QTreeWidget

#: 估算可用文字宽度时额外扣掉的余量（像素）。
#: Qt 把文字摆在 ``visualItemRect()`` 给的框里，框右边还留了一条内边距
#: （实测 272px 宽的列表里约 12px），不扣掉的话会把「刚好卡边界」的名字
#: 当成画得下。宁可偶尔漏弹，也不要给明明显示完整的短名字弹提示。
_TEXT_WIDTH_SLACK = 12


class ChapterTree(QTreeWidget):
    """章节树：章节名被省略号截断时，悬停显示完整名称。"""

    def viewportEvent(self, event):
        # QEvent.ToolTip（QHelpEvent）是发给 viewport 的，坐标也就按 viewport 算。
        # 这里直接吞掉，不再交给 QAbstractItemView 去取 Qt::ToolTipRole。
        if event.type() == QEvent.ToolTip:
            self._show_full_name(event)
            return True
        return super().viewportEvent(event)

    # ---------------- 悬停提示 ----------------

    def _show_full_name(self, event):
        """按悬停到的条目决定弹不弹完整名"""
        item = self.itemAt(event.pos())
        text = item.text(0) if item is not None else ""
        if text and self.is_name_elided(item, text):
            QToolTip.showText(event.globalPos(), text, self.viewport(),
                              self.visualItemRect(item))
        else:
            # 从被截断的条目挪到完整条目上时，得把上一条提示收掉，
            # 否则它会一直挂在那儿（Qt 只在鼠标移到别处时才自动收）
            QToolTip.hideText()

    def is_name_elided(self, item, text=None):
        """这一行的文字画得下吗——画不下 Qt 就会补省略号"""
        if text is None:
            text = item.text(0)
        if not text:
            return False
        available = self.available_text_width(item)
        if available <= 0:
            return True
        return self.fontMetrics().horizontalAdvance(text) > available

    def available_text_width(self, item):
        """这一行留给文字的像素宽度（已扣掉右侧余量）

        ``visualItemRect()`` 返回的是**扣完树形缩进之后**的内容框（顶层条目
        的框左边就从缩进处开始），所以这里不用再减一次缩进。
        """
        return self.visualItemRect(item).width() - _TEXT_WIDTH_SLACK
