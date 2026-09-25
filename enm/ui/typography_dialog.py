# -*- coding: utf-8 -*-
"""排版设置对话框：行距 + 段间距（不跟随主题的那一套全局阅读排版）。

以前「设置」菜单里只有字体设置（字体 + 字号，走 Qt 原生的 ``QFontDialog``），
行距是写死在代码里的 —— 更要命的是写在样式表里的 ``line-height`` 根本不生效，
所以用户从来没机会调它。这个对话框把两件事一起补上：

* 行距（倍数，1.0~3.0）：``QTextBlockFormat.setLineHeight`` 按百分比套；
* 段间距（像素，0~80）：块的上下边距各分一半，所以两个正常段落之间的间隙
  正好等于这个值。Qt 给 ``<p>`` 的默认上下边距是各 12px，所以 24 = 默认外观。

改动是**实时预览**的：拖动数值时主窗口立刻重排正文（不写配置），按「取消」
由主窗口把阅读区还原回原来的值。这样不用来回确定-撤销地试。

排版跟随主题（``typography_follow_theme``）打开且主题自带该项时，这里对应的
输入框会禁用并标注「由当前主题决定」——不然改了没反应会以为是 bug。
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFormLayout, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QVBoxLayout)

from .. import i18n
from ..managers.theme import (DEFAULT_LINE_SPACING,
                              DEFAULT_PARAGRAPH_SPACING, LINE_SPACING_RANGE,
                              PARAGRAPH_SPACING_RANGE, normalise_line_spacing,
                              normalise_paragraph_spacing)
from .theme_qss import build_style_sheet
from .titlebar import apply_to_widget


class TypographySettingsDialog(QDialog):
    """行距 / 段间距设置。

    ``line_follows_theme`` / ``paragraph_follows_theme`` 表示该项当前由主题
    决定（对应输入框禁用）。
    """

    #: 数值变化 → (行距倍数, 段间距像素)，主窗口据此实时重排阅读区
    preview_changed = pyqtSignal(float, int)

    def __init__(self, line_spacing=None, paragraph_spacing=None, parent=None,
                 ui_theme=None, titlebar_theme=None,
                 line_follows_theme=False, paragraph_follows_theme=False):
        super().__init__(parent)

        spacing = normalise_line_spacing(line_spacing)
        self._line_spacing = spacing if spacing is not None else DEFAULT_LINE_SPACING
        paragraph = normalise_paragraph_spacing(paragraph_spacing)
        self._paragraph_spacing = (DEFAULT_PARAGRAPH_SPACING
                                   if paragraph is None else paragraph)
        self._line_follows_theme = bool(line_follows_theme)
        self._paragraph_follows_theme = bool(paragraph_follows_theme)
        #: 本对话框自己的标题栏用哪套配色（showEvent 里才会真正套上去）
        self._titlebar_theme = titlebar_theme

        if ui_theme:
            self.setStyleSheet(build_style_sheet(ui_theme))

        self.setWindowTitle(i18n.t("dialog.typography_settings"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setup_ui()

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        """搭界面"""
        layout = QVBoxLayout(self)

        hint = QLabel(i18n.t("typography.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(*LINE_SPACING_RANGE)
        self.line_spacing_spin.setSingleStep(0.1)
        self.line_spacing_spin.setDecimals(2)
        self.line_spacing_spin.setValue(self._line_spacing)
        self.line_spacing_spin.setEnabled(not self._line_follows_theme)
        self.line_spacing_spin.valueChanged.connect(self.emit_preview)

        self.paragraph_spacing_spin = QSpinBox()
        self.paragraph_spacing_spin.setRange(*PARAGRAPH_SPACING_RANGE)
        self.paragraph_spacing_spin.setSingleStep(2)
        self.paragraph_spacing_spin.setSuffix(" px")
        self.paragraph_spacing_spin.setValue(self._paragraph_spacing)
        self.paragraph_spacing_spin.setEnabled(not self._paragraph_follows_theme)
        self.paragraph_spacing_spin.valueChanged.connect(self.emit_preview)

        form = QFormLayout()
        form.addRow(i18n.t("typography.line_spacing_label"),
                    self.line_spacing_spin)
        form.addRow(i18n.t("typography.paragraph_spacing_label"),
                    self.paragraph_spacing_spin)
        layout.addLayout(form)

        # 由主题决定的那几项标注一句，免得用户以为程序坏了
        locked = []
        if self._line_follows_theme:
            locked.append(i18n.t("typography.line_spacing_label"))
        if self._paragraph_follows_theme:
            locked.append(i18n.t("typography.paragraph_spacing_label"))
        if locked:
            lock_hint = QLabel(i18n.t("typography.locked", fields=" / ".join(
                text.rstrip(":：") for text in locked)))
            lock_hint.setWordWrap(True)
            layout.addWidget(lock_hint)

        button_row = QHBoxLayout()
        self.reset_btn = QPushButton(i18n.t("common.reset_default"))
        self.reset_btn.clicked.connect(self.reset_defaults)
        button_row.addWidget(self.reset_btn)
        button_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(i18n.t("common.ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    # ------------------------------------------------------------------ 交互

    def emit_preview(self, *_args):
        """数值变了就通知主窗口实时试排（取消时由主窗口还原）"""
        self.preview_changed.emit(*self.values())

    def reset_defaults(self):
        """行距 / 段间距还原成默认值（被主题锁定的那项不动）"""
        if not self._line_follows_theme:
            self.line_spacing_spin.setValue(DEFAULT_LINE_SPACING)
        if not self._paragraph_follows_theme:
            self.paragraph_spacing_spin.setValue(DEFAULT_PARAGRAPH_SPACING)
        self.emit_preview()

    def values(self):
        """当前值，返回 ``(行距倍数, 段间距像素)``"""
        return (round(float(self.line_spacing_spin.value()), 2),
                int(self.paragraph_spacing_spin.value()))
