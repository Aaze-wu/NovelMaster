# -*- coding: utf-8 -*-
"""「朗读 → 读音纠正」对话框：可视化编辑多音字替换词典。

所有引擎都会把一部分多音字读错（``银行`` 读成 xíng、``重新`` 读成 zhòng、
``单薄`` 读成 báo）。本项目的解法是把读错的字换成**读音相同、而且只有这一个
读音**的常用字（``银行 → 银航``），四个引擎一视同仁。菜单里能改的只有这个
词典本身 —— 它就是一张「原词 → 改成」的表。

窗口里能看出三层实际生效的结果：

* **内置**（灰）—— :data:`~enm.managers.tts_pron.BUILTIN_RULES` 里手写的高频
  词，开箱即用，不需要 pypinyin；
* **已修改 / 已停用**（高亮）—— 用户词典里覆盖了同名的内置词；
* **自定义** —— 用户自己加的词。

按钮的分工（都作用于当前选中行，或下面输入框里的「原词」）：

* **保存** —— 原词已存在就改，不存在就加；
* **删除** —— 删掉用户词典里的这条。删的是内置词的话，它就退回内置规则；
* **保持原样** —— 加一条「改成」为空白的记录，意思是「这个词别动」。这条
  同时会**挡住自动推断层**，用来对付「引擎本来读对了、却被自动层改坏」的
  情况（``高兴`` 这种）；
* **恢复默认** —— 把内置词退回出厂设置（等价于删掉覆盖它的用户条目）。

窗口自己不改朗读状态：每次改动都直接落盘到
``%APPDATA%/NovelMaster/pronunciation.json``，改正器用的是同一个单例，下一次
``speak()`` 立刻生效。正在读的那一句不受影响（音频已经合成好了）。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .. import i18n
from ..managers.tts_pron import (BUILTIN_RULES, KEEP_SENTINEL,
                                 auto_available, get_pronouncer)
from .theme_qss import apply_style_sheet
from .titlebar import apply_to_widget

#: 挂在行上的原始数据（原词 / 是不是用户条目）
WORD_ROLE = Qt.UserRole
USER_ROLE = Qt.UserRole + 1

#: 「改成」为空时的显示文本（真实含义是「不替换」）
KEEP_LABEL = "（不替换）"

#: 预览框里的默认例句，一行里塞了三个典型读错的词
SAMPLE_TEXT = "他去银行取钱，重新数了一遍，又买了张薄饼。"


class TtsPronDialog(QDialog):
    """多音字读音纠正的设置窗口（非模态，改完即时生效）。"""

    #: 词典或开关改过了（主窗口拿它刷新提示 / 丢掉预合成）
    changed = pyqtSignal()

    def __init__(self, parent=None, ui_theme=None, titlebar_theme=None):
        super().__init__(parent)

        self._titlebar_theme = titlebar_theme
        #: 当前用的界面主题（换主题时由 :meth:`apply_ui_theme` 更新）
        self._ui_theme = ui_theme
        #: 程序化改控件时挡住信号，避免「回填 → 触发保存」的回环
        self._filling = False

        apply_style_sheet(self, ui_theme)

        self.setWindowTitle(i18n.t("tts.pron.dialog_title",
                                   default="读音纠正"))
        self.setModal(False)
        self.setMinimumSize(660, 540)
        self.setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(i18n.t(
            "tts.pron.hint",
            default="引擎读不准多音字时，可以把读错的字换成读音相同、"
                    "而且只有这一个读音的常用字，例如「银行」改成「银航」。"
                    "只改送给引擎的那一份文本，正文、逐句高亮和自动滚动都不变。"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.master_box = QCheckBox(i18n.t(
            "tts.pron.master", default="启用读音纠正"))
        self.master_box.toggled.connect(self._on_master_toggled)
        layout.addWidget(self.master_box)

        self.auto_box = QCheckBox(i18n.t(
            "tts.pron.auto",
            default="自动推断多音字（需要 pypinyin，默认关闭）"))
        self.auto_box.toggled.connect(self._on_auto_toggled)
        if auto_available():
            self.auto_box.setToolTip(i18n.t(
                "tts.pron.auto_tip",
                default="按上下文给每个字注音，只替换引擎读错的地方。"
                        "默认关闭：实测神经引擎（edge）自己就能读对多音字，"
                        "真会被读错的主要是老式系统语音；而且自动层判断一错，"
                        "就会把常用字改得莫名其妙（「不」→「醭」）。")
                + i18n.t("tts.pron.auto_safe",
                         default="两道保险：① 只有上下文读音和这个字的默认读音"
                                 "不一样时才动手，所以「慢慢地」「高兴地说」"
                                 "这种读对的地方不会被改；② 这个读音如果被 "
                                 "pypinyin 词表里的词确认过，就认为引擎也认得，"
                                 "同样不动它。"))
        else:
            self.auto_box.setEnabled(False)
            self.auto_box.setToolTip(i18n.t(
                "tts.pron.auto_missing",
                default="没装 pypinyin，自动推断不可用。"
                        "「用户词典」和「内置规则」两层不受影响。"))
        layout.addWidget(self.auto_box)

        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setColumnCount(4)
        labels = [
            i18n.t("tts.pron.col_source", default="原词"),
            i18n.t("tts.pron.col_target", default="改成"),
            i18n.t("tts.pron.col_layer", default="来源"),
            i18n.t("tts.pron.col_note", default="说明"),
        ]
        self.tree.setHeaderLabels(labels)
        # 列宽跟着表头文字走：英文（"Replace with"）比中文长，写死 110 会被截成
        # 「Replace wit」，所以取「表头宽度 + 内边距」和下界的较大者。
        self._fit_columns()
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.currentItemChanged.connect(self._on_row_changed)
        layout.addWidget(self.tree, 1)

        # ---- 编辑区 ----
        edit = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText(
            i18n.t("tts.pron.source_ph", default="原词，例如 银行"))
        self.source_edit.setMinimumWidth(120)
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText(
            i18n.t("tts.pron.target_ph", default="改成，例如 银航"))
        self.target_edit.setMinimumWidth(120)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText(
            i18n.t("tts.pron.note_ph", default="说明（可留空）"))
        note_label = QLabel(i18n.t("tts.pron.source_label", default="原词"))
        target_label = QLabel(i18n.t("tts.pron.target_label", default="改成"))
        edit.addWidget(note_label)
        edit.addWidget(self.source_edit, 2)
        edit.addWidget(target_label)
        edit.addWidget(self.target_edit, 2)
        edit.addWidget(self.note_edit, 3)
        layout.addLayout(edit)

        buttons = QHBoxLayout()
        self.save_button = QPushButton(i18n.t("tts.pron.save", default="保存"))
        self.save_button.clicked.connect(self._on_save)
        self.remove_button = QPushButton(i18n.t("tts.pron.delete", default="删除"))
        self.remove_button.clicked.connect(self._on_delete)
        self.keep_button = QPushButton(
            i18n.t("tts.pron.keep", default="保持原样"))
        self.keep_button.setToolTip(i18n.t(
            "tts.pron.keep_tip",
            default="加一条空记录，表示这个词别替换；同时挡住自动推断层，"
                    "适合「引擎本来就读对了」的词。"))
        self.keep_button.clicked.connect(self._on_keep)
        self.revert_button = QPushButton(
            i18n.t("tts.pron.revert", default="恢复默认"))
        self.revert_button.clicked.connect(self._on_revert)
        self.close_button = QPushButton(i18n.t("tts.pron.close", default="关闭"))
        self.close_button.clicked.connect(self.close)
        for button in (self.save_button, self.remove_button,
                       self.keep_button, self.revert_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        # ---- 预览 ----
        preview = QHBoxLayout()
        preview.addWidget(QLabel(i18n.t("tts.pron.preview_label", default="预览")))
        self.preview_edit = QLineEdit(SAMPLE_TEXT)
        self.preview_edit.setClearButtonEnabled(True)
        self.preview_edit.textChanged.connect(lambda _t: self._update_preview())
        preview.addWidget(self.preview_edit, 1)
        layout.addLayout(preview)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    def apply_ui_theme(self, ui_theme, titlebar_theme=None):
        """换主题：窗口开着的时候也要立刻变，而不是等关掉重开。

        主窗口 ``apply_theme()`` 会遍历所有**非模态**对话框调这个方法——
        模态对话框开着时菜单点不动，本来就换不了主题。原生标题栏的颜色
        一起更新（``titlebar_theme`` 为空表示「标题栏跟随主题」是关的，
        这时不动它，和 :meth:`showEvent` 一个口径）。
        """
        self._ui_theme = ui_theme
        apply_style_sheet(self, ui_theme)
        self._titlebar_theme = titlebar_theme
        apply_to_widget(self, titlebar_theme)
        # 表格的列宽是照表头文字算的，字号变了要重算
        self._fit_columns()

    def _fit_columns(self):
        """按表头文字宽度定列宽（英文比中文长，写死数值会被截断）"""
        labels = [self.tree.headerItem().text(i) for i in range(4)]
        metrics = self.tree.header().fontMetrics()
        for index, (label, minimum) in enumerate(zip(labels, (110, 110, 90))):
            self.tree.setColumnWidth(
                index, max(minimum, metrics.horizontalAdvance(label) + 24))

    # ------------------------------------------------------------------ 数据

    def _rows(self):
        """把「内置规则 + 用户词典」合并成一张有效表（用户覆盖内置）。

        返回 ``[(原词, 改成, 说明, 来源, 是否用户条目)]``。
        """
        pronouncer = get_pronouncer()
        user = {e.source: e for e in pronouncer.entries()}
        layer_user = i18n.t("tts.pron.layer_user", default="自定义")
        layer_off = i18n.t("tts.pron.layer_off", default="已停用")
        layer_edit = i18n.t("tts.pron.layer_edit", default="已修改")
        layer_rule = i18n.t("tts.pron.layer_rule", default="内置")

        rows = []
        builtin_words = set()
        for word, target, _reading, note in BUILTIN_RULES:
            builtin_words.add(word)
            entry = user.get(word)
            if entry is None:
                rows.append((word, target, note, layer_rule, False))
            elif not entry.enabled:
                rows.append((word, target, entry.note or note, layer_off, True))
            elif entry.target:
                rows.append((word, entry.target, entry.note or note,
                             layer_edit, True))
            else:
                # target 为空 = 保持原样
                rows.append((word, KEEP_SENTINEL, entry.note or note,
                             layer_edit, True))
        for source, entry in user.items():
            if source in builtin_words:
                continue
            rows.append((source, entry.target if entry.enabled else KEEP_SENTINEL,
                         entry.note, layer_user if entry.enabled else layer_off,
                         True))
        rows.sort(key=lambda row: (-len(row[0]), row[0]))
        return rows

    # ------------------------------------------------------------------ 刷新

    def refresh(self):
        """整表 + 开关 + 预览全部重画（打开时和每次改动后都走这里）。"""
        pronouncer = get_pronouncer()
        self._filling = True
        try:
            self.master_box.setChecked(pronouncer.enabled)
            self.auto_box.setChecked(pronouncer.auto_enabled)
            self.auto_box.setEnabled(auto_available())

            selected = self.source_edit.text().strip()
            self.tree.clear()
            for word, target, note, layer, is_user in self._rows():
                item = QTreeWidgetItem([word, target or KEEP_LABEL, layer, note])
                item.setData(0, WORD_ROLE, word)
                item.setData(0, USER_ROLE, is_user)
                if is_user:
                    for column in range(4):
                        font = item.font(column)
                        font.setBold(True)
                        item.setFont(column, font)
                self.tree.addTopLevelItem(item)
            if selected:
                self._select_word(selected)
        finally:
            self._filling = False
        self._update_preview()
        self._update_status()

    def _select_word(self, word):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, WORD_ROLE) == word:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def _update_status(self):
        pronouncer = get_pronouncer()
        if not auto_available():
            self.status_label.setText(i18n.t(
                "tts.pron.status_no_pypinyin",
                default="提示：没装 pypinyin，自动推断层已关闭（"
                        "「用户词典」和「内置规则」照常生效）。"))
            return
        total = len(BUILTIN_RULES)
        mine = len(pronouncer.entries())
        self.status_label.setText(i18n.t(
            "tts.pron.status",
            default="内置规则 {total} 条，用户词典 {mine} 条。"
                    "词典文件：{path}",
            total=total, mine=mine, path=str(pronouncer.path)))

    def _update_preview(self):
        """拿例句跑一遍三层替换，把「改前 → 改后」摆出来。"""
        text = self.preview_edit.text()
        pronouncer = get_pronouncer()
        try:
            summary = pronouncer.diff_summary(text)
            result = pronouncer.correct(text)
        except Exception as exc:            # noqa: BLE001 - 预览不能崩
            self.preview_label.setText(f"{exc}")
            return
        if not pronouncer.enabled:
            self.preview_label.setText(
                i18n.t("tts.pron.preview_off", default="读音纠正已关闭，原文照读。"))
        elif not summary:
            self.preview_label.setText(
                i18n.t("tts.pron.preview_none", default="这句话没有要改的地方。"))
        else:
            self.preview_label.setText(i18n.t(
                "tts.pron.preview", default="送引擎的文本：{result}　（{summary}）",
                result=result, summary=summary))

    # ------------------------------------------------------------------ 交互

    def _on_row_changed(self, current, _previous):
        if self._filling or current is None:
            return
        word = current.data(0, WORD_ROLE) or ""
        self.source_edit.setText(word)
        target = current.text(1)
        self.target_edit.setText("" if target == KEEP_LABEL else target)
        self.note_edit.setText("" if current.text(3) == KEEP_LABEL
                              else current.text(3))

    def _on_master_toggled(self, checked):
        if self._filling:
            return
        pronouncer = get_pronouncer()
        pronouncer.enabled = checked
        pronouncer.save()
        self._update_preview()
        self.changed.emit()

    def _on_auto_toggled(self, checked):
        if self._filling:
            return
        pronouncer = get_pronouncer()
        pronouncer.auto_enabled = checked
        pronouncer.save()
        self._update_preview()
        self.changed.emit()

    def _on_save(self):
        source = self.source_edit.text().strip()
        if not source:
            self._complain(i18n.t("tts.pron.need_source",
                                  default="请先填「原词」。"))
            return
        target = self.target_edit.text().strip()
        pronouncer = get_pronouncer()
        pronouncer.add_entry(source, target, self.note_edit.text().strip())
        pronouncer.save()
        self.refresh()
        self._select_word(source)
        self.changed.emit()

    def _on_delete(self):
        word = self._current_word()
        if not word:
            self._complain(i18n.t("tts.pron.need_select",
                                  default="请先选中要处理的那一行。"))
            return
        pronouncer = get_pronouncer()
        if pronouncer.remove_entry(word):
            pronouncer.save()
            self.refresh()
            self._select_word(word)
            self.changed.emit()
        else:
            self._complain(i18n.t(
                "tts.pron.not_user",
                default="「{word}」是内置规则，没有可删的用户条目；"
                        "它本来就是默认行为。", word=word))

    def _on_keep(self):
        word = self._current_word()
        if not word:
            self._complain(i18n.t("tts.pron.need_select",
                                  default="请先选中要处理的那一行。"))
            return
        pronouncer = get_pronouncer()
        note = self.note_edit.text().strip() or i18n.t(
            "tts.pron.keep_note", default="保持原样，不替换")
        pronouncer.add_entry(word, KEEP_SENTINEL, note)
        pronouncer.save()
        self.refresh()
        self._select_word(word)
        self.changed.emit()

    def _on_revert(self):
        word = self._current_word()
        if not word:
            self._complain(i18n.t("tts.pron.need_select",
                                  default="请先选中要处理的那一行。"))
            return
        pronouncer = get_pronouncer()
        target = pronouncer.revert_builtin(word)
        pronouncer.save()
        self.refresh()
        self._select_word(word)
        self.changed.emit()
        if target is None:
            self._complain(i18n.t(
                "tts.pron.reverted_none",
                default="「{word}」不在内置规则里，已从用户词典移除。",
                word=word))

    def _current_word(self):
        """当前要操作的词：以输入框为准，其次才是表格里选中的那一行。

        **必须优先输入框**：用户可能是先在表格里点了「银行」，再把「原词」改成
        「高兴」去点「保持原样」，这时表格的选中项还停在「银行」上，若以选中项
        为准就会改错行。
        """
        word = self.source_edit.text().strip()
        if word:
            return word
        item = self.tree.currentItem()
        if item is not None:
            return item.data(0, WORD_ROLE) or ""
        return ""

    def _complain(self, message):
        self.status_label.setText(message)

    # ------------------------------------------------------------------ 收尾

    def shutdown(self):
        """主窗口退出时收尾（这个窗口自己不占线程 / 文件）"""
        self.close()


__all__ = ["TtsPronDialog"]
