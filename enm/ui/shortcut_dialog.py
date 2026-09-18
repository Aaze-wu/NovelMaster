# -*- coding: utf-8 -*-
"""快捷键设置（改键）对话框。

按分组列出所有可自定义的动作，每项都可以重新录制按键：

* 点一下按键框再按新组合键即可改键；
* 每行右侧的「恢复默认」只还原当前这一项；
* 底部「全部恢复默认」一次性还原所有项；
* 出现重复按键时直接拒绝保存并列出冲突项，避免按下快捷键时行为不确定。

界面文案全部走 ``enm.i18n``（语言键前缀 ``shortcut.``），分组名与功能名
由 :mod:`enm.shortcuts` 的 ``group_label`` / ``label_of`` / ``hint_of`` 提供。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QGroupBox,
                             QHBoxLayout, QKeySequenceEdit, QLabel,
                             QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

from .. import i18n
from ..logger import logger
from ..shortcuts import (DEFS_BY_ID, display_text, group_label,
                         grouped_definitions, hint_of, label_of,
                         normalise_sequence)
from .titlebar import apply_to_widget


class ShortcutSettingsDialog(QDialog):
    """快捷键设置对话框"""

    def __init__(self, shortcut_manager, parent=None, titlebar_theme=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        # 动作 id -> QKeySequenceEdit
        self.editors = {}
        #: 本对话框自己的标题栏用哪套配色（showEvent 里才会真正套上去）
        self._titlebar_theme = titlebar_theme

        self.setWindowTitle(i18n.t("dialog.shortcut_settings"))
        self.resize(560, 620)

        layout = QVBoxLayout(self)

        hint = QLabel(i18n.t("shortcut.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        for group, definitions in grouped_definitions():
            container_layout.addWidget(self.build_group(group, definitions))
        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # 底部按钮
        button_row = QHBoxLayout()

        self.reset_all_btn = QPushButton(i18n.t("common.reset_all_default"))
        self.reset_all_btn.clicked.connect(self.reset_all)
        button_row.addWidget(self.reset_all_btn)
        button_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(i18n.t("common.ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    # ---------------- 构建界面 ----------------

    def build_group(self, group, definitions):
        """按分组生成一组按键设置行"""
        box = QGroupBox(group_label(group))
        box_layout = QVBoxLayout(box)

        for definition in definitions:
            box_layout.addLayout(self.build_row(definition))
        return box

    def build_row(self, definition):
        """生成单条设置行"""
        row = QHBoxLayout()

        action_id = definition.action_id
        label_text = label_of(action_id)
        hint_text = hint_of(action_id)

        label = QLabel(label_text)
        label.setMinimumWidth(150)
        if hint_text:
            label.setToolTip(hint_text)
        row.addWidget(label)

        editor = QKeySequenceEdit()
        editor.setKeySequence(self.shortcut_manager.key_sequence_of(action_id))
        editor.setToolTip(hint_text)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.editors[action_id] = editor
        row.addWidget(editor, 1)

        default_text = QLabel(i18n.t(
            "shortcut.default", keys=display_text(definition.default)))
        default_text.setMinimumWidth(110)
        row.addWidget(default_text)

        reset_btn = QPushButton(i18n.t("common.reset_default"))
        reset_btn.setToolTip(i18n.t("shortcut.reset_tooltip", label=label_text))
        reset_btn.clicked.connect(
            lambda _checked, target=action_id: self.reset_one(target))
        row.addWidget(reset_btn)

        return row

    # ---------------- 交互 ----------------

    def reset_one(self, action_id):
        """把某一项还原为默认按键"""
        editor = self.editors.get(action_id)
        if editor is None:
            return
        editor.setKeySequence(
            self.shortcut_manager.key_sequence_of(action_id, use_default=True))

    def reset_all(self):
        """还原全部默认按键"""
        for action_id, editor in self.editors.items():
            editor.setKeySequence(self.shortcut_manager.key_sequence_of(
                action_id, use_default=True))

    def collected_bindings(self):
        """收集界面上当前的绑定（动作 id -> 按键文本）"""
        bindings = {}
        for action_id, editor in self.editors.items():
            bindings[action_id] = normalise_sequence(
                editor.keySequence().toString(QKeySequence.PortableText))
        return bindings

    def conflict_message(self, groups):
        """把冲突项拼成提示文本"""
        separator = i18n.t("common.list_separator", default="、")
        lines = []
        for text, action_ids in groups:
            names = separator.join(label_of(action_id)
                                   for action_id in action_ids
                                   if action_id in DEFS_BY_ID)
            lines.append(i18n.t("shortcut.conflict_line", keys=text, names=names))
        return i18n.t("shortcut.conflict_message", details="\n".join(lines))

    def accept(self):
        """确定：校验冲突后保存到配置"""
        bindings = self.collected_bindings()
        conflicts = self.shortcut_manager.conflict_groups(bindings)
        if conflicts:
            logger.log("快捷键设置保存失败: 存在重复按键")
            QMessageBox.warning(self, i18n.t("shortcut.conflict_title"),
                                self.conflict_message(conflicts))
            return

        self.shortcut_manager.apply(bindings)
        self.shortcut_manager.save()
        super().accept()
