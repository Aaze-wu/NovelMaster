"""系统托盘图标（v1.3.9）。

朗读相关的那几项**复用主窗口里已经建好的动作对象**（一个 QAction 可以同时挂在
多个菜单上）：「开始 / 暂停 / 继续朗读」这种随状态变文案的项在托盘里也跟着变，
不必在这里再抄一遍状态判断，快捷键提示也天然一致。

托盘自己的菜单项只有三样：显示 / 隐藏主窗口、退出程序，以及「朗读控制」那组的
分隔布局。文案走 ``main_window.bind_text``，切语言时主窗口会一并刷新。
"""

from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon

from .. import i18n
from ..constants import PROJECT_NAME

#: 气泡提示（首次藏到托盘）停留时长
NOTICE_TIMEOUT_MS = 8000

#: 托盘菜单里复用的主窗口动作（按顺序摆）
SPEECH_ACTION_IDS = ("tts.play_pause", "tts.stop", "tts.prev_sentence",
                     "tts.next_sentence")


class TrayIcon:
    """托盘图标。

    不是 QObject 派生（不需要信号），生命周期由主窗口管：``show()`` /
    ``hide()`` / ``shutdown()``。
    """

    def __init__(self, window):
        self._window = window
        self._tray = QSystemTrayIcon(window.windowIcon())
        self._menu = QMenu()

        # 显示 / 隐藏主窗口（文案随窗口可见性变，用可调用键交给 bind_text）
        self._toggle_action = window.make_action(self._toggle_key,
                                                 self.toggle_window)
        self._menu.addAction(self._toggle_action)

        self._menu.addSeparator()

        # 朗读控制：直接用主窗口那几个动作
        for action_id in SPEECH_ACTION_IDS:
            action = window.action(action_id)
            if action is not None:
                self._menu.addAction(action)

        self._menu.addSeparator()

        voice_action = getattr(window, "speech_voice_action", None)
        if voice_action is not None:
            self._menu.addAction(voice_action)

        shortcut_action = window.action("view.shortcut_config")
        if shortcut_action is not None:
            self._menu.addAction(shortcut_action)

        self._menu.addSeparator()

        self._quit_action = QAction(self._menu)
        self._quit_action.triggered.connect(window.quit_from_tray)
        self._menu.addAction(self._quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self.refresh()

    # ---------------- 显隐 ----------------

    @staticmethod
    def available():
        """系统有没有托盘（没有就别建，免得留个看不见的图标）"""
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def is_visible(self):
        return self._tray.isVisible()

    def shutdown(self):
        """收摊：摘掉菜单再销毁（菜单是自己 new 的，得自己收）"""
        try:
            self._tray.setContextMenu(None)
            self._tray.hide()
        except Exception:  # noqa: BLE001
            pass
        menu, self._menu = self._menu, None
        if menu is not None:
            menu.deleteLater()

    # ---------------- 交互 ----------------

    def notify(self, title, body):
        """气泡提示（点一下就消失，也可以等它自己走）"""
        try:
            self._tray.showMessage(title, body, QSystemTrayIcon.Information,
                                   NOTICE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 - 个别系统托盘不支持气泡
            pass

    def refresh(self):
        """刷新托盘提示与「显示 / 隐藏」「退出」等文案（切语言、状态变化时调）"""
        self._toggle_action.setText(i18n.t(self._toggle_key()))
        self._quit_action.setText(i18n.t("tray.quit"))
        self._tray.setToolTip(self._tooltip_text())

    def _toggle_key(self):
        """「显示主窗口」还是「隐藏主窗口」"""
        return ("tray.toggle_hide" if self._window.isVisible()
                else "tray.toggle_show")

    def _tooltip_text(self):
        """托盘提示：应用名 + 朗读状态（开着书的话再补一行书名）"""
        state = self._window.speech_state()
        state_key = {"playing": "tts.state.playing",
                     "paused": "tts.state.paused"}.get(state, "tts.state.idle")
        text = i18n.t("tray.tooltip", default="{app} · {state}",
                      app=PROJECT_NAME, state=i18n.t(state_key))
        try:
            # 用媒体面板那份（同名同源，且没开书时不会吐出 "None"）
            title, _chapter = self._window.media_panel_track()
        except Exception:  # noqa: BLE001
            title = ""
        if title:
            text = "{}\n{}".format(text, title)
        return text

    def toggle_window(self):
        """显示 / 隐藏主窗口，并把新状态反映到菜单文案上"""
        window = self._window
        if window.isVisible() and not window.isMinimized():
            window.hide()
        else:
            window.showNormal()
            window.raise_()
            window.activateWindow()
        self.refresh()

    def _on_activated(self, reason):
        """双击托盘图标：显示 / 隐藏主窗口（单击留给系统）"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_window()
        elif reason == QSystemTrayIcon.Context:
            self.refresh()
