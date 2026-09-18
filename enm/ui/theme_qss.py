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
* 还有一批控件**只认调色板、不认样式表**：``QScrollArea`` 的视口、
  ``QFontComboBox``、列表 / 表格里由委托画出来的条目，以及 Qt 自带对话框
  （字体 / 颜色 / 输入框 / 消息框）内部的控件。这些地方要 :func:`build_palette`
  把主题灌进 ``QApplication.setPalette`` 才会变色，否则深色主题下会留一块
  系统默认的浅底（白字压浅底，等于看不见）。
* 反过来说，``QSpinBox`` / ``QDoubleSpinBox`` **必须显式写规则**。
  ``QAbstractSpinBox`` 不是 ``QLineEdit``，下面那条 ``QLineEdit`` 规则管不到它；
  而样式表完全没碰某个控件时，Windows 原生样式会拿自己的主题去画，
  **调色板改成纯黑它照样是一块白底**（禁用时浅灰）。主题编辑器的字号 /
  行距两个框就是这么白的——光靠 :func:`build_palette` 治不了。
* 同一条规律也适用于 ``QSplitter::handle``：章节列表和阅读区之间那条分隔条
  原生样式画的是系统灰，深色主题下就是一道扎眼的白缝，必须显式上色。

颜色分工：**原生标题栏不归这里管**。系统画的标题栏（含最小化 / 最大化 /
关闭三个按钮）Qt 样式表碰不到，由 :mod:`enm.ui.titlebar` 走 DWM 上色。
所以主题里 ``titlebar`` / ``titlebar_text`` 两个字段在本模块里用不到，
是为了让整个主题的配色能一眼看全才放在一起的。
"""

from PyQt5.QtGui import QColor, QPalette

from ..managers.theme import derive_missing, lightness, mix, normalise_color

# 「隔行变色」的深浅比例：底色往文字色方向混一点点。
# 明暗主题自动适配——浅色主题得到淡淡的灰，深色主题得到略亮的一档。
_ALTERNATE_RATIO = 0.08

#: 章节列表与阅读区之间那条分隔条的宽度（像素）。
#: 主窗口用它调 ``QSplitter.setHandleWidth()``，下面样式表用它定 handle 的宽；
#: 两处必须同源，不然「画出来的条」和「能拖中的热区」会对不上。
SPLITTER_HANDLE_WIDTH = 4


def color_on_accent(theme):
    """强调色底上该用的文字色：浅底配深字，深底配白字"""
    accent = normalise_color(theme.get("accent")) or "#007ACC"
    if lightness(accent) > 150:
        return normalise_color(theme.get("background")) or "#FFFFFF"
    return "#ffffff"


def build_palette(theme):
    """按主题生成 :class:`QPalette`，交给 ``QApplication.setPalette`` 全局生效。

    样式表管不到的地方都靠它兜底：``QScrollArea`` 的视口、``QFontComboBox``、
    列表 / 表格里由委托画的条目，以及 Qt 自带对话框（字体 / 颜色 / 输入框 /
    消息框）内部的控件——它们取底色和文字色走的是 **调色板**。只写样式表的话，
    深色主题下这些地方会保留系统默认的浅色（主题编辑器左边的滚动区、
    快捷键设置窗口、字体对话框的字体清单踩的就是这个坑）。

    注意：``QSpinBox`` / ``QDoubleSpinBox`` **不归这里管**。它们没有样式表
    规则时由 Windows 原生样式绘制，会直接无视调色板画成白底，只能靠
    :func:`build_style_sheet` 里的显式规则上色。
    """
    theme = derive_missing(theme)
    background = QColor(theme["background"])
    foreground = QColor(theme["foreground"])
    accent = QColor(theme["accent"])
    selection = QColor(theme["selection"])
    disabled = QColor(theme["disabled"])
    tooltip = QColor(theme["tooltip"])
    on_accent = QColor(color_on_accent(theme))
    alternate = QColor(mix(theme["background"], theme["foreground"],
                           _ALTERNATE_RATIO))

    def shade(ratio):
        """底色往文字色方向混一档——3D 边框用的灰阶，明暗主题都合适"""
        return QColor(mix(theme["background"], theme["foreground"], ratio))

    palette = QPalette()
    # setColor(role, color) 会同时写进 Active / Inactive / Disabled 三组
    palette.setColor(QPalette.Window, background)
    palette.setColor(QPalette.WindowText, foreground)
    palette.setColor(QPalette.Base, background)
    palette.setColor(QPalette.AlternateBase, alternate)
    palette.setColor(QPalette.Text, foreground)
    palette.setColor(QPalette.Button, background)
    palette.setColor(QPalette.ButtonText, foreground)
    palette.setColor(QPalette.BrightText, on_accent)
    palette.setColor(QPalette.Highlight, selection)
    palette.setColor(QPalette.HighlightedText, on_accent)
    palette.setColor(QPalette.ToolTipBase, tooltip)
    palette.setColor(QPalette.ToolTipText, foreground)
    palette.setColor(QPalette.Link, accent)
    palette.setColor(QPalette.LinkVisited, accent)
    palette.setColor(QPalette.PlaceholderText, disabled)
    # 立体边框（框架 / 分隔线的明暗边）用的灰阶
    palette.setColor(QPalette.Light, shade(0.28))
    palette.setColor(QPalette.Midlight, shade(0.20))
    palette.setColor(QPalette.Mid, shade(0.36))
    palette.setColor(QPalette.Dark, shade(0.44))
    palette.setColor(QPalette.Shadow, shade(0.52))
    # 禁用态文字统一压成 disabled 色，免得深色主题下灰底黑字
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, disabled)
    palette.setColor(QPalette.Disabled, QPalette.Base, background)
    palette.setColor(QPalette.Disabled, QPalette.AlternateBase, alternate)
    palette.setColor(QPalette.Disabled, QPalette.Button, background)
    palette.setColor(QPalette.Disabled, QPalette.Highlight, selection)
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, disabled)
    return palette


def build_style_sheet(theme, font_size=12, line_spacing=1.5, extra_rules=""):
    """按 ``theme`` 生成完整样式表。

    ``theme`` 需要含 ``background`` / ``foreground`` / ``accent`` /
    ``highlight`` / ``border`` 五个必需色；扩展色（``titlebar`` /
    ``titlebar_text`` / ``selection`` / ``disabled`` / ``scrollbar`` /
    ``tooltip`` / ``sidebar`` / ``reader``）缺了也没关系——这里会先跑一遍
    :func:`enm.managers.theme.derive_missing`，所以传 5 色旧主题进来同样能用。

    ``font_size`` / ``line_spacing`` 作用于阅读区（``QTextEdit``）。
    ``extra_rules`` 追加在最前面，给「一小块容器也要整块上色」的预览区用。

    注意：标题栏**不在这里**。原生标题栏由 :mod:`enm.ui.titlebar` 走 DWM
    上色，Qt 样式表管不到系统画的标题栏。
    """
    theme = derive_missing(theme)
    background = theme["background"]
    foreground = theme["foreground"]
    accent = theme["accent"]
    highlight = theme["highlight"]
    border = theme["border"]
    selection = theme["selection"]
    disabled = theme["disabled"]
    scrollbar = theme["scrollbar"]
    tooltip = theme["tooltip"]
    sidebar = theme["sidebar"]
    reader = theme["reader"]
    on_accent = color_on_accent(theme)
    # 隔行变色用的条纹色。必须由主题算出来，见下面列表规则的注释。
    alternate = mix(background, foreground, _ALTERNATE_RATIO)

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

    /* 阅读区：底色走 reader，想要米黄 / 护眼绿就改它 */
    QTextEdit, QPlainTextEdit {{
        background-color: {reader};
        color: {foreground};
        border: 1px solid {border};
        font-size: {font_size}px;
        line-height: {line_spacing};
    }}

    /* 左侧章节列表：单独一块底色，与阅读区区分开 */
    #sidebar {{
        background-color: {sidebar};
    }}
    #sidebar QLabel {{
        color: {foreground};
        background: transparent;
    }}

    /* 列表类控件。「视图」类要单独写：Qt 自带对话框（字体对话框的字体清单、
       尺寸清单）和下拉框弹层用的都是 QListView，只写 QTreeWidget / QListWidget
       的话它们的底色会走调色板（系统默认浅色），深色主题下就是一块白底。 */
    QTreeWidget, QListWidget, QTreeView, QListView, QTableView, QTableWidget,
    QColumnView {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
    }}
    /* 开了 setAlternatingRowColors(True) 的表格，Qt 画隔行用的是**调色板**里的
       AlternateBase，而不是样式表里的 background-color。样式表里不显式给一个
       alternate-background-color，隔行就一直是系统默认的浅色，于是深色主题下
       出现白底浅字（「继续阅读」列表踩的就是这个）。这里只声明这一个属性，
       不碰底色 / 边框，避免影响下拉框等复用 QListView 的控件。 */
    QTreeWidget, QListWidget, QTreeView, QListView, QTableView, QTableWidget, QColumnView {{
        alternate-background-color: {alternate};
    }}
    QTreeWidget::item:hover, QListWidget::item:hover {{
        background-color: {highlight};
    }}
    QTreeWidget::item:selected, QListWidget::item:selected {{
        background-color: {selection};
        color: {on_accent};
    }}
    QHeaderView::section {{
        background-color: {highlight};
        color: {foreground};
        border: none;
        border-right: 1px solid {border};
        padding: 4px 6px;
    }}
    /* 排序指示器：Qt 系统箭头是用调色板里的浅灰画的，样式表换不了它的颜色
       （image 只能指向图片文件，本项目不放这类素材；纯 QSS 的「零尺寸盒子 +
       三角形边框」在 Qt 里会被当成整块矩形填充）。深色主题下那个浅灰箭头
       会变成表头上的一块白斑，所以这里直接把它藏掉，排序方向改由表头文字
       里的 ↑ / ↓ 表示（见 continue_dialog.refresh_header_labels）。 */
    QHeaderView::up-arrow, QHeaderView::down-arrow {{
        image: none;
        width: 0;
        height: 0;
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
        background-color: {selection};
        color: {on_accent};
    }}
    QMenu::item:disabled {{
        color: {disabled};
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
        color: {disabled};
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
        color: {disabled};
    }}

    /* 输入框 / 下拉框 */
    QLineEdit, QKeySequenceEdit {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 3px 6px;
        selection-background-color: {selection};
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
        selection-background-color: {selection};
        selection-color: {on_accent};
    }}

    /* 数字输入框（字号 / 行距）。QSpinBox 与 QDoubleSpinBox 的基类是
       QAbstractSpinBox，跟 QLineEdit 没有继承关系，上面那条规则管不到它们；
       而样式表**一条规则都没碰**某个控件时，Windows 原生样式会拿自己的主题
       去画，于是深色主题下它们是一块纯白的输入区（禁用时浅灰），调色板灌成
       纯黑也没用——必须像下面这样显式上色，跟面板其余部分的 QLineEdit 对齐。

       这里**只给输入区上色，上下按钮交给原生样式画**：箭头颜色取自调色板
       （深色主题下正好是白的、禁用时是灰的，看得见）。一旦连 ::up-button /
       ::down-button 一起上色，Qt 就不再沿用原生箭头，而 ::up-arrow 只能指
       图片文件（本项目不放这类素材，纯 QSS 的三角形会被当成矩形填充），
       结果按钮变成一个没有箭头的色块，反而更难用。 */
    QSpinBox, QDoubleSpinBox {{
        background-color: {background};
        color: {foreground};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 3px 6px;
        selection-background-color: {selection};
        selection-color: {on_accent};
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {accent};
    }}
    QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {disabled};
    }}

    /* 章节列表与阅读区之间的分隔条。原生样式用系统灰画它，深色主题下就是
       一道白缝；这里换成主题边框色，鼠标悬停（准备拖）时用主色提示「这条
       能拖」。宽度取 SPLITTER_HANDLE_WIDTH，和 main_window 里
       QSplitter.setHandleWidth() 是同一个常量。 */
    QSplitter::handle {{
        background-color: {border};
    }}
    QSplitter::handle:horizontal {{
        width: {SPLITTER_HANDLE_WIDTH}px;
    }}
    QSplitter::handle:hover {{
        background-color: {accent};
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
        background: {scrollbar};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::handle:horizontal {{
        background: {scrollbar};
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

    /* 提示气泡：底色单独一档，与主窗口拉开层次 */
    QToolTip {{
        background-color: {tooltip};
        color: {foreground};
        border: 1px solid {border};
    }}
    """
