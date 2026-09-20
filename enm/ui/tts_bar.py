# -*- coding: utf-8 -*-
"""阅读区底部的朗读条。

常驻在正文下方（不弹窗、不遮挡正文），一眼能看到当前进度：

    [朗读] [停止] | [上一句] [下一句] | 语速[正常] | ☑自动读下一章 ☑跟随高亮    第 3/128 句

控件只用 QPushButton / QComboBox / QCheckBox / QLabel —— 这几种
:mod:`enm.ui.theme_qss` 里都已经有配色规则，所以朗读条在深浅主题下都不会
出现「原生白底」那块补丁（**QSlider 没有样式表规则**，所以语速用下拉框而不是
拖动条，顺带也让「很慢 / 慢 / 正常 / 快 / 很快」比 -1.0~1.0 更好懂）。

控件文案由本类自己维护（跟主窗口的 ``bind_text`` 是同一套「登记 → 重刷」
思路），主窗口切换语言时调一次 :meth:`TtsBar.retranslate` 即可。
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
                             QPushButton, QWidget)

from .. import i18n

#: 语速档位：Qt/SAPI 的取值范围是 -1.0（最慢）~ 1.0（最快），0 为系统默认
RATE_PRESETS = (-1.0, -0.5, 0.0, 0.5, 1.0)

#: 档位 → 语言键
RATE_KEYS = {
    -1.0: "tts.rate.very_slow",
    -0.5: "tts.rate.slow",
    0.0: "tts.rate.normal",
    0.5: "tts.rate.fast",
    1.0: "tts.rate.very_fast",
}


def nearest_rate(value):
    """把配置里的语速吸附到最近的档位"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    return min(RATE_PRESETS, key=lambda preset: abs(preset - value))


class TtsBar(QWidget):
    """朗读条（纯界面，不含任何朗读逻辑）。

    朗读逻辑在 :class:`enm.managers.tts.SpeechQueue` 里，主窗口把这里的信号
    接到队列上、再把队列的状态回灌给 :meth:`set_state`，两边互不认识。
    """

    #: 播放 / 暂停按钮被按下（按钮文案由状态决定，所以交给主窗口判断该做什么）
    play_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    previous_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    #: 语速档位变化（-1.0 ~ 1.0）
    rate_changed = pyqtSignal(float)
    #: 是否自动朗读下一章
    auto_next_changed = pyqtSignal(bool)
    #: 朗读时是否高亮并滚动到当前句
    highlight_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_bindings = []
        self._state = "idle"
        self._index = -1
        self._total = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        self.play_btn = QPushButton()
        self.play_btn.setMinimumWidth(72)
        self.play_btn.clicked.connect(self.play_clicked.emit)

        self.stop_btn = QPushButton()
        self.stop_btn.clicked.connect(self.stop_clicked.emit)

        self.previous_btn = QPushButton()
        self.previous_btn.clicked.connect(self.previous_clicked.emit)

        self.next_btn = QPushButton()
        self.next_btn.clicked.connect(self.next_clicked.emit)

        self.rate_label = QLabel()
        self.rate_combo = QComboBox()
        for preset in RATE_PRESETS:
            self.rate_combo.addItem("", preset)
        self.rate_combo.currentIndexChanged.connect(self._on_rate_index)

        self.auto_next_check = QCheckBox()
        self.auto_next_check.toggled.connect(self.auto_next_changed.emit)

        self.highlight_check = QCheckBox()
        self.highlight_check.toggled.connect(self.highlight_changed.emit)

        self.status_label = QLabel()
        self.status_label.setMinimumWidth(120)

        layout.addWidget(self.play_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.previous_btn)
        layout.addWidget(self.next_btn)
        layout.addWidget(self.rate_label)
        layout.addWidget(self.rate_combo)
        layout.addWidget(self.auto_next_check)
        layout.addWidget(self.highlight_check)
        layout.addStretch()
        layout.addWidget(self.status_label)

        # 动态文案（随播放状态变化的那几个）由状态刷新负责，这里只登记静态的
        self._bind(self.stop_btn, "tts.stop")
        self._bind(self.previous_btn, "tts.previous_sentence")
        self._bind(self.next_btn, "tts.next_sentence")
        self._bind(self.rate_label, "tts.rate.label")
        self._bind(self.auto_next_check, "tts.auto_next_chapter")
        self._bind(self.highlight_check, "tts.highlight")
        self._refresh_play_text()
        self._refresh_rate_items()
        self._refresh_status()

    # ---------------- 文案 ----------------

    def _bind(self, widget, key, setter="setText"):
        binding = (widget, key, setter)
        self._text_bindings.append(binding)
        getattr(widget, setter)(i18n.t(key))
        return widget

    def _play_key(self):
        """播放按钮文案随播放状态变化"""
        if self._state == "playing":
            return "tts.pause"
        if self._state == "paused":
            return "tts.resume"
        return "tts.play"

    def _refresh_play_text(self):
        self.play_btn.setText(i18n.t(self._play_key()))

    def _refresh_rate_items(self):
        """刷新语速下拉框的显示文本（保持当前档位不变）"""
        current = self.rate_combo.currentIndex()
        blocked = self.rate_combo.blockSignals(True)
        try:
            for row, preset in enumerate(RATE_PRESETS):
                self.rate_combo.setItemText(row, i18n.t(RATE_KEYS[preset]))
        finally:
            self.rate_combo.blockSignals(blocked)
        if current >= 0:
            self.rate_combo.setCurrentIndex(current)

    def _refresh_status(self):
        """状态栏文案：``朗读中 · 第 3/128 句``"""
        state_key = {"playing": "tts.state.playing",
                     "paused": "tts.state.paused"}.get(self._state, "tts.state.idle")
        state_text = i18n.t(state_key)
        if self._total > 0 and self._index >= 0:
            position = i18n.t("tts.state.position", index=self._index + 1,
                              total=self._total)
            self.status_label.setText(f"{state_text} · {position}")
        else:
            self.status_label.setText(state_text)

    def retranslate(self):
        """切换语言后刷新全部文案"""
        for widget, key, setter in self._text_bindings:
            getattr(widget, setter)(i18n.t(key))
        self._refresh_rate_items()
        self._refresh_play_text()
        self._refresh_status()

    # ---------------- 状态同步 ----------------

    def set_state(self, state):
        """朗读状态：``idle`` / ``playing`` / ``paused``"""
        if state not in ("idle", "playing", "paused"):
            state = "idle"
        if state == self._state:
            return
        self._state = state
        self._refresh_play_text()
        self._refresh_status()

    def set_position(self, index, total):
        """当前句位置（``index`` 从 0 开始，-1 表示没有句子）"""
        self._index = int(index)
        self._total = int(total)
        self._refresh_status()

    def set_rate(self, rate):
        """同步语速下拉框（不触发 :attr:`rate_changed`）"""
        row = RATE_PRESETS.index(nearest_rate(rate))
        if row == self.rate_combo.currentIndex():
            return
        blocked = self.rate_combo.blockSignals(True)
        self.rate_combo.setCurrentIndex(row)
        self.rate_combo.blockSignals(blocked)

    def set_auto_next(self, enabled):
        """同步「自动读下一章」勾选（不触发信号）"""
        blocked = self.auto_next_check.blockSignals(True)
        self.auto_next_check.setChecked(bool(enabled))
        self.auto_next_check.blockSignals(blocked)

    def set_highlight(self, enabled):
        """同步「跟随高亮」勾选（不触发信号）"""
        blocked = self.highlight_check.blockSignals(True)
        self.highlight_check.setChecked(bool(enabled))
        self.highlight_check.blockSignals(blocked)

    def set_available(self, available):
        """没有可用语音引擎时整条置灰"""
        for widget in (self.play_btn, self.stop_btn, self.previous_btn,
                       self.next_btn, self.rate_label, self.rate_combo,
                       self.auto_next_check, self.highlight_check):
            widget.setEnabled(bool(available))

    def shortcut_widgets(self):
        """``快捷键动作 id → 控件``，供主窗口挂快捷键提示"""
        return {
            "tts.play_pause": self.play_btn,
            "tts.stop": self.stop_btn,
            "tts.previous_sentence": self.previous_btn,
            "tts.next_sentence": self.next_btn,
        }

    # ---------------- 内部 ----------------

    def _on_rate_index(self, row):
        if 0 <= row < len(RATE_PRESETS):
            self.rate_changed.emit(RATE_PRESETS[row])


__all__ = ["RATE_KEYS", "RATE_PRESETS", "TtsBar", "nearest_rate"]
