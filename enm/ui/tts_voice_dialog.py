# -*- coding: utf-8 -*-
"""「朗读 → 选择音色」对话框：一个独立窗口里用列表挑音色。

以前音色是直接铺在菜单里的，可在线音色有 322 个（光中文就 8 个）、离线神经
音色也有 106 个，菜单一拉开能从屏幕顶排到屏幕底，翻起来还容易点错。这个窗口
把三件事收在一起：

* **搜索框** —— 音色名、语言代号、模型名都能搜（``xiaoxiao`` / ``zh`` / ``kokoro``）；
* **模型筛选** —— 只在下拉里挑某个模型（Kokoro 一家 103 个音色，筛一下清净很多）；
* **引擎下拉** —— 换引擎不用退回菜单，切完列表跟着换。

窗口自己不认识主窗口，只吃一份 :class:`VoiceSnapshot`（由调用方每次 ``refresh()``
现取），所以音色列表永远是新的；选中的音色通过 ``voice_selected`` 发回主窗口，
由主窗口去改配置、处理「朗读中先记下来」和「模型没下载先问一句」这些事。
"""

from collections import namedtuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout)

from .. import i18n
from ..managers import tts_models
from ..managers.tts import EDGE_ENGINE, NEURAL_ENGINE, order_voices, voice_label
from .theme_qss import apply_style_sheet
from .titlebar import apply_to_widget

#: 音色在列表里的那份数据：引擎、可切换的引擎、音色表、当前音色、
#: 列表是不是拉全了（在线音色要联网）、顶部额外提示
VoiceSnapshot = namedtuple(
    "VoiceSnapshot",
    "engine engine_label engines voices current_id ready note",
    defaults=("", "", (), (), "", True, ""))

#: 挂在列表项上的额外数据（音色 id / 所属模型 / 供搜索用的原文）
VOICE_ROLE = Qt.UserRole
MODEL_ROLE = Qt.UserRole + 1
SEARCH_ROLE = Qt.UserRole + 2
SOURCE_ROLE = Qt.UserRole + 3


def voice_display_name(voice):
    """音色名（去掉 :func:`voice_label` 追加的那截语言后缀，语言单占一列）"""
    label = voice_label(voice, show_gender=True)
    suffix = f" ({voice.locale})"
    if voice.locale and label.endswith(suffix):
        return label[:-len(suffix)]
    return label


class TtsVoiceDialog(QDialog):
    """挑音色的窗口（非模态，可以开着它一边听一边换）。"""

    #: 用户点了「使用这个音色」（带上音色 id）
    voice_selected = pyqtSignal(str)
    #: 用户点了「刷新在线音色」
    refresh_requested = pyqtSignal()
    #: 用户点了「音色管理…」（下载 / 删除离线模型）
    manage_requested = pyqtSignal()
    #: 用户在下拉里换了朗读引擎（带上引擎标识）
    engine_selected = pyqtSignal(str)

    def __init__(self, parent=None, ui_theme=None, titlebar_theme=None,
                 snapshot=None):
        super().__init__(parent)

        self._titlebar_theme = titlebar_theme
        #: 当前用的界面主题（换主题时由 :meth:`apply_ui_theme` 更新）
        self._ui_theme = ui_theme
        #: 现取数据用的小函数（返回 :class:`VoiceSnapshot`），由主窗口给
        self._snapshot_source = snapshot
        self._snapshot = VoiceSnapshot()
        self._filling = False

        apply_style_sheet(self, ui_theme)

        self.setWindowTitle(i18n.t("tts.voice.dialog_title", default="选择音色"))
        # 挑音色的时候多半在听，别把阅读器锁住
        self.setModal(False)
        self.setMinimumSize(520, 460)
        self.setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.hint_label = QLabel(i18n.t("tts.voice.hint"))
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        top = QHBoxLayout()
        self.engine_label = QLabel(i18n.t("tts.voice.engine_label"))
        self.engine_combo = QComboBox()
        self.engine_combo.setMinimumWidth(200)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        top.addWidget(self.engine_label)
        top.addWidget(self.engine_combo, 1)
        layout.addLayout(top)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(i18n.t("tts.voice.search"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self._apply_filter())
        filters.addWidget(self.search_edit, 1)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(170)
        self.model_combo.currentIndexChanged.connect(
            lambda _index: self._apply_filter())
        filters.addWidget(self.model_combo)
        layout.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            i18n.t("tts.voice.col_name"),
            i18n.t("tts.voice.col_locale"),
            i18n.t("tts.voice.col_model"),
        ])
        self.tree.setColumnWidth(0, 230)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 170)
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.tree.itemDoubleClicked.connect(lambda *_: self._use_selected())
        layout.addWidget(self.tree, 1)

        self.count_label = QLabel("")
        layout.addWidget(self.count_label)

        self.current_label = QLabel("")
        self.current_label.setWordWrap(True)
        layout.addWidget(self.current_label)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton(i18n.t("tts.voice.refresh"))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.manage_button = QPushButton(i18n.t("tts.voice.manage"))
        self.manage_button.clicked.connect(self.manage_requested.emit)
        self.use_button = QPushButton(i18n.t("tts.voice.use"))
        self.use_button.clicked.connect(self._use_selected)
        self.close_button = QPushButton(i18n.t("tts.voice.close"))
        self.close_button.clicked.connect(self.close)
        for button in (self.refresh_button, self.manage_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.use_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)
        self.refresh()

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

    # ------------------------------------------------------------------ 数据

    def refresh(self):
        """向主窗口重新要一份音色表，重建列表（保留原来的选中项）"""
        source = self._snapshot_source
        snapshot = source() if callable(source) else source
        self._snapshot = snapshot if snapshot is not None else VoiceSnapshot()
        selected = self.selected_voice_id()
        self._filling = True
        try:
            self._fill_engines()
            self._fill_models()
            self._fill_tree()
        finally:
            self._filling = False
        self._restore_selection(selected)
        self._apply_filter()          # 顺带把底部计数和按钮刷一遍
        self._update_current_label()

    def _fill_engines(self):
        """顶部下拉：当前引擎 + 其它可用引擎"""
        snapshot = self._snapshot
        self.engine_combo.clear()
        for engine_id, label in snapshot.engines:
            self.engine_combo.addItem(label, engine_id)
        index = self.engine_combo.findData(snapshot.engine)
        if index >= 0:
            self.engine_combo.setCurrentIndex(index)
        # 只有一种引擎可选时这一行没意义
        usable = len(snapshot.engines) > 1
        self.engine_label.setVisible(usable)
        self.engine_combo.setVisible(usable)

    def _fill_models(self):
        """模型筛选下拉（只有离线神经音色才有多个模型，别的引擎藏起来）

        注意不能只看音色 id 里有没有 ``|``：系统语音的 id 长成
        ``zh_CN|Microsoft Huihui``，「模型」会变成语言代号，反而把人绕晕。
        """
        snapshot = self._snapshot
        self.model_combo.clear()
        self.model_combo.addItem(i18n.t("tts.voice.model_all"), "")
        models = []
        if snapshot.engine == NEURAL_ENGINE:
            for voice in snapshot.voices:
                model_id = self._model_id(voice)
                if model_id and model_id not in models:
                    models.append(model_id)
        for model_id in models:
            info = tts_models.model_info(model_id)
            self.model_combo.addItem(info.name if info is not None else model_id,
                                     model_id)
        self.model_combo.setCurrentIndex(0)
        self.model_combo.setVisible(len(models) > 1)

    def _fill_tree(self):
        """铺音色列表；在线音色清单没拉回来时只放一行「正在获取…」"""
        snapshot = self._snapshot
        self.tree.clear()
        want = self._sorted_voices()
        if not want:
            text = (i18n.t("tts.voice.loading")
                    if snapshot.engine == EDGE_ENGINE and not snapshot.ready
                    else i18n.t("tts.voice.empty_neural")
                    if snapshot.engine == NEURAL_ENGINE
                    else i18n.t("tts.voice.none"))
            item = QTreeWidgetItem([text, "", ""])
            item.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(item)
            return
        bold = QFont()
        bold.setBold(True)
        for voice in want:
            model_id = self._model_id(voice)
            item = QTreeWidgetItem([
                voice_display_name(voice), voice.locale,
                self._model_text(snapshot, model_id)])
            item.setData(0, VOICE_ROLE, voice.voice_id)
            item.setData(0, MODEL_ROLE, model_id)
            item.setData(0, SOURCE_ROLE, self._source_text(snapshot))
            item.setData(0, SEARCH_ROLE,
                         " ".join((voice.name or "", voice.locale or "",
                                   voice.voice_id, item.text(2))).lower())
            item.setToolTip(0, voice_label(voice, show_gender=True))
            if voice.voice_id == snapshot.current_id:
                for column in range(3):
                    item.setFont(column, bold)
            self.tree.addTopLevelItem(item)

    def _sorted_voices(self):
        """按界面语言排序；离线音色再按「模型」归堆，同模型的挨在一起"""
        snapshot = self._snapshot
        ordered = order_voices(list(snapshot.voices), i18n.current_language())
        if snapshot.engine != NEURAL_ENGINE:
            return ordered
        # 离线音色按「模型」归堆：Kokoro 一家 103 个音色，打散了没法看
        order = {info.model_id: index
                 for index, info in enumerate(tts_models.MODELS)}
        rank = {voice.voice_id: index for index, voice in enumerate(ordered)}
        return sorted(ordered, key=lambda voice: (
            order.get(self._model_id(voice), len(order)),
            rank.get(voice.voice_id, 0)))

    @staticmethod
    def _model_id(voice):
        """音色的模型标识（离线音色是 ``模型|说话人``；别的引擎没有）"""
        text = voice.voice_id or ""
        return text.rpartition("|")[0] if "|" in text else ""

    def _model_text(self, snapshot, model_id):
        """列表第三列：离线写模型名 + 下载状态，在线 / 系统写来源"""
        if snapshot.engine == NEURAL_ENGINE and model_id:
            info = tts_models.model_info(model_id)
            name = info.name if info is not None else model_id
            state = (i18n.t("tts.voice.model_installed")
                     if tts_models.is_installed(model_id)
                     else i18n.t("tts.voice.model_missing"))
            return f"{name}（{state}）"
        if snapshot.engine == EDGE_ENGINE:
            return i18n.t("tts.voice.model_online")
        return i18n.t("tts.voice.model_system")

    @staticmethod
    def _source_text(snapshot):
        return snapshot.engine_label or snapshot.engine

    # ------------------------------------------------------------------ 筛选

    def _apply_filter(self):
        """按搜索词 + 模型筛选显示哪几行（不重建列表，只动可见性）"""
        if self._filling:
            return
        needle = self.search_edit.text().strip().lower()
        model_id = self.model_combo.currentData() or ""
        shown = total = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, VOICE_ROLE) is None:      # 「正在获取 / 没有音色」占位行
                continue
            total += 1
            visible = (not model_id or item.data(0, MODEL_ROLE) == model_id)
            if visible and needle:
                visible = needle in (item.data(0, SEARCH_ROLE) or "")
            item.setHidden(not visible)
            if visible:
                shown += 1
        if self.tree.currentItem() is not None \
                and self.tree.currentItem().isHidden():
            self.tree.setCurrentItem(None)
        self._update_count(shown, total)
        self._update_buttons()

    def _update_count(self, shown, total):
        """底部那行：有没有在筛选、当前引擎一共多少个音色"""
        snapshot = self._snapshot
        if not total:
            self.count_label.setText(snapshot.note or "")
            return
        if shown != total:
            text = i18n.t("tts.voice.count_filtered", shown=shown, total=total)
        else:
            text = i18n.t("tts.voice.count", count=total)
        note = snapshot.note
        self.count_label.setText(f"{text}　{note}" if note else text)

    def _update_current_label(self):
        """「当前使用」那行：正在用的音色可能不在筛选出来的这几行里"""
        snapshot = self._snapshot
        name = i18n.t("tts.voice.none")
        for voice in snapshot.voices:
            if voice.voice_id == snapshot.current_id:
                name = voice_label(voice, show_gender=True)
                break
        self.current_label.setText(i18n.t("tts.voice.current", name=name))

    def _restore_selection(self, voice_id=""):
        """选中项：优先沿用用户刚选的，其次当前正在用的音色"""
        wanted = voice_id or self._snapshot.current_id
        item = self._item_for(wanted)
        if item is None:
            item = self._first_visible()
        self.tree.setCurrentItem(item)
        if item is not None:
            self.tree.scrollToItem(item)

    def _item_for(self, voice_id):
        if not voice_id:
            return None
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, VOICE_ROLE) == voice_id:
                return item
        return None

    def _first_visible(self):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if not item.isHidden() and item.data(0, VOICE_ROLE) is not None:
                return item
        return None

    # ------------------------------------------------------------------ 交互

    def selected_voice_id(self):
        """列表里选中的音色 id（没选中返回空串）"""
        item = self.tree.currentItem()
        if item is None:
            return ""
        return item.data(0, VOICE_ROLE) or ""

    def _update_buttons(self):
        """按引擎刷新按钮：在线才有「刷新」，离线才有「音色管理」"""
        snapshot = self._snapshot
        self.refresh_button.setVisible(snapshot.engine == EDGE_ENGINE)
        self.manage_button.setVisible(snapshot.engine == NEURAL_ENGINE)
        self.use_button.setEnabled(bool(self.selected_voice_id()))

    def _use_selected(self):
        voice_id = self.selected_voice_id()
        if voice_id:
            self.voice_selected.emit(voice_id)

    def _on_engine_changed(self, index):
        """用户换了朗读引擎：交给主窗口去停朗读 / 重建队列"""
        if self._filling or index < 0:
            return
        engine = self.engine_combo.itemData(index)
        if engine and engine != self._snapshot.engine:
            self.engine_selected.emit(engine)

    # ------------------------------------------------------------------ 收尾

    def shutdown(self):
        """主窗口退出时收尾（这个窗口自己不占线程 / 文件）"""
        self.close()


__all__ = ["TtsVoiceDialog", "VoiceSnapshot", "voice_display_name"]
