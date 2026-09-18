"""「继续阅读」面板。

把 ``saves/`` 下的所有阅读记录汇总成一张表：按最后阅读时间倒序排列，
双击（或右键 / 「继续阅读」按钮）即可接着上次的位置读。附带：

* 按书名、作者、文件名过滤的搜索框；
* 删除单条记录（只删阅读进度，不动书籍文件）；
* 一键清理失效记录（记录指向的文件已经被移动或删除）；
* 右键菜单：继续阅读 / 打开所在文件夹 / 复制完整路径 / 删除记录。

界面文案全部走 ``enm.i18n``（语言键前缀 ``continue.`` / ``common.``），
对话框在构造时读取当前语言，因此切换语言后下次打开就是新文案。
"""

import subprocess
import sys
import time
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import i18n
from ..constants import PROJECT_NAME
from ..logger import logger

# 表格列（序号常量不随语言变化，标题文字随时从语言文件取）
(
    COLUMN_TITLE,
    COLUMN_AUTHOR,
    COLUMN_PROGRESS,
    COLUMN_CHAPTERS,
    COLUMN_DURATION,
    COLUMN_LAST,
    COLUMN_FILE,
) = range(7)

COLUMN_COUNT = 7


def column_titles():
    """表头文案（跟随当前语言）"""
    return [i18n.t(key) for key in (
        "continue.column_title",
        "continue.column_author",
        "continue.column_progress",
        "continue.column_chapters",
        "continue.column_duration",
        "continue.column_last_read",
        "continue.column_file",
    )]


# 失效记录的置灰颜色
MISSING_COLOR = QColor(150, 150, 150)

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def dash():
    """空占位符（中文为破折号，英文为短横线）"""
    return i18n.t("common.dash", default="—")


def format_duration(seconds):
    """把秒数格式化成「1 小时 23 分」这类可读文本（随时按当前语言生成）"""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return dash()

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return i18n.t("continue.duration_hours", default="{hours} 小时 {minutes} 分",
                      hours=hours, minutes=minutes)
    if minutes:
        return i18n.t("continue.duration_minutes", default="{minutes} 分 {seconds} 秒",
                      minutes=minutes, seconds=secs)
    return i18n.t("continue.duration_seconds", default="{seconds} 秒", seconds=secs)


def latest_time_text(record):
    """记录的最后阅读时间（缺字段时退回保存时间，都没有则返回占位符）"""
    for field in ("last_opened_at", "saved_at"):
        text = str(record.get(field) or "").strip()
        if text:
            return text

    timestamp = record.get("timestamp")
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        return time.strftime(_TIME_FORMAT, time.localtime(timestamp))
    return dash()


class _RecordItem(QTreeWidgetItem):
    """带排序键的表格项

    直接按显示文本排序会把「1 小时 23 分」和「45 秒」按字典序排乱，
    所以每列额外存一个可比较的排序键（``sort_keys``）。
    """

    def __init__(self, texts, sort_keys, record, record_file, exists):
        super().__init__(list(texts))
        self.sort_keys = list(sort_keys)
        self.record = record
        self.record_file = record_file
        self.exists = exists

    def __lt__(self, other):
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        if not 0 <= column < len(self.sort_keys):
            column = 0
        try:
            return self.sort_keys[column] < other.sort_keys[column]
        except (AttributeError, IndexError, TypeError):
            return super().__lt__(other)


class ContinueReadingDialog(QDialog):
    """汇集所有阅读记录的对话框"""

    def __init__(self, progress_manager, parent=None):
        super().__init__(parent)
        self.progress_manager = progress_manager
        # 用户选定要打开的路径，由主窗口读取
        self.selected_path = ""
        # [(记录文件路径, 记录内容, 文件是否还在)]
        self.records = []

        self.setWindowTitle(i18n.t("dialog.continue_reading", app=PROJECT_NAME))
        self.setModal(True)
        self.resize(900, 520)
        self.setup_ui()
        self.reload()

    # ---------------- 界面 ----------------

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(i18n.t("continue.search_placeholder"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.search_edit)

        self.record_tree = QTreeWidget()
        self.record_tree.setColumnCount(COLUMN_COUNT)
        self.record_tree.setHeaderLabels(column_titles())
        self.record_tree.setRootIsDecorated(False)
        self.record_tree.setAlternatingRowColors(True)
        self.record_tree.setUniformRowHeights(True)
        self.record_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.record_tree.setSortingEnabled(True)
        self.record_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.record_tree.customContextMenuRequested.connect(self.show_context_menu)
        self.record_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.record_tree.itemSelectionChanged.connect(self.update_buttons)

        header = self.record_tree.header()
        header.setSectionResizeMode(COLUMN_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COLUMN_FILE, QHeaderView.Interactive)
        for column in (
            COLUMN_AUTHOR,
            COLUMN_PROGRESS,
            COLUMN_CHAPTERS,
            COLUMN_DURATION,
            COLUMN_LAST,
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.record_tree, 1)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        button_layout = QHBoxLayout()
        self.open_btn = QPushButton(i18n.t("continue.open"))
        self.open_btn.clicked.connect(self.open_selected)
        self.delete_btn = QPushButton(i18n.t("continue.delete"))
        self.delete_btn.clicked.connect(self.delete_selected)
        self.clean_btn = QPushButton(i18n.t("continue.clean"))
        self.clean_btn.clicked.connect(self.clean_missing)
        self.close_btn = QPushButton(i18n.t("continue.close"))
        self.close_btn.clicked.connect(self.reject)

        button_layout.addWidget(self.open_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addWidget(self.clean_btn)
        button_layout.addStretch(1)
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)

    # ---------------- 数据 ----------------

    def reload(self):
        """重新读取所有阅读记录并刷新列表"""
        self.record_tree.setSortingEnabled(False)
        self.record_tree.clear()
        self.records = []

        for record_file, record in self.progress_manager.iter_records():
            exists = self.record_target_exists(record)
            self.records.append((record_file, record, exists))
            self.record_tree.addTopLevelItem(self.build_item(record, record_file, exists))

        self.record_tree.setSortingEnabled(True)
        self.record_tree.sortByColumn(COLUMN_LAST, Qt.DescendingOrder)
        self.apply_filter(self.search_edit.text())
        self.update_buttons()

    @staticmethod
    def record_target_exists(record):
        """记录指向的文件 / 文件夹是否还在"""
        file_path = record.get("file_path")
        if not file_path:
            return False
        return Path(str(file_path)).exists()

    def build_item(self, record, record_file, exists):
        """把一条记录转成表格行"""
        placeholder = dash()
        novelname = str(record.get("novelname") or record.get("filename")
                        or i18n.t("book.unknown_title"))
        author = str(record.get("author") or placeholder)
        filename = str(record.get("filename") or placeholder)
        if not exists:
            novelname = f"⚠ {novelname}"

        total_chapters = int(record.get("total_chapters") or 0)
        reached = max(int(record.get("max_chapter") or 0), int(record.get("chapter") or 0)) + 1
        if total_chapters > 0:
            percent = min(100.0, reached / total_chapters * 100)
            progress_text = i18n.t("continue.progress", reached=reached,
                                   total=total_chapters, percent=f"{percent:.0f}")
            progress_key = (0, percent)
        elif reached > 1:
            progress_text = i18n.t("continue.progress_chapter", count=reached)
            progress_key = (1, 0.0)
        else:
            progress_text = placeholder
            progress_key = (2, 0.0)

        chapter_count = int(record.get("read_chapter_count") or 0)
        read_seconds = float(record.get("total_read_seconds") or 0)
        last_read = latest_time_text(record)

        texts = (
            novelname,
            author,
            progress_text,
            (i18n.t("continue.chapters_count", count=chapter_count)
             if chapter_count else placeholder),
            format_duration(read_seconds),
            last_read,
            filename,
        )
        sort_keys = (
            novelname,
            author,
            progress_key,
            chapter_count,
            read_seconds,
            last_read,
            filename,
        )

        item = _RecordItem(texts, sort_keys, record, record_file, exists)
        item.setToolTip(COLUMN_TITLE, self.build_tooltip(record, exists))
        if not exists:
            for column in range(COLUMN_COUNT):
                item.setForeground(column, QBrush(MISSING_COLOR))
        return item

    @staticmethod
    def build_tooltip(record, exists):
        """鼠标悬停时的详细信息"""
        placeholder = dash()
        lines = []
        if not exists:
            lines.append(i18n.t("continue.tooltip_missing"))
        rows = (
            ("continue.tooltip_file_path", record.get("file_path") or placeholder),
            ("continue.tooltip_title", record.get("novelname") or placeholder),
            ("continue.tooltip_author", record.get("author") or placeholder),
            ("continue.tooltip_open_count", int(record.get("open_count") or 0)),
            ("continue.tooltip_first_opened", record.get("first_opened_at") or placeholder),
            ("continue.tooltip_last_opened", record.get("last_opened_at") or placeholder),
            ("continue.tooltip_total_duration",
             format_duration(record.get("total_read_seconds"))),
            ("continue.tooltip_read_chapters",
             int(record.get("read_chapter_count") or 0)),
            ("continue.tooltip_record_key",
             f"{record.get('key_type', '?')}:{record.get('md5', '?')}"),
            ("continue.tooltip_saved_at", record.get("saved_at") or placeholder),
        )
        for key, value in rows:
            lines.append(i18n.t("continue.tooltip_line", label=i18n.t(key),
                                value=value))
        return "\n".join(lines)

    # ---------------- 过滤与状态 ----------------

    def apply_filter(self, text):
        """按书名 / 作者 / 文件名过滤列表"""
        keyword = (text or "").strip().lower()
        visible = 0

        for index in range(self.record_tree.topLevelItemCount()):
            item = self.record_tree.topLevelItem(index)
            if not keyword:
                item.setHidden(False)
                visible += 1
                continue

            record = getattr(item, "record", {})
            haystack = " ".join(str(record.get(field) or "") for field in (
                "novelname", "author", "filename", "md5", "file_path",
            )).lower()
            item.setHidden(keyword not in haystack)
            if not item.isHidden():
                visible += 1

        self.update_summary(visible)

    def update_summary(self, visible=None):
        """底部汇总：记录数、累计时长、失效数量"""
        total = len(self.records)
        missing = sum(1 for _, _, exists in self.records if not exists)
        seconds = sum(float(record.get("total_read_seconds") or 0) for _, record, _ in self.records)

        parts = []
        if visible is not None and visible != total:
            parts.append(i18n.t("continue.summary_filtered", count=visible))
        parts.append(i18n.t("continue.summary_total", count=total))
        parts.append(i18n.t("continue.summary_duration",
                            duration=format_duration(seconds)))
        if missing:
            parts.append(i18n.t("continue.summary_missing", count=missing))
        self.summary_label.setText(" · ".join(parts))

    def update_buttons(self):
        """没有选中记录 / 没有失效记录时禁用对应按钮"""
        item = self.current_item()
        has_missing = any(not exists for _, _, exists in self.records)
        self.open_btn.setEnabled(item is not None)
        self.delete_btn.setEnabled(item is not None)
        self.clean_btn.setEnabled(has_missing)

    def current_item(self):
        item = self.record_tree.currentItem()
        return item if isinstance(item, _RecordItem) else None

    # ---------------- 操作 ----------------

    def on_item_double_clicked(self, item, column):
        self.open_item(item if isinstance(item, _RecordItem) else None)

    def open_selected(self):
        self.open_item(self.current_item())

    def open_item(self, item):
        """校验选中的记录并把它交给主窗口打开"""
        if item is None:
            return

        file_path = item.record.get("file_path")
        if not file_path:
            QMessageBox.warning(self, i18n.t("continue.err_no_path_title"),
                                i18n.t("continue.err_no_path"))
            return

        path = Path(str(file_path))
        if not path.exists():
            QMessageBox.warning(
                self,
                i18n.t("continue.err_missing_title"),
                i18n.t("continue.err_missing", path=path),
            )
            return

        self.selected_path = str(path)
        self.accept()

    def delete_selected(self):
        """删除单条阅读记录（不动书籍文件）"""
        item = self.current_item()
        if item is None:
            return

        name = (item.record.get("novelname") or item.record.get("filename")
                or i18n.t("continue.delete_fallback_name"))
        answer = QMessageBox.question(
            self,
            i18n.t("continue.delete_title"),
            i18n.t("continue.delete_body", name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if self.progress_manager.delete_record_file(item.record_file):
            logger.log(f"删除阅读记录: {item.record.get('file_path') or item.record_file}")
            self.reload()

    def clean_missing(self):
        """批量清理指向的文件已不存在的记录"""
        missing = [(f, r) for f, r, exists in self.records if not exists]
        if not missing:
            QMessageBox.information(self, i18n.t("continue.clean_title"),
                                    i18n.t("continue.clean_none"))
            return

        answer = QMessageBox.question(
            self,
            i18n.t("continue.clean_title"),
            i18n.t("continue.clean_confirm", count=len(missing)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        removed = 0
        for record_file, _record in missing:
            if self.progress_manager.delete_record_file(record_file):
                removed += 1

        logger.log(f"清理失效阅读记录: {removed} 条")
        self.reload()
        QMessageBox.information(self, i18n.t("continue.clean_title"),
                                i18n.t("continue.clean_done", count=removed))

    def show_context_menu(self, position):
        """右键菜单：继续阅读 / 打开所在文件夹 / 复制完整路径 / 删除记录"""
        item = self.record_tree.itemAt(position)
        if not isinstance(item, _RecordItem):
            return
        self.record_tree.setCurrentItem(item)

        menu = QMenu(self)
        open_action = menu.addAction(i18n.t("continue.menu_open"))
        folder_action = menu.addAction(i18n.t("continue.menu_folder"))
        copy_action = menu.addAction(i18n.t("continue.menu_copy"))
        menu.addSeparator()
        delete_action = menu.addAction(i18n.t("continue.menu_delete"))

        action = menu.exec_(self.record_tree.viewport().mapToGlobal(position))
        if action is open_action:
            self.open_item(item)
        elif action is folder_action:
            self.open_containing_folder(item.record)
        elif action is copy_action:
            QApplication.clipboard().setText(str(item.record.get("file_path") or ""))
        elif action is delete_action:
            self.delete_selected()

    @staticmethod
    def open_containing_folder(record):
        """在系统文件管理器里定位记录指向的文件"""
        file_path = record.get("file_path")
        if not file_path:
            return

        path = Path(str(file_path))
        try:
            if sys.platform.startswith("win"):
                if path.exists():
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    subprocess.Popen(["explorer", str(path.parent)])
            elif sys.platform == "darwin":
                if path.exists():
                    subprocess.Popen(["open", "-R", str(path)])
                else:
                    subprocess.Popen(["open", str(path.parent)])
            else:
                target = path if path.is_dir() else path.parent
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            logger.log(f"打开所在文件夹失败: {e}", "WARN")
