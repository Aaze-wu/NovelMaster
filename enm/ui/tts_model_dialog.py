# -*- coding: utf-8 -*-
"""「朗读 → 音色管理」对话框：下载 / 删除离线神经音色的模型。

安装包里**不带**模型（Kokoro 解压后 200 MB，带上安装包就没法看了），
所以第一次想用离线神经音色时得先把模型下下来。这个对话框负责：

* 列出所有可选的模型（体积、是否已下载、许可、一句话说明）；
* 下载 / 取消 / 删除，带进度条；
* 显示模型目录与已占用空间（用户想手动放模型进去也照这里找路径）。

下载跑在 :class:`~enm.managers.tts_models.ModelDownloadWorker` 的后台线程里，
所以对话框是**非模态**的 —— 下载要几分钟，不该把整个阅读器锁住；关掉这个
窗口下载也照常继续（worker 归主窗口所有，见 ``worker`` 参数）。

没装 ``sherpa-onnx`` 时对话框也能打开，只是会顶上多一行提示：模型能下，
但要装上 sherpa-onnx 才能真的出声。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                             QProgressBar, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout)

from .. import i18n
from ..managers import tts_models
from ..managers.tts_models import ModelDownloadWorker
from .theme_qss import build_style_sheet
from .titlebar import apply_to_widget


def format_mb(value):
    """把 MB 数写成界面上看的那几个字（``13.4 MB``）"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.1f} MB"


class TtsModelDialog(QDialog):
    """离线音色模型的下载 / 删除窗口。"""

    #: 装了或删了模型 —— 主窗口据此刷新神经后端的音色列表
    installed_changed = pyqtSignal()

    def __init__(self, parent=None, ui_theme=None, titlebar_theme=None,
                 worker=None):
        super().__init__(parent)

        self._titlebar_theme = titlebar_theme
        #: 下载线程：主窗口传进来时可以跨窗口复用（约定：谁建谁管）
        self._worker = worker if worker is not None else ModelDownloadWorker(self)
        self._own_worker = worker is None
        self._busy_id = ""

        if ui_theme:
            self.setStyleSheet(build_style_sheet(ui_theme))

        self.setWindowTitle(i18n.t("tts.model.dialog_title",
                                   default="音色管理"))
        # 下载要好几分钟，别把阅读器锁住
        self.setModal(False)
        self.setMinimumSize(560, 430)
        self.setup_ui()
        self.refresh()

        self._worker.progress.connect(self._on_progress)
        self._worker.status.connect(self._on_status)
        self._worker.finished.connect(self._on_finished)

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)
        self.refresh()

    def closeEvent(self, event):
        """关窗户不等于停下载：隐藏起来，让模型继续下"""
        if self._busy_id:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.hint_label = QLabel(i18n.t(
            "tts.model.hint",
            default="离线音色不联网也能用，但模型要先下下来（第一次用需要联网）。"))
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            i18n.t("tts.model.col_name", default="模型"),
            i18n.t("tts.model.col_size", default="下载体积"),
            i18n.t("tts.model.col_status", default="状态"),
        ])
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 150)
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.tree, 1)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.usage_label = QLabel("")
        layout.addWidget(self.usage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.download_button = QPushButton(i18n.t("tts.model.download",
                                                  default="下载"))
        self.download_button.clicked.connect(self.download_selected)
        self.cancel_button = QPushButton(i18n.t("tts.model.cancel",
                                                default="取消下载"))
        self.cancel_button.clicked.connect(self.cancel_download)
        self.remove_button = QPushButton(i18n.t("tts.model.remove",
                                                default="删除"))
        self.remove_button.clicked.connect(self.remove_selected)
        self.close_button = QPushButton(i18n.t("tts.model.close", default="关闭"))
        self.close_button.clicked.connect(self.close)
        for button in (self.download_button, self.cancel_button,
                       self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ 列表

    def refresh(self):
        """重建模型列表（保留当前选中的那行）"""
        selected = self._selected_model_id()
        self.tree.clear()
        for info in tts_models.MODELS:
            installed = tts_models.is_installed(info.model_id)
            if installed:
                status = i18n.t("tts.model.status_installed",
                                default="已下载（占 {size}）",
                                size=format_mb(
                                    tts_models.installed_size_mb(info.model_id)))
            else:
                status = i18n.t("tts.model.status_missing", default="未下载")
            item = QTreeWidgetItem([info.name, format_mb(info.size_mb), status])
            item.setData(0, Qt.UserRole, info.model_id)
            item.setToolTip(0, self._describe(info))
            item.setToolTip(2, item.text(2))
            self.tree.addTopLevelItem(item)
            if info.model_id == selected:
                self.tree.setCurrentItem(item)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._update_usage()
        self._update_buttons()

    def _describe(self, info):
        """模型的一行说明（名称 / 许可 / 说话人数 / 补充说明）"""
        parts = [info.note,
                 i18n.t("tts.model.license", default="许可：{license}",
                        license=info.license)]
        if len(info.voices) > 1:
            parts.append(i18n.t("tts.model.voice_count",
                                default="{count} 个音色",
                                count=len(info.voices)))
        return "\n".join(text for text in parts if text)

    def _update_usage(self):
        """底部那两行：模型目录 + 已占用空间"""
        directory = str(tts_models.models_dir())
        total = sum(tts_models.installed_size_mb(info.model_id)
                    for info in tts_models.MODELS)
        self.usage_label.setText(
            i18n.t("tts.model.usage", default="已占用 {size}　目录：{path}",
                   size=format_mb(total), path=directory))
        self.usage_label.setToolTip(directory)

    def _selected_model_id(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else ""

    def _item_for(self, model_id):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, Qt.UserRole) == model_id:
                return item
        return None

    def _update_buttons(self):
        """按「选中哪个模型 + 正在下哪个」刷新按钮可用性"""
        model_id = self._selected_model_id()
        busy = bool(self._busy_id)
        self.download_button.setEnabled(
            bool(model_id) and not busy
            and not tts_models.is_installed(model_id))
        self.cancel_button.setEnabled(busy and model_id == self._busy_id)
        self.remove_button.setEnabled(
            bool(model_id) and not busy and tts_models.is_installed(model_id))

        info = tts_models.model_info(model_id)
        if info is None:
            self.detail_label.setText("")
            return
        self.detail_label.setText(self._describe(info))

    # ------------------------------------------------------------------ 下载

    def download_selected(self):
        """下载选中的模型"""
        self._start(self._selected_model_id())

    def _start(self, model_id):
        info = tts_models.model_info(model_id)
        if info is None:
            return False
        if tts_models.is_installed(model_id):
            self.status_label.setText(i18n.t("tts.model.already",
                                             default="这个模型已经下好了。"))
            return False
        if self._worker.busy() and self._worker.busy() != model_id:
            self.status_label.setText(i18n.t(
                "tts.model.busy", default="正在下载另一个模型，等它下完再试。"))
            return False
        if not self._worker.submit(model_id):
            self.status_label.setText(i18n.t(
                "tts.model.busy", default="正在下载另一个模型，等它下完再试。"))
            return False
        self._busy_id = model_id
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(i18n.t("tts.model.progress_download",
                                           default="下载中 {done} / {total}",
                                           done="0.0 MB", total="?"))
        self.progress_bar.show()
        self.status_label.setText(i18n.t("tts.model.started",
                                         default="开始下载「{name}」…",
                                         name=info.name))
        self._update_buttons()
        return True

    def prompt_download(self, model_id, parent=None):
        """主窗口用：确认之后开始下某个模型（并把这个窗口带到前面）"""
        info = tts_models.model_info(model_id)
        if info is None or tts_models.is_installed(model_id):
            return False
        answer = QMessageBox.question(
            parent or self,
            i18n.t("tts.model.dialog_title", default="音色管理"),
            i18n.t("tts.model.ask_download",
                   default="「{name}」还没下载，现在下载吗？（约 {size}，"
                           "支持断点续传）",
                   name=info.name, size=format_mb(info.size_mb)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return False
        self.show()
        self.raise_()
        self.activateWindow()
        item = self._item_for(model_id)
        if item is not None:
            self.tree.setCurrentItem(item)
        return self._start(model_id)

    def cancel_download(self):
        """取消当前下载（``.part`` 留着，下次接着下）"""
        if self._worker.cancel(self._busy_id or None):
            self.status_label.setText(i18n.t("tts.model.cancelling",
                                             default="正在取消…"))

    def remove_selected(self):
        """删除已下载的模型（要确认，删完得重新下）"""
        model_id = self._selected_model_id()
        info = tts_models.model_info(model_id)
        if info is None or not tts_models.is_installed(model_id):
            return
        answer = QMessageBox.question(
            self, i18n.t("tts.model.dialog_title", default="音色管理"),
            i18n.t("tts.model.ask_remove",
                   default="删掉「{name}」之后要重新下载（{size}）。确定删除吗？",
                   name=info.name,
                   size=format_mb(tts_models.installed_size_mb(model_id))),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        ok = tts_models.delete_model(model_id)
        self.status_label.setText(
            i18n.t("tts.model.removed", default="已删除「{name}」。",
                   name=info.name) if ok else
            i18n.t("tts.model.remove_failed",
                   default="删除失败，可能有文件正被占用，稍后再试。"))
        self.refresh()
        if ok:
            self.installed_changed.emit()

    def _on_double_clicked(self, item, _column):
        model_id = item.data(0, Qt.UserRole)
        if tts_models.is_installed(model_id):
            self.remove_selected()
        else:
            self._start(model_id)

    # ------------------------------------------------------------------ 进度

    def _on_progress(self, model_id, phase, done, total):
        if model_id != self._busy_id:
            self._busy_id = model_id
        self.progress_bar.show()
        if phase == "unpack":
            self.progress_bar.setRange(0, 0)          # 解压没进度，走来回条
            self.progress_bar.setFormat(i18n.t("tts.model.unpacking",
                                               default="正在解压…"))
            return
        self.progress_bar.setRange(0, 1000)
        ratio = (float(done) / float(total)) if total else 0.0
        self.progress_bar.setValue(max(0, min(1000, int(ratio * 1000))))
        self.progress_bar.setFormat(i18n.t(
            "tts.model.progress_download", default="下载中 {done} / {total}",
            done=format_mb(done / (1024.0 * 1024.0)),
            total=format_mb(total / (1024.0 * 1024.0)) if total else "?"))

    def _on_status(self, model_id, text):
        if model_id != self._busy_id:
            self._busy_id = model_id
        self.status_label.setText(text)

    def _on_finished(self, model_id, ok, message):
        if model_id == self._busy_id:
            self._busy_id = ""
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 1000)
        self.status_label.setText(message or "")
        self.refresh()
        if ok:
            self.installed_changed.emit()

    # ------------------------------------------------------------------ 收尾

    def worker(self):
        """下载线程（主窗口挂在朗读条上显示进度用）"""
        return self._worker

    def shutdown(self):
        """主窗口退出时收线程（自己建的才需要收，别人传进来的由人家收）"""
        if self._own_worker:
            self._worker.shutdown()


__all__ = ["TtsModelDialog", "format_mb"]
