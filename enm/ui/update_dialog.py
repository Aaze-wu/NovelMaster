# -*- coding: utf-8 -*-
"""「检查更新」对话框：报告新版本、下载安装包、准备退出安装。

一条流程走完四件事，界面按状态切换（见 :meth:`UpdateDialog.set_state`）：

``checking`` → ``available`` → ``downloading`` → ``ready``

外加两个终点 ``latest``（已经最新）与 ``error``（检查失败，可重试）。

两条产品规则写在这里，改之前先想清楚：

* **便携版只引导，不自动下载安装包**。安装程序装出来是 ``Program Files``
  下的另一份，跟便携版并排躺着，用户只会以为更新没生效；所以便携版这一路
  把主按钮换成「前往下载页」，由用户自己去拿 zip。
* **安装版下载完还要用户再确认一次**才会退出程序。退出是不可逆的（正在朗读、
  刚翻到一半的章节都在这儿结束），不能因为「点了下载」就顺带把程序关了。

下载跑在 :class:`~enm.managers.update.UpdateWorker` 的后台线程里，取消后
``.part`` 会留着，下次接着下。

真正「启动安装程序并退出主窗口」由主窗口负责：对话框只把安装包路径记在
:attr:`UpdateDialog.install_path` 里，等 ``exec_()`` 返回后主窗口读它。
放在对话框里做的话，退出时机就落在一个正在被关闭的窗口的回调里，容易踩到
「信号发完窗口已经没了」这类顺序问题。
"""

from pathlib import Path

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                             QProgressBar, QPushButton, QTextBrowser,
                             QVBoxLayout)

from .. import i18n
from ..constants import VERSION
from ..logger import logger
from ..managers import update as update_manager
from .theme_qss import apply_style_sheet
from .titlebar import apply_to_widget

#: 更新说明那一块最多显示多高（像素）；再长也不把对话框撑爆
NOTES_MAX_HEIGHT = 260


def format_size(count):
    """字节数 → 界面上看的字符串（``48.2 MB``）"""
    try:
        value = float(count)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 1024 ** 3:
        return f"{value / 1024 ** 3:.2f} GB"
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value:.0f} B"


def format_speed(kbps):
    """KB/s → 界面上看的字符串（``1.2 MB/s``）"""
    try:
        value = float(kbps)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 1024:
        return f"{value / 1024:.1f} MB/s"
    return f"{value:.0f} KB/s"


class UpdateDialog(QDialog):
    """检查更新 / 下载安装包的窗口。

    ``preloaded`` 是 ``(状态, 结果)``：启动时的自动检查可能已经查过了，
    直接拿它的结论铺开界面，不必再问一次 GitHub（匿名接口每小时只有 60 次）。
    """

    def __init__(self, parent=None, ui_theme=None, titlebar_theme=None,
                 worker=None, preloaded=None):
        super().__init__(parent)

        self._ui_theme = ui_theme
        self._titlebar_theme = titlebar_theme
        #: 后台线程：主窗口传进来时共用（约定：谁建谁管，这里不负责关它）
        self._worker = (worker if worker is not None
                        else update_manager.UpdateWorker(self))
        self._own_worker = worker is None
        #: 检查出来的新版本信息；没查到时是 ``None``
        self.info = None
        #: 下载好的安装包路径（主窗口读完就拿去安装）
        self.install_path = ""
        #: 当前状态
        self._state = ""
        #: 详情 / 提示两行字的后备内容（各个状态自己填）
        self._detail_text = ""
        self._error_text = ""
        #: 用户主动取消过下载（判断结果时别把取消当成下载失败）
        self._cancelled = False
        #: 窗口正在关：之后到达的信号一律忽略
        self._closing = False
        #: 用户在设置里填的下载镜像前缀
        self._mirror = self._read_mirror()

        apply_style_sheet(self, ui_theme)
        self.setWindowTitle(i18n.t("update.title", default="检查更新"))
        self.setMinimumSize(640, 520)
        self.setup_ui()

        self._worker.checked.connect(self._on_checked)
        self._worker.progress.connect(self._on_progress)
        self._worker.status.connect(self._on_status)
        self._worker.downloaded.connect(self._on_downloaded)

        if preloaded is not None:
            self._on_checked(*preloaded)
        else:
            self.start_check()

    # ------------------------------------------------------------------ 主题

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    def apply_ui_theme(self, ui_theme, titlebar_theme=None):
        """换主题：窗口开着的时候也要立刻变（主窗口对非模态窗口调这个方法）"""
        self._ui_theme = ui_theme
        apply_style_sheet(self, ui_theme)
        self._titlebar_theme = titlebar_theme
        apply_to_widget(self, titlebar_theme)

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.title_label = QLabel("")
        font = self.title_label.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.notes_view = QTextBrowser()
        self.notes_view.setOpenExternalLinks(True)
        self.notes_view.setMaximumHeight(NOTES_MAX_HEIGHT)
        self.notes_view.setMinimumHeight(120)
        layout.addWidget(self.notes_view, 1)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        self.page_btn = QPushButton(i18n.t("update.open_page",
                                           default="打开发布页"))
        self.page_btn.clicked.connect(self._open_page)
        buttons.addWidget(self.page_btn)

        buttons.addStretch()

        self.later_btn = QPushButton(i18n.t("update.later", default="稍后"))
        self.later_btn.clicked.connect(self.reject)
        buttons.addWidget(self.later_btn)

        self.primary_btn = QPushButton("")
        self.primary_btn.setDefault(True)
        self.primary_btn.clicked.connect(self._on_primary)
        buttons.addWidget(self.primary_btn)

        layout.addLayout(buttons)

    def set_state(self, state):
        """按状态刷新整块界面（文案、按钮、进度条的可见性都在这儿定）"""
        if self._closing:
            return
        self._state = state
        self.progress_bar.setVisible(state == "downloading")
        self.notes_view.setVisible(state in ("available", "ready"))
        self.page_btn.setVisible(state in ("available", "error") and
                                 not self._is_portable())
        self.later_btn.setVisible(state in ("available", "ready", "error"))

        if state == "checking":
            self.notes_view.clear()
            self.progress_bar.setRange(0, 0)
            self._set_texts(i18n.t("update.checking", default="正在检查更新…"),
                            "", "")
            self._set_primary(i18n.t("update.cancel", default="取消"), True)
            self.later_btn.setVisible(False)
        elif state == "latest":
            self.notes_view.clear()
            self._set_texts(
                i18n.t("update.latest_title", default="已是最新版本"),
                i18n.t("update.latest_detail", version=VERSION,
                       default="当前版本 v{version}，没有更新的正式版本。"),
                "")
            self._set_primary(i18n.t("update.close", default="关闭"), True)
            self.later_btn.setVisible(False)
        elif state == "error":
            self.notes_view.clear()
            self._set_texts(i18n.t("update.error_title", default="检查更新失败"),
                            self._error_text, "")
            self._set_primary(i18n.t("update.retry", default="重试"), True)
        elif state == "available":
            self._show_available()
        elif state == "downloading":
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self._set_texts(
                i18n.t("update.downloading_title", default="正在下载安装包…"),
                self._detail_text, "")
            self._set_primary(i18n.t("update.cancel", default="取消"), True)
        elif state == "ready":
            self._set_texts(
                i18n.t("update.ready_title",
                       default="安装包已就绪，可以安装了"),
                self._detail_text,
                i18n.t("update.ready_hint",
                       default="点「立即安装并退出」后，NovelMaster 会关闭并"
                               "启动安装程序；安装向导会保留你的设置与阅读"
                               "记录。"))
            self._set_primary(i18n.t("update.install_now",
                                     default="立即安装并退出"), True)

    def _show_available(self):
        """「发现新版本」那一屏（安装版与便携版的措辞不同）"""
        info = self.info
        portable = self._is_portable()
        asset = info.portable if portable else info.installer
        detail = i18n.t("update.available_detail", version=info.version,
                        current=VERSION,
                        default="当前 v{current} → 最新 v{version}")
        if info.published:
            detail += "  ·  " + i18n.t("update.published",
                                       date=info.published[:10],
                                       default="发布于 {date}")
        if asset is not None and asset.size:
            detail += "  ·  " + format_size(asset.size)

        if portable:
            hint = i18n.t(
                "update.portable_hint",
                default="当前是便携版（zip 解压运行），不能自动安装 —— "
                        "装出来会是 Program Files 下的另一份。请到发布页下载"
                        " portable.zip，解压覆盖现在的目录即可。")
            primary = i18n.t("update.go_page", default="前往下载页")
        else:
            hint = i18n.t(
                "update.installer_hint",
                default="点「下载并安装」会把安装包下到这里，下完再问一次"
                        "你是否退出程序。")
            primary = i18n.t("update.download", default="下载并安装")

        self._set_texts(i18n.t("update.available_title", version=info.version,
                               default="发现新版本 v{version}"),
                        detail, hint)
        self.notes_view.setMarkdown(
            info.notes.strip() or
            i18n.t("update.notes_empty", default="（这个版本没有写更新说明。）"))
        self._set_primary(primary, True)

    def _set_texts(self, title, detail, hint):
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.hint_label.setText(hint)

    def _set_primary(self, text, enabled):
        self.primary_btn.setText(text)
        self.primary_btn.setEnabled(enabled)

    # ------------------------------------------------------------------ 状态

    def _is_portable(self):
        """当前跑的是便携版（不能自动安装）"""
        return not update_manager.is_installed_copy()

    def _read_mirror(self):
        """用户在设置里填的下载镜像前缀"""
        parent = self.parent()
        manager = getattr(parent, "config_manager", None)
        if manager is None:
            return ""
        return manager.get("update_mirror", "") or ""

    def start_check(self):
        """发起一次检查（已经有任务在跑就等它的结果）"""
        self._error_text = ""
        self.set_state("checking")
        if not self._worker.submit_check():
            logger.log("已有更新任务在跑，等它的结果", "INFO")

    # ------------------------------------------------------------------ 按钮

    def _on_primary(self):
        state = self._state
        if state == "checking":
            # 检查没法半路掐断（就一次 HTTP），「取消」等于不等了、先关窗口；
            # 结果回来时窗口已经关上，信号会被 _closing 挡掉
            self.reject()
        elif state == "latest":
            self.accept()
        elif state == "error":
            self.start_check()
        elif state == "available":
            if self._is_portable():
                self._open_page()
            else:
                self._begin_download()
        elif state == "downloading":
            self._cancel_download()
        elif state == "ready":
            self._install()

    def _open_page(self):
        """打开发布页（便携版这条路就靠它，浏览器自己会问下不下载）"""
        url = self.info.page if self.info is not None else \
            update_manager.RELEASES_URL
        QDesktopServices.openUrl(QUrl(url))

    def _begin_download(self):
        info = self.info
        if info is None or info.installer is None:
            self._error_text = i18n.t(
                "update.no_installer",
                default="这个版本没有提供安装程序，请到发布页手动下载。")
            self.set_state("error")
            return
        self._cancelled = False
        self._detail_text = info.installer.name
        dest = update_manager.update_dir() / info.installer.name
        self.set_state("downloading")
        if not self._worker.submit_download(info.installer.url, str(dest),
                                            info.installer.size, self._mirror):
            logger.log("已有更新任务在跑，这次的下载请求被忽略", "WARN")

    def _cancel_download(self):
        self._cancelled = True
        self._worker.cancel()

    def _install(self):
        """记下安装包路径并关闭窗口（主窗口接着启动安装程序）"""
        self.accept()

    # ------------------------------------------------------------------ 回调

    def _on_checked(self, state, result):
        if self._closing:
            return
        if state == "update":
            self.info = result
            self.set_state("available")
        elif state == "latest":
            self.info = None
            self.set_state("latest")
        else:
            self._error_text = str(result)
            self.set_state("error")

    def _on_status(self, text):
        """进度之外的说明（例如「换镜像重试」）"""
        if not self._closing and self._state == "downloading":
            self.hint_label.setText(text)

    def _on_progress(self, done, total, speed):
        if self._closing or self._state != "downloading":
            return
        if total:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(done * 100 / total))
            text = i18n.t("update.progress",
                          default="{done} / {total}（{speed}）",
                          done=format_size(done), total=format_size(total),
                          speed=format_speed(speed))
        else:
            self.progress_bar.setRange(0, 0)
            text = i18n.t("update.progress_unknown",
                          default="已下载 {done}（{speed}）",
                          done=format_size(done), speed=format_speed(speed))
        self.detail_label.setText(text)

    def _on_downloaded(self, ok, message, path):
        if self._closing:
            return
        if ok and path:
            self.install_path = path
            self._detail_text = Path(path).name
            self.set_state("ready")
            return
        if self._cancelled:
            # 用户自己按的取消：回到「发现新版本」那一屏，别报错
            self._cancelled = False
            self.set_state("available")
            return
        if self._state == "downloading":
            self._error_text = message
            self.set_state("error")

    # ------------------------------------------------------------------ 关闭

    def closeEvent(self, event):
        """下载中点关闭要问一句：这一下等于取消，前面下的白下了"""
        if self._state == "downloading":
            answer = QMessageBox.question(
                self, i18n.t("update.cancel_download_title", default="取消下载"),
                i18n.t("update.cancel_download_body",
                       default="安装包还没下完，现在关闭会取消下载。确定吗？"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._cancelled = True
            self._worker.cancel()
            self.install_path = ""
        self._closing = True
        if self._own_worker:
            self._worker.shutdown()
        super().closeEvent(event)


__all__ = ["UpdateDialog", "format_size", "format_speed"]
