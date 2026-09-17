"""主题生成器对话框。"""

from PyQt5.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox,
                             QFormLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout)


class ThemeGeneratorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("主题生成器")
        self.setModal(True)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 主题名称
        form_layout = QFormLayout()
        self.theme_name_edit = QLineEdit()
        form_layout.addRow("主题名称:", self.theme_name_edit)
        
        # 颜色选择
        self.bg_color_btn = QPushButton("选择背景色")
        self.bg_color_btn.clicked.connect(lambda: self.choose_color("background"))
        self.fg_color_btn = QPushButton("选择前景色")
        self.fg_color_btn.clicked.connect(lambda: self.choose_color("foreground"))
        self.accent_color_btn = QPushButton("选择强调色")
        self.accent_color_btn.clicked.connect(lambda: self.choose_color("accent"))
        
        form_layout.addRow("背景色:", self.bg_color_btn)
        form_layout.addRow("前景色:", self.fg_color_btn)
        form_layout.addRow("强调色:", self.accent_color_btn)
        
        # 颜色预览
        self.color_preview = QLabel()
        self.color_preview.setMinimumHeight(100)
        self.color_preview.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CCCCCC;")
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
        self.color_preview.setText(f"背景: {self.colors['background']}\n前景: {self.colors['foreground']}\n强调: {self.colors['accent']}")
    
    def get_theme_data(self):
        return {
            "name": self.theme_name_edit.text() or "自定义主题",
            "background": self.colors["background"],
            "foreground": self.colors["foreground"],
            "accent": self.colors["accent"],
            "highlight": self.colors["accent"],
            "border": self.colors["accent"]
        }
