# -*- coding: utf-8 -*-
"""「朗读范围 → 指定起止章节」对话框：两个章节下拉列表。

为什么不用 ``QInputDialog.getInt`` 问两个序号：章节名常常长得很像
（「第一章」和「第一章 归来」），只看序号根本不知道自己在选哪一章。
这里把当前文件的章节标题原样列出来，选的就是看得见的那两章。

范围是**一次性**的：读完结束章就停下并回到「整章」默认（见主窗口的
:meth:`~enm.ui.main_window.NovelMaster.on_speech_finished`），所以这里
不需要「记住」之类的勾选项。
"""

from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QLabel, QVBoxLayout)

from .. import i18n
from .theme_qss import build_style_sheet
from .titlebar import apply_to_widget


class SpeechRangeDialog(QDialog):
    """选择从哪一章读到哪一章（章节名下拉列表 + 确定 / 取消）。"""

    def __init__(self, titles, current=0, parent=None, ui_theme=None,
                 titlebar_theme=None):
        super().__init__(parent)

        #: 章节标题列表（空标题也不丢，用序号兜底显示）
        self._titles = [str(text or "").strip() for text in (titles or ())]
        self._current = max(0, min(len(self._titles) - 1, int(current or 0)))
        self._titlebar_theme = titlebar_theme

        if ui_theme:
            self.setStyleSheet(build_style_sheet(ui_theme))

        self.setWindowTitle(i18n.t("tts.range.dialog_title"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setup_ui()

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        """搭界面：说明一句 + 两个章节下拉 + 按钮"""
        layout = QVBoxLayout(self)

        hint = QLabel(i18n.t("tts.range.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.from_combo = QComboBox()
        self.to_combo = QComboBox()
        for index, text in enumerate(self._titles):
            # 标题为空时退回「第 N 章」这种编号写法，免得下拉里是一排空白
            label = text or i18n.t("tts.range.unnamed", index=index + 1)
            self.from_combo.addItem(label, index)
            self.to_combo.addItem(label, index)

        # 默认「从当前章读到最后一章」：想读的往往就是剩下的部分
        self.from_combo.setCurrentIndex(self._current)
        self.to_combo.setCurrentIndex(len(self._titles) - 1)

        form = QFormLayout()
        form.addRow(i18n.t("tts.range.from_label"), self.from_combo)
        form.addRow(i18n.t("tts.range.to_label"), self.to_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(i18n.t("tts.range.start"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ 结果

    def selected_range(self):
        """选中的起止章节序号 ``(from, to)``（已经按大小排好，容错倒着选）"""
        first = self.from_combo.currentData()
        last = self.to_combo.currentData()
        first = 0 if first is None else int(first)
        last = 0 if last is None else int(last)
        return (first, last) if first <= last else (last, first)
