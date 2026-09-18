"""主题编辑器与主题预览控件。

原来的「主题生成器」只给了 3 个颜色按钮和一块纯色预览，而 ``highlight`` /
``border`` 直接拿强调色顶上，于是按钮悬停色和常态色一模一样、边框整圈涂成
强调色——生出来的主题自己就不好看。现在：

* 5 个颜色都能单独调（色块按钮 + 可直接填写 ``#RRGGBB`` 的输入框）
* 内置配色预设，一键铺满 5 个颜色再微调
* 预览区是真的控件（按钮 / 输入框 / 进度条 / 列表 / 下拉框），
  和主窗口用同一份样式表，所见即所得
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QColorDialog, QComboBox, QDialog,
                             QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QProgressBar,
                             QPushButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from .. import i18n
from ..managers.theme import (COLOR_FIELDS, DEFAULT_THEME, NAME_FIELD,
                              THEME_PRESETS, normalise_color,
                              sanitize_theme_name)
from .theme_qss import build_style_sheet

#: 颜色字段 → 语言键（界面标签与校验错误信息共用）
COLOR_LABEL_KEYS = {
    "background": "theme_editor.background_label",
    "foreground": "theme_editor.foreground_label",
    "accent": "theme_editor.accent_label",
    "highlight": "theme_editor.highlight_label",
    "border": "theme_editor.border_label",
}

#: 颜色输入框填错时的提示边框（不跟着主题走，红得看得见就行）
_INVALID_INPUT_STYLE = "border: 1px solid #D13438;"


def color_field_label(field):
    """颜色字段的本地化名称"""
    return i18n.t(COLOR_LABEL_KEYS.get(field, field), default=field)


def describe_theme_errors(errors):
    """把 ThemeManager 返回的校验错误码翻成当前语言的文本（一行一条）"""
    lines = []
    for code, params in errors:
        kwargs = dict(params)
        if "field" in kwargs:
            kwargs["field"] = color_field_label(kwargs["field"])
        lines.append(i18n.t(code, default=code, **kwargs))
    return "\n".join(line for line in lines if line)


def theme_display_label(manager, name, is_builtin=None):
    """主题在界面上的显示名：内置主题走语言键，自定义主题用 JSON 里的 name"""
    if name is None:
        return ""
    if is_builtin is None:
        is_builtin = manager.is_builtin(name)
    if is_builtin:
        key = manager.name_keys.get(name)
        if key:
            return i18n.t(key, default=manager.display_name(name))
    return manager.display_name(name)


class ColorButton(QPushButton):
    """色块按钮：直接把当前颜色画出来，上面写十六进制值"""

    def __init__(self, color="#FFFFFF", parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(110)
        self._color = color
        self.refresh()

    def color(self):
        """当前颜色"""
        return self._color

    def set_color(self, color):
        """设置颜色"""
        self._color = color
        self.refresh()

    def refresh(self):
        """刷新色块与文字"""
        # 色块上要写十六进制值，得按亮度挑字色，否则浅色块上的白字看不见
        text_color = "#000000" if QColor(self._color).lightness() > 140 else "#FFFFFF"
        self.setText(self._color.upper())
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; color: {text_color};"
            f" border: 1px solid #808080; border-radius: 4px; padding: 5px 10px; }}")


class ThemePreviewWidget(QWidget):
    """用真实控件展示一套配色：按钮、输入框、进度条、列表、下拉框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("theme_preview")

        self.text_label = QLabel()
        self.text_label.setWordWrap(True)

        self.button = QPushButton()
        self.disabled_button = QPushButton()
        self.disabled_button.setEnabled(False)
        self.input = QLineEdit()

        self.progress = QProgressBar()
        self.progress.setValue(45)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(92)

        self.combo = QComboBox()

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        button_row.addWidget(self.button)
        button_row.addWidget(self.disabled_button)
        button_row.addWidget(self.combo, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.text_label)
        layout.addWidget(self.input)
        layout.addWidget(self.progress)
        layout.addLayout(button_row)
        layout.addWidget(self.tree, 1)

        self.retranslate()

    def set_theme(self, theme, font_size=None):
        """按主题刷新自身样式（和主窗口用同一份样式表）"""
        # 容器自己的底色要单独写一条：QMainWindow/QDialog 的规则管不到它
        extra = (f"#theme_preview {{ background-color: {theme['background']};"
                 f" border: 1px solid {theme['border']}; border-radius: 4px; }}")
        self.setStyleSheet(build_style_sheet(theme, font_size=font_size or 12,
                                             extra_rules=extra))

    def retranslate(self):
        """刷新预览里的示例文案"""
        self.text_label.setText(i18n.t("theme_editor.preview_text"))
        self.button.setText(i18n.t("theme_editor.preview_button"))
        self.disabled_button.setText(i18n.t("theme_editor.preview_button_disabled"))
        self.input.setText(i18n.t("theme_editor.preview_input"))
        self.combo.clear()
        self.combo.addItem(i18n.t("theme_editor.preview_text"))

        self.tree.clear()
        for index in (1, 2, 3):
            self.tree.addTopLevelItem(
                QTreeWidgetItem([i18n.t("theme_editor.preview_item", index=index)]))
        self.tree.setCurrentItem(self.tree.topLevelItem(0))


class ThemeEditorDialog(QDialog):
    """新建 / 修改一套自定义主题。

    * ``theme`` 不为空 = 改这套配色（``name`` 是它原来的主题键）
    * ``ui_theme`` = 对话框外壳自己用哪套配色，一般是当前正在用的主题
    """

    def __init__(self, manager, theme=None, name="", parent=None, ui_theme=None):
        super().__init__(parent)
        self.manager = manager
        self._original_key = name if theme is not None else None
        self._loading = False

        source = theme or manager.get_theme(DEFAULT_THEME)
        self.colors = {field: source[field] for field in COLOR_FIELDS}
        self._default_name = name or manager.next_available_name(
            i18n.t("theme_editor.name_default"))

        if ui_theme:
            self.setStyleSheet(build_style_sheet(ui_theme))

        self.setWindowTitle(i18n.t("theme_editor.title_edit" if theme is not None
                                   else "theme_editor.title_new"))
        self.setModal(True)
        self.setMinimumSize(760, 480)
        self.setup_ui()

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        """搭界面"""
        self.name_edit = QLineEdit(self._default_name)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(i18n.t("theme_editor.preset_custom"))
        for preset_name, _ in THEME_PRESETS:
            self.preset_combo.addItem(preset_name)
        self.preset_combo.currentIndexChanged.connect(self.apply_preset)

        form = QFormLayout()
        form.setSpacing(8)
        form.addRow(i18n.t("theme_editor.name_label"), self.name_edit)
        form.addRow(i18n.t("theme_editor.preset_label"), self.preset_combo)

        # 5 个颜色：色块按钮 + 可手填的十六进制输入框
        self.color_buttons = {}
        self.color_edits = {}
        for field in COLOR_FIELDS:
            button = ColorButton(self.colors[field])
            button.setToolTip(i18n.t("theme_editor.choose_color_tooltip"))
            button.clicked.connect(lambda _checked, key=field: self.choose_color(key))

            edit = QLineEdit(self.colors[field].upper())
            edit.setFixedWidth(96)
            edit.textEdited.connect(lambda _text, key=field: self.on_color_text(key))
            edit.editingFinished.connect(lambda key=field: self.normalise_color_text(key))

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            row_layout.addWidget(button)
            row_layout.addWidget(edit)
            row_layout.addStretch(1)

            self.color_buttons[field] = button
            self.color_edits[field] = edit
            form.addRow(i18n.t(COLOR_LABEL_KEYS[field]), row)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(form)
        left_layout.addWidget(QLabel(i18n.t("theme_editor.live_hint")))
        left_layout.addStretch(1)

        # 实时预览
        self.preview = ThemePreviewWidget()
        preview_box = QVBoxLayout()
        preview_box.setSpacing(6)
        preview_box.addWidget(QLabel(i18n.t("theme_editor.preview_title")))
        preview_box.addWidget(self.preview, 1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(left)
        body.addLayout(preview_box, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText(i18n.t("common.ok"))
        button_box.button(QDialogButtonBox.Cancel).setText(i18n.t("common.cancel"))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addLayout(body, 1)
        layout.addWidget(button_box)

        self.preview.set_theme(self.colors)
        self.sync_preset_combo()

    # -------------------------------------------------------------- 颜色交互

    def choose_color(self, field):
        """弹系统取色器选颜色"""
        color = QColorDialog.getColor(
            QColor(self.colors[field]), self,
            i18n.t("theme_editor.choose_color", field=color_field_label(field)))
        if color.isValid():
            self.set_color(field, color.name())
            self.sync_preset_combo()

    def set_color(self, field, color):
        """设置某个字段的颜色并刷新界面"""
        self.colors[field] = color
        self.color_buttons[field].set_color(color)
        self.color_edits[field].setStyleSheet("")
        self.color_edits[field].setText(color.upper())
        self.refresh_preview()

    def on_color_text(self, field):
        """手填十六进制时的即时反馈：合法就立刻换色，不合法就先标红"""
        value = normalise_color(self.color_edits[field].text())
        if value is None:
            self.color_edits[field].setStyleSheet(_INVALID_INPUT_STYLE)
            return
        self.color_edits[field].setStyleSheet("")
        self.colors[field] = value
        self.color_buttons[field].set_color(value)
        self.refresh_preview()

    def normalise_color_text(self, field):
        """填完一个颜色后统一成小写规范值；填错就先留着，确定时再报错"""
        value = normalise_color(self.color_edits[field].text())
        if value is None:
            return
        self.set_color(field, value)
        self.sync_preset_combo()

    def apply_preset(self, index):
        """套用配色预设"""
        if self._loading or index <= 0:
            return
        preset = THEME_PRESETS[index - 1][1]
        for field in COLOR_FIELDS:
            self.colors[field] = preset[field]
            self.color_buttons[field].set_color(preset[field])
            self.color_edits[field].setStyleSheet("")
            self.color_edits[field].setText(preset[field].upper())
        self.refresh_preview()

    def sync_preset_combo(self):
        """当前配色和某个预设完全一致时，把下拉框选到那一项"""
        self._loading = True
        index = 0
        for position, (_, preset) in enumerate(THEME_PRESETS, start=1):
            if all(self.colors[field] == preset[field] for field in COLOR_FIELDS):
                index = position
                break
        self.preset_combo.setCurrentIndex(index)
        self._loading = False

    def refresh_preview(self):
        """预览区跟着颜色走（有填错的颜色就先不动预览）"""
        if all(normalise_color(self.color_edits[field].text())
               for field in COLOR_FIELDS):
            self.preview.set_theme(self.colors)

    # ------------------------------------------------------------------ 结果

    def collect_theme(self):
        """收集结果，返回 ``(主题字典, 错误列表)``"""
        errors = []
        theme = {}
        for field in COLOR_FIELDS:
            raw = self.color_edits[field].text().strip()
            color = normalise_color(raw)
            if color is None:
                self.color_edits[field].setStyleSheet(_INVALID_INPUT_STYLE)
                errors.append(("theme_error.invalid_color",
                               {"field": field, "value": raw}))
                continue
            theme[field] = color

        if errors:
            return None, errors
        theme[NAME_FIELD] = self.name_edit.text().strip()
        return theme, []

    def accept(self):
        """确定前把名称与颜色校验一遍，说清楚到底是哪儿不对"""
        theme, errors = self.collect_theme()
        if theme is None:
            QMessageBox.warning(self, i18n.t("common.warning"),
                                describe_theme_errors(errors))
            return

        key = sanitize_theme_name(theme[NAME_FIELD])
        if not key:
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("theme_editor.name_required"))
            self.name_edit.setFocus()
            return
        if self.manager.is_builtin(key):
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("theme_error.reserved_name", name=key))
            self.name_edit.setFocus()
            return
        if key != self._original_key and self.manager.is_custom(key):
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("theme_error.name_exists", name=key))
            self.name_edit.setFocus()
            return

        super().accept()

    def get_theme_data(self):
        """校验通过时返回主题数据，否则 ``None``"""
        theme, _ = self.collect_theme()
        return theme

