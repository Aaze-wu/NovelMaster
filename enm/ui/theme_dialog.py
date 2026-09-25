"""主题编辑器与主题预览控件。

早先的「主题生成器」只给了 3 个颜色按钮和一块纯色预览，而 ``highlight`` /
``border`` 直接拿强调色顶上，于是按钮悬停色和常态色一模一样、边框整圈涂成
强调色——生出来的主题自己就不好看。现在：

* **13 个颜色**都能单独调（色块按钮 + 可直接填写 ``#RRGGBB`` 的输入框），
  按「基础 / 窗口 / 状态 / 阅读区」分组；扩展色**留空 = 自动推导**
* 配色预设一键铺满（内置 16 套）
* 「以其它主题为起点」：把任意已有主题当作起点铺进来。**仅是一次性起点**：
  主题文件里不会保存什么继承关系，保存时展开成完整字段，文件自包含
* 「一键派生」：只给一个主色，自动算出整套配色（深浅方向由主色明暗决定）
* 排版（字体 / 字号 / 行距 / 段间距）可以跟着主题一起存，也能随时关掉
* 预览区是真的控件（假标题栏 / 阅读区 / 按钮 / 输入框 / 进度条 / 列表 /
  下拉框），和主窗口用同一份样式表，所见即所得
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                             QDialogButtonBox, QDoubleSpinBox, QFontComboBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QScrollArea, QSpinBox,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from .. import i18n
from ..managers.theme import (COLOR_FIELDS, DEFAULT_PARAGRAPH_SPACING,
                              DEFAULT_THEME, FIELD_GROUPS, FONT_SIZE_RANGE,
                              LINE_SPACING_RANGE, NAME_FIELD,
                              OPTIONAL_COLOR_FIELDS, PARAGRAPH_SPACING_RANGE,
                              REQUIRED_COLOR_FIELDS, THEME_PRESETS, TYPO_FIELDS,
                              derive_missing, derive_palette,
                              normalise_color, normalise_font_family,
                              normalise_font_size, normalise_line_spacing,
                              normalise_paragraph_spacing, preset_colors,
                              sanitize_theme_name)
from .reader_typography import apply_reader_typography
from .theme_qss import build_style_sheet
from .titlebar import apply_to_widget

#: 颜色字段 → 语言键（界面标签与校验错误信息共用）
COLOR_LABEL_KEYS = {
    "background": "theme_editor.background_label",
    "foreground": "theme_editor.foreground_label",
    "accent": "theme_editor.accent_label",
    "highlight": "theme_editor.highlight_label",
    "border": "theme_editor.border_label",
    "titlebar": "theme_editor.titlebar_label",
    "titlebar_text": "theme_editor.titlebar_text_label",
    "selection": "theme_editor.selection_label",
    "disabled": "theme_editor.disabled_label",
    "scrollbar": "theme_editor.scrollbar_label",
    "tooltip": "theme_editor.tooltip_label",
    "sidebar": "theme_editor.sidebar_label",
    "reader": "theme_editor.reader_label",
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
    """用真实控件展示一套配色：标题栏、阅读区、按钮、输入框、进度条、列表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("theme_preview")

        # 原生标题栏没法在这里画，就摆一个假的。颜色和真标题栏同源
        # （titlebar / titlebar_text），调这两个字段时能直接看到效果
        self.titlebar = QWidget()
        self.titlebar.setObjectName("preview_titlebar")
        self.titlebar.setFixedHeight(26)
        self.titlebar_label = QLabel()
        titlebar_row = QHBoxLayout(self.titlebar)
        titlebar_row.setContentsMargins(8, 0, 8, 0)
        titlebar_row.addWidget(self.titlebar_label)
        titlebar_row.addStretch(1)

        self.text_label = QLabel()
        self.text_label.setWordWrap(True)

        # 阅读区：reader 底色 + 主题排版，改完立刻看得出来
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.reader.setFixedHeight(58)

        self.button = QPushButton()
        self.disabled_button = QPushButton()
        self.disabled_button.setEnabled(False)
        self.input = QLineEdit()

        self.progress = QProgressBar()
        self.progress.setValue(45)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(76)

        self.combo = QComboBox()

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        button_row.addWidget(self.button)
        button_row.addWidget(self.disabled_button)
        button_row.addWidget(self.combo, 1)

        body = QVBoxLayout()
        body.setContentsMargins(10, 8, 10, 10)
        body.setSpacing(8)
        body.addWidget(self.text_label)
        body.addWidget(self.reader)
        body.addWidget(self.input)
        body.addWidget(self.progress)
        body.addLayout(button_row)
        body.addWidget(self.tree, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.titlebar)
        layout.addLayout(body, 1)

        self.retranslate()

    def set_theme(self, theme, font_size=None, line_spacing=None,
                  paragraph_spacing=None):
        """按主题刷新自身样式（和主窗口用同一份样式表）

        行距 / 段间距不可能是样式表管得了的（Qt 不支持 ``line-height``），
        所以样式表设完后还得给预览文档套一遍块格式。
        """
        theme = derive_missing(theme)
        # 容器自己的底色、假标题栏都要单独写规则：
        # QMainWindow / QDialog 的规则管不到它们，真标题栏则归 titlebar.py 管。
        # 假标题栏里的 QLabel 用 #preview_titlebar 限定，比通用 QLabel 规则
        # 更具体，所以不会又被刷成前景色。
        extra = (
            f"#theme_preview {{ background-color: {theme['background']};"
            f" border: 1px solid {theme['border']}; border-radius: 4px; }}"
            f"#preview_titlebar {{ background-color: {theme['titlebar']}; }}"
            f"#preview_titlebar QLabel {{ color: {theme['titlebar_text']};"
            f" background: transparent; }}"
        )
        self.setStyleSheet(build_style_sheet(theme, font_size=font_size or 12,
                                             extra_rules=extra))
        apply_reader_typography(self.reader, line_spacing, paragraph_spacing)

    def retranslate(self):
        """刷新预览里的示例文案"""
        self.titlebar_label.setText(i18n.t("theme_editor.preview_titlebar"))
        self.text_label.setText(i18n.t("theme_editor.preview_text"))
        self.reader.setPlainText(i18n.t("theme_editor.preview_reader"))
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
    * ``titlebar_theme`` = 给对话框自己的 Windows 原生标题栏上色用的主题；
      为空就不上色（对应「标题栏跟随主题」开关关闭）
    * ``font_family`` / ``font_size`` / ``line_spacing`` / ``paragraph_spacing``
      = 主题还没带排版信息时编辑器里显示什么默认值（一般传当前阅读设置），
      省得用户从零填

    主题里带没带排版信息，直接决定「排版」那一组的勾选状态：带了就勾上并
    回填，没带就默认不勾——不勾 = 保存时**不写**排版字段，阅读区继续用
    ``config.json`` 里的字号行距。这样「主题」和「全局阅读设置」不会互相打架。
    """

    def __init__(self, manager, theme=None, name="", parent=None, ui_theme=None,
                 titlebar_theme=None, font_family=None, font_size=None,
                 line_spacing=None, paragraph_spacing=None):
        super().__init__(parent)
        self.manager = manager
        self._original_key = name if theme is not None else None
        self._loading = False
        #: 本对话框自己的标题栏用哪套配色（showEvent 里才会真正套上去）
        self._titlebar_theme = titlebar_theme

        source = derive_missing(theme or manager.get_theme(DEFAULT_THEME))
        self.colors = {field: source[field] for field in COLOR_FIELDS}
        self._source_typography = {field: source.get(field) for field in TYPO_FIELDS}
        paragraph = normalise_paragraph_spacing(paragraph_spacing)
        self._fallback_typography = {
            "font_family": normalise_font_family(font_family),
            "font_size": normalise_font_size(font_size) or 16,
            "line_spacing": normalise_line_spacing(line_spacing) or 1.8,
            "paragraph_spacing": (DEFAULT_PARAGRAPH_SPACING
                                  if paragraph is None else paragraph),
        }
        self._default_name = name or manager.next_available_name(
            i18n.t("theme_editor.name_default"))

        if ui_theme:
            self.setStyleSheet(build_style_sheet(ui_theme))

        self.setWindowTitle(i18n.t("theme_editor.title_edit" if theme is not None
                                   else "theme_editor.title_new"))
        self.setModal(True)
        self.setMinimumSize(900, 620)
        self.setup_ui()

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        """搭界面"""
        self.name_edit = QLineEdit(self._default_name)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(i18n.t("theme_editor.preset_custom"))
        for preset_name, _ in THEME_PRESETS:
            self.preset_combo.addItem(preset_name)
        self.preset_combo.currentIndexChanged.connect(self.apply_preset)

        # 「以其它主题为起点」：只是把配色铺进来当起点，不保存继承关系，
        # 保存时展开成完整字段，主题文件始终自包含
        self.base_combo = QComboBox()
        self.base_combo.addItem(i18n.t("theme_editor.base_none"), "")
        for key, is_builtin, _theme in self.manager.entries():
            self.base_combo.addItem(
                theme_display_label(self.manager, key, is_builtin), key)
        self.base_button = QPushButton(i18n.t("theme_editor.base_load"))
        self.base_button.clicked.connect(self.load_base_theme)
        base_row = QWidget()
        base_layout = QHBoxLayout(base_row)
        base_layout.setContentsMargins(0, 0, 0, 0)
        base_layout.setSpacing(6)
        base_layout.addWidget(self.base_combo, 1)
        base_layout.addWidget(self.base_button)

        # 一键派生：只挑一个主色，其余（含深浅方向）全自动
        self.seed_button = ColorButton(self.colors["accent"])
        self.seed_button.setToolTip(i18n.t("theme_editor.derive_tooltip"))
        self.derive_button = QPushButton(i18n.t("theme_editor.derive_button"))
        self.derive_button.clicked.connect(self.derive_from_seed)
        seed_row = QWidget()
        seed_layout = QHBoxLayout(seed_row)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.setSpacing(6)
        seed_layout.addWidget(self.seed_button)
        seed_layout.addWidget(self.derive_button)
        seed_layout.addStretch(1)

        basics = QGroupBox(i18n.t("theme_editor.group_general"))
        basics_form = QFormLayout(basics)
        basics_form.setSpacing(8)
        basics_form.addRow(i18n.t("theme_editor.name_label"), self.name_edit)
        basics_form.addRow(i18n.t("theme_editor.preset_label"), self.preset_combo)
        basics_form.addRow(i18n.t("theme_editor.base_label"), base_row)
        basics_form.addRow(i18n.t("theme_editor.derive_seed_label"), seed_row)

        self.color_buttons = {}
        self.color_edits = {}

        # 预览控件必须在建分组之前就位：_build_typography_group() 收尾会调用
        # _sync_typography_state() → refresh_preview()，那时预览还没建就会炸。
        self.preview = ThemePreviewWidget()

        # 分组来自 managers.theme.FIELD_GROUPS（界面与校验共用同一份定义）。
        # 万一那边漏了字段，这里补一组兜底：少了哪个颜色用户就永远改不了。
        groups = [(key, tuple(fields)) for key, fields in FIELD_GROUPS]
        grouped = {field for _key, fields in groups for field in fields}
        leftover = tuple(field for field in COLOR_FIELDS if field not in grouped)
        if leftover:
            groups.append((None, leftover))

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)
        panel_layout.addWidget(basics)
        for title_key, fields in groups:
            group = QGroupBox(i18n.t(title_key) if title_key else "")
            form = QFormLayout(group)
            form.setSpacing(8)
            for field in fields:
                self._add_color_row(form, field)
            panel_layout.addWidget(group)
        panel_layout.addWidget(self._build_typography_group())
        panel_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(400)

        # 操作反馈（预设 / 起点主题 / 一键派生的结果）就写在这里，
        # 不再为「点了一下按钮」弹一个模态框打断用户
        self.info_hint = QLabel(i18n.t("theme_editor.live_hint"))
        self.info_hint.setWordWrap(True)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(scroll, 1)
        left_layout.addWidget(self.info_hint)

        # 实时预览
        preview_box = QVBoxLayout()
        preview_box.setSpacing(6)
        preview_box.addWidget(QLabel(i18n.t("theme_editor.preview_title")))
        preview_box.addWidget(self.preview, 1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(left, 1)
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

        self.sync_preset_combo()
        self.refresh_preview()

    def _add_color_row(self, form, field):
        """加一行「色块按钮 + 十六进制输入框」"""
        button = ColorButton(self.colors[field])
        button.setToolTip(i18n.t("theme_editor.choose_color_tooltip"))
        button.clicked.connect(lambda _checked, key=field: self.choose_color(key))

        edit = QLineEdit(self.colors[field].upper())
        edit.setFixedWidth(96)
        if field in OPTIONAL_COLOR_FIELDS:
            edit.setPlaceholderText(i18n.t("theme_editor.auto_placeholder"))
            edit.setToolTip(i18n.t("theme_editor.auto_tooltip"))
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

    def _build_typography_group(self):
        """排版组：勾上才跟着主题走，不勾就只存颜色"""
        self.typography_check = QCheckBox(i18n.t("theme_editor.typography_follow"))

        self.font_combo = QFontComboBox()
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(*FONT_SIZE_RANGE)
        self.font_size_spin.setSuffix(" px")
        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(*LINE_SPACING_RANGE)
        self.line_spacing_spin.setSingleStep(0.1)
        self.line_spacing_spin.setDecimals(2)
        self.paragraph_spacing_spin = QSpinBox()
        self.paragraph_spacing_spin.setRange(*PARAGRAPH_SPACING_RANGE)
        self.paragraph_spacing_spin.setSingleStep(2)
        self.paragraph_spacing_spin.setSuffix(" px")

        family = (self._source_typography.get("font_family")
                  or self._fallback_typography["font_family"])
        if family:
            self.font_combo.setCurrentFont(QFont(family))
        self.font_size_spin.setValue(self._source_typography.get("font_size")
                                    or self._fallback_typography["font_size"])
        self.line_spacing_spin.setValue(
            self._source_typography.get("line_spacing")
            or self._fallback_typography["line_spacing"])
        # 段间距合法值含 0，所以不能用 ``or`` 接兑底值
        paragraph = normalise_paragraph_spacing(
            self._source_typography.get("paragraph_spacing"))
        self.paragraph_spacing_spin.setValue(
            self._fallback_typography["paragraph_spacing"]
            if paragraph is None else paragraph)
        self.typography_check.setChecked(
            any(self._source_typography.get(field) is not None
                for field in TYPO_FIELDS))

        hint = QLabel(i18n.t("theme_editor.typography_hint"))
        hint.setWordWrap(True)

        group = QGroupBox(i18n.t("theme_editor.group_typography"))
        form = QFormLayout(group)
        form.setSpacing(8)
        form.addRow(self.typography_check)
        form.addRow(i18n.t("theme_editor.font_family_label"), self.font_combo)
        form.addRow(i18n.t("theme_editor.font_size_label"), self.font_size_spin)
        form.addRow(i18n.t("theme_editor.line_spacing_label"),
                    self.line_spacing_spin)
        form.addRow(i18n.t("theme_editor.paragraph_spacing_label"),
                    self.paragraph_spacing_spin)
        form.addRow(hint)

        self.typography_check.stateChanged.connect(self._sync_typography_state)
        self.font_size_spin.valueChanged.connect(self.refresh_preview)
        self.line_spacing_spin.valueChanged.connect(self.refresh_preview)
        self.paragraph_spacing_spin.valueChanged.connect(self.refresh_preview)
        self.font_combo.currentFontChanged.connect(self.refresh_preview)
        self._sync_typography_state()
        return group

    def _sync_typography_state(self, *_args):
        """勾选框决定四个排版输入能不能用"""
        enabled = self.typography_check.isChecked()
        for widget in (self.font_combo, self.font_size_spin,
                       self.line_spacing_spin, self.paragraph_spacing_spin):
            widget.setEnabled(enabled)
        self.refresh_preview()

    # -------------------------------------------------------------- 颜色交互

    def choose_color(self, field):
        """弹系统取色器选颜色"""
        color = QColorDialog.getColor(
            QColor(self.colors[field]), self,
            i18n.t("theme_editor.choose_color", field=color_field_label(field)))
        if color.isValid():
            self.set_color(field, color.name())
            self.sync_preset_combo()

    def _set_color_field(self, field, color):
        """更新某个颜色字段对应的控件（不刷新预览）"""
        self.colors[field] = color
        self.color_buttons[field].set_color(color)
        self.color_edits[field].setStyleSheet("")
        self.color_edits[field].setText(color.upper())

    def set_color(self, field, color):
        """设置某个字段的颜色并刷新界面"""
        self._set_color_field(field, color)
        self.refresh_preview()

    def current_colors(self):
        """当前界面对应的完整 13 色。

        扩展色输入框留空 = 「自动推导」：把该字段置空后交给 ``derive_missing``
        按必需色算出来。必需色永远取 ``self.colors`` 里最后一次合法的值，所以
        用户把某个必需色输入框填坏时预览不会崩，只是那行标红。
        """
        values = {field: self.colors[field] for field in REQUIRED_COLOR_FIELDS}
        for field in OPTIONAL_COLOR_FIELDS:
            text = self.color_edits[field].text().strip()
            values[field] = normalise_color(text) if text else None
        return derive_missing(values)

    def _apply_theme_dict(self, theme, include_typography=True):
        """把一套配色铺到界面上（预设 / 起点主题 / 一键派生都走这里）"""
        self._loading = True
        theme = derive_missing(theme)
        for field in COLOR_FIELDS:
            color = theme.get(field)
            if color:
                self._set_color_field(field, color)

        if include_typography:
            family = theme.get("font_family")
            if family:
                self.font_combo.setCurrentFont(QFont(family))
            if theme.get("font_size"):
                self.font_size_spin.setValue(int(theme["font_size"]))
            if theme.get("line_spacing"):
                self.line_spacing_spin.setValue(float(theme["line_spacing"]))
            paragraph = normalise_paragraph_spacing(theme.get("paragraph_spacing"))
            if paragraph is not None:
                self.paragraph_spacing_spin.setValue(paragraph)
            self.typography_check.setChecked(
                any(theme.get(field) is not None for field in TYPO_FIELDS))

        self._loading = False
        self._sync_typography_state()
        self.sync_preset_combo()

    def on_color_text(self, field):
        """手填十六进制时的即时反馈：合法就立刻换色，留空算「自动推导」"""
        text = self.color_edits[field].text().strip()
        if not text:
            self.color_edits[field].setStyleSheet("")
            if field in OPTIONAL_COLOR_FIELDS:
                self.refresh_preview()
            return

        value = normalise_color(text)
        if value is None:
            self.color_edits[field].setStyleSheet(_INVALID_INPUT_STYLE)
            return
        self.color_edits[field].setStyleSheet("")
        self.colors[field] = value
        self.color_buttons[field].set_color(value)
        self.refresh_preview()

    def normalise_color_text(self, field):
        """填完一个颜色后统一成小写规范值。

        扩展色留空 = 交回自动推导：把色块和预览刷成推导出来的颜色，输入框依然
        留空（下次打开编辑器就会从这里存下的真实颜色回填）。
        """
        text = self.color_edits[field].text().strip()
        if not text:
            if field in OPTIONAL_COLOR_FIELDS:
                self.color_edits[field].setStyleSheet("")
                self.colors[field] = self.current_colors()[field]
                self.color_buttons[field].set_color(self.colors[field])
                self.refresh_preview()
            return

        value = normalise_color(text)
        if value is None:
            return
        self.set_color(field, value)
        self.sync_preset_combo()

    def apply_preset(self, index):
        """套用配色预设（13 个颜色全部铺满，扩展色用推导值）"""
        if self._loading or index <= 0:
            return
        self._apply_theme_dict(preset_colors(THEME_PRESETS[index - 1][1]),
                               include_typography=False)
        self.info_hint.setText(i18n.t("theme_editor.preset_applied",
                                      name=THEME_PRESETS[index - 1][0]))

    def load_base_theme(self):
        """把选中的主题当作起点铺进来（一次性起点，不保存任何继承关系）"""
        key = self.base_combo.currentData()
        if not key:
            self.info_hint.setText(i18n.t("theme_editor.base_hint"))
            return
        self._apply_theme_dict(self.manager.get_theme(key))
        self.info_hint.setText(i18n.t(
            "theme_editor.base_loaded",
            name=theme_display_label(self.manager, key)))

    def derive_from_seed(self):
        """只给一个主色，自动派生整套配色（深浅方向由主色明暗决定）"""
        self._apply_theme_dict(derive_palette(self.seed_button.color()),
                               include_typography=False)
        self.info_hint.setText(i18n.t("theme_editor.derive_done"))

    def sync_preset_combo(self):
        """当前配色和某个预设一致时，把下拉框选到那一项。

        只比 5 个必需色：预设本身也只带这 5 个，扩展色都是推导出来的，
        用户单独微调过扩展色不该让预设「脱选」。
        """
        self._loading = True
        current = self.current_colors()
        index = 0
        for position, (_, preset) in enumerate(THEME_PRESETS, start=1):
            if all(current.get(field) == normalise_color(preset.get(field))
                   for field in REQUIRED_COLOR_FIELDS):
                index = position
                break
        self.preset_combo.setCurrentIndex(index)
        self._loading = False

    def refresh_preview(self):
        """预览区跟着颜色走（排版也一起，看得到实际效果）"""
        typography = self.typography_check.isChecked()
        self.preview.set_theme(
            self.current_colors(),
            font_size=(self.font_size_spin.value() if typography else None),
            line_spacing=(self.line_spacing_spin.value() if typography else None),
            paragraph_spacing=(self.paragraph_spacing_spin.value()
                               if typography else None))

    # ------------------------------------------------------------------ 结果

    def collect_theme(self):
        """收集结果，返回 ``(主题字典, 错误列表)``。

        扩展色与排版字段**只在填了的时候**才写进结果：``validate_theme`` 会
        把缺的扩展色按必需色推导，所以「留空 = 自动推导」不需要在这里补值。
        """
        errors = []
        theme = {}

        for field in REQUIRED_COLOR_FIELDS:
            raw = self.color_edits[field].text().strip()
            color = normalise_color(raw)
            if color is None:
                self.color_edits[field].setStyleSheet(_INVALID_INPUT_STYLE)
                errors.append(("theme_error.invalid_color",
                               {"field": field, "value": raw}))
                continue
            theme[field] = color

        for field in OPTIONAL_COLOR_FIELDS:
            raw = self.color_edits[field].text().strip()
            if not raw:
                continue
            color = normalise_color(raw)
            if color is None:
                self.color_edits[field].setStyleSheet(_INVALID_INPUT_STYLE)
                errors.append(("theme_error.invalid_color",
                               {"field": field, "value": raw}))
                continue
            theme[field] = color

        if errors:
            return None, errors

        if self.typography_check.isChecked():
            family = normalise_font_family(self.font_combo.currentFont().family())
            if family:
                theme["font_family"] = family
            theme["font_size"] = int(self.font_size_spin.value())
            theme["line_spacing"] = round(float(self.line_spacing_spin.value()), 2)
            theme["paragraph_spacing"] = int(self.paragraph_spacing_spin.value())

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

