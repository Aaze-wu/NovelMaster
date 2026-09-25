# -*- coding: utf-8 -*-
"""阅读区底部的朗读条。

常驻在正文下方（不弹窗、不遮挡正文），一眼能看到当前进度：

    [朗读] [停止] | [上一句] [下一句] | 语速[正常] 音量[————] |
    ☑自动读下一章 ☑跟随高亮 定时[不定时▾]      剩余 12:34 第 3/128 句 [▾]

控件只用 QPushButton / QComboBox / QCheckBox / QLabel / QSlider —— 这几种
:mod:`enm.ui.theme_qss` 里都已经有配色规则，所以朗读条在深浅主题下都不会
出现「原生白底」那块补丁。**语速**用下拉框而不是拖动条：档位（很慢 / 慢 /
正常 / 快 / 很快）比 -1.0~1.0 的数字更好懂，而且两端档位还容易选准。
**音量**没有「档位」可言，用滑块才顺手。**定时停止**也是一条下拉框
（不定时 / 15~90 分钟 / 自定义 / 读完本章停）。

右边那个 ``[▾]`` 是收起按钮，收起后只剩一行状态（``朗读中 · 第 3/128 句``
与倒计时），给「正文想多看两行、但朗读不能停」的场合让出纵向空间。
收起状态记在配置里。

⚠️ 朗读条自己**不掌握定时**：下拉框只把用户的选择报出去（
:attr:`timer_changed` / :attr:`custom_timer_requested`），真正计时的是主窗口
里的 ``QTimer``；剩余时间再回灌给 :meth:`set_timer_remaining` 显示。
「自定义…」也一样 —— 本类弹不了输入框（它是纯界面），只发信号让主窗口去问。

控件文案由本类自己维护（跟主窗口的 ``bind_text`` 是同一套「登记 → 重刷」
思路），主窗口切换语言时调一次 :meth:`TtsBar.retranslate` 即可。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
                             QPushButton, QSlider, QWidget)

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


#: 音量滑块用整数百分比（QSlider 只认整数），对外一律换算成 0.0~1.0
VOLUME_MAX = 100


def quantize_volume(value):
    """把配置里的音量夹到 0.0~1.0（坏值当默认的 1.0）"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(1.0, value))


#: 定时停止：数值就是「多少分钟后停」，0 = 不定时，负数留给特殊项
TIMER_OFF = 0
#: 「自定义…」占位项：点了要弹输入框，本身不是一个生效值
TIMER_CUSTOM = -1
#: 「读完本章就停」：不按时间算，只在章末拦一次
TIMER_CHAPTER = -2

#: 固定档位（分钟）。15 分钟的粒度对睡前听书刚好，再细没必要
TIMER_PRESETS = (15, 30, 45, 60, 90)

#: 「自定义…」输入框的范围与默认值
TIMER_MIN_MINUTES = 1
TIMER_MAX_MINUTES = 600
TIMER_DEFAULT_MINUTES = 20


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
    #: 音量变化（0.0 ~ 1.0）
    volume_changed = pyqtSignal(float)
    #: 是否自动朗读下一章
    auto_next_changed = pyqtSignal(bool)
    #: 朗读时是否高亮并滚动到当前句
    highlight_changed = pyqtSignal(bool)
    #: 朗读条是否被收起（用户点收起按钮时发出，程序里回灌状态不发）
    collapsed_changed = pyqtSignal(bool)
    #: 定时选择变化：0 = 不定时 / 正数 = 分钟数 / :data:`TIMER_CHAPTER`
    timer_changed = pyqtSignal(int)
    #: 用户选了「自定义…」那一项，请主窗口去问一个分钟数（问完用
    #: :meth:`set_timer` 回灌结果；取消就不要回灌，下拉框会自己还原）
    custom_timer_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_bindings = []
        self._state = "idle"
        self._index = -1
        self._total = 0
        self._collapsed = False
        #: 当前生效的定时档位（0 / 分钟数 / TIMER_CHAPTER）
        self._timer = TIMER_OFF
        #: 自定义过的那几分钟：留着好让下拉框里一直有这一项
        self._timer_custom = 0
        #: 倒计时显示用：剩余秒数与「是不是读完本章停」
        #: （记下来才能切语言时重渲染，不用让主窗口再报一次）
        self._timer_seconds = 0
        self._timer_chapter = False
        #: 临时提示（如「正在下载音色模型 45%」，v1.3.8）：非空时顶掉状态文字
        self._notice = ""

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

        self.volume_label = QLabel()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, VOLUME_MAX)
        self.volume_slider.setValue(VOLUME_MAX)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self._on_volume_value)

        self.auto_next_check = QCheckBox()
        self.auto_next_check.toggled.connect(self.auto_next_changed.emit)

        self.highlight_check = QCheckBox()
        self.highlight_check.toggled.connect(self.highlight_changed.emit)

        self.timer_label = QLabel()
        self.timer_combo = QComboBox()
        for value in self._timer_values():
            self.timer_combo.addItem(self._timer_text(value), value)
        self.timer_combo.currentIndexChanged.connect(self._on_timer_index)

        # 倒计时：只在有定时时出现（收起朗读条也留着它，不然定时就成了
        # 「设了看不见」，用户会以为没生效）
        self.timer_status_label = QLabel()
        self.timer_status_label.hide()

        self.status_label = QLabel()
        self.status_label.setMinimumWidth(120)

        # 收起/展开。用纯文本箭头而不是图标：主题里没放按钮图标素材，
        # 字符最少、任何字体都有，也不用管深浅主题换图
        self.collapse_btn = QPushButton()
        self.collapse_btn.setFixedWidth(28)
        self.collapse_btn.clicked.connect(self._on_collapse_clicked)

        layout.addWidget(self.play_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.previous_btn)
        layout.addWidget(self.next_btn)
        layout.addWidget(self.rate_label)
        layout.addWidget(self.rate_combo)
        layout.addWidget(self.volume_label)
        layout.addWidget(self.volume_slider)
        layout.addWidget(self.auto_next_check)
        layout.addWidget(self.highlight_check)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.timer_combo)
        layout.addStretch()
        layout.addWidget(self.timer_status_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.collapse_btn)

        #: 收起时要藏起来的控件（顺序即布局顺序，方便对照）
        self._collapsible = (self.play_btn, self.stop_btn, self.previous_btn,
                             self.next_btn, self.rate_label, self.rate_combo,
                             self.volume_label, self.volume_slider,
                             self.auto_next_check, self.highlight_check,
                             self.timer_label, self.timer_combo)

        # 动态文案（随播放状态变化的那几个）由状态刷新负责，这里只登记静态的
        self._bind(self.stop_btn, "tts.stop")
        self._bind(self.previous_btn, "tts.previous_sentence")
        self._bind(self.next_btn, "tts.next_sentence")
        self._bind(self.rate_label, "tts.rate.label")
        self._bind(self.volume_label, "tts.volume.label")
        self._bind(self.auto_next_check, "tts.auto_next_chapter")
        self._bind(self.highlight_check, "tts.highlight")
        self._bind(self.timer_label, "tts.timer.label")
        self._refresh_play_text()
        self._refresh_rate_items()
        self._refresh_timer_items()
        self._refresh_status()
        self._refresh_collapse_button()

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

    def _timer_values(self):
        """下拉框里该有哪些项（固定档位 + 自定义过的分钟数 + 两个特殊项）"""
        values = [TIMER_OFF]
        values.extend(TIMER_PRESETS)
        custom = self._timer_custom
        if custom > 0 and custom not in TIMER_PRESETS:
            values.append(custom)
        values.append(TIMER_CUSTOM)
        values.append(TIMER_CHAPTER)
        return values

    def _timer_text(self, value):
        """某一项的显示文案"""
        if value == TIMER_OFF:
            return i18n.t("tts.timer.none")
        if value == TIMER_CUSTOM:
            return i18n.t("tts.timer.custom")
        if value == TIMER_CHAPTER:
            return i18n.t("tts.timer.chapter")
        return i18n.t("tts.timer.minutes", minutes=value)

    def _refresh_timer_items(self):
        """按当前语言重写定时下拉框的全部文案（保持选中项不变）"""
        blocked = self.timer_combo.blockSignals(True)
        try:
            for row in range(self.timer_combo.count()):
                self.timer_combo.setItemText(
                    row, self._timer_text(self.timer_combo.itemData(row)))
        finally:
            self.timer_combo.blockSignals(blocked)
        self._select_timer(self._timer)

    def _select_timer(self, value):
        """把下拉框拨到某个档位（找不到就落回「不定时」）"""
        row = self.timer_combo.findData(value)
        if row < 0:
            row = self.timer_combo.findData(TIMER_OFF)
        if row < 0 or row == self.timer_combo.currentIndex():
            return
        blocked = self.timer_combo.blockSignals(True)
        self.timer_combo.setCurrentIndex(row)
        self.timer_combo.blockSignals(blocked)

    def _refresh_status(self):
        """状态栏文案：``朗读中 · 第 3/128 句``（有临时提示就先显示提示）"""
        if self._notice:
            self.status_label.setText(self._notice)
            return
        state_key = {"playing": "tts.state.playing",
                     "paused": "tts.state.paused"}.get(self._state, "tts.state.idle")
        state_text = i18n.t(state_key)
        if self._total > 0 and self._index >= 0:
            position = i18n.t("tts.state.position", index=self._index + 1,
                              total=self._total)
            self.status_label.setText(f"{state_text} · {position}")
        else:
            self.status_label.setText(state_text)

    def _refresh_collapse_button(self):
        """收起按钮：箭头指向「点下去会发生什么」+ 悬停说明

        用实心小三角而不是 ``⌃`` / ``⌄`` 那对细箭头 —— 后者在 12px 字号下
        几乎分不出朝向（实测两种字形都在字体里，纯粹是辨识度问题）。
        """
        # 展开着 → 三角朝下（点一下收起来）；收起了 → 三角朝上（点一下放下来）
        key = "tts.expand" if self._collapsed else "tts.collapse"
        self.collapse_btn.setText("▴" if self._collapsed else "▾")
        self.collapse_btn.setToolTip(i18n.t(key))

    def retranslate(self):
        """切换语言后刷新全部文案"""
        for widget, key, setter in self._text_bindings:
            getattr(widget, setter)(i18n.t(key))
        self._refresh_rate_items()
        self._refresh_play_text()
        self._refresh_timer_items()
        self._refresh_timer_status()
        self._refresh_status()
        self._refresh_collapse_button()

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

    def set_notice(self, text):
        """显示一句临时提示（传空串恢复寻常的状态文字）

        下载音色模型要几分钟，用户在正文里等着的时候得看得见进度，
        所以借朗读条的这一行；提示优先于「朗读中 · 第 x/y 句」。
        """
        self._notice = str(text or "")
        self._refresh_status()

    def set_rate(self, rate):
        """同步语速下拉框（不触发 :attr:`rate_changed`）"""
        row = RATE_PRESETS.index(nearest_rate(rate))
        if row == self.rate_combo.currentIndex():
            return
        blocked = self.rate_combo.blockSignals(True)
        self.rate_combo.setCurrentIndex(row)
        self.rate_combo.blockSignals(blocked)

    def set_volume(self, volume):
        """同步音量滑块（不触发 :attr:`volume_changed`）"""
        value = int(round(quantize_volume(volume) * VOLUME_MAX))
        if value == self.volume_slider.value():
            return
        blocked = self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(value)
        self.volume_slider.blockSignals(blocked)

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

    def set_timer(self, value):
        """同步定时档位（不触发 :attr:`timer_changed`）

        传进来的分钟数如果是个新的自定义值，会顺手加进下拉框里，这样
        「自定义 20 分钟」之后菜单里就一直留着「20 分钟」这一项，下次
        直接选它，不用再输一遍。
        """
        value = int(value)
        if value > 0 and value not in TIMER_PRESETS:
            self._timer_custom = value
            # 自定义档插在固定档之后，并按分钟数升序排（不然用过几个自定义
            # 值以后下拉框里是「用过什么顺序」而不是「多长」）
            row = self.timer_combo.count() - 2      # 默认插在「自定义…」前面
            for index in range(self.timer_combo.count()):
                data = self.timer_combo.itemData(index)
                if (isinstance(data, int) and data > 0
                        and data not in TIMER_PRESETS and data > value):
                    row = index
                    break
            blocked = self.timer_combo.blockSignals(True)
            try:
                self.timer_combo.insertItem(row, self._timer_text(value), value)
            finally:
                self.timer_combo.blockSignals(blocked)
        self._timer = value
        self._select_timer(value)

    def timer_value(self):
        """当前生效的定时档位（0 / 分钟数 / :data:`TIMER_CHAPTER`）"""
        return self._timer

    def set_timer_remaining(self, seconds, chapter=False):
        """倒计时显示：``chapter`` 为真显示「读完本章停」，``seconds<=0`` 隐藏"""
        self._timer_seconds = max(0, int(seconds))
        self._timer_chapter = bool(chapter)
        self._refresh_timer_status()

    def _refresh_timer_status(self):
        """按记下来的剩余时间重画倒计时（切语言时也走这里）"""
        if self._timer_chapter:
            text = i18n.t("tts.timer.chapter")
            self.timer_status_label.setText(text)
            self.timer_status_label.setToolTip(text)
            self.timer_status_label.show()
            return
        if self._timer_seconds <= 0:
            self.timer_status_label.clear()
            self.timer_status_label.hide()
            return
        seconds = self._timer_seconds
        self.timer_status_label.setText(
            i18n.t("tts.timer.remaining",
                   time=f"{seconds // 60:02d}:{seconds % 60:02d}"))
        self.timer_status_label.show()

    def set_collapsed(self, collapsed):
        """同步收起状态（不触发 :attr:`collapsed_changed`）"""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_collapsed()
        self._refresh_collapse_button()

    def is_collapsed(self):
        """朗读条当前是否处于收起状态"""
        return self._collapsed

    def set_available(self, available):
        """没有可用语音引擎时整条置灰"""
        for widget in (self.play_btn, self.stop_btn, self.previous_btn,
                       self.next_btn, self.rate_label, self.rate_combo,
                       self.volume_label, self.volume_slider,
                       self.auto_next_check, self.highlight_check,
                       self.timer_label, self.timer_combo):
            widget.setEnabled(bool(available))

    def shortcut_widgets(self):
        """``快捷键动作 id → 控件``，供主窗口挂快捷键提示"""
        return {
            "tts.play_pause": self.play_btn,
            "tts.stop": self.stop_btn,
            # 注意这里要用动作 id（tts.prev_sentence），不是按钮文案的键
            # （tts.previous_sentence），写错了提示里会直接显示动作 id
            "tts.prev_sentence": self.previous_btn,
            "tts.next_sentence": self.next_btn,
        }

    # ---------------- 内部 ----------------

    def _apply_collapsed(self):
        """收起时藏掉整排控件，只留状态与收起按钮（那些控件照旧工作）"""
        for widget in self._collapsible:
            widget.setVisible(not self._collapsed)

    def _on_collapse_clicked(self):
        self._collapsed = not self._collapsed
        self._apply_collapsed()
        self._refresh_collapse_button()
        self.collapsed_changed.emit(self._collapsed)

    def _on_rate_index(self, row):
        if 0 <= row < len(RATE_PRESETS):
            self.rate_changed.emit(RATE_PRESETS[row])

    def _on_volume_value(self, value):
        self.volume_changed.emit(value / VOLUME_MAX)

    def _on_timer_index(self, row):
        """下拉框选中项变化：特殊项各有处理，其余就是「多少分钟」"""
        value = self.timer_combo.itemData(row)
        if value == TIMER_CUSTOM:
            # 「自定义…」不是一个生效值：先把下拉框拨回当前档位，
            # 再请主窗口去问分钟数（问完会 set_timer 回灌）
            self._select_timer(self._timer)
            self.custom_timer_requested.emit()
            return
        self._timer = value
        self.timer_changed.emit(int(value))


__all__ = ["RATE_KEYS", "RATE_PRESETS", "TIMER_CHAPTER", "TIMER_CUSTOM",
           "TIMER_DEFAULT_MINUTES", "TIMER_MAX_MINUTES", "TIMER_MIN_MINUTES",
           "TIMER_OFF", "TIMER_PRESETS", "TtsBar", "VOLUME_MAX",
           "nearest_rate", "quantize_volume"]
