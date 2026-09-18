"""主窗口：菜单栏、工具栏、章节树、阅读区与所有交互逻辑。"""

import base64
import json
import time
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QTextCursor
from PyQt5.QtWidgets import (QAction, QDialog, QFileDialog, QFontDialog,
                             QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                             QMessageBox, QProgressBar, QPushButton, QTextEdit,
                             QToolBar, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from .. import i18n
from ..constants import (AUTHOR_NAME, DEBUG_MODE, ICON_PATH, PROJECT_NAME,
                         VERSION)
from ..managers import (ConfigManager, ReadingProgressManager,
                        ThemeManager, format_timestamp, split_file_key)
from ..readers import (SUPPORTED_EXTENSIONS, FolderReader, ReaderError,
                       build_open_file_filter, create_reader,
                       format_chapter_html, supported_extensions_text)
from ..shortcuts import (ACTION_DEFS, DEFS_BY_ID, READER, WINDOW,
                         ShortcutManager, event_key_sequence, key_sequence,
                         label_of)
from .continue_dialog import ContinueReadingDialog
from .shortcut_dialog import ShortcutSettingsDialog
from .theme_dialog import ThemeGeneratorDialog
from ..logger import logger

# 阅读区字号范围（字体增大 / 减小用）
FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 48

class NovelMaster(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 初始化管理器（logger 全局单例，重复构造不会叠加处理器）
        self.logger = logger
        self.config_manager = ConfigManager()
        self.progress_manager = ReadingProgressManager()
        self.theme_manager = ThemeManager()
        
        # 界面语言（i18n 是全局单例，阅读器 / 对话框共用同一份翻译表）：
        # 必须在搭建界面之前套用，否则菜单等文案会是默认语言
        i18n.set_language(self.config_manager.get("language", i18n.DEFAULT_LANG))
        # 随语言刷新的文本（部件, 语言键, setter）
        self._text_bindings = []
        # 快捷键注册表（读取 config.json 里的自定义绑定）
        self.shortcut_manager = ShortcutManager(self.config_manager)
        # 动作 id -> QAction（窗口级与阅读区级都登记在这里）
        self._actions = {}
        # 普通按钮的提示（随快捷键变化刷新）
        self._hint_widgets = []
        # 阅读区按键 -> 处理函数
        self._reader_handlers = {
            "nav.prev_chapter": self.previous_chapter,
            "nav.next_chapter": self.next_chapter,
            "nav.reader_prev": self.previous_chapter,
            "nav.reader_next": self.next_chapter,
        }
        # 按生效范围缓存的绑定快照，供阅读区按键过滤使用
        self._window_bindings = {}
        self._reader_bindings = {}
        self._snapshot_bindings()
        
        # 当前阅读器
        self.current_reader = None
        self.current_file_path = None

        # 内嵌图片尺寸缓存与自适应重算定时器
        self._image_widths = {}
        self.image_fit_timer = QTimer()
        self.image_fit_timer.setSingleShot(True)
        self.image_fit_timer.timeout.connect(self.fit_document_images)
        
        # 自动保存定时器
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self.auto_save_progress)

        # 阅读统计会话状态（仅窗口激活时计时）与待恢复的章内位置
        self._stats = self.empty_stats()
        self._focus_started_at = None
        self._pending_scroll_percent = 0.0
        
        # 设置窗口图标
        self.set_window_icon()
        
        self.setup_ui()
        self.apply_settings()
        self.setup_auto_save()
        
        # 确保侧边栏和按钮正确显示
        if self.sidebar_visible:
            self.sidebar.show()
            self.toggle_sidebar_btn.show()
        
        self.logger.log(f"{PROJECT_NAME} 启动成功")
    
    def set_window_icon(self):
        """设置窗口图标"""
        try:
            if ICON_PATH.exists():
                icon = QIcon(str(ICON_PATH))
                self.setWindowIcon(icon)
                if DEBUG_MODE:
                    self.logger.debug(f"窗口图标设置成功: {ICON_PATH}")
            else:
                if DEBUG_MODE:
                    self.logger.debug(f"图标文件不存在: {ICON_PATH}")
        except Exception as e:
            self.logger.log(f"设置窗口图标失败: {e}", "ERROR")
    
    def setup_ui(self):
        """设置用户界面"""
        # 章节列表默认显示状态（侧边栏文案会依赖它，必须先初始化）
        self.sidebar_visible = True
        
        self.update_window_title()
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧边栏（章节列表）
        self.sidebar = QWidget()
        # 主题里用 #sidebar QLabel 限定标签配色，避免样式表渗到对话框
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMaximumWidth(300)
        sidebar_layout = QVBoxLayout(self.sidebar)
        
        # 章节列表标题栏
        sidebar_header_layout = QHBoxLayout()
        self.chapter_tree_label = self.bind_text(QLabel(self),
                                                  "sidebar.chapter_list")
        self.toggle_sidebar_btn = QPushButton()
        self.toggle_sidebar_btn.setMaximumWidth(60)
        self.toggle_sidebar_btn.clicked.connect(self.toggle_sidebar)
        self.bind_text(self.toggle_sidebar_btn, self._sidebar_button_key)
        self.bind_hint(self.toggle_sidebar_btn, "view.toggle_sidebar")
        
        sidebar_header_layout.addWidget(self.chapter_tree_label)
        sidebar_header_layout.addStretch()
        sidebar_header_layout.addWidget(self.toggle_sidebar_btn)
        sidebar_layout.addLayout(sidebar_header_layout)
        
        self.chapter_tree = QTreeWidget()
        self.chapter_tree.setHeaderHidden(True)  # 隐藏默认的标题栏
        self.chapter_tree.itemClicked.connect(self.on_chapter_selected)
        sidebar_layout.addWidget(self.chapter_tree)
        
        # 阅读进度
        self.progress_label = QLabel()
        self.progress_bar = QProgressBar()
        sidebar_layout.addWidget(self.progress_label)
        sidebar_layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(self.sidebar)
        
        # 右侧阅读区域
        self.reader_widget = QWidget()
        reader_layout = QVBoxLayout(self.reader_widget)
        
        # 阅读器控件
        self.reader_display = QTextEdit()
        self.reader_display.setReadOnly(True)
        reader_layout.addWidget(self.reader_display)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        self.prev_btn = QPushButton()
        self.next_btn = QPushButton()
        self.bind_text(self.prev_btn, "menu.previous_chapter")
        self.bind_text(self.next_btn, "menu.next_chapter")
        self.prev_btn.clicked.connect(self.previous_chapter)
        self.next_btn.clicked.connect(self.next_chapter)
        self.bind_hint(self.prev_btn, "nav.prev_chapter")
        self.bind_hint(self.next_btn, "nav.next_chapter")
        
        control_layout.addWidget(self.prev_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.next_btn)
        
        reader_layout.addLayout(control_layout)
        main_layout.addWidget(self.reader_widget)
        
        # 创建菜单栏
        self.create_menus()
        
        # 创建工具栏
        self.create_toolbar()
        
        # 阅读区按键过滤：方向键 / 翻页键翻章，Ctrl 组合键优先于 QTextEdit 自带行为
        self.reader_display.installEventFilter(self)
        self.reader_display.viewport().installEventFilter(self)
    
    # ---------------- 多语言 ----------------
    
    def bind_text(self, widget, key, setter="setText"):
        """登记一个随语言切换刷新的文本
        
        ``key`` 可以是语言键，也可以是返回语言键的函数（用于「显示 / 隐藏」
        这类会随状态变化的文案）。返回 widget，便于链式构造。
        """
        binding = (widget, key, setter)
        self._text_bindings.append(binding)
        self._apply_text_binding(binding)
        return widget
    
    def _resolve_text(self, key):
        """语言键 → 当前语言文本（key 允许是函数）"""
        if callable(key):
            key = key()
        return i18n.t(key)
    
    def _apply_text_binding(self, binding):
        widget, key, setter = binding
        getattr(widget, setter)(self._resolve_text(key))
    
    def _sidebar_button_key(self):
        """侧边栏按钮文案（显示 / 隐藏）"""
        return ("sidebar.toggle_hide" if self.sidebar_visible
                else "sidebar.toggle_show")
    
    def _sidebar_action_key(self):
        """侧边栏工具栏动作文案（显示章节列表 / 隐藏章节列表）"""
        return ("toolbar.sidebar_hide" if self.sidebar_visible
                else "toolbar.sidebar_show")
    
    def _refresh_sidebar_text(self):
        """侧边栏文案随显示状态刷新（并把新文案写回快捷键提示）"""
        for binding in self._text_bindings:
            if binding[1] in (self._sidebar_button_key, self._sidebar_action_key):
                self._apply_text_binding(binding)
        self.update_action_hint("view.toggle_sidebar")
    
    def make_action(self, key, slot=None, action_id=None, scope=WINDOW):
        """创建随语言切换自动更新文案的动作（可选同时登记快捷键）"""
        action = QAction(self)
        self.bind_text(action, key)
        if slot is not None:
            action.triggered.connect(slot)
        if action_id:
            self.register_action(action_id, action, scope)
        return action
    
    def add_menu(self, parent, key):
        """添加随语言切换自动更新标题的子菜单"""
        menu = parent.addMenu("")
        self.bind_text(menu, key, "setTitle")
        return menu
    
    def retranslate_ui(self):
        """按当前语言刷新整个界面（切换语言后调用，无需重启）"""
        for binding in self._text_bindings:
            self._apply_text_binding(binding)
        
        # 语言菜单的勾选状态
        for code, action in getattr(self, "language_actions", {}).items():
            action.setChecked(code == i18n.current_language())
        
        # 自动编号的章节标题（「第 N 章」等）就地重生成
        reader = self.current_reader
        if reader is not None and reader.retranslate_titles():
            self.update_chapter_list()
            self.refresh_reader_text()
        
        self.update_progress()
        self.update_window_title()
        # 提示文本里含功能名，必须在文案刷新之后再重建
        self.refresh_shortcuts()
    
    def refresh_reader_text(self):
        """按当前语言重渲染正在显示的章节（保留章内阅读位置）"""
        if self.current_reader is None:
            return
        self._pending_scroll_percent = self.current_scroll_percent()
        self.display_content()
    
    def create_menus(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = self.add_menu(menubar, "menu.file")
        
        self.make_action("menu.open_file", self.open_file, "file.open")
        file_menu.addAction(self._actions["file.open"])
        
        self.make_action("menu.open_folder", self.open_folder, "file.open_folder")
        file_menu.addAction(self._actions["file.open_folder"])
        
        file_menu.addSeparator()
        
        # 最近文件
        self.recent_menu = self.add_menu(file_menu, "menu.recent_files")
        self.update_recent_files_menu()
        
        self.make_action("menu.continue_reading", self.show_continue_reading,
                         "file.continue")
        file_menu.addAction(self._actions["file.continue"])
        
        file_menu.addSeparator()
        
        self.make_action("menu.exit", self.close, "file.quit")
        file_menu.addAction(self._actions["file.quit"])
        
        # 阅读菜单（翻章 / 跳章）
        read_menu = self.add_menu(menubar, "menu.read")
        
        self.make_action("menu.previous_chapter", self.previous_chapter,
                         "nav.prev_chapter", READER)
        read_menu.addAction(self._actions["nav.prev_chapter"])
        
        self.make_action("menu.next_chapter", self.next_chapter,
                         "nav.next_chapter", READER)
        read_menu.addAction(self._actions["nav.next_chapter"])
        
        read_menu.addSeparator()
        
        self.make_action("menu.goto_chapter", self.goto_chapter,
                         "nav.goto_chapter")
        read_menu.addAction(self._actions["nav.goto_chapter"])
        
        self.make_action("menu.chapter_start", self.scroll_to_chapter_start,
                         "nav.chapter_start")
        read_menu.addAction(self._actions["nav.chapter_start"])
        
        self.make_action("menu.chapter_end", self.scroll_to_chapter_end,
                         "nav.chapter_end")
        read_menu.addAction(self._actions["nav.chapter_end"])
        
        # 设置菜单
        view_menu = self.add_menu(menubar, "menu.settings")
        
        theme_menu = self.add_menu(view_menu, "menu.theme")
        
        self.make_action("menu.theme_light",
                         lambda: self.change_theme("light"),
                         "view.theme_light")
        theme_menu.addAction(self._actions["view.theme_light"])
        
        self.make_action("menu.theme_dark",
                         lambda: self.change_theme("dark"),
                         "view.theme_dark")
        theme_menu.addAction(self._actions["view.theme_dark"])
        
        theme_menu.addSeparator()
        
        theme_menu.addAction(self.make_action("menu.theme_import",
                                              self.import_theme))
        theme_menu.addAction(self.make_action("menu.theme_export",
                                              self.export_theme))
        theme_menu.addAction(self.make_action("menu.theme_generator",
                                              self.open_theme_generator))
        
        # 字体设置
        self.make_action("menu.font_settings", self.change_font,
                         "view.font_dialog")
        view_menu.addAction(self._actions["view.font_dialog"])
        
        self.make_action("menu.font_increase", self.increase_font_size,
                         "view.font_inc")
        view_menu.addAction(self._actions["view.font_inc"])
        
        self.make_action("menu.font_decrease", self.decrease_font_size,
                         "view.font_dec")
        view_menu.addAction(self._actions["view.font_dec"])
        
        # 记住章内阅读位置
        self.restore_scroll_action = self.make_action(
            "menu.restore_scroll", self.toggle_restore_scroll)
        self.restore_scroll_action.setCheckable(True)
        self.restore_scroll_action.setChecked(
            self.config_manager.get("restore_scroll_position", True))
        view_menu.addAction(self.restore_scroll_action)
        
        # 快捷键设置
        self.make_action("menu.shortcut_settings", self.open_shortcut_dialog,
                         "view.shortcut_config")
        view_menu.addAction(self._actions["view.shortcut_config"])
        
        # 语言设置（选项来自 i18n.available_languages，新增语言无需改这里）
        self.language_menu = self.add_menu(view_menu, "menu.language")
        self.language_actions = {}
        for code in i18n.available_languages():
            action = QAction(i18n.language_name(code), self)
            action.setCheckable(True)
            action.setChecked(code == i18n.current_language())
            action.triggered.connect(
                lambda _checked=False, target=code: self.change_language(target))
            self.language_menu.addAction(action)
            self.language_actions[code] = action
        
        # 帮助菜单
        help_menu = self.add_menu(menubar, "menu.help")
        help_menu.addAction(self.make_action("menu.about", self.show_about))
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = QToolBar()
        self.bind_text(toolbar, "toolbar.main", "setWindowTitle")
        self.addToolBar(toolbar)
        
        open_action = self.make_action("toolbar.open_file", self.open_file)
        self.bind_hint(open_action, "file.open")
        toolbar.addAction(open_action)
        
        continue_action = self.make_action("toolbar.continue_reading",
                                           self.show_continue_reading)
        self.bind_hint(continue_action, "file.continue")
        toolbar.addAction(continue_action)
        
        toolbar.addSeparator()
        
        # 章节列表显示/隐藏按钮
        self.toggle_sidebar_action = self.make_action(
            self._sidebar_action_key, self.toggle_sidebar, "view.toggle_sidebar")
        toolbar.addAction(self.toggle_sidebar_action)
        
        toolbar.addSeparator()
        
        prev_action = self.make_action("toolbar.previous_chapter",
                                       self.previous_chapter)
        self.bind_hint(prev_action, "nav.prev_chapter")
        toolbar.addAction(prev_action)
        
        next_action = self.make_action("toolbar.next_chapter",
                                       self.next_chapter)
        self.bind_hint(next_action, "nav.next_chapter")
        toolbar.addAction(next_action)
    
    # ---------------- 快捷键 ----------------
    
    def register_action(self, action_id, action, scope=WINDOW):
        """登记动作并套用当前绑定
        
        窗口级动作（``WINDOW``）用 ``Qt.WindowShortcut``，窗口内任意位置都生效；
        阅读区级动作（``READER``）挂在阅读区上，只在阅读区获得焦点时生效
        （同时会出现在阅读区的右键菜单里）。
        """
        if action_id not in DEFS_BY_ID:
            return action
        
        if scope == READER:
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.reader_display.addAction(action)
        else:
            action.setShortcutContext(Qt.WindowShortcut)
        
        self._actions[action_id] = action
        self.apply_action_shortcut(action_id)
        return action
    
    def apply_action_shortcut(self, action_id):
        """把注册表里的按键套用到动作上，并刷新提示文本"""
        action = self._actions.get(action_id)
        if action is None:
            return
        action.setShortcut(key_sequence(self.shortcut_manager.get(action_id)))
        self.update_action_hint(action_id)
    
    def update_action_hint(self, action_id):
        """把快捷键写进动作的提示文本
        
        用动作「当前」的文本拼提示，兼容「显示/隐藏章节列表」这类会变文案的动作。
        """
        action = self._actions.get(action_id)
        if action is None:
            return
        text = i18n.t("common.label_with_keys",
                      default="{label}（{keys}）",
                      label=action.text(),
                      keys=self.shortcut_manager.display(action_id))
        action.setToolTip(text)
        action.setStatusTip(text)
    
    def bind_hint(self, widget, action_id):
        """让普通按钮 / 工具栏动作的提示跟着快捷键变化"""
        self._hint_widgets.append((widget, action_id))
        widget.setToolTip(self.hint_text(action_id))
        return widget
    
    def hint_text(self, action_id):
        """「功能名（快捷键）」形式的提示文本（功能名跟随语言）"""
        label = label_of(action_id)
        if not label:
            definition = DEFS_BY_ID.get(action_id)
            label = definition.label if definition else ""
        return i18n.t("common.label_with_keys",
                      default="{label}（{keys}）",
                      label=label,
                      keys=self.shortcut_manager.display(action_id))
    
    def _refresh_widget_hints(self):
        """刷新普通按钮 / 工具栏动作的提示文本"""
        for widget, action_id in self._hint_widgets:
            widget.setToolTip(self.hint_text(action_id))
    
    def _snapshot_bindings(self):
        """按生效范围缓存绑定快照，供阅读区按键过滤使用"""
        self._window_bindings = {}
        self._reader_bindings = {}
        for definition in ACTION_DEFS:
            text = self.shortcut_manager.get(definition.action_id)
            if not text:
                continue
            target = (self._reader_bindings if definition.scope == READER
                      else self._window_bindings)
            target[definition.action_id] = key_sequence(text)
    
    def refresh_shortcuts(self):
        """改键后重新套用全部快捷键"""
        for action_id in list(self._actions):
            self.apply_action_shortcut(action_id)
        self._snapshot_bindings()
        self._refresh_widget_hints()
    
    def open_shortcut_dialog(self):
        """打开快捷键设置面板"""
        dialog = ShortcutSettingsDialog(self.shortcut_manager, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self.refresh_shortcuts()
        self.logger.log("快捷键设置已更新")
    
    def eventFilter(self, obj, event):
        """阅读区按键过滤
        
        * ``ShortcutOverride``：把 Ctrl+Home / Ctrl+End 这类按键放行给窗口级快捷键，
          否则会被 ``QTextEdit`` 自带的「文档首 / 文档尾」吃掉；
        * ``KeyPress``：派发只在阅读区生效的按键（方向键、翻页键）。
        """
        display = getattr(self, "reader_display", None)
        if display is None or obj not in (display, display.viewport()):
            return super().eventFilter(obj, event)
        
        if event.type() == QEvent.ShortcutOverride:
            sequence = event_key_sequence(event)
            for binding in self._window_bindings.values():
                if sequence == binding:
                    event.ignore()
                    return True
            return super().eventFilter(obj, event)
        
        if event.type() == QEvent.KeyPress:
            sequence = event_key_sequence(event)
            for action_id, binding in self._reader_bindings.items():
                if sequence != binding:
                    continue
                if event.isAutoRepeat():
                    # 长按不连续翻章，避免一不小心翻掉几十章
                    return True
                handler = self._reader_handlers.get(action_id)
                if handler is not None:
                    handler()
                return True
            return super().eventFilter(obj, event)
        
        return super().eventFilter(obj, event)
    
    def apply_settings(self):
        """应用设置"""
        # 应用主题
        theme_name = self.config_manager.get("theme", "light")
        self.apply_theme(theme_name)
        
        # 应用字体
        font_family = self.config_manager.get("font_family", "Microsoft YaHei")
        font_size = self.config_manager.get("font_size", 16)
        self.apply_font(font_family, font_size)
        
        # 应用窗口设置
        window_size = self.config_manager.get("window_size", [1200, 800])
        window_position = self.config_manager.get("window_position", [100, 100])
        self.resize(*window_size)
        self.move(*window_position)
        
        # 应用侧边栏状态
        self.sidebar_visible = self.config_manager.get("sidebar_visible", True)
        if self.sidebar_visible:
            self.sidebar.show()
            self.toggle_sidebar_btn.show()
        else:
            self.sidebar.hide()
        # 文案（显示 / 隐藏）已随之改变，刷新按钮、工具栏动作与提示文本
        self._refresh_sidebar_text()
        self.update_progress()
    
    def apply_theme(self, theme_name):
        """应用主题"""
        theme = self.theme_manager.get_theme(theme_name)

        # 强调色底上的文字色，样式表里多处复用
        on_accent = self.color_on_accent(theme)

        # 应用样式表
        # 注意：Qt 样式表只能命中写了选择器的控件，不会把 QMainWindow 的
        # color 继承给子控件。所以没写规则的控件（进度条上方的“阅读进度”
        # 这个 QLabel、菜单栏、工具栏等）在深色主题下会一直是 Qt 默认的
        # 浅底黑字，必须逐个补上规则。
        style_sheet = f"""
        QMainWindow {{
            background-color: {theme['background']};
            color: {theme['foreground']};
        }}
        QTextEdit {{
            background-color: {theme['background']};
            color: {theme['foreground']};
            border: 1px solid {theme['border']};
            font-size: {self.config_manager.get('font_size', 12)}px;
            line-height: {self.config_manager.get('line_spacing', 1.5)};
        }}
        QTreeWidget {{
            background-color: {theme['background']};
            color: {theme['foreground']};
            border: 1px solid {theme['border']};
        }}
        /* 标签：限定在侧栏内。样式表会沿对象树往对话框里渗，
           而对话框自身底色不受 #sidebar 影响，全域设 QLabel 会把
           对话框的文字刷成白字压在浅底上 */
        #sidebar QLabel {{
            color: {theme['foreground']};
        }}
        /* 菜单栏 / 菜单：Windows 样式会自己画一块浅色底，
           所以得用规则明确指定颜色 */
        QMenuBar {{
            background-color: {theme['background']};
            color: {theme['foreground']};
        }}
        QMenuBar::item {{
            background: transparent;
            color: {theme['foreground']};
            padding: 4px 8px;
        }}
        QMenuBar::item:selected {{
            background-color: {theme['accent']};
            color: {on_accent};
        }}
        QMenu {{
            background-color: {theme['background']};
            color: {theme['foreground']};
            border: 1px solid {theme['border']};
        }}
        QMenu::item {{
            color: {theme['foreground']};
        }}
        QMenu::item:selected {{
            background-color: {theme['accent']};
            color: {on_accent};
        }}
        QMenu::separator {{
            background-color: {theme['border']};
            height: 1px;
        }}
        QToolBar {{
            background-color: {theme['background']};
            border: none;
            spacing: 4px;
        }}
        QToolButton {{
            color: {theme['foreground']};
            background: transparent;
            padding: 4px 6px;
            border-radius: 3px;
        }}
        QToolButton:hover {{
            background-color: {theme['accent']};
            color: {on_accent};
        }}
        QToolButton:disabled {{
            color: {theme['border']};
        }}
        QProgressBar {{
            background-color: {theme['background']};
            color: {theme['foreground']};
            border: 1px solid {theme['border']};
            border-radius: 4px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {theme['accent']};
            border-radius: 3px;
        }}
        QPushButton {{
            background-color: {theme['accent']};
            color: {on_accent};
            border: none;
            padding: 5px 10px;
        }}
        QPushButton:hover {{
            background-color: {theme['highlight']};
        }}
        """

        self.setStyleSheet(style_sheet)

    @staticmethod
    def color_on_accent(theme):
        """返回强调色底上应该用的文字色：浅底配深字，深底配白字"""
        accent = QColor(theme['accent'])
        if accent.lightness() > 150:
            return QColor(theme['background']).name()
        return QColor("#FFFFFF").name()

    def apply_font(self, font_family, font_size):
        """应用字体设置"""
        font = QFont(font_family, font_size)
        self.reader_display.setFont(font)
    
    def setup_auto_save(self):
        """设置自动保存"""
        if self.config_manager.get("auto_save", True):
            interval = self.config_manager.get("auto_save_interval", 30) * 1000  # 转换为毫秒
            self.auto_save_timer.start(interval)
    
    def open_file(self):
        """打开文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.open_file"), "", build_open_file_filter()
        )
        
        if file_path:
            self.load_file(file_path)
    
    def open_folder(self):
        """打开文件夹"""
        folder_path = QFileDialog.getExistingDirectory(
            self, i18n.t("dialog.open_folder"))
        
        if folder_path:
            self.load_folder(folder_path)
    
    def load_file(self, file_path):
        """加载文件"""
        try:
            file_path = Path(file_path)
            
            if DEBUG_MODE:
                self.logger.debug(f"开始加载文件: {file_path}")
            
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                QMessageBox.warning(
                    self, i18n.t("common.error"),
                    i18n.t("msg.unsupported_format",
                           extension=file_path.suffix or i18n.t("common.unknown"),
                           supported=supported_extensions_text())
                )
                if DEBUG_MODE:
                    self.logger.debug(f"不支持的文件格式: {file_path.suffix}")
                return
            
            # 创建阅读器（失败时保留当前正在阅读的文件）
            try:
                new_reader = create_reader(str(file_path))
            except ReaderError as e:
                QMessageBox.warning(self, i18n.t("msg.cannot_open_file"),
                                    f"{file_path.name}\n\n{e}")
                self.logger.log(f"无法打开文件: {file_path} - {e}", "ERROR")
                return
            
            # 切换书籍前先把上一本的进度与阅读时长落盘
            if self.current_reader is not None:
                self.save_reading_progress()
            
            self.release_current_reader()
            self.current_reader = new_reader
            if DEBUG_MODE:
                self.logger.debug(f"创建 {type(self.current_reader).__name__} 阅读器，"
                                  f"章节数: {self.current_reader.get_chapter_count()}")
            
            self.current_file_path = file_path
            self.update_recent_files(str(file_path))
            
            # 先更新章节列表
            self.update_chapter_list()
            
            # 然后恢复阅读进度
            self.load_reading_progress()
            
            # 最后显示内容
            self.display_content()
            
            self.update_window_title()
            
            self.logger.log(f"成功加载文件: {file_path}")
            
            if DEBUG_MODE:
                self.logger.debug(f"文件加载完成，当前章节: {self.current_reader.current_chapter if self.current_reader else 'N/A'}")
            
        except Exception as e:
            QMessageBox.critical(self, i18n.t("common.error"),
                                 i18n.t("msg.load_file_failed", error=str(e)))
            self.logger.log(f"加载文件失败: {e}", "ERROR")
            if DEBUG_MODE:
                self.logger.debug(f"加载文件异常详情: {e}", exc_info=True)
    
    def load_folder(self, folder_path):
        """加载文件夹"""
        try:
            new_reader = FolderReader(folder_path)
            
            if new_reader.get_file_count() == 0:
                QMessageBox.information(self, i18n.t("common.info"),
                                        i18n.t("msg.no_supported_files"))
                new_reader.close()
                return
            
            # 切换书籍前先把上一本的进度与阅读时长落盘
            if self.current_reader is not None:
                self.save_reading_progress()
            
            self.release_current_reader()
            self.current_reader = new_reader
            self.current_file_path = Path(folder_path)
            
            # 先更新章节列表
            self.update_chapter_list()
            
            # 然后恢复阅读进度（内部会重建章节列表，因为当前文件可能发生变化）
            self.load_reading_progress()
            
            # 最后显示内容
            self.display_content()
            
            self.update_window_title()
            
            self.logger.log(f"成功加载文件夹: {folder_path}")
            
        except Exception as e:
            QMessageBox.critical(self, i18n.t("common.error"),
                                 i18n.t("msg.load_folder_failed", error=str(e)))
            self.logger.log(f"加载文件夹失败: {e}", "ERROR")
    
    def display_content(self):
        """显示内容"""
        if not self.current_reader:
            return
        
        reader = self.current_reader
        if isinstance(reader, FolderReader):
            inner = reader.get_current_reader()
            if not inner or inner.get_chapter_count() == 0:
                self.reader_display.setHtml("<p>%s</p>" % i18n.t(
                    "msg.no_displayable_content_folder"))
                self.update_progress()
                return
            # 修正越界的章节索引
            if not (0 <= inner.current_chapter < inner.get_chapter_count()):
                inner.current_chapter = 0
            # 让文件夹层与外层进度保持同步
            reader.current_chapter = inner.current_chapter
            title = inner.get_chapter_title(inner.current_chapter)
            content = inner.get_chapter_content(inner.current_chapter)
            chapter_index = inner.current_chapter
        else:
            if reader.get_chapter_count() == 0:
                self.reader_display.setHtml("<p>%s</p>" % i18n.t(
                    "msg.no_displayable_content"))
                self.update_progress()
                return
            if not (0 <= reader.current_chapter < reader.get_chapter_count()):
                reader.current_chapter = 0
            title = reader.get_chapter_title(reader.current_chapter)
            content = reader.get_chapter_content(reader.current_chapter)
            chapter_index = reader.current_chapter
        
        self.reader_display.setHtml(format_chapter_html(title, content))

        # 图片自适应阅读区宽度（重新渲染章节时重置缓存）
        self._image_widths = {}
        self.fit_document_images()

        # 统计已读章节，并按记录恢复章内位置（无待恢复值时回到章首）
        self.mark_chapter_read(chapter_index)
        self.restore_pending_scroll()
        
        self.update_progress()

    # ---------------- 内嵌图片展示 ----------------

    def resizeEvent(self, event):
        """窗口尺寸变化后重新计算图片显示宽度"""
        super().resizeEvent(event)
        if self.current_reader is not None:
            self.image_fit_timer.start(150)

    def changeEvent(self, event):
        """窗口激活状态变化时开始/暂停阅读计时"""
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange:
            self.on_activation_changed(self.isActiveWindow())

    def fit_document_images(self):
        """把超过阅读区宽度的内嵌图片缩小到阅读区宽度"""
        display = getattr(self, 'reader_display', None)
        if display is None:
            return

        available = display.viewport().width() - 24
        if available < 80:
            return

        document = display.document()
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        try:
            block = document.begin()
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid():
                        char_format = fragment.charFormat()
                        if char_format.isImageFormat():
                            self._fit_image_fragment(cursor, fragment,
                                                     char_format.toImageFormat(),
                                                     available)
                    iterator += 1
                block = block.next()
        finally:
            cursor.endEditBlock()

    def _fit_image_fragment(self, cursor, fragment, image_format, available):
        """按需调整单个图片片段的宽度"""
        natural = self._image_natural_width(image_format.name())
        if natural <= 0:
            return

        target = min(natural, float(available))
        if abs(image_format.width() - target) < 0.5:
            return

        image_format.setWidth(target)
        cursor.setPosition(fragment.position())
        cursor.setPosition(fragment.position() + fragment.length(),
                           QTextCursor.KeepAnchor)
        cursor.setCharFormat(image_format)

    def _image_natural_width(self, resource_name):
        """获取图片原始宽度（仅对 data URI 生效，结果按章节缓存）"""
        if not resource_name:
            return 0
        cached = self._image_widths.get(resource_name)
        if cached is not None:
            return cached

        width = 0
        if resource_name.startswith('data:'):
            try:
                _header, _, payload = resource_name.partition(',')
                image = QImage.fromData(base64.b64decode(payload))
                if not image.isNull():
                    width = image.width()
            except Exception:
                width = 0

        self._image_widths[resource_name] = width
        return width
    
    def update_chapter_list(self):
        """更新章节列表"""
        self.chapter_tree.blockSignals(True)
        try:
            self.chapter_tree.clear()
            
            if not self.current_reader:
                return
            
            if isinstance(self.current_reader, FolderReader):
                # 文件夹模式：显示文件列表，当前文件下展开其章节
                for i, file_info in enumerate(self.current_reader.files):
                    item = QTreeWidgetItem([file_info['name']])
                    item.setData(0, Qt.UserRole, ("file", i))
                    self.chapter_tree.addTopLevelItem(item)
                
                current_index = self.current_reader.current_file_index
                if 0 <= current_index < len(self.current_reader.files):
                    current_item = self.chapter_tree.topLevelItem(current_index)
                    inner = self.current_reader.get_current_reader()
                    if current_item is not None and inner is not None:
                        for j in range(inner.get_chapter_count()):
                            child = QTreeWidgetItem([inner.get_chapter_title(j)])
                            child.setData(0, Qt.UserRole, ("chapter", j))
                            current_item.addChild(child)
                        current_item.setExpanded(True)
                        if 0 <= inner.current_chapter < current_item.childCount():
                            self.chapter_tree.setCurrentItem(
                                current_item.child(inner.current_chapter))
                        else:
                            self.chapter_tree.setCurrentItem(current_item)
            else:
                # 单文件模式：显示章节列表
                for i in range(self.current_reader.get_chapter_count()):
                    title = self.current_reader.get_chapter_title(i)
                    item = QTreeWidgetItem([title])
                    item.setData(0, Qt.UserRole, ("chapter", i))
                    self.chapter_tree.addTopLevelItem(item)
                
                # 高亮当前章节
                index = self.current_reader.current_chapter
                item = self.chapter_tree.topLevelItem(index)
                if item:
                    self.chapter_tree.setCurrentItem(item)
        finally:
            self.chapter_tree.blockSignals(False)
    
    def on_chapter_selected(self, item):
        """章节选择事件"""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type, index = data
        
        if item_type == "file" and isinstance(self.current_reader, FolderReader):
            if index == self.current_reader.current_file_index:
                return
            self.current_reader.current_file_index = index
            inner = self.current_reader.get_current_reader()
            if inner is not None:
                # 切换到文件后重建章节列表（不同文件的章节结构不同）
                self.update_chapter_list()
            self.display_content()
        elif item_type == "chapter":
            if isinstance(self.current_reader, FolderReader):
                reader = self.current_reader.get_current_reader()
                if reader:
                    reader.current_chapter = index
            else:
                self.current_reader.current_chapter = index
            self.display_content()
    
    def previous_chapter(self):
        """上一章（文件夹模式下可跨文件回退）"""
        if not self.current_reader:
            if DEBUG_MODE:
                self.logger.debug("切换到上一章失败: 没有当前阅读器")
            return
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            if reader is None:
                return
            
            if reader.current_chapter > 0:
                reader.current_chapter -= 1
            else:
                # 回退到上一个文件
                moved = False
                index = self.current_reader.current_file_index
                while index > 0:
                    index -= 1
                    self.current_reader.current_file_index = index
                    prev_reader = self.current_reader.get_current_reader()
                    if prev_reader is not None and prev_reader.get_chapter_count() > 0:
                        prev_reader.current_chapter = prev_reader.get_chapter_count() - 1
                        moved = True
                        break
                if not moved:
                    if DEBUG_MODE:
                        self.logger.debug("已经是第一篇，无法切换到上一章")
                    return
                self.update_chapter_list()
        elif self.current_reader.current_chapter > 0:
            self.current_reader.current_chapter -= 1
            if DEBUG_MODE:
                self.logger.debug(f"单文件模式: 切换到章节 {self.current_reader.current_chapter}")
        else:
            if DEBUG_MODE:
                self.logger.debug("已经是第一章，无法切换到上一章")
            return
        
        self.display_content()
    
    def next_chapter(self):
        """下一章（文件夹模式下可跨文件前进）"""
        if not self.current_reader:
            if DEBUG_MODE:
                self.logger.debug("切换到下一章失败: 没有当前阅读器")
            return
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            if reader is None:
                return
            
            if reader.current_chapter < reader.get_chapter_count() - 1:
                reader.current_chapter += 1
            else:
                # 前进到下一个文件
                moved = False
                index = self.current_reader.current_file_index
                while index < len(self.current_reader.files) - 1:
                    index += 1
                    self.current_reader.current_file_index = index
                    next_reader = self.current_reader.get_current_reader()
                    if next_reader is not None and next_reader.get_chapter_count() > 0:
                        next_reader.current_chapter = 0
                        moved = True
                        break
                if not moved:
                    if DEBUG_MODE:
                        self.logger.debug("已经是最后一篇，无法切换到下一章")
                    return
                self.update_chapter_list()
        elif self.current_reader.current_chapter < self.current_reader.get_chapter_count() - 1:
            self.current_reader.current_chapter += 1
            if DEBUG_MODE:
                self.logger.debug(f"单文件模式: 切换到章节 {self.current_reader.current_chapter}")
        else:
            if DEBUG_MODE:
                self.logger.debug("已经是最后一章，无法切换到下一章")
            return
        
        self.display_content()
    
    # ---------------- 章节跳转与章内位置 ----------------
    
    def chapter_count(self):
        """当前文件的章节总数（未打开书籍时为 0）"""
        if not self.current_reader:
            return 0
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            return reader.get_chapter_count() if reader else 0
        return self.current_reader.get_chapter_count()
    
    def current_chapter_index(self):
        """当前章节序号（未打开书籍时为 0）"""
        if not self.current_reader:
            return 0
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            return reader.current_chapter if reader else 0
        return self.current_reader.current_chapter
    
    def goto_chapter(self):
        """「转到章节」：按当前文件内的章节序号跳转"""
        total = self.chapter_count()
        if total <= 0:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return
        
        current = self.current_chapter_index()
        number, ok = QInputDialog.getInt(
            self, i18n.t("dialog.goto_chapter"),
            i18n.t("dialog.goto_chapter_prompt", total=total),
            current + 1, 1, total, 1)
        if not ok:
            return
        
        self.jump_to_chapter(number - 1)
    
    def jump_to_chapter(self, index):
        """切换到指定章节（越界自动夹到有效范围）"""
        total = self.chapter_count()
        if total <= 0:
            return
        
        index = max(0, min(int(total) - 1, int(index)))
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            if reader is None:
                return
            reader.current_chapter = index
        else:
            self.current_reader.current_chapter = index
        
        self.display_content()
        self.select_chapter_in_tree("chapter", index)
        if DEBUG_MODE:
            self.logger.debug(f"跳转到章节 {index + 1}/{total}")
    
    def scroll_to_chapter_start(self):
        """回到当前章节开头"""
        self.reader_display.verticalScrollBar().setValue(0)
    
    def scroll_to_chapter_end(self):
        """跳到当前章节末尾"""
        scroll = self.reader_display.verticalScrollBar()
        scroll.setValue(scroll.maximum())
    
    def update_progress(self):
        """更新进度"""
        if not self.current_reader:
            self.progress_label.setText(
                i18n.t("sidebar.progress", percent="0.0"))
            self.progress_bar.setValue(0)
            return
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            if reader and reader.get_chapter_count():
                progress = (reader.current_chapter + 1) / reader.get_chapter_count() * 100
            else:
                progress = 0
        else:
            count = self.current_reader.get_chapter_count()
            progress = ((self.current_reader.current_chapter + 1) / count * 100
                        if count else 0)
        
        self.progress_bar.setValue(int(progress))
        self.progress_label.setText(
            i18n.t("sidebar.progress", default="阅读进度: {percent}%",
                   percent=f"{progress:.1f}"))
    
    def update_recent_files(self, file_path):
        """更新最近文件列表"""
        recent_files = self.config_manager.get("recent_files", [])
        
        if file_path in recent_files:
            recent_files.remove(file_path)
        
        recent_files.insert(0, file_path)
        
        # 限制最近文件数量
        if len(recent_files) > 10:
            recent_files = recent_files[:10]
        
        self.config_manager.set("recent_files", recent_files)
        self.update_recent_files_menu()
    
    def update_recent_files_menu(self):
        """更新最近文件菜单"""
        self.recent_menu.clear()
        recent_files = self.config_manager.get("recent_files", [])
        
        for file_path in recent_files:
            action = QAction(Path(file_path).name, self)
            action.triggered.connect(lambda checked, path=file_path: self.load_file(path))
            self.recent_menu.addAction(action)
    
    def progress_key(self):
        """当前书籍的阅读记录键（文件按内容哈希，文件夹按路径哈希）"""
        if not self.current_file_path:
            return ""
        return self.progress_manager.build_file_key(self.current_file_path)

    def legacy_progress_key(self):
        """旧版本使用的阅读记录键（直接是路径），仅用于迁移旧记录"""
        return str(self.current_file_path) if self.current_file_path else ""

    def progress_metadata(self):
        """生成阅读记录的元数据：文件名、内容哈希、书名与作者等。"""
        if not self.current_file_path:
            return {}

        path = Path(str(self.current_file_path))
        metadata = self.progress_manager.key_metadata(self.current_file_path,
                                                      self.progress_key())

        info = {}
        if self.current_reader:
            try:
                info = self.current_reader.get_book_info() or {}
            except Exception as e:
                self.logger.log(f"读取书籍信息失败: {e}", "WARN")
                info = {}

        title = str(info.get("title") or "").strip()
        author = str(info.get("author") or "").strip()
        # 书名缺失时回退到文件名（文件夹模式则用文件夹名）
        if not title:
            title = path.name if path.is_dir() else path.stem

        metadata["novelname"] = title
        metadata["author"] = author
        metadata["app_version"] = VERSION

        if self.current_reader:
            try:
                metadata["total_chapters"] = self.current_reader.get_chapter_count()
            except Exception as e:
                self.logger.log(f"获取章节总数失败: {e}", "WARN")

        if isinstance(self.current_reader, FolderReader):
            current = self.current_reader.get_current_file()
            if current:
                metadata["inner_filename"] = current['name']
                try:
                    _, metadata["inner_md5"] = split_file_key(
                        self.progress_manager.build_file_key(current['path']))
                except Exception as e:
                    self.logger.log(f"计算内层文件哈希失败: {e}", "WARN")

        return metadata

    @staticmethod
    def chapter_title_of(reader, index):
        """安全地取章节标题（越界或阅读器异常时返回空字符串）"""
        try:
            if reader and 0 <= index < reader.get_chapter_count():
                return reader.get_chapter_title(index) or ""
        except Exception:
            pass
        return ""

    def load_reading_progress(self):
        """加载阅读进度"""
        if not self.current_file_path or not self.current_reader:
            return

        file_key = self.progress_key()
        progress = self.progress_manager.load_progress(file_key, self.legacy_progress_key())

        # 打开次数 +1、载入统计数据并开始本次阅读计时
        self.begin_reading_session(progress)
        
        if progress:
            # 恢复阅读位置
            if isinstance(self.current_reader, FolderReader):
                # 文件夹模式：恢复文件索引和章节（优先按内层文件名定位，
                # 这样增删文件导致顺序变化时也能找到原来那本）
                file_index = progress.get("file_index", 0)
                inner_name = progress.get("inner_filename")
                if inner_name:
                    for i, item in enumerate(self.current_reader.files):
                        if item['name'] == inner_name:
                            file_index = i
                            break
                chapter_index = progress.get("chapter", 0)
                
                if 0 <= file_index < self.current_reader.get_file_count():
                    self.current_reader.current_file_index = file_index
                    reader = self.current_reader.get_current_reader()
                    if reader and 0 <= chapter_index < reader.get_chapter_count():
                        reader.current_chapter = chapter_index
                    # 文件可能已变化，重建章节列表后再选中
                    self.update_chapter_list()
                    self.select_chapter_in_tree("file", file_index)
            else:
                # 单文件模式：恢复章节
                chapter_index = progress.get("chapter", 0)
                if 0 <= chapter_index < self.current_reader.get_chapter_count():
                    self.current_reader.current_chapter = chapter_index
                    # 自动选中对应的章节
                    self.select_chapter_in_tree("chapter", chapter_index)

            # 章内位置：只在开关打开且重新打开的是同一章节时才还原
            if self.config_manager.get("restore_scroll_position", True):
                try:
                    self._pending_scroll_percent = float(progress.get("scroll_percent") or 0)
                except (TypeError, ValueError):
                    self._pending_scroll_percent = 0.0
            else:
                self._pending_scroll_percent = 0.0
            
            self.logger.log(f"恢复阅读进度: {file_key} -> 章节 {chapter_index}")

    def select_chapter_in_tree(self, item_type, index):
        """在章节树中选中指定章节（支持文件夹模式下的子节点）"""
        for i in range(self.chapter_tree.topLevelItemCount()):
            top_item = self.chapter_tree.topLevelItem(i)
            data = top_item.data(0, Qt.UserRole)
            if data and data[0] == item_type and data[1] == index:
                self.chapter_tree.setCurrentItem(top_item)
                return
            
            for j in range(top_item.childCount()):
                child = top_item.child(j)
                child_data = child.data(0, Qt.UserRole)
                if child_data and child_data[0] == item_type and child_data[1] == index:
                    self.chapter_tree.setCurrentItem(child)
                    return
    
    def save_reading_progress(self):
        """保存阅读进度、阅读统计与章内位置"""
        if not self.current_file_path or not self.current_reader:
            return
        
        # 先把当前专注时段结算掉，保证阅读时长不丢
        self.accumulate_focus_time()
        
        file_key = self.progress_key()
        file_path = str(self.current_file_path)
        progress_data = {
            "file_path": file_path,
            "timestamp": time.time(),
        }
        progress_data.update(self.progress_metadata())
        progress_data.update(self.serialize_stats())
        progress_data["scroll_percent"] = self.current_scroll_percent()
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            if reader:
                chapter = reader.current_chapter
                progress_data.update({
                    "chapter": chapter,
                    "file_index": self.current_reader.current_file_index,
                    "chapter_title": self.chapter_title_of(reader, chapter),
                })
        else:
            chapter = self.current_reader.current_chapter
            progress_data.update({
                "chapter": chapter,
                "chapter_title": self.chapter_title_of(self.current_reader, chapter),
            })
        
        if self.progress_manager.save_progress(file_key, progress_data):
            self.logger.log(f"保存阅读进度: {file_path} -> 章节 {progress_data.get('chapter', 0)}")
        else:
            self.logger.log(f"保存阅读进度失败: {file_path}", "ERROR")
    
    # ---------------- 阅读统计 ----------------

    @staticmethod
    def empty_stats():
        """空白的统计状态（与阅读记录里的统计字段对应）"""
        return {
            "open_count": 0,
            "first_opened_at": "",
            "last_opened_at": "",
            "total_read_seconds": 0.0,
            "session_read_seconds": 0.0,
            "read_chapters": {},
        }

    def current_unit_name(self):
        """统计单元名：单文件模式是文件名，文件夹模式是当前内层文件名"""
        if isinstance(self.current_reader, FolderReader):
            current = self.current_reader.get_current_file()
            if current:
                return str(current['name'])
        if self.current_file_path:
            return Path(str(self.current_file_path)).name
        return ""

    def begin_reading_session(self, progress):
        """载入记录里的统计数据并开始本次会话（打开次数 +1、记录打开时间）"""
        self.finish_reading_session()
        
        progress = progress or {}
        read_chapters = {}
        for unit, indexes in (progress.get("read_chapters") or {}).items():
            try:
                read_chapters[str(unit)] = {int(index) for index in indexes}
            except (TypeError, ValueError):
                continue
        
        self._stats = {
            "open_count": int(progress.get("open_count") or 0) + 1,
            "first_opened_at": progress.get("first_opened_at") or format_timestamp(),
            "last_opened_at": format_timestamp(),
            "total_read_seconds": float(progress.get("total_read_seconds") or 0),
            "session_read_seconds": 0.0,
            "read_chapters": read_chapters,
        }
        # 只有窗口处于激活状态才计时
        self._focus_started_at = time.monotonic() if self.isActiveWindow() else None

    def finish_reading_session(self):
        """结算本次阅读时长并停止计时"""
        self.accumulate_focus_time()
        self._focus_started_at = None

    def accumulate_focus_time(self):
        """把当前专注段落的时长累加进统计（未计时时返回 0）"""
        if self._focus_started_at is None:
            return 0.0
        
        now = time.monotonic()
        elapsed = max(0.0, now - self._focus_started_at)
        self._focus_started_at = now
        self._stats["total_read_seconds"] += elapsed
        self._stats["session_read_seconds"] += elapsed
        return elapsed

    def on_activation_changed(self, active):
        """窗口激活状态变化：激活时开始计时，失焦时结算并落盘一次"""
        if active:
            if self.current_reader is not None and self._focus_started_at is None:
                self._focus_started_at = time.monotonic()
            return
        
        self.accumulate_focus_time()
        self._focus_started_at = None
        # 失焦时顺手保存一次，避免异常退出丢掉进度
        if self.current_reader is not None and self.config_manager.get("auto_save", True):
            self.save_reading_progress()

    def mark_chapter_read(self, index):
        """把章节记为已读（用于统计去重后的已读章节数）"""
        unit = self.current_unit_name()
        if not unit:
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if index < 0:
            return
        self._stats["read_chapters"].setdefault(unit, set()).add(index)

    def serialize_stats(self):
        """把内存里的统计数据转成可写入阅读记录的形式"""
        unit = self.current_unit_name()
        chapters = {
            name: sorted(indexes)
            for name, indexes in self._stats["read_chapters"].items()
            if indexes
        }
        return {
            "open_count": self._stats["open_count"],
            "first_opened_at": self._stats["first_opened_at"],
            "last_opened_at": self._stats["last_opened_at"],
            "total_read_seconds": round(self._stats["total_read_seconds"], 1),
            "session_read_seconds": round(self._stats["session_read_seconds"], 1),
            # max_chapter 取当前单元的最远章节，文件夹模式下各内层文件互不干扰
            "max_chapter": max(chapters.get(unit) or [0]),
            "read_chapters": chapters,
            "read_chapter_count": sum(len(indexes) for indexes in chapters.values()),
        }

    # ---------------- 章内位置 ----------------

    def current_scroll_percent(self):
        """当前章内滚动百分比（没有滚动空间时返回 0）"""
        scroll = self.reader_display.verticalScrollBar()
        maximum = scroll.maximum()
        if maximum <= 0:
            return 0.0
        return round(scroll.value() / maximum * 100, 2)

    def apply_scroll_percent(self, percent):
        """按百分比设置阅读区滚动位置"""
        scroll = self.reader_display.verticalScrollBar()
        maximum = scroll.maximum()
        if maximum > 0:
            scroll.setValue(int(round(maximum * float(percent) / 100.0)))

    def restore_pending_scroll(self):
        """应用待恢复的章内位置（没有待恢复值时回到章首）"""
        percent = self._pending_scroll_percent
        self._pending_scroll_percent = 0.0
        if percent and percent > 0:
            self.apply_scroll_percent(percent)
        else:
            self.reader_display.verticalScrollBar().setValue(0)

    def toggle_restore_scroll(self, checked):
        """切换「记住章内阅读位置」"""
        self.config_manager.set("restore_scroll_position", bool(checked))
        if not checked:
            self._pending_scroll_percent = 0.0

    def show_continue_reading(self):
        """打开「继续阅读」面板，选中记录后直接接着读"""
        dialog = ContinueReadingDialog(self.progress_manager, self)
        if dialog.exec_() != QDialog.Accepted or not dialog.selected_path:
            return
        
        path = Path(dialog.selected_path)
        if not path.exists():
            QMessageBox.warning(self, i18n.t("msg.file_missing"),
                                i18n.t("msg.file_missing_detail", path=path))
            return
        
        if path.is_dir():
            self.load_folder(str(path))
        else:
            self.load_file(str(path))
    
    def auto_save_progress(self):
        """自动保存进度"""
        auto_save_enabled = self.config_manager.get("auto_save", True)
        
        if DEBUG_MODE:
            self.logger.debug(f"自动保存检查 - 启用: {auto_save_enabled}, 当前文件: {self.current_file_path}")
        
        if auto_save_enabled and self.current_file_path:
            if DEBUG_MODE:
                self.logger.debug("开始自动保存阅读进度")
            
            self.save_reading_progress()
            
            if DEBUG_MODE:
                self.logger.debug("自动保存完成")
        elif DEBUG_MODE:
            if not auto_save_enabled:
                self.logger.debug("自动保存已禁用")
            elif not self.current_file_path:
                self.logger.debug("没有打开文件，跳过自动保存")
    
    def toggle_sidebar(self):
        """切换章节列表显示/隐藏"""
        self.sidebar_visible = not self.sidebar_visible
        
        if self.sidebar_visible:
            self.sidebar.show()
        else:
            self.sidebar.hide()
        
        # 文案（显示 / 隐藏）已随之改变，刷新按钮、工具栏动作与提示文本
        self._refresh_sidebar_text()
        
        # 保存侧边栏状态到配置
        self.config_manager.set("sidebar_visible", self.sidebar_visible)
    
    def change_theme(self, theme_name):
        """切换主题"""
        if DEBUG_MODE:
            self.logger.debug(f"切换主题: {theme_name}")
        
        self.config_manager.set("theme", theme_name)
        self.apply_theme(theme_name)
        
        if DEBUG_MODE:
            self.logger.debug(f"主题切换完成: {theme_name}")
    
    def change_font(self):
        """更改字体"""
        current_font = QFont(
            self.config_manager.get("font_family", "Microsoft YaHei"),
            self.config_manager.get("font_size", 16)
        )
        
        font, ok = QFontDialog.getFont(current_font, self)
        if ok:
            family = font.family()
            size = font.pointSize()
            if size <= 0:
                # 选到的是按像素定义的字号，退回原值，避免样式表里出现非法数值
                size = int(self.config_manager.get("font_size", 16) or 16)
            self.config_manager.set("font_family", family)
            self.config_manager.set("font_size", size)
            self.apply_font(family, size)
            # 主题样式表里也写了字号，改完字体要重新套用一次才生效
            self.apply_theme(self.config_manager.get("theme", "light"))
    
    def increase_font_size(self):
        """字体增大"""
        self._step_font_size(1)
    
    def decrease_font_size(self):
        """字体减小"""
        self._step_font_size(-1)
    
    def _step_font_size(self, delta):
        """按步长调整阅读区字号（限制在 FONT_SIZE_MIN ~ FONT_SIZE_MAX）"""
        current = int(self.config_manager.get("font_size", 16) or 16)
        target = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, current + delta))
        if target == current:
            if DEBUG_MODE:
                self.logger.debug(f"字号已到边界: {current}")
            return
        
        self.config_manager.set("font_size", target)
        self.apply_font(self.config_manager.get("font_family", "Microsoft YaHei"),
                        target)
        # 主题样式表里也写了字号，改完字号要重新套用一次才生效
        self.apply_theme(self.config_manager.get("theme", "light"))
        if DEBUG_MODE:
            self.logger.debug(f"阅读区字号: {target}")
    
    def change_language(self, lang_code):
        """切换界面语言（立即生效，无需重启）"""
        if not i18n.set_language(lang_code):
            self.logger.log(f"无法切换到语言: {lang_code}", "WARN")
            return
        
        self.config_manager.set("language", lang_code)
        # 日志由 LanguageManager.set_language 统一输出，这里不再重复记录
        self.retranslate_ui()
    
    def import_theme(self):
        """导入主题"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.import_theme"), "",
            i18n.t("common.theme_file_filter")
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    theme_data = json.load(f)
                
                theme_name = Path(file_path).stem
                if self.theme_manager.save_theme(theme_name, theme_data):
                    QMessageBox.information(self, i18n.t("common.success"),
                                            i18n.t("msg.theme_import_success"))
                else:
                    QMessageBox.warning(self, i18n.t("common.error"),
                                        i18n.t("msg.theme_import_failed"))
                    
            except Exception as e:
                QMessageBox.critical(self, i18n.t("common.error"),
                                     i18n.t("msg.theme_import_error",
                                            error=str(e)))
    
    def export_theme(self):
        """导出主题"""
        current_theme = self.config_manager.get("theme")
        theme_data = self.theme_manager.get_theme(current_theme)
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dialog.export_theme"), f"{current_theme}.json",
            i18n.t("common.theme_file_filter")
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(theme_data, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, i18n.t("common.success"),
                                        i18n.t("msg.theme_export_success"))
            except Exception as e:
                QMessageBox.critical(self, i18n.t("common.error"),
                                     i18n.t("msg.theme_export_error",
                                            error=str(e)))
    
    def open_theme_generator(self):
        """打开主题生成器"""
        dialog = ThemeGeneratorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            theme_data = dialog.get_theme_data()
            theme_name = theme_data["name"]
            
            if self.theme_manager.save_theme(theme_name, theme_data):
                QMessageBox.information(self, i18n.t("common.success"),
                                        i18n.t("msg.theme_create_success"))
                # 应用新主题
                self.config_manager.set("theme", theme_name)
                self.apply_theme(theme_name)
            else:
                QMessageBox.warning(self, i18n.t("common.error"),
                                    i18n.t("msg.theme_create_failed"))
    
    def show_about(self):
        """显示关于对话框"""
        feature_params = {
            "about.feature_formats": {"formats": supported_extensions_text()},
            "about.feature_folder": {},
            "about.feature_autosave": {},
            "about.feature_theme": {},
            "about.feature_i18n": {},
            "about.feature_shortcuts": {},
            "about.feature_ui": {},
        }
        features = "".join(f"<li>{i18n.t(key, **params)}</li>"
                           for key, params in feature_params.items())
        about_text = (
            f"<h2>{PROJECT_NAME}</h2>"
            f"<p>{i18n.t('about.version', version=VERSION)}</p>"
            f"<p>{i18n.t('about.author', author=AUTHOR_NAME)}</p>"
            f"<p>{i18n.t('about.description')}</p>"
            f"<p>{i18n.t('about.features')}</p>"
            f"<ul>{features}</ul>"
        )
        
        QMessageBox.about(self, i18n.t("about.title"), about_text)
    
    def closeEvent(self, event):
        """关闭事件"""
        # 保存窗口设置
        self.config_manager.set("window_size", [self.width(), self.height()])
        self.config_manager.set("window_position", [self.x(), self.y()])
        
        # 保存阅读进度
        self.save_reading_progress()
        
        # 结算本次阅读时长并停止计时
        self.finish_reading_session()
        
        # 停止自动保存定时器
        self.auto_save_timer.stop()
        
        # 释放阅读器（清理 ZIP/JAR/MOBI 等解压出来的临时文件）
        self.release_current_reader()
        
        self.logger.log(f"{PROJECT_NAME} 正常退出")
        event.accept()

    def release_current_reader(self):
        """释放当前阅读器及其占用的临时资源"""
        reader = getattr(self, "current_reader", None)
        if reader is None:
            return
        try:
            reader.close()
        except Exception as e:
            self.logger.log(f"释放阅读器失败: {e}", "ERROR")
        self.current_reader = None

    def update_window_title(self):
        """根据当前书籍更新窗口标题"""
        base_title = f"{PROJECT_NAME} - {VERSION}"
        if not self.current_reader:
            self.setWindowTitle(base_title)
            return

        book_title = None
        author = None
        try:
            info = self.current_reader.get_book_info() or {}
            book_title = info.get('title') or Path(str(self.current_file_path)).name
            author = info.get('author')
        except Exception as e:
            if DEBUG_MODE:
                self.logger.debug(f"读取书籍信息失败: {e}")
            book_title = None
        
        if book_title:
            title = f"{book_title} - {base_title}"
            if author:
                title = i18n.t("window.title_with_author",
                               default="{title}（{author}） - {app}",
                               title=book_title, author=author, app=base_title)
            self.setWindowTitle(title)
        else:
            self.setWindowTitle(base_title)
