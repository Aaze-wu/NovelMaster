# -*- coding: utf-8 -*-
"""「发现同一本书的其它版本」确认对话框。

打开书籍时，如果书名 + 作者认出一份已有的阅读记录，但**章节标题指纹对不上**
（记录太老没存指纹，或者这本确实被改写过），就不再自动合并，而是先问一句，
免得把两本不相干的书悄悄并到一起：

* 表格里并排列出「当前文件」与「已有记录」的关键信息（文件名 / 章节数 /
  阅读位置 / 已读章节 / 累计时长 / 最近阅读），用户自己判断是不是同一本；
* 「共用阅读进度」把两份记录并成一份（阅读位置取较新的那份，时长与打开次数
  累加，已读章节取并集）；
* 「保持独立」什么都不做，这份文件继续用自己那份记录；
* 勾上「以后不再询问」后，这一对文件再遇到就沿用这次的选择
  （选择记在配置的 ``progress_share_ignored`` 里），不会再弹窗。

界面文案全部走 ``enm.i18n``（语言键前缀 ``merge.``）。
"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout,
                             QLabel, QPushButton, QVBoxLayout, QWidget)

from .. import i18n
from .continue_dialog import format_duration, latest_time_text
from .titlebar import apply_to_widget

#: 表格每一行：(语言键, 取值函数)，取值函数拿记录字典给出展示文本
_ROWS = (
    ("merge.row_filename", lambda record: record.get("filename")),
    ("merge.row_chapters", lambda record: (_int(record.get("total_chapters")) or None)),
    ("merge.row_position", lambda record: _position_text(record)),
    ("merge.row_read_chapters", lambda record: (
        i18n.t("continue.chapters_count", count=_int(record.get("read_chapter_count")))
        if _int(record.get("read_chapter_count")) else None)),
    ("merge.row_duration", lambda record: (
        format_duration(record.get("total_read_seconds"))
        if float(record.get("total_read_seconds") or 0) > 0 else None)),
    ("merge.row_last", lambda record: latest_time_text(record)),
)


def _int(value):
    """安全转整数（脏数据按 0 处理）"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _position_text(record):
    """阅读位置文本：第 reached/total 章（没有总数时只显示章号）"""
    reached = max(_int(record.get("max_chapter")), _int(record.get("chapter"))) + 1
    total = _int(record.get("total_chapters"))
    if total > 0:
        return i18n.t("merge.position", reached=min(reached, total), total=total)
    if reached > 1:
        return i18n.t("merge.position_only", reached=reached)
    return ""


class BookMergeDialog(QDialog):
    """同书不同版本的合并确认对话框"""

    def __init__(self, current, candidates, parent=None, titlebar_theme=None,
                 weak=False):
        super().__init__(parent)
        #: 当前打开的文件（记录字典形式，键与阅读记录一致）
        self.current = dict(current or {})
        #: 认出来的其它版本：``[(记录文件路径, 记录字典)]``
        self.candidates = list(candidates or [])
        #: 用户是否选择共用进度（点「保持独立」或直接关掉窗口时为 False）
        self.share = False
        #: 用户是否勾了「以后不再询问」
        self.dont_ask = False
        #: 身份只按书名认出来的（章节标题指纹没用）——提示语要说清楚
        self.weak = bool(weak)
        #: 本对话框自己的标题栏用哪套配色（showEvent 里才会真正套上去）
        self._titlebar_theme = titlebar_theme

        self.setWindowTitle(i18n.t("merge.title", app=i18n.t("app.name")))
        self.setModal(True)
        self.setup_ui()
        self.fit_to_content()

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    # ---------------- 界面 ----------------

    def setup_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(i18n.t("merge.hint_weak" if self.weak else "merge.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(self.build_table())

        extra = len(self.candidates) - 1
        if extra > 0:
            more = QLabel(i18n.t("merge.more_versions", count=extra))
            more.setWordWrap(True)
            layout.addWidget(more)

        self.dont_ask_box = QCheckBox(i18n.t("merge.dont_ask"))
        layout.addWidget(self.dont_ask_box)

        buttons = QHBoxLayout()
        self.separate_btn = QPushButton(i18n.t("merge.separate"))
        self.separate_btn.clicked.connect(self.choose_separate)
        self.share_btn = QPushButton(i18n.t("merge.share_progress"))
        self.share_btn.clicked.connect(self.choose_share)
        self.share_btn.setDefault(True)
        buttons.addWidget(self.separate_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.share_btn)
        layout.addLayout(buttons)

    def build_table(self):
        """用网格标签列出两份记录的对照信息（标签一定跟着主题走色）"""
        columns = [dict(self.current)]
        columns.extend(record for _record_file, record in self.candidates[:2])

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)

        headers = [i18n.t("merge.column_current"), i18n.t("merge.column_candidate")]
        for offset, record in enumerate(columns):
            if offset == 0:
                text = headers[0]
            else:
                text = headers[1] if offset == 1 else i18n.t(
                    "merge.column_candidate_more", index=offset)
            header = QLabel(text)
            header.setStyleSheet("font-weight: bold;")
            grid.addWidget(header, 0, offset + 1)

        for row, (key, getter) in enumerate(_ROWS, start=1):
            label = QLabel(i18n.t(key))
            grid.addWidget(label, row, 0)
            for offset, record in enumerate(columns):
                value = getter(record)
                grid.addWidget(self.build_value(value), row, offset + 1)

        grid.setColumnStretch(0, 0)
        for offset in range(len(columns)):
            grid.setColumnStretch(offset + 1, 1)
        container = QWidget()
        container.setLayout(grid)
        return container

    @staticmethod
    def build_value(value):
        """单元格里的值（空值统一显示成「—」）"""
        text = str(value) if value not in (None, "") else i18n.t("common.dash")
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setToolTip(text)
        return label

    def fit_to_content(self):
        """按内容算个合适的尺寸（文件名可能很长）"""
        self.setMinimumWidth(520)
        hint = self.sizeHint()
        self.resize(min(880, max(560, hint.width())), max(300, hint.height()))

    # ---------------- 结果 ----------------

    def choose_share(self):
        """共用阅读进度"""
        self.share = True
        self.dont_ask = self.dont_ask_box.isChecked()
        self.accept()

    def choose_separate(self):
        """保持独立（这一次不合并）"""
        self.share = False
        self.dont_ask = self.dont_ask_box.isChecked()
        self.reject()

    def confirmed_record_files(self):
        """用户确认要合并进来的记录文件（未共用时为空列表）"""
        if not self.share:
            return []
        return [Path(record_file) for record_file, _record in self.candidates]


__all__ = ["BookMergeDialog"]
