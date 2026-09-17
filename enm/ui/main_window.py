"""主窗口：菜单栏、工具栏、章节树、阅读区与所有交互逻辑。"""

import base64
import json
import time
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QImage, QTextCursor
from PyQt5.QtWidgets import (QAction, QDialog, QFileDialog, QFontDialog,
                             QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QProgressBar, QPushButton, QTextEdit, QToolBar,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from ..constants import (AUTHOR_NAME, DEBUG_MODE, ICON_PATH, PROJECT_NAME,
                         VERSION)
from ..managers import (ConfigManager, LanguageManager, ReadingProgressManager,
                        ThemeManager, format_timestamp, split_file_key)
from ..readers import (SUPPORTED_EXTENSIONS, FolderReader, ReaderError,
                       build_open_file_filter, create_reader,
                       format_chapter_html, supported_extensions_text)
from .continue_dialog import ContinueReadingDialog
from .theme_dialog import ThemeGeneratorDialog
from ..logger import logger

class EpubNovelMaster(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 初始化管理器（logger 全局单例，重复构造不会叠加处理器）
        self.logger = logger
        self.config_manager = ConfigManager()
        self.progress_manager = ReadingProgressManager()
        self.theme_manager = ThemeManager()
        self.language_manager = LanguageManager()
        
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
        
        self.logger.log("EpubNovelMaster 启动成功")
    
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
        self.setWindowTitle(f"{PROJECT_NAME} - {VERSION}")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧边栏（章节列表）
        self.sidebar = QWidget()
        self.sidebar.setMaximumWidth(300)
        sidebar_layout = QVBoxLayout(self.sidebar)
        
        # 章节列表标题栏
        sidebar_header_layout = QHBoxLayout()
        self.chapter_tree_label = QLabel("章节列表")
        self.toggle_sidebar_btn = QPushButton("隐藏")
        self.toggle_sidebar_btn.setMaximumWidth(60)
        self.toggle_sidebar_btn.clicked.connect(self.toggle_sidebar)
        
        sidebar_header_layout.addWidget(self.chapter_tree_label)
        sidebar_header_layout.addStretch()
        sidebar_header_layout.addWidget(self.toggle_sidebar_btn)
        sidebar_layout.addLayout(sidebar_header_layout)
        
        self.chapter_tree = QTreeWidget()
        self.chapter_tree.setHeaderHidden(True)  # 隐藏默认的标题栏
        self.chapter_tree.itemClicked.connect(self.on_chapter_selected)
        sidebar_layout.addWidget(self.chapter_tree)
        
        # 阅读进度
        self.progress_label = QLabel("阅读进度: 0%")
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
        self.prev_btn = QPushButton("上一章")
        self.next_btn = QPushButton("下一章")
        self.prev_btn.clicked.connect(self.previous_chapter)
        self.next_btn.clicked.connect(self.next_chapter)
        
        control_layout.addWidget(self.prev_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.next_btn)
        
        reader_layout.addLayout(control_layout)
        main_layout.addWidget(self.reader_widget)
        
        # 章节列表默认显示状态
        self.sidebar_visible = True
        
        # 创建菜单栏
        self.create_menus()
        
        # 创建工具栏
        self.create_toolbar()
    
    def create_menus(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        open_file_action = QAction("打开文件", self)
        open_file_action.triggered.connect(self.open_file)
        file_menu.addAction(open_file_action)
        
        open_folder_action = QAction("打开文件夹", self)
        open_folder_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_folder_action)
        
        file_menu.addSeparator()
        
        # 最近文件
        self.recent_menu = file_menu.addMenu("最近文件")
        self.update_recent_files_menu()
        
        continue_action = QAction("继续阅读...", self)
        continue_action.triggered.connect(self.show_continue_reading)
        file_menu.addAction(continue_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图")
        
        theme_menu = view_menu.addMenu("主题")
        
        light_theme_action = QAction("浅色主题", self)
        light_theme_action.triggered.connect(lambda: self.change_theme("light"))
        theme_menu.addAction(light_theme_action)
        
        dark_theme_action = QAction("深色主题", self)
        dark_theme_action.triggered.connect(lambda: self.change_theme("dark"))
        theme_menu.addAction(dark_theme_action)
        
        theme_menu.addSeparator()
        
        import_theme_action = QAction("导入主题", self)
        import_theme_action.triggered.connect(self.import_theme)
        theme_menu.addAction(import_theme_action)
        
        export_theme_action = QAction("导出主题", self)
        export_theme_action.triggered.connect(self.export_theme)
        theme_menu.addAction(export_theme_action)
        
        theme_generator_action = QAction("主题生成器", self)
        theme_generator_action.triggered.connect(self.open_theme_generator)
        theme_menu.addAction(theme_generator_action)
        
        # 字体设置
        font_action = QAction("字体设置", self)
        font_action.triggered.connect(self.change_font)
        view_menu.addAction(font_action)
        
        # 记住章内阅读位置
        self.restore_scroll_action = QAction("记住章内阅读位置", self)
        self.restore_scroll_action.setCheckable(True)
        self.restore_scroll_action.setChecked(
            self.config_manager.get("restore_scroll_position", True))
        self.restore_scroll_action.toggled.connect(self.toggle_restore_scroll)
        view_menu.addAction(self.restore_scroll_action)
        
        # 语言设置
        language_menu = view_menu.addMenu("语言")
        
        chinese_action = QAction("简体中文", self)
        chinese_action.triggered.connect(lambda: self.change_language("zh_CN"))
        language_menu.addAction(chinese_action)
        
        english_action = QAction("English", self)
        english_action.triggered.connect(lambda: self.change_language("en_US"))
        language_menu.addAction(english_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = QToolBar("主工具栏")
        self.addToolBar(toolbar)
        
        open_file_action = QAction("打开文件", self)
        open_file_action.triggered.connect(self.open_file)
        toolbar.addAction(open_file_action)
        
        continue_action = QAction("继续阅读", self)
        continue_action.triggered.connect(self.show_continue_reading)
        toolbar.addAction(continue_action)
        
        toolbar.addSeparator()
        
        # 章节列表显示/隐藏按钮
        self.toggle_sidebar_action = QAction("隐藏章节列表", self)
        self.toggle_sidebar_action.triggered.connect(self.toggle_sidebar)
        toolbar.addAction(self.toggle_sidebar_action)
        
        toolbar.addSeparator()
        
        prev_action = QAction("上一章", self)
        prev_action.triggered.connect(self.previous_chapter)
        toolbar.addAction(prev_action)
        
        next_action = QAction("下一章", self)
        next_action.triggered.connect(self.next_chapter)
        toolbar.addAction(next_action)
    
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
        sidebar_visible = self.config_manager.get("sidebar_visible", True)
        self.sidebar_visible = sidebar_visible
        if not sidebar_visible:
            self.sidebar.hide()
            self.toggle_sidebar_btn.setText("显示")
            self.toggle_sidebar_action.setText("显示章节列表")
        else:
            self.sidebar.show()
            self.toggle_sidebar_btn.setText("隐藏")
            self.toggle_sidebar_action.setText("隐藏章节列表")
    
    def apply_theme(self, theme_name):
        """应用主题"""
        theme = self.theme_manager.get_theme(theme_name)
        
        # 应用样式表
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
        QPushButton {{
            background-color: {theme['accent']};
            color: white;
            border: none;
            padding: 5px 10px;
        }}
        QPushButton:hover {{
            background-color: {theme['highlight']};
        }}
        """
        
        self.setStyleSheet(style_sheet)
    
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
            self, "打开文件", "", build_open_file_filter()
        )
        
        if file_path:
            self.load_file(file_path)
    
    def open_folder(self):
        """打开文件夹"""
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        
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
                    self, "错误",
                    f"不支持的文件格式: {file_path.suffix or '未知'}\n\n"
                    f"支持的格式: {supported_extensions_text()}"
                )
                if DEBUG_MODE:
                    self.logger.debug(f"不支持的文件格式: {file_path.suffix}")
                return
            
            # 创建阅读器（失败时保留当前正在阅读的文件）
            try:
                new_reader = create_reader(str(file_path))
            except ReaderError as e:
                QMessageBox.warning(self, "无法打开文件", f"{file_path.name}\n\n{e}")
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
            QMessageBox.critical(self, "错误", f"加载文件失败: {str(e)}")
            self.logger.log(f"加载文件失败: {e}", "ERROR")
            if DEBUG_MODE:
                self.logger.debug(f"加载文件异常详情: {e}", exc_info=True)
    
    def load_folder(self, folder_path):
        """加载文件夹"""
        try:
            new_reader = FolderReader(folder_path)
            
            if new_reader.get_file_count() == 0:
                QMessageBox.information(self, "提示", "文件夹中没有支持的文件")
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
            QMessageBox.critical(self, "错误", f"加载文件夹失败: {str(e)}")
            self.logger.log(f"加载文件夹失败: {e}", "ERROR")
    
    def display_content(self):
        """显示内容"""
        if not self.current_reader:
            return
        
        reader = self.current_reader
        if isinstance(reader, FolderReader):
            inner = reader.get_current_reader()
            if not inner or inner.get_chapter_count() == 0:
                self.reader_display.setHtml("<p>无法读取该文件或文件中没有可显示的内容。</p>")
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
                self.reader_display.setHtml("<p>文件中没有可显示的内容。</p>")
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
    
    def update_progress(self):
        """更新进度"""
        if not self.current_reader:
            return
        
        if isinstance(self.current_reader, FolderReader):
            reader = self.current_reader.get_current_reader()
            if reader:
                progress = (reader.current_chapter + 1) / reader.get_chapter_count() * 100
        else:
            progress = (self.current_reader.current_chapter + 1) / self.current_reader.get_chapter_count() * 100
        
        self.progress_bar.setValue(int(progress))
        self.progress_label.setText(f"阅读进度: {progress:.1f}%")
    
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
            QMessageBox.warning(self, "文件不存在",
                               f"{path}\n\n文件可能已被移动或删除。")
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
            self.toggle_sidebar_btn.setText("隐藏")
            self.toggle_sidebar_action.setText("隐藏章节列表")
        else:
            self.sidebar.hide()
            self.toggle_sidebar_btn.setText("显示")
            self.toggle_sidebar_action.setText("显示章节列表")
        
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
            self.config_manager.set("font_family", font.family())
            self.config_manager.set("font_size", font.pointSize())
            self.apply_font(font.family(), font.pointSize())
    
    def change_language(self, lang_code):
        """更改语言"""
        self.config_manager.set("language", lang_code)
        # 这里可以添加语言切换逻辑
        QMessageBox.information(self, "提示", "语言设置将在下次启动时生效")
    
    def import_theme(self):
        """导入主题"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入主题", "", "主题文件 (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    theme_data = json.load(f)
                
                theme_name = Path(file_path).stem
                if self.theme_manager.save_theme(theme_name, theme_data):
                    QMessageBox.information(self, "成功", "主题导入成功")
                else:
                    QMessageBox.warning(self, "错误", "主题导入失败")
                    
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入主题失败: {str(e)}")
    
    def export_theme(self):
        """导出主题"""
        current_theme = self.config_manager.get("theme")
        theme_data = self.theme_manager.get_theme(current_theme)
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出主题", f"{current_theme}.json", "主题文件 (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(theme_data, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "成功", "主题导出成功")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出主题失败: {str(e)}")
    
    def open_theme_generator(self):
        """打开主题生成器"""
        dialog = ThemeGeneratorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            theme_data = dialog.get_theme_data()
            theme_name = theme_data["name"]
            
            if self.theme_manager.save_theme(theme_name, theme_data):
                QMessageBox.information(self, "成功", "主题创建成功")
                # 应用新主题
                self.config_manager.set("theme", theme_name)
                self.apply_theme(theme_name)
            else:
                QMessageBox.warning(self, "错误", "主题创建失败")
    
    def show_about(self):
        """显示关于对话框"""
        about_text = f"""
        <h2>{PROJECT_NAME}</h2>
        <p>版本: {VERSION}</p>
        <p>作者: {AUTHOR_NAME}</p>
        <p>一个功能强大的小说阅读器，支持多种格式和丰富的自定义选项。</p>
        <p>功能特性:</p>
        <ul>
            <li>支持 {supported_extensions_text()} 文件格式</li>
            <li>支持文件夹模式阅读（可跨文件连续翻章）</li>
            <li>自动保存阅读记录</li>
            <li>主题切换和自定义</li>
            <li>多语言支持</li>
            <li>现代化的用户界面</li>
        </ul>
        """
        
        QMessageBox.about(self, "关于", about_text)
    
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
        
        self.logger.log("EpubNovelMaster 正常退出")
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
                title = f"{book_title}（{author}） - {base_title}"
            self.setWindowTitle(title)
        else:
            self.setWindowTitle(base_title)
