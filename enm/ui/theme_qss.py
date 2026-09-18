"""按主题配色生成 Qt 样式表（主窗口、各对话框、主题编辑器预览共用）。

单独抽一个模块，是因为主题编辑器和主题管理器都要「用另一套配色渲染一小块
控件」给用户看，主窗口也要用同一份规则；写两份迟早会不一致。

两个踩过的坑写在这里，改样式表前先看一眼：

* Qt 样式表**不继承**。``QMainWindow {{ color }}`` 只作用在 QMainWindow
  自己身上，没有写进选择器的控件（QLabel、菜单栏、工具栏、滚动条……）会一直
  用 Qt 默认调色板，于是在深色主题下变成浅底黑字甚至黑底黑字。用到的控件
  类型必须逐个写规则。
* 样式表会沿对象树**渗到子对话框**。主窗口设了 ``QLabel {{ color }}`` 之后，
  以主窗口为父窗口的 QDialog 里的标签也会变白，而对话框自己的底色还是浅色，
  结果白字压浅底。所以这里必须同时接管 ``QDialog`` 的底色与文字色
  （顺带的好处：对话框、消息框也一起跟随主题了）。
"""

from PyQt5.QtGui import QColor


def color_on_accent(theme):
    """强调色底上该用的文字色：浅底配深字，深底配白字"""
    accent = QColor(theme["accent"])
    if accent.lightness() > 150:
        return QColor(theme["background"]).name()
    return QColor("#FFFFFF").name()


def build_style_sheet(theme, font_size=12, line_spacing=1.5, extra_rules=""):
    """按 ``theme`` 生成完整样式表。

    ``theme`` 需要含 ``background`` / ``foreground`` / ``accent`` /
    ``highlight`` / ``border`` 五个颜色（``ThemeManager.get_theme()`` 保证齐全）。
    ``font_size`` / ``line_spacing`` 只作用于阅读区（``QTextEdit``）。
    ``extra_rules`` 追加在最前面，给「一小块容器也要整块上色」的预览区用。
    """
    background = theme["background"]
    foreground = theme["foreground"]
    accent = theme["accent"]
    highlight = theme["highlight"]
    border = theme["border"]
    on_accent = color_on_accent(theme)

    return f"""
    {extra_rules}

    /* 窗口与对话框：QDialog 一起接管，否则子对话框会被上面的
       QLabel 规则刷成白字、底色却还是浅色 */
    QMainWindow, QDialog {{
        background-color: {background};
        color: {foreground};
    }}
    QLabel {{
        color: {foreground};
        background: transparent;
    }}
    QCheckBox, QRadioButton, QGroupBox {{
        color: {foreground};
    }}
    QGroupBox {{
        border: 1px solid {border};
        border-radius: 4px;
        margin-top: 10px;
        padding-top: 6px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {foreground};
    }}

    /* 阅读区 */
    QTextEdit, QPlainTextEdit {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        font-size: {font_size}px;
        line-height: {line_spacing};
    }}

    /* 列表类控件 */
    QTreeWidget, QListWidget {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
    }}
    QTreeWidget::item:hover, QListWidget::item:hover {{
        background-color: {highlight};
    }}
    QTreeWidget::item:selected, QListWidget::item:selected {{
        background-color: {accent};
        color: {on_accent};
    }}
    QHeaderView::section {{
        background-color: {highlight};
        color: {foreground};
        border: none;
        border-right: 1px solid {border};
        padding: 4px 6px;
    }}

    /* 菜单栏 / 菜单：Windows 样式会自己画一块浅色底，
       所以得用规则明确指定颜色 */
    QMenuBar {{
        background-color: {background};
        color: {foreground};
    }}
    QMenuBar::item {{
        background: transparent;
        color: {foreground};
        padding: 4px 8px;
    }}
    QMenuBar::item:selected {{
        background-color: {accent};
        color: {on_accent};
    }}
    QMenu {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
    }}
    QMenu::item {{
        color: {foreground};
        padding: 4px 22px;
    }}
    QMenu::item:selected {{
        background-color: {accent};
        color: {on_accent};
    }}
    QMenu::item:disabled {{
        color: {border};
    }}
    QMenu::separator {{
        background-color: {border};
        height: 1px;
    }}

    /* 工具栏 */
    QToolBar {{
        background-color: {background};
        border: none;
        spacing: 4px;
    }}
    QToolButton {{
        color: {foreground};
        background: transparent;
        padding: 4px 6px;
        border-radius: 3px;
    }}
    QToolButton:hover {{
        background-color: {accent};
        color: {on_accent};
    }}
    QToolButton:disabled {{
        color: {border};
    }}

    /* 进度条 */
    QProgressBar {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        border-radius: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {accent};
        border-radius: 3px;
    }}

    /* 按钮：常态用强调色，悬停换成高亮色，这才看得出反馈 */
    QPushButton {{
        background-color: {accent};
        color: {on_accent};
        border: none;
        border-radius: 4px;
        padding: 5px 10px;
    }}
    QPushButton:hover {{
        background-color: {highlight};
        color: {foreground};
    }}
    QPushButton:disabled {{
        background-color: {border};
        color: {background};
    }}

    /* 输入框 / 下拉框 */
    QLineEdit, QKeySequenceEdit {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 3px 6px;
        selection-background-color: {accent};
        selection-color: {on_accent};
    }}
    QLineEdit:focus, QKeySequenceEdit:focus {{
        border: 1px solid {accent};
    }}
    QComboBox {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 3px 6px;
    }}
    QComboBox:hover {{
        border: 1px solid {accent};
    }}
    QComboBox QAbstractItemView {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        selection-background-color: {accent};
        selection-color: {on_accent};
    }}

    /* 滚动条 */
    QScrollBar:vertical {{
        background: {background};
        width: 12px;
        margin: 0;
    }}
    QScrollBar:horizontal {{
        background: {background};
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {border};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::handle:horizontal {{
        background: {border};
        border-radius: 6px;
        min-width: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {accent};
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {accent};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0;
        width: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}

    /* 提示气泡 */
    QToolTip {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
    }}
    """
