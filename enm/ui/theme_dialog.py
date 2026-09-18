"""主题生成器对话框。"""

from PyQt5.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox,
                             QFormLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout)

from .. import i18n


class ThemeGeneratorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("theme_editor.title"))
        self.setModal(True)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 主题名称
        form_layout = QFormLayout()
        self.theme_name_edit = QLineEdit()
        form_layout.addRow(i18n.t("theme_editor.name_label"), self.theme_name_edit)
        
        # 颜色选择
        self.bg_color_btn = QPushButton(i18n.t("theme_editor.choose_background"))
        self.bg_color_btn.clicked.connect(lambda: self.choose_color("background"))
        self.fg_color_btn = QPushButton(i18n.t("theme_editor.choose_foreground"))
        self.fg_color_btn.clicked.connect(lambda: self.choose_color("foreground"))
        self.accent_color_btn = QPushButton(i18n.t("theme_editor.choose_accent"))
        self.accent_color_btn.clicked.connect(lambda: self.choose_color("accent"))
        
        form_layout.addRow(i18n.t("theme_editor.background_label"), self.bg_color_btn)
        form_layout.addRow(i18n.t("theme_editor.foreground_label"), self.fg_color_btn)
        form_layout.addRow(i18n.t("theme_editor.accent_label"), self.accent_color_btn)
        
        # 颜色预览
        self.color_preview = QLabel()
        self.color_preview.setMinimumHeight(100)
        self.color_preview.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CCCCCC;")
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText(i18n.t("common.ok"))
        button_box.button(QDialogButtonBox.Cancel).setText(i18n.t("common.cancel"))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addLayout(form_layout)
        layout.addWidget(self.color_preview)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        
        # 默认颜色
        self.colors = {
            "background": "#FFFFFF",
            "foreground": "#000000",
            "accent": "#007ACC"
        }
    
    def choose_color(self, color_type):
        color = QColorDialog.getColor()
        if color.isValid():
            self.colors[color_type] = color.name()
            self.update_preview()
    
    def update_preview(self):
        style = f"background-color: {self.colors['background']}; color: {self.colors['foreground']}; border: 1px solid {self.colors['accent']};"
        self.color_preview.setStyleSheet(style)
        self.color_preview.setText(i18n.t(
            "theme_editor.preview",
            background=self.colors['background'],
            foreground=self.colors['foreground'],
            accent=self.colors['accent']))
    
    def get_theme_data(self):
        return {
            "name": (self.theme_name_edit.text()
                     or i18n.t("theme_editor.name_default")),
            "background": self.colors["background"],
            "foreground": self.colors["foreground"],
            "accent": self.colors["accent"],
            "highlight": self.colors["accent"],
            "border": self.colors["accent"]
        }
