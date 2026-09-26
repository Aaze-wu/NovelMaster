"""主窗口：菜单栏、工具栏、章节树、阅读区与所有交互逻辑。"""

import base64
import time
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import (QColor, QFont, QIcon, QImage, QKeySequence,
                         QTextCharFormat, QTextCursor)
from PyQt5.QtWidgets import (QAbstractSpinBox, QAction, QApplication, QComboBox,
                             QDialog, QFileDialog, QFontDialog, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                             QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QSplitter, QTextEdit, QToolBar,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import i18n
from ..constants import (AUTHOR_NAME, DEBUG_MODE, ICON_PATH, PROJECT_NAME,
                         VERSION)
from ..managers import (ConfigManager, DEFAULT_PARAGRAPH_SPACING,
                        DEFAULT_LINE_SPACING, DEFAULT_THEME,
                        ReadingProgressManager, TYPO_FIELDS, ThemeManager,
                        format_timestamp, is_dark, normalise_font_size,
                        normalise_line_spacing, normalise_paragraph_spacing,
                        record_covers_file, record_file_key, split_file_key)
from ..managers.book_identity import (FINGERPRINT_SAMPLE, build_identity,
                                      chapter_index_in,
                                      normalise_chapter_title)
from ..managers import tts_models
from ..managers.media_keys import (MediaKeysController, media_keys_available,
                                   media_keys_importable,
                                   media_keys_unavailable_reason)
from ..managers.tts import (DEFAULT_MAX_CHARS, EDGE_ENGINE, NEURAL_ENGINE,
                            SpeechQueue, available_engines, create_backend,
                            pick_voice, sentences_for_blocks, voice_label)
from ..readers import (SUPPORTED_EXTENSIONS, FolderReader, ReaderError,
                       build_open_file_filter, create_reader,
                       format_chapter_html, supported_extensions_text)
from ..shortcuts import (ACTION_DEFS, DEFS_BY_ID, READER, WINDOW,
                         ShortcutManager, event_key_sequence, key_sequence,
                         label_of, mouse_token_of_event)
from .book_merge_dialog import BookMergeDialog
from .chapter_tree import ChapterTree
from .continue_dialog import ContinueReadingDialog
from .dialog_help_button import install as install_dialog_help_filter
from .dialog_titlebar import install as install_dialog_titlebar_filter
from .qt_translations import install as install_qt_translations
from .reader_typography import apply_reader_typography
from .shortcut_dialog import ShortcutSettingsDialog
from .theme_dialog import describe_theme_errors, theme_display_label
from .theme_manager_dialog import ThemeManagerDialog
from .theme_qss import (SPLITTER_HANDLE_WIDTH, build_palette,
                        build_style_sheet)
from .titlebar import (apply_dark_mode, apply_titlebar_theme, available,
                       reset_titlebar_theme)
from .tray import TrayIcon
from .tts_bar import (RATE_PRESETS, TIMER_CHAPTER, TIMER_DEFAULT_MINUTES,
                      TIMER_MAX_MINUTES, TIMER_MIN_MINUTES, TIMER_OFF, TtsBar,
                      nearest_rate, quantize_volume)
from .tts_model_dialog import TtsModelDialog
from .tts_pron_dialog import TtsPronDialog
from .tts_range_dialog import SpeechRangeDialog
from .tts_voice_dialog import TtsVoiceDialog, VoiceSnapshot
from .typography_dialog import TypographySettingsDialog
from ..logger import logger

# 阅读区字号范围（字体增大 / 减小用）
FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 48

# 侧边栏（章节列表）宽度：默认沿用旧版写死的值；用户拖过分隔条之后
# 实际宽度会记到 config.json 的 sidebar_width，下次启动照旧
SIDEBAR_WIDTH_DEFAULT = 300
SIDEBAR_WIDTH_MIN = 160
SIDEBAR_WIDTH_MAX = 720
# 阅读区最小宽度：侧边栏最多能拖多宽，由「窗口宽度 - 它」反推，别把正文挤没
READER_WIDTH_MIN = 280
# 拖动分隔条会连着发 splitterMoved，等手停下来再写盘（毫秒）
SIDEBAR_WIDTH_SAVE_DELAY = 400

# 「同一个文件不再询问是否共用进度」最多记这么多条（只当备忘，不参与逻辑）
MAX_SHARE_IGNORED = 100

# 全局媒体键的会话在自己的线程里建，起来要一会儿；
# 隔这么久回头看一眼有没有报错（毫秒）
MEDIA_KEYS_CHECK_MS = 1500


def clamp_sidebar_width(value):
    """把侧边栏宽度夹进合法区间（手改过 config.json 也不会把界面搞坏）"""
    try:
        width = int(value)
    except (TypeError, ValueError):
        width = SIDEBAR_WIDTH_DEFAULT
    return max(SIDEBAR_WIDTH_MIN, min(width, SIDEBAR_WIDTH_MAX))


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
        # Qt 自己画的对话框（字体 / 颜色 / 输入框 / 消息框）的文案来自 Qt 的
        # 翻译目录，不装的话永远英文（「字体选择」窗口的标题就是这种）
        self._install_qt_translations()
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
            # 朗读相关：全部只注册在阅读区，这样空格等键不会从输入框里被抢走
            "tts.play_pause": self.toggle_speech,
            "tts.stop": self.stop_speech,
            "tts.prev_sentence": self.previous_sentence,
            "tts.next_sentence": self.next_sentence,
            "tts.rate_up": self.speech_rate_up,
            "tts.rate_down": self.speech_rate_down,
            # 朗读范围（v1.3.7）：点了就开读，默认不绑键
            "tts.range_chapter": self.speak_whole_chapter,
            "tts.range_cursor": self.speak_from_cursor,
            "tts.range_selection": self.speak_selection,
            "tts.range_chapters": self.speak_chapter_range,
        }
        # 按生效范围缓存的绑定快照，供阅读区按键过滤使用
        self._window_bindings = {}
        self._reader_bindings = {}
        # 动作 id -> 鼠标记号（鼠标键不分 scope，详见 handle_mouse_shortcut）
        self._mouse_bindings = {}
        # 去抖用：鼠标键没有 isAutoRepeat，某些鼠标 / 驱动按住会连发 Press，
        # 这里记下上一次触发的是哪个记号、什么时候（对应用键盘时的长按保护）
        self._mouse_last_token = ""
        self._mouse_last_time = 0.0
        self._snapshot_bindings()
        
        # 当前阅读器
        self.current_reader = None
        self.current_file_path = None

        #: 当前生效的完整主题字典（apply_theme 写入；原生标题栏与子对话框共用）
        self._current_theme = None

        # Qt 自带对话框（字体 / 颜色 / 输入框 / 消息框）由 Qt 内部创建，外层拿不到
        # 引用，没法在 showEvent 里上色，只能靠应用级事件过滤器兜住
        self._dialog_titlebar_filter = install_dialog_titlebar_filter(
            QApplication.instance(), self.dialog_titlebar_theme, parent=self)

        # 同理，Qt 对话框标题栏上那个「?」（上下文帮助）按钮也去不掉引用，
        # 靠应用级事件过滤器在窗口显示前清掉标志（见 dialog_help_button）
        self._dialog_help_filter = install_dialog_help_filter(
            QApplication.instance(), parent=self)

        # 内嵌图片尺寸缓存与自适应重算定时器
        self._image_widths = {}
        self.image_fit_timer = QTimer()
        self.image_fit_timer.setSingleShot(True)
        self.image_fit_timer.timeout.connect(self.fit_document_images)
        
        # 自动保存定时器
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self.auto_save_progress)

        # 拖动分隔条改侧边栏宽度：拖动过程中 splitterMoved 会连着发，
        # 每次都写一次 config.json 太浪费，用个单次定时器等手停下来再落盘
        self.sidebar_width_timer = QTimer()
        self.sidebar_width_timer.setSingleShot(True)
        self.sidebar_width_timer.setInterval(SIDEBAR_WIDTH_SAVE_DELAY)
        self.sidebar_width_timer.timeout.connect(self._save_sidebar_width)

        # 阅读统计会话状态（仅窗口激活时计时）与待恢复的章内位置
        self._stats = self.empty_stats()
        self._focus_started_at = None
        self._pending_scroll_percent = 0.0

        # 当前书籍的身份签名（书名 / 作者 / 章节标题指纹）与实际使用的记录键，
        # 打开书籍时由 resolve_reading_record() 算一次；缓存是为了让保存时
        # 不必重复解析章节标题
        self._book_identity = {}
        self._progress_record_key = ""

        # 朗读（v1.3.5）：引擎和句子队列都是懒创建的——没点过朗读就不加载
        # 系统语音；_tts_available 缓存「这台机器有没有引擎」的结论
        self._tts_backend = None
        self._tts_queue = None
        self._tts_available = None
        self._speech_state = "idle"
        self._tts_highlight_index = -1
        # 自动翻章后要不要接着读（sync_speech_content 读出后立刻清掉）
        self._tts_continues = False
        # 朗读进行中用户换了语音：先记下来，等停下来再换
        self._tts_voice_pending = ""
        # 音色管理窗口与它的下载线程（懒创建，见 tts_model_dialog()）
        self._tts_model_dialog = None
        self._tts_model_lang = ""
        # 音色选择窗口（懒创建；音色太多，菜单里铺不下，见 tts_voice_dialog()）
        self._tts_voice_dialog = None
        self._tts_voice_lang = ""
        self._tts_pron_dialog = None
        self._tts_pron_lang = ""
        # 用户选了一个「还没下载」的音色：下完自动换上
        self._tts_voice_after_download = ""

        # 朗读定时停止（v1.3.7）：倒计时只在「朗读中」走，暂停就冻住，
        # 这样「暂停去倒杯水、回来接着听」不会把剩余时间白耗掉。
        # 定时是**本次会话**的事，不写 config.json —— 重启后不该还记得一个小时前
        # 设的闹钟。_speech_timer_mode 取值 None / "minutes" / "chapter"
        self._speech_timer_mode = None
        self._speech_timer_remaining = 0
        self._speech_timer = QTimer()
        self._speech_timer.setInterval(1000)
        self._speech_timer.timeout.connect(self._on_speech_timer_tick)

        # 朗读范围（v1.3.7）：None = 整章（默认），其余都是**一次性**的——
        # 读完立刻复位成整章，不会在下次朗读里静默生效。取值：
        #   {"kind": "cursor",  "start": int, "anchor": (文件序号, 章节序号)}
        #   {"kind": "span",    "start": int, "end": int, "anchor": …}
        #   {"kind": "chapters","from": int, "to": int, "file": 文件序号}
        # 字符偏移那种（cursor / span）只在当时那一章里有效，用户手动翻章
        # 就对不上了，所以记下 anchor，对不上就作废。
        self._speech_range = None

        # 系统托盘与全局媒体键（v1.3.9）：都是懒创建，没开功能就不干活
        self._tray_icon = None
        #: 这个进程是不是从托盘菜单「退出程序」退的（真退，不藏）
        self._quitting_from_tray = False
        self._media_keys = None
        #: 媒体键启动失败只弹一次，免得每次翻章都弹
        self._media_keys_error_reported = False
        
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

        # 章节列表和阅读区之间夹一条可拖动的分隔条：章节名长的时候把侧边栏
        # 直接拖宽就行，宽度记在 config.json 的 sidebar_width 里
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(SPLITTER_HANDLE_WIDTH)
        # 不允许把某一边拖成 0（隐藏章节列表走的是「显示 / 隐藏章节列表」开关）
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.splitterMoved.connect(self._on_splitter_moved)
        main_layout.addWidget(self.main_splitter)

        # 左侧边栏（章节列表）
        self.sidebar = QWidget()
        # 主题里用 #sidebar QLabel 限定标签配色，避免样式表渗到对话框
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(SIDEBAR_WIDTH_MIN)
        self.sidebar.setMaximumWidth(SIDEBAR_WIDTH_MAX)
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
        
        self.chapter_tree = ChapterTree()
        self.chapter_tree.setHeaderHidden(True)  # 隐藏默认的标题栏
        self.chapter_tree.itemClicked.connect(self.on_chapter_selected)
        sidebar_layout.addWidget(self.chapter_tree)
        
        # 阅读进度
        self.progress_label = QLabel()
        self.progress_bar = QProgressBar()
        sidebar_layout.addWidget(self.progress_label)
        sidebar_layout.addWidget(self.progress_bar)
        
        self.main_splitter.addWidget(self.sidebar)
        
        # 右侧阅读区域
        self.reader_widget = QWidget()
        reader_layout = QVBoxLayout(self.reader_widget)
        
        # 阅读器控件
        self.reader_display = QTextEdit()
        self.reader_display.setReadOnly(True)
        reader_layout.addWidget(self.reader_display)

        # 朗读条（常驻正文下方；控件本体在 enm/ui/tts_bar.py，这里只接线）
        self.tts_bar = TtsBar(self.reader_widget)
        self._connect_speech_bar()
        reader_layout.addWidget(self.tts_bar)
        
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
        self.reader_widget.setMinimumWidth(READER_WIDTH_MIN)
        self.main_splitter.addWidget(self.reader_widget)
        # 多余的宽度全给阅读区，侧边栏保持自己那份
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        
        # 创建菜单栏
        self.create_menus()
        
        # 创建工具栏
        self.create_toolbar()
        
        # 阅读区按键过滤：方向键 / 翻页键翻章，Ctrl 组合键优先于 QTextEdit 自带行为
        self.reader_display.installEventFilter(self)
        # 右键菜单：QTextEdit 自带那份只有复制 / 全选，这里换成带朗读命令的
        self.reader_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self.reader_display.customContextMenuRequested.connect(
            self.show_reader_context_menu)
        self.reader_display.viewport().installEventFilter(self)
        # 鼠标侧键 / 中键：装在应用上（而不是某一个控件上），这样窗口里
        # 任何位置按下都能触发；是否接受由 handle_mouse_shortcut 判断
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
    
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
    
    # ---------------- 托盘图标与全局媒体键（v1.3.9） ----------------

    def action(self, action_id):
        """按 id 取已登记的动作（托盘菜单复用主窗口的朗读动作）"""
        return self._actions.get(action_id)

    def speech_state(self):
        """当前朗读状态（托盘提示用）"""
        return self._speech_state

    def apply_tray_settings(self):
        """按配置显示 / 隐藏托盘图标（系统没有托盘时就只记日志）"""
        if not self.config_manager.get("tray_enabled", True):
            self._shutdown_tray()
            return
        if not TrayIcon.available():
            self.logger.log("系统没有可用的托盘，托盘图标未创建", "WARN")
            return
        if self._tray_icon is None:
            self._tray_icon = TrayIcon(self)
        self._tray_icon.show()
        self._tray_icon.refresh()

    def _shutdown_tray(self):
        """收掉托盘图标（菜单是它自己建的，得自己销毁）"""
        tray, self._tray_icon = getattr(self, "_tray_icon", None), None
        if tray is None:
            return
        # 托盘没了就只剩「关窗 = 退出」一条路，否则窗口会藏得找不回来
        if not self.isVisible():
            self.showNormal()
            self.raise_()
        tray.shutdown()

    def _reset_check(self, action):
        """把被拒的勾选退回去（触发函数里改 checked 会再发一次信号）"""
        if action is None:
            return
        action.blockSignals(True)
        action.setChecked(False)
        action.blockSignals(False)

    def toggle_tray_enabled(self, checked):
        """切换「显示托盘图标」"""
        if checked and not TrayIcon.available():
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("tray.unavailable"))
            self._reset_check(getattr(self, "tray_action", None))
            return
        self.config_manager.set("tray_enabled", bool(checked))
        self.logger.log(f"系统托盘: {'开启' if checked else '关闭'}")
        self.apply_tray_settings()

    def toggle_close_to_tray(self, checked):
        """切换「关闭窗口时隐藏到托盘」"""
        if checked and not TrayIcon.available():
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("tray.unavailable"))
            self._reset_check(getattr(self, "tray_close_action", None))
            return
        self.config_manager.set("tray_close_to_tray", bool(checked))
        self.logger.log(f"关闭窗口时隐藏到托盘: {'开启' if checked else '关闭'}")

    def should_hide_to_tray(self):
        """这次点 X 是不是该收进托盘而不是退出"""
        if getattr(self, "_quitting_from_tray", False):
            return False
        if getattr(self, "_tray_icon", None) is None:
            return False
        return bool(self.config_manager.get("tray_close_to_tray", False))

    def quit_from_tray(self):
        """托盘菜单里的「退出程序」：这次真的退"""
        self._quitting_from_tray = True
        self.close()
        QApplication.quit()

    def _show_tray_notice(self):
        """第一次收进托盘时冒个泡，免得用户以为程序已经退了"""
        tray = getattr(self, "_tray_icon", None)
        if tray is None or self.config_manager.get("tray_notice_shown", False):
            return
        tray.notify(i18n.t("tray.notice_title"), i18n.t("tray.notice_body"))
        self.config_manager.set("tray_notice_shown", True)

    def _refresh_tray(self):
        """刷新托盘提示与菜单文案（切语言、显隐、朗读状态变化时调）"""
        tray = getattr(self, "_tray_icon", None)
        if tray is not None:
            tray.refresh()

    # ---- 全局媒体键（SMTC） ----

    def apply_media_keys_settings(self):
        """按配置启动 / 停止全局媒体键（winrt 是可选依赖，缺了就跳过）"""
        if not self.config_manager.get("media_keys_enabled", False):
            self._shutdown_media_keys()
            return
        if not media_keys_available():
            reason = media_keys_unavailable_reason() or "未知原因"
            self.logger.log(f"全局媒体键不可用: {reason}", "WARN")
            return
        if self._media_keys is None:
            self._media_keys = MediaKeysController(self)
            self._media_keys.action.connect(self.on_media_key_action)
        title, chapter = self.media_panel_track()
        self._media_keys_error_reported = False
        self._media_keys.start(
            playing=(self._speech_state == SpeechQueue.PLAYING),
            title=title, subtitle=chapter)
        # 会话是在自己的线程里建的，起来要一会儿；过一会儿再回头看看有没有报错
        QTimer.singleShot(MEDIA_KEYS_CHECK_MS, self._report_media_keys_error)

    def _report_media_keys_error(self):
        """会话没建起来就告诉用户（只报一次，免得反复弹）"""
        controller = getattr(self, "_media_keys", None)
        if controller is None or getattr(self, "_media_keys_error_reported", False):
            return
        reason = controller.error()
        if not reason:
            return
        self._media_keys_error_reported = True
        self.logger.log(f"全局媒体键启动失败: {reason}", "WARN")
        QMessageBox.warning(self, i18n.t("menu.media_keys"),
                            i18n.t("msg.media_keys_failed", default="{error}",
                                   error=reason))

    def _shutdown_media_keys(self):
        """停掉全局媒体键（它有自己的线程与消息泵，退出前必须收摊）"""
        controller, self._media_keys = getattr(self, "_media_keys", None), None
        if controller is None:
            return
        try:
            controller.stop()
        except Exception as e:  # noqa: BLE001
            self.logger.log(f"停止全局媒体键失败: {e}", "WARN")

    def media_panel_track(self):
        """系统媒体面板上那两行字：书名 + 当前章节名（没开书就都空着）"""
        if not self.current_file_path:
            return "", ""
        try:
            title, _author = self.current_book_title()
        except Exception as e:  # noqa: BLE001
            if DEBUG_MODE:
                self.logger.debug(f"读取书名失败: {e}")
            title = ""
        chapter = ""
        reader = getattr(self, "current_reader", None)
        if reader is not None:
            try:
                if isinstance(reader, FolderReader):
                    inner = reader.get_current_reader()
                    if inner is not None:
                        chapter = inner.get_chapter_title(inner.current_chapter)
                else:
                    chapter = reader.get_chapter_title(reader.current_chapter)
            except Exception as e:  # noqa: BLE001
                if DEBUG_MODE:
                    self.logger.debug(f"读取章节名失败: {e}")
        return title or "", chapter or ""

    def refresh_media_panel(self):
        """把书名 / 章节名与朗读状态推给系统媒体面板（没开这项就什么都不做）"""
        controller = getattr(self, "_media_keys", None)
        if controller is None:
            return
        title, chapter = self.media_panel_track()
        controller.set_track(title, chapter)
        controller.set_playing(self._speech_state == SpeechQueue.PLAYING)

    def on_media_key_action(self, action):
        """键盘上的媒体键：转给朗读控制（动作名见 media_keys.BUTTON_ACTIONS）"""
        handlers = {"toggle": self.toggle_speech, "stop": self.stop_speech,
                    "next": self.next_sentence,
                    "previous": self.previous_sentence}
        handler = handlers.get(action)
        if handler is None:
            return
        self.logger.log(f"全局媒体键: {action}")
        handler()

    def toggle_media_keys(self, checked):
        """切换「媒体键控制朗读」（SMTC 会话要占一个静音音源，所以默认关闭）"""
        if checked and not media_keys_available():
            QMessageBox.information(self, i18n.t("menu.media_keys"),
                                    i18n.t("msg.media_keys_missing"))
            self._reset_check(getattr(self, "media_keys_action", None))
            return
        self.config_manager.set("media_keys_enabled", bool(checked))
        self.logger.log(f"全局媒体键: {'开启' if checked else '关闭'}")
        self.apply_media_keys_settings()

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
        # 主题菜单里的自定义主题列表（内置主题名与空列表提示都是翻译文本）
        self.update_theme_menu()
        # 朗读条上的按钮 / 开关文案（「开始朗读」等不在 _text_bindings 里，
        # 它在朗读条内部自己管）
        self.tts_bar.retranslate()
        # 托盘提示与菜单文案（显示 / 隐藏、退出）
        self._refresh_tray()
    
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

        # 朗读菜单（引擎 / 开关在 apply_speech_settings 里按配置刷新）
        speech_menu = self.add_menu(menubar, "menu.tts")

        self.make_action(self._speech_play_key, self.toggle_speech,
                         "tts.play_pause", READER)
        speech_menu.addAction(self._actions["tts.play_pause"])

        self.make_action("menu.tts_stop", self.stop_speech, "tts.stop", READER)
        speech_menu.addAction(self._actions["tts.stop"])

        speech_menu.addSeparator()

        self.make_action("menu.tts_prev_sentence", self.previous_sentence,
                         "tts.prev_sentence", READER)
        speech_menu.addAction(self._actions["tts.prev_sentence"])

        self.make_action("menu.tts_next_sentence", self.next_sentence,
                         "tts.next_sentence", READER)
        speech_menu.addAction(self._actions["tts.next_sentence"])

        speech_menu.addSeparator()

        # 朗读范围（v1.3.7）：命令式——点了就开读，没有「先设范围再读」两步；
        # 这几项同时登记在阅读区（READER），所以阅读区右键菜单里也有一份
        self.speech_range_menu = self.add_menu(speech_menu, "menu.tts_range")
        self.make_action("menu.tts_range_chapter", self.speak_whole_chapter,
                         "tts.range_chapter", READER)
        self.speech_range_menu.addAction(self._actions["tts.range_chapter"])
        self.make_action("menu.tts_range_cursor", self.speak_from_cursor,
                         "tts.range_cursor", READER)
        self.speech_range_menu.addAction(self._actions["tts.range_cursor"])
        self.make_action("menu.tts_range_selection", self.speak_selection,
                         "tts.range_selection", READER)
        self.speech_range_menu.addAction(self._actions["tts.range_selection"])
        self.speech_range_menu.addSeparator()
        self.make_action("menu.tts_range_chapters", self.speak_chapter_range,
                         "tts.range_chapters", READER)
        self.speech_range_menu.addAction(self._actions["tts.range_chapters"])

        speech_menu.addSeparator()

        # 引擎列表要枚举系统语音（会加载引擎），所以打开菜单时才填
        self.speech_engine_menu = self.add_menu(speech_menu, "menu.tts_engine")
        self.speech_engine_menu.aboutToShow.connect(self.update_speech_engine_menu)

        # 音色不再铺在菜单里：在线音色 322 个、离线神经 106 个，一拉开就占满
        # 整个屏幕，翻起来还容易点错。改成打开一个独立窗口挑（见
        # enm/ui/tts_voice_dialog.py）
        self.speech_voice_action = self.make_action(
            "menu.tts_voice", self.open_tts_voice_dialog)
        speech_menu.addAction(self.speech_voice_action)

        # 读音纠正（多音字）：字典内容的编辑窗口。这一个动作同时挂在
        # 「朗读」和「设置」两个菜单下（QAction 可以同时属于多个菜单）
        self.speech_pron_action = self.make_action(
            "menu.tts_pron", self.open_tts_pron_dialog)
        speech_menu.addAction(self.speech_pron_action)

        self.speech_auto_next_action = self.make_action(
            "menu.tts_auto_next", self.toggle_speech_auto_next)
        self.speech_auto_next_action.setCheckable(True)
        speech_menu.addAction(self.speech_auto_next_action)

        self.speech_highlight_action = self.make_action(
            "menu.tts_highlight", self.toggle_speech_highlight)
        self.speech_highlight_action.setCheckable(True)
        speech_menu.addAction(self.speech_highlight_action)
        
        # 设置菜单
        settings_menu = self.add_menu(menubar, "menu.settings")
        
        theme_menu = self.add_menu(settings_menu, "menu.theme")
        
        self.make_action("menu.theme_light",
                         lambda: self.change_theme("light"),
                         "view.theme_light")
        self._actions["view.theme_light"].setCheckable(True)
        theme_menu.addAction(self._actions["view.theme_light"])
        
        self.make_action("menu.theme_dark",
                         lambda: self.change_theme("dark"),
                         "view.theme_dark")
        self._actions["view.theme_dark"].setCheckable(True)
        theme_menu.addAction(self._actions["view.theme_dark"])
        
        theme_menu.addSeparator()
        
        # 自定义主题列表（内容随 themes 目录变化，见 update_theme_menu）
        self.custom_theme_menu = self.add_menu(theme_menu, "menu.theme_custom")
        
        theme_menu.addSeparator()
        
        theme_menu.addAction(self.make_action("menu.theme_manager",
                                              self.open_theme_manager))
        theme_menu.addAction(self.make_action("menu.theme_import",
                                              self.import_theme))
        theme_menu.addAction(self.make_action("menu.theme_export",
                                              self.export_theme))
        self.update_theme_menu()
        
        # 字体设置
        self.make_action("menu.font_settings", self.change_font,
                         "view.font_dialog")
        settings_menu.addAction(self._actions["view.font_dialog"])
        
        self.make_action("menu.font_increase", self.increase_font_size,
                         "view.font_inc")
        settings_menu.addAction(self._actions["view.font_inc"])
        
        self.make_action("menu.font_decrease", self.decrease_font_size,
                         "view.font_dec")
        settings_menu.addAction(self._actions["view.font_dec"])

        # 排版设置（行距 / 段间距；字体与字号在上面那条原生字体对话框里）
        self.make_action("menu.typography_settings",
                         self.open_typography_dialog,
                         "view.typography_dialog")
        settings_menu.addAction(self._actions["view.typography_dialog"])
        
        # 记住章内阅读位置
        self.restore_scroll_action = self.make_action(
            "menu.restore_scroll", self.toggle_restore_scroll)
        self.restore_scroll_action.setCheckable(True)
        self.restore_scroll_action.setChecked(
            self.config_manager.get("restore_scroll_position", True))
        settings_menu.addAction(self.restore_scroll_action)

        # 原生标题栏跟随主题（默认关闭：保持系统默认样式）
        self.titlebar_action = self.make_action(
            "menu.titlebar_follow", self.toggle_titlebar_follow)
        self.titlebar_action.setCheckable(True)
        self.titlebar_action.setChecked(
            self.config_manager.get("titlebar_follow_theme", False))
        if not available():
            self.titlebar_action.setEnabled(False)
        settings_menu.addAction(self.titlebar_action)

        # 允许主题自带的字体 / 字号 / 行距 / 段间距覆盖全局阅读设置
        self.typography_action = self.make_action(
            "menu.typography_follow", self.toggle_typography_follow)
        self.typography_action.setCheckable(True)
        self.typography_action.setChecked(
            self.config_manager.get("typography_follow_theme", False))
        settings_menu.addAction(self.typography_action)

        # 同名书籍的不同版本（重新导出 / 追加新章节）共用同一份阅读记录
        self.share_progress_action = self.make_action(
            "menu.share_progress", self.toggle_share_progress)
        self.share_progress_action.setCheckable(True)
        self.share_progress_action.setChecked(
            self.config_manager.get("share_progress_versions", True))
        settings_menu.addAction(self.share_progress_action)

        # 系统托盘（v1.3.9）：托盘图标本身，以及「关闭窗口时收进托盘」
        self.tray_action = self.make_action("menu.tray_icon",
                                            self.toggle_tray_enabled)
        self.tray_action.setCheckable(True)
        self.tray_action.setChecked(
            self.config_manager.get("tray_enabled", True))
        settings_menu.addAction(self.tray_action)

        self.tray_close_action = self.make_action("menu.tray_close_hide",
                                                  self.toggle_close_to_tray)
        self.tray_close_action.setCheckable(True)
        self.tray_close_action.setChecked(
            self.config_manager.get("tray_close_to_tray", False))
        settings_menu.addAction(self.tray_close_action)

        # 全局媒体键（v1.3.9）：键盘上的播放 / 暂停、上一句 / 下一句直接控制朗读
        # （会话要在音量合成器里占一个静音音源，所以默认关闭）
        self.media_keys_action = self.make_action("menu.media_keys",
                                                  self.toggle_media_keys)
        self.media_keys_action.setCheckable(True)
        self.media_keys_action.setChecked(
            self.config_manager.get("media_keys_enabled", False))
        if not media_keys_importable():
            # winrt 没装：说明挂在 tooltip 上，点开关时还会再弹一次
            self.bind_text(self.media_keys_action,
                           "menu.media_keys_unavailable", "setToolTip")
        settings_menu.addAction(self.media_keys_action)
        
        # 快捷键设置
        self.make_action("menu.shortcut_settings", self.open_shortcut_dialog,
                         "view.shortcut_config")
        settings_menu.addAction(self._actions["view.shortcut_config"])

        # 读音纠正：与朗读菜单里那一份是同一个动作
        settings_menu.addAction(self.speech_pron_action)
        
        # 语言设置（选项来自 i18n.available_languages，新增语言无需改这里）
        self.language_menu = self.add_menu(settings_menu, "menu.language")
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

        toolbar.addSeparator()

        # 朗读开关（文案随播放状态变，见 _speech_play_key）
        toolbar.addAction(self._actions["tts.play_pause"])
    
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
                      keys=self.shortcut_manager.display_all(action_id))
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
                      keys=self.shortcut_manager.display_all(action_id))
    
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
        # 鼠标键单独缓存：鼠标没有「焦点」概念，只看主窗口在不在前台，
        # 所以不按 scope 分桶（见 handle_mouse_shortcut）
        self._mouse_bindings = {}
        for definition in ACTION_DEFS:
            token = self.shortcut_manager.mouse_token_of(definition.action_id)
            if token:
                self._mouse_bindings[definition.action_id] = token
    
    def refresh_shortcuts(self):
        """改键后重新套用全部快捷键"""
        for action_id in list(self._actions):
            self.apply_action_shortcut(action_id)
        self._snapshot_bindings()
        self._refresh_widget_hints()
    
    def open_shortcut_dialog(self):
        """打开快捷键设置面板"""
        dialog = ShortcutSettingsDialog(self.shortcut_manager, self,
                                        titlebar_theme=self.dialog_titlebar_theme())
        if dialog.exec_() != QDialog.Accepted:
            return
        self.refresh_shortcuts()
        self.logger.log("快捷键设置已更新")
    
    # 鼠标键落在这些可编辑控件里时不触发动作：鼠标按在输入框 / 微调框 /
    # 下拉框 / 可编辑文本区里是「放光标 / 选内容」，不该顺手翻一章
    EDITABLE_TEXT_TYPES = (QLineEdit, QAbstractSpinBox, QComboBox)

    #: 同一个鼠标键两次触发之间的最短间隔（秒）：按住侧键时连发的 Press 会被
    #: 去抖掉（值很小，人手快速连点不会受影响）
    MOUSE_REPEAT_GUARD = 0.06

    def _mouse_action_for(self, token):
        """鼠标记号 → 动作 id（没有绑过就返回空字符串）"""
        for action_id, binding in self._mouse_bindings.items():
            if binding == token:
                return action_id
        return ""

    def _inside_editable_text(self, widget):
        """按下的位置是否落在可编辑控件里（沿父链往上找）"""
        node = widget
        while node is not None:
            if isinstance(node, self.EDITABLE_TEXT_TYPES):
                return True
            if (isinstance(node, (QTextEdit, QPlainTextEdit))
                    and not node.isReadOnly()):
                return True
            # 走到窗口（阅读区的 QTextEdit 是只读的，不拦）就不必再往上
            if node.isWindow():
                return False
            node = node.parentWidget()
        return False

    def _mouse_shortcut_allowed(self, obj):
        """这次鼠标按下要不要当成快捷键处理

        鼠标键没有「焦点」这个概念，所以只要求主窗口是当前活动窗口：
        对话框、弹出菜单开着的时候按侧键不会顺手把章节翻掉。
        """
        if not isinstance(obj, QWidget):
            return False
        app = QApplication.instance()
        if app is None or app.activeWindow() is not self:
            return False
        if obj is not self and not self.isAncestorOf(obj):
            return False
        return not self._inside_editable_text(obj)

    def handle_mouse_shortcut(self, obj, event):
        """鼠标键（侧键 / 中键）派发：绑定了就触发对应动作

        返回 ``True`` 表示事件已经用掉（不要再给控件处理）。
        """
        token = mouse_token_of_event(event)
        if not token or not self._mouse_shortcut_allowed(obj):
            return False
        now = time.monotonic()
        if (token == self._mouse_last_token
                and now - self._mouse_last_time < self.MOUSE_REPEAT_GUARD):
            # 同一下按键的连发（按住侧键）：当成已处理，但不再触发
            return True
        action_id = self._mouse_action_for(token)
        if not action_id:
            return False
        self._mouse_last_token = token
        self._mouse_last_time = now
        handler = self._reader_handlers.get(action_id)
        if handler is not None:
            handler()
            return True
        action = self._actions.get(action_id)
        if action is None or not action.isEnabled():
            return False
        action.trigger()
        return True

    def eventFilter(self, obj, event):
        """阅读区按键过滤 + 鼠标键派发

        * ``MouseButtonPress``：鼠标侧键 / 中键绑了快捷键就派发（应用级过滤器）；
        * ``ShortcutOverride``：把 Ctrl+Home / Ctrl+End 这类按键放行给窗口级快捷键，
          否则会被 ``QTextEdit`` 自带的「文档首 / 文档尾」吃掉；
        * ``KeyPress``：派发只在阅读区生效的按键（方向键、翻页键）。
        """
        if event.type() == QEvent.MouseButtonPress:
            if self.handle_mouse_shortcut(obj, event):
                return True

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
        # 应用主题（名字已经失效时回落到默认主题，并把配置改回去）
        theme_name = self.config_manager.get("theme", DEFAULT_THEME)
        if not self.theme_manager.exists(theme_name):
            self.logger.log(f"主题 {theme_name!r} 不存在，回落到 {DEFAULT_THEME}", "WARN")
            theme_name = DEFAULT_THEME
            self.config_manager.set("theme", theme_name)
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
        # 恢复上次拖到的宽度（旧配置里没这个键就用默认值）
        self.apply_sidebar_width()
        # 文案（显示 / 隐藏）已随之改变，刷新按钮、工具栏动作与提示文本
        self._refresh_sidebar_text()
        self.update_theme_menu()
        self.update_progress()
        # 朗读相关配置（语速 / 开关 / 可用性）
        self.apply_speech_settings()
        # 系统托盘与全局媒体键（v1.3.9）
        self.apply_tray_settings()
        self.apply_media_keys_settings()
    
    def apply_theme(self, theme_name):
        """应用主题。

        样式表统一由 :func:`enm.ui.theme_qss.build_style_sheet` 生成（主题编辑器
        的实时预览用的是同一份规则，所以预览看到的就是实际效果）；拿不到主题
        时 ``get_theme()`` 会兜底成浅色，不会因为配置里存了个坏名字就打不开。

        同时把 :func:`enm.ui.theme_qss.build_palette` 生成的调色板设到
        ``QApplication`` 上：滚动区视口、数值微调框、字体清单，以及 Qt 自带
        对话框（字体 / 颜色 / 输入框）内部那些**只认调色板**的控件，光靠
        样式表刷不到，深色主题下会留浅色底。设到应用级是为了不漏掉这些
        不属于主窗口子树的控件（含 Qt 自带的顶层对话框）。

        排版（字体 / 字号 / 行距 / 段间距）的优先级：``typography_follow_theme``
        打开且主题自带排版 → 用主题的；否则 → 用 ``config.json`` 里的全局设置。
        """
        theme = self.theme_manager.get_theme(theme_name)
        self._current_theme = theme

        family, size, _spacing, _paragraph = self.resolve_typography(theme)
        if family:
            self.reader_display.setFont(QFont(family, size))
        self.setStyleSheet(build_style_sheet(theme, font_size=size))
        # 行距 / 段间距样式表管不了（Qt 不支持 line-height），必须给文档套块格式
        self.apply_reader_typography(keep_scroll=True)
        app = QApplication.instance()
        if app is not None:
            app.setPalette(build_palette(theme))

        self.apply_native_titlebar(theme)
        # 高亮底色取自主题（highlight / selection / accent），换主题或改字号
        # 之后要重标一次，否则还留着上一套配色
        self.apply_speech_highlight(self._tts_highlight_index)
        # 开着的对话框也要跟着变，不能等关掉重开（只有非模态那几个会变）
        self.restyle_open_dialogs(theme)

    def restyle_open_dialogs(self, theme=None):
        """把换好的主题重新套到已经打开的非模态对话框上。

        只管有 ``apply_ui_theme()`` 的可视窗口——也就是音色、音色管理、读音
        纠正这三个 TTS 窗口。其它对话框都是模态的，开着的时候菜单点不动、
        主题根本换不了，不需要这条路。真出错了只记日志：换个主题不应该把
        别的东西带崩。
        """
        if theme is None:
            theme = getattr(self, "_current_theme", None)
        titlebar_theme = self.dialog_titlebar_theme()
        for name in ("_tts_voice_dialog", "_tts_model_dialog",
                     "_tts_pron_dialog"):
            dialog = getattr(self, name, None)
            if dialog is None or not dialog.isVisible():
                continue
            apply_theme = getattr(dialog, "apply_ui_theme", None)
            if apply_theme is None:
                continue
            try:
                apply_theme(theme, titlebar_theme)
            except Exception as exc:        # noqa: BLE001 - 换主题不能崩
                self.logger.log(f"刷新对话框主题失败：{exc}", "WARN")

    # ---------------- 原生标题栏与主题排版 ----------------

    def resolve_typography(self, theme):
        """当前该用的阅读排版。

        返回 ``(字体, 字号, 行距倍数, 段间距像素)``：主题自带排版且开了「排版
        跟随主题」时用主题的，否则一律用全局设置——这样主题和设置菜单里的
        字体 / 排版对话框不会互相抢控制权。逐项判定，所以只带了字体的主题
        不会把行距一并接管。
        """
        family = self.config_manager.get("font_family", "Microsoft YaHei")
        size = int(self.config_manager.get("font_size", 16) or 16)
        spacing = normalise_line_spacing(
            self.config_manager.get("line_spacing", DEFAULT_LINE_SPACING))
        paragraph = normalise_paragraph_spacing(
            self.config_manager.get("paragraph_spacing",
                                    DEFAULT_PARAGRAPH_SPACING))

        following = self.config_manager.get("typography_follow_theme", False)
        # 注意用 ``is not None``：段间距 0 是合法值，不能用真假判断
        has_typography = any(theme.get(field) is not None
                             for field in TYPO_FIELDS)
        if not following or not has_typography:
            return (family, size,
                    spacing if spacing is not None else DEFAULT_LINE_SPACING,
                    paragraph if paragraph is not None
                    else DEFAULT_PARAGRAPH_SPACING)

        theme_paragraph = normalise_paragraph_spacing(theme.get("paragraph_spacing"))
        return (theme.get("font_family") or family,
                int(normalise_font_size(theme.get("font_size")) or size),
                normalise_line_spacing(theme.get("line_spacing"))
                or spacing or DEFAULT_LINE_SPACING,
                (theme_paragraph if theme_paragraph is not None
                 else (paragraph if paragraph is not None
                       else DEFAULT_PARAGRAPH_SPACING)))

    def resolve_typography_locks(self, theme=None):
        """哪几项排版被主题接管了，返回 ``(行距, 段间距)`` 两个布尔值。

        「排版设置」对话框靠它决定哪个输入框要禁用（改主题管着的值没意义）。
        """
        theme = theme if theme is not None else getattr(
            self, "_current_theme", None) or {}
        if not self.config_manager.get("typography_follow_theme", False):
            return False, False
        return (normalise_line_spacing(theme.get("line_spacing")) is not None,
                normalise_paragraph_spacing(theme.get("paragraph_spacing")) is not None)

    def apply_reader_typography(self, line_spacing=None, paragraph_spacing=None,
                                keep_scroll=False):
        """把行距 / 段间距套到阅读区文档上。

        参数为 ``None`` 时用当前生效的排版（见 :meth:`resolve_typography`）。
        换字体、换字号、换主题、重新 ``setHtml()`` 之后都必须再调一次：
        ``setHtml`` 会把块格式一并冲掉（新建的文档没带行距信息）。

        ``keep_scroll=True`` 会把滚动条位置按比例还原——改间距会让文档变高，
        不还原的话阅读位置会跳得很难受。
        """
        if line_spacing is None or paragraph_spacing is None:
            _family, _size, current_line, current_paragraph = \
                self.resolve_typography(getattr(self, "_current_theme", None) or {})
            line_spacing = current_line if line_spacing is None else line_spacing
            paragraph_spacing = (current_paragraph if paragraph_spacing is None
                                 else paragraph_spacing)

        percent = self.current_scroll_percent() if keep_scroll else 0.0
        apply_reader_typography(self.reader_display, line_spacing,
                                paragraph_spacing)
        if keep_scroll:
            self.apply_scroll_percent(percent)

    def titlebar_follow_enabled(self):
        """是否让 Windows 原生标题栏跟着主题走"""
        return bool(self.config_manager.get("titlebar_follow_theme", False))

    def titlebar_theme(self):
        """要套到标题栏上的主题字典；不上色时返回 ``None``"""
        if not self.titlebar_follow_enabled():
            return None
        return getattr(self, "_current_theme", None)

    def dialog_titlebar_theme(self):
        """子对话框的标题栏该用哪套配色（和主窗口一致：一起上色 / 一起不上）"""
        return self.titlebar_theme()

    def apply_native_titlebar(self, theme=None, hwnd=None):
        """把主题的标题栏配色刷到原生窗口上。

        Win11 22H2（Build 22000）以上：标题栏底色、文字色、边框色全上；
        更老的系统这些属性会被拒，退化成「只切深浅模式」（按标题栏底色明度
        自动选），至少让系统画的三个按钮不至于和深色背景糊在一起。
        窗口还没 ``show()`` 时句柄无效，调用会静默失败——``changeEvent``
        里会补一次。
        """
        if not available():
            return 0
        if hwnd is None:
            hwnd = int(self.winId())

        if not self.titlebar_follow_enabled() or not theme:
            reset_titlebar_theme(hwnd)
            return 0

        applied = apply_titlebar_theme(hwnd, theme)
        if applied:
            return applied

        # 一个属性都没写成功（老系统）：退化成只切深浅。底色取 titlebar，
        # 没推导出来就退到 background
        base = theme.get("titlebar") or theme.get("background") or "#FFFFFF"
        apply_dark_mode(hwnd, is_dark(base))
        return 0

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
                self.apply_reader_typography()
                self.update_progress()
                # 正文没了：同步一次，别让朗读继续读上一本书
                self.sync_speech_content()
                # 换到空文件时标题也得跟着走，别停在上一篇
                self.update_window_title()
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
                self.apply_reader_typography()
                self.update_progress()
                self.sync_speech_content()
                self.update_window_title()
                return
            if not (0 <= reader.current_chapter < reader.get_chapter_count()):
                reader.current_chapter = 0
            title = reader.get_chapter_title(reader.current_chapter)
            content = reader.get_chapter_content(reader.current_chapter)
            chapter_index = reader.current_chapter
        
        self.reader_display.setHtml(format_chapter_html(title, content))
        # setHtml 会重建文档、顺便把块格式冲掉，行距 / 段间距得重新套（Qt 样式表
        # 里的 line-height 是无效属性，间距只能这么做）
        self.apply_reader_typography()

        # 图片自适应阅读区宽度（重新渲染章节时重置缓存）
        self._image_widths = {}
        self.fit_document_images()

        # 统计已读章节，并按记录恢复章内位置（无待恢复值时回到章首）
        self.mark_chapter_read(chapter_index)
        self.restore_pending_scroll()
        
        self.update_progress()
        # 正文换了：重排朗读句子表（正在朗读时接着读，见 sync_speech_content）
        self.sync_speech_content()
        # 书名 / 章节名跟着走，窗口标题栏与系统媒体面板都要刷。
        # 文件夹模式下这一步不能省：翻章可能翻到**另一个文件**，
        # get_book_info() 返回的是当前文件的名字，标题不刷就会停在上一次打开的那篇。
        # （update_window_title 内部已经调了 refresh_media_panel）
        self.update_window_title()

    # ---------------- 内嵌图片展示 ----------------

    def resizeEvent(self, event):
        """窗口尺寸变化后重新计算图片显示宽度"""
        super().resizeEvent(event)
        if self.current_reader is not None:
            self.image_fit_timer.start(150)

    def changeEvent(self, event):
        """窗口状态变化时的处理。

        * ``ActivationChange``：开始 / 暂停阅读计时；
        * ``Show`` / ``WinIdChange``：窗口刚显示、或原生窗口被重建（切窗口标志、
          从最大化还原等）后，原来的 DWM 属性可能丢了，得重新刷一遍。
        """
        super().changeEvent(event)
        event_type = event.type()
        if event_type == QEvent.ActivationChange:
            self.on_activation_changed(self.isActiveWindow())
        elif event_type in (QEvent.Show, QEvent.WinIdChange):
            self.apply_native_titlebar(getattr(self, "_current_theme", None))
            if event_type == QEvent.Show:
                # 从托盘唤回来：「显示 / 隐藏主窗口」得跟着改文案
                self._refresh_tray()
        elif event_type == QEvent.Hide:
            self._refresh_tray()

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
                start_index = self.current_reader.current_file_index
                index = start_index
                while index > 0:
                    index -= 1
                    self.current_reader.current_file_index = index
                    prev_reader = self.current_reader.get_current_reader()
                    if prev_reader is not None and prev_reader.get_chapter_count() > 0:
                        prev_reader.current_chapter = prev_reader.get_chapter_count() - 1
                        moved = True
                        break
                if not moved:
                    # 前面的文件全是空的/打不开的：索引退回原处
                    self.current_reader.current_file_index = start_index
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
                start_index = self.current_reader.current_file_index
                index = start_index
                while index < len(self.current_reader.files) - 1:
                    index += 1
                    self.current_reader.current_file_index = index
                    next_reader = self.current_reader.get_current_reader()
                    if next_reader is not None and next_reader.get_chapter_count() > 0:
                        next_reader.current_chapter = 0
                        moved = True
                        break
                if not moved:
                    # 后面的文件全是空的/打不开的：索引退回原处，免得界面和状态对不上
                    self.current_reader.current_file_index = start_index
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
        """当前书籍实际使用的阅读记录键

        一般是按文件内容（文件夹按路径）哈希出来的键；认出书本身份之后会换成
        ``book:<book_id>``，让同一本书的不同版本共用同一份记录与统计。
        """
        if not self.current_file_path:
            return ""
        if self._progress_record_key:
            return self._progress_record_key
        return self.progress_manager.build_file_key(self.current_file_path)

    def legacy_progress_key(self):
        """旧版本使用的阅读记录键（直接是路径），仅用于迁移旧记录"""
        return str(self.current_file_path) if self.current_file_path else ""

    # ---------------- 书本身份与多版本共用进度 ----------------

    def current_book_title(self):
        """当前书籍的书名与作者（书名缺失时回退到文件名 / 文件夹名）"""
        path = Path(str(self.current_file_path))
        info = {}
        if self.current_reader:
            try:
                info = self.current_reader.get_book_info() or {}
            except Exception as e:
                self.logger.log(f"读取书籍信息失败: {e}", "WARN")
                info = {}

        title = str(info.get("title") or "").strip()
        if not title:
            title = path.name if path.is_dir() else path.stem
        return title, str(info.get("author") or "").strip()

    def current_book_identity(self):
        """当前书籍的身份签名（书名 + 作者 + 开头几章的标题指纹）

        文件夹模式不参与：它的记录键就是目录路径，增删文件都不影响。
        章节名是自动编号的（UMD 缺章节标题、TXT 只有「第N章」等）算不出指纹，
        此时给出只看书名的**弱身份**（``weak_id``），由调用方去问用户；
        连书名都没有的（既没有 ``book_id`` 也没有 ``weak_id``）才退回按内容哈希。
        """
        if self._book_identity:
            return self._book_identity
        if not self.current_reader or isinstance(self.current_reader, FolderReader):
            return {}

        title, author = self.current_book_title()
        try:
            total = self.current_reader.get_chapter_count()
        except Exception as e:
            self.logger.log(f"获取章节总数失败: {e}", "WARN")
            total = 0

        titles = [self.chapter_title_of(self.current_reader, index)
                  for index in range(min(FINGERPRINT_SAMPLE, total))]
        self._book_identity = build_identity(title, titles, author=author,
                                             total_chapters=total)
        return self._book_identity

    def progress_share_decisions(self):
        """配置里「不再询问」的答案：``{比对键: 是否共用进度}``"""
        entries = self.config_manager.get("progress_share_ignored", [])
        decisions = {}
        if not isinstance(entries, list):
            return decisions
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "")
            if key:
                decisions[key] = bool(entry.get("share"))
        return decisions

    @staticmethod
    def progress_share_key(identity, entry):
        """「不再询问」的比对键：书名 + 这一份已有记录"""
        _record_file, record, _reason = entry
        return f"{identity.get('title_key', '')}|{record_file_key(record)}"

    def remember_progress_share(self, identity, pending, picked):
        """把用户「以后不再询问」的选择写进配置

        ``picked`` 是本次确认要合并的记录文件；不在里面的就是选了「保持独立」，
        下次遇到这一对文件就直接按这次的选择办。
        """
        entries = self.config_manager.get("progress_share_ignored", [])
        entries = list(entries) if isinstance(entries, list) else []
        picked = {Path(item) for item in (picked or [])}
        known = {str(entry.get("key") or "") for entry in entries
                 if isinstance(entry, dict)}

        for entry in pending:
            key = self.progress_share_key(identity, entry)
            if not key or key in known:
                continue
            entries.append({"key": key, "share": Path(entry[0]) in picked})
            known.add(key)
        self.config_manager.set("progress_share_ignored", entries[-MAX_SHARE_IGNORED:])

    def ask_merge_progress(self, file_key, pending, weak=False):
        """弹一次确认框：认出来的其它版本要不要共用阅读进度

        返回 ``(确认要合并的记录文件列表, 用户是否勾了不再询问)``。
        """
        current = self.progress_manager.load_progress(file_key) or self.progress_metadata()
        dialog = BookMergeDialog(
            current,
            [(Path(record_file), record)
             for record_file, record, _reason in pending],
            self, titlebar_theme=self.dialog_titlebar_theme(), weak=weak)
        dialog.exec_()
        return dialog.confirmed_record_files(), dialog.dont_ask

    def adopt_shared_record(self, plan, content_key):
        """关掉自动共用时：身份键上的记录要不要拿来当这本书的记录

        强身份直接在，因为书本身份已经认定是同一本；弱身份（只按书名）得先
        看到记录里确实有当前这个文件，否则那可能是同名另一本书的进度。
        """
        target_key = str((plan or {}).get("key") or "")
        if not target_key or target_key == content_key:
            return False
        if not plan.get("weak"):
            return self.progress_manager.get_progress_file_path(target_key).exists()
        return record_covers_file(self.progress_manager.load_progress(target_key),
                                  content_key, str(self.current_file_path))

    def resolve_reading_record(self):
        """决定用哪个记录键打开这本书，需要时把其它版本的进度合并进来

        返回最终使用的记录键。这项功能只做加值：认不出身份、连书名都取不到、
        或者中途出错，一律退回按内容哈希的旧行为，绝不让书打不开。

        身份分两等：书名 + 章节指纹的**强身份**可以静默共用进度；
        章节名是程序自动编号的书只有书名可用（**弱身份**），一律先问用户。
        """
        self._book_identity = {}
        self._progress_record_key = ""
        if not self.current_file_path:
            return ""

        content_key = self.progress_manager.build_file_key(self.current_file_path)
        self._progress_record_key = content_key

        try:
            identity = self.current_book_identity()
            weak = not identity.get("book_id")
            if not (identity.get("book_id") or identity.get("weak_id")):
                return content_key

            plan = self.progress_manager.plan_record_key(
                content_key, identity, str(self.current_file_path))
            target_key = str(plan.get("key") or content_key)

            if not self.config_manager.get("share_progress_versions", True):
                # 关掉自动共用：已经存在的书本身份记录照读不误（否则以前合并过的
                # 进度会好像丢了），但不做任何迁移与合并
                if self.adopt_shared_record(plan, content_key):
                    self._progress_record_key = target_key
                return self._progress_record_key

            decisions = self.progress_share_decisions()
            confirmed = []
            pending = []
            for entry in plan.get("candidates") or []:
                decision = decisions.get(self.progress_share_key(identity, entry))
                if decision is True:
                    confirmed.append(Path(entry[0]))
                elif decision is None:
                    # 还没问过用户的才需要问；回答过「保持独立」的就此略过
                    pending.append(entry)

            if pending:
                picked, dont_ask = self.ask_merge_progress(content_key, pending,
                                                           weak=weak)
                confirmed.extend(picked)
                if dont_ask:
                    self.remember_progress_share(identity, pending, picked)

            self._progress_record_key = self.progress_manager.apply_record_key(
                plan, confirmed)

            merged = len(plan.get("sources") or []) + len(confirmed)
            if merged:
                self.logger.log(f"按书本身份共用阅读记录（合并 {merged} 份）: "
                                f"{content_key} -> {self._progress_record_key}")
        except Exception as e:
            self.logger.log(f"识别同书不同版本失败，改用内容哈希记录: {e}", "WARN")
            self._book_identity = {}
            self._progress_record_key = content_key

        return self._progress_record_key

    def progress_metadata(self):
        """生成阅读记录的元数据：文件名、内容哈希、书名与身份签名等。"""
        if not self.current_file_path:
            return {}

        path = Path(str(self.current_file_path))
        metadata = self.progress_manager.key_metadata(self.current_file_path,
                                                      self.progress_key())

        title, author = self.current_book_title()
        metadata["novelname"] = title
        metadata["author"] = author
        metadata["app_version"] = VERSION

        # 书本身份：下次拿同一本书的另一个版本（重新导出 / 追加了章节）打开时，
        # 靠这几个字段认出来并共用进度
        identity = self.current_book_identity()
        if identity:
            metadata["title_key"] = identity.get("title_key", "")
            metadata["author_key"] = identity.get("author_key", "")
            metadata["book_id"] = identity.get("book_id", "")
            metadata["chapter_fingerprint"] = identity.get("chapter_fingerprint", "")
            metadata["fingerprint_titles"] = identity.get("fingerprint_titles", [])

        # 内容哈希与记录键无关：用来区分同一本书的不同版本（文件）；
        # 文件夹没有内容哈希
        if path.is_file():
            file_digest = self.progress_manager.content_digest(path)
            if file_digest:
                metadata["file_md5"] = file_digest

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

    def reader_titles(self, reader):
        """某本书（或文件夹里的某个文件）的全部章节标题，取不到时给空列表"""
        try:
            count = max(0, reader.get_chapter_count())
        except Exception:
            return []
        return [self.chapter_title_of(reader, index) for index in range(count)]

    def locate_chapter(self, reader, index, title):
        """在新版本里定位上次读到的章节

        先按章节标题找（同名章节取离原下标最近的那个），找不到再退回夹到有效
        范围的下标：新版本基本都是往后追加章节，原下标本身往往就是对的。
        """
        try:
            count = max(0, reader.get_chapter_count())
        except Exception:
            return 0
        if count <= 0:
            return 0

        try:
            index = max(0, min(count - 1, int(index or 0)))
        except (TypeError, ValueError):
            index = 0

        wanted = normalise_chapter_title(title)
        if not wanted:
            return index
        if normalise_chapter_title(self.chapter_title_of(reader, index)) == wanted:
            return index
        return chapter_index_in(self.reader_titles(reader), index, title)

    def load_reading_progress(self):
        """加载阅读进度"""
        if not self.current_file_path or not self.current_reader:
            return

        # 先认书：同一本书的其它版本共用同一份记录，需要时在这里把它合并过来
        file_key = self.resolve_reading_record() or self.progress_key()
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

                if 0 <= file_index < self.current_reader.get_file_count():
                    self.current_reader.current_file_index = file_index
                    reader = self.current_reader.get_current_reader()
                    # 章节也按标题定位：换过版本的内层文件章节序号可能错位
                    chapter_index = progress.get("chapter", 0)
                    if reader:
                        chapter_index = self.locate_chapter(
                            reader, chapter_index, progress.get("chapter_title"))
                        reader.current_chapter = chapter_index
                    # 文件可能已变化，重建章节列表后再选中
                    self.update_chapter_list()
                    self.select_chapter_in_tree("file", file_index)
            else:
                # 单文件模式：恢复章节（先按上次的章节标题定位，
                # 重新导出导致章节序号错位时也能找回原来那一章）
                chapter_index = self.locate_chapter(
                    self.current_reader, progress.get("chapter", 0),
                    progress.get("chapter_title"))
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
        """统计单元名：单文件模式统一是 ``"*"``，文件夹模式是当前内层文件名

        单文件模式一份记录就对应整本书，用文件名当单元名的话，文件改名或换成
        另一个版本后，同一批章节会在同一份记录里被数好几遍。
        """
        if isinstance(self.current_reader, FolderReader):
            current = self.current_reader.get_current_file()
            if current:
                return str(current['name'])
            return ""
        return "*" if self.current_reader else ""

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
        """窗口激活状态变化：激活时开始计时，失焦时结算并落盘一次

        例外：正在朗读时不结算 —— 用户就是让程序读给自己听，窗口失焦
        （切去看别的东西）这段仍然是阅读时间，等朗读停下来再结算。
        """
        if active:
            if self.current_reader is not None and self._focus_started_at is None:
                self._focus_started_at = time.monotonic()
            return
        
        if not self.speech_active():
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

    def toggle_titlebar_follow(self, checked):
        """切换「原生标题栏跟随主题」"""
        self.config_manager.set("titlebar_follow_theme", bool(checked))
        current = self.config_manager.get("theme", DEFAULT_THEME)
        self.apply_theme(current)

    def toggle_typography_follow(self, checked):
        """切换「排版跟随主题」（大小依赖主题自带的字体 / 字号 / 行距）"""
        self.config_manager.set("typography_follow_theme", bool(checked))
        current = self.config_manager.get("theme", DEFAULT_THEME)
        self.apply_theme(current)

    def toggle_share_progress(self, checked):
        """切换「同名书籍共用阅读进度」

        开关影响的是「下次打开书籍时怎么找记录」，所以当前这本书维持现状，
        重新打开后才按新的设置走。
        """
        self.config_manager.set("share_progress_versions", bool(checked))
        self.logger.log(f"同名书籍共用阅读进度: {'开启' if checked else '关闭'}")

    def show_continue_reading(self):
        """打开「继续阅读」面板，选中记录后直接接着读"""
        dialog = ContinueReadingDialog(self.progress_manager, self,
                                       titlebar_theme=self.dialog_titlebar_theme())
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
            # QSplitter 在侧边栏隐藏期间会把它的宽度压成 0，显示回来时得
            # 重新摆一次，否则章节列表恢复出来只有一条缝
            self.apply_sidebar_width()
        else:
            self.sidebar.hide()
        
        # 文案（显示 / 隐藏）已随之改变，刷新按钮、工具栏动作与提示文本
        self._refresh_sidebar_text()
        
        # 保存侧边栏状态到配置
        self.config_manager.set("sidebar_visible", self.sidebar_visible)

    # ---------------- 侧边栏宽度（分隔条） ----------------

    def apply_sidebar_width(self):
        """按配置里的宽度摆好分隔条位置。

        QSplitter 分的是「两边各占多少」，所以把宽度换算成
        ``[侧边栏, 剩下的全给阅读区]``；窗口尺寸变化时 QSplitter 会按这个
        比例自己折算，所以窗口还没真正显示出来也能先设。
        """
        width = clamp_sidebar_width(
            self.config_manager.get("sidebar_width", SIDEBAR_WIDTH_DEFAULT))
        total = max(self.main_splitter.width(), self.width(), 1)
        self.main_splitter.setSizes([width, max(1, total - width)])

    def _on_splitter_moved(self, _position, _index):
        """拖动中：只重启定时器，等手停下来再落盘"""
        self.sidebar_width_timer.start()

    def _save_sidebar_width(self):
        """把当前侧边栏宽度写进配置。

        侧边栏隐藏时 QSplitter 会把它的宽度压成 0，这时写进去等于把用户
        之前拖出来的宽度冲掉，所以直接跳过。
        """
        if not self.sidebar_visible:
            return
        width = self.sidebar.width()
        if width > 0:
            self.config_manager.set("sidebar_width", width)
    
    def current_theme_name(self):
        """当前主题键（配置里的值；已经不存在时返回默认主题）"""
        theme_name = self.config_manager.get("theme", DEFAULT_THEME)
        if self.theme_manager.get_theme(theme_name, fallback=None) is None:
            return DEFAULT_THEME
        return theme_name

    def update_theme_menu(self):
        """刷新主题菜单：内置主题的勾选状态 + 重建自定义主题列表"""
        current = self.current_theme_name()
        self._actions["view.theme_light"].setChecked(current == "light")
        self._actions["view.theme_dark"].setChecked(current == "dark")

        self.custom_theme_menu.clear()
        names = self.theme_manager.custom_theme_names()
        if not names:
            empty = self.custom_theme_menu.addAction(
                i18n.t("menu.theme_custom_empty"))
            empty.setEnabled(False)
            return

        for name in names:
            action = QAction(theme_display_label(self.theme_manager, name, False), self)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.triggered.connect(
                lambda _checked=False, target=name: self.change_theme(target))
            self.custom_theme_menu.addAction(action)

    def change_theme(self, theme_name):
        """切换主题"""
        if not self.theme_manager.exists(theme_name):
            self.logger.log(f"主题 {theme_name!r} 不存在，改用 {DEFAULT_THEME}", "WARN")
            theme_name = DEFAULT_THEME

        if DEBUG_MODE:
            self.logger.debug(f"切换主题: {theme_name}")
        
        self.config_manager.set("theme", theme_name)
        self.apply_theme(theme_name)
        self.update_theme_menu()
        
        if DEBUG_MODE:
            self.logger.debug(f"主题切换完成: {theme_name}")
    
    def change_font(self):
        """更改字体"""
        current_font = QFont(
            self.config_manager.get("font_family", "Microsoft YaHei"),
            self.config_manager.get("font_size", 16)
        )

        # 不用 QFontDialog.getFont() 静态函数：它建的对话框拿不到引用，
        # 标题与标题栏都没法控制（标题默认是 Qt 自己的 "Select Font"，
        # 而标题栏要靠主窗口的应用级事件过滤器上色，也只能是可见的窗口）
        dialog = QFontDialog(current_font, self)
        dialog.setWindowTitle(i18n.t("menu.font_settings"))
        if dialog.exec_() != QDialog.Accepted:
            return

        font = dialog.selectedFont()
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
    
    def open_typography_dialog(self):
        """打开「排版设置」（行距 / 段间距）。

        对话框只负责取值与实时试排；配置与阅读区由这里统一更新——按「取消」
        时再把阅读区还原回原来的值，所以拖动数值不会脏掉配置。
        """
        original = (self.config_manager.get("line_spacing", DEFAULT_LINE_SPACING),
                    self.config_manager.get("paragraph_spacing",
                                            DEFAULT_PARAGRAPH_SPACING))
        theme = getattr(self, "_current_theme", None)
        line_locked, paragraph_locked = self.resolve_typography_locks(theme)

        dialog = TypographySettingsDialog(
            line_spacing=original[0], paragraph_spacing=original[1], parent=self,
            ui_theme=self.theme_manager.get_theme(self.current_theme_name()),
            titlebar_theme=self.dialog_titlebar_theme(),
            line_follows_theme=line_locked,
            paragraph_follows_theme=paragraph_locked)
        dialog.preview_changed.connect(self.preview_typography)

        accepted = dialog.exec_() == QDialog.Accepted
        if not accepted:
            # 取消：把试排结果丢掉，回到磁盘上的值
            self.apply_reader_typography(keep_scroll=True)
            return

        spacing, paragraph = dialog.values()
        self.config_manager.set("line_spacing", spacing)
        self.config_manager.set("paragraph_spacing", paragraph)
        # 重新套一遍：主题样式表要重算，排版也顺手刷新（含标题栏 / 高亮）
        self.apply_theme(self.current_theme_name())
        self.logger.log(f"排版设置: 行距 {spacing}、段间距 {paragraph}px")

    def preview_typography(self, line_spacing, paragraph_spacing):
        """排版设置对话框的实时试排（只动显示，不写配置）"""
        self.apply_reader_typography(line_spacing, paragraph_spacing,
                                     keep_scroll=True)

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
        # Qt 自己画的对话框（字体 / 颜色 / 输入框 / 消息框）得换一套目录，
        # 否则它们还停在上一门语言
        self._install_qt_translations()
        # 日志由 LanguageManager.set_language 统一输出，这里不再重复记录
        self.retranslate_ui()
        # 界面语言变了，朗读语音也跟着换（中文书用中文语音，英文书用英文语音）；
        # 用户手动指定过语音的话 pick_voice 会优先用它
        self.apply_speech_voice()
    
    def _install_qt_translations(self):
        """按当前界面语言装卸 Qt 自带翻译（见 :mod:`enm.ui.qt_translations`）

        影响的是 Qt 自己画的对话框（字体选择、颜色选择、输入框、消息框）
        的标题 / 标签 / 按钮 —— 这些文案不在 ``lang/*.json`` 里，得靠 Qt 的
        ``.qm`` 目录。英文时只卸载不加载（Qt 源语言就是英文）。
        """
        files = install_qt_translations(QApplication.instance(),
                                        i18n.current_language())
        if DEBUG_MODE:
            self.logger.debug(f"Qt 翻译: {files or '（无，用 Qt 源语言）'}")
    
    def _theme_choices(self):
        """(显示名, 主题键) 列表，用于让用户挑选一个主题"""
        return [(theme_display_label(self.theme_manager, key, is_builtin),
                 key)
                for key, is_builtin, _theme in self.theme_manager.entries()]

    def pick_theme(self, title, label):
        """弹出一个下拉框让用户选主题，返回主题键（取消返回 None）"""
        choices = self._theme_choices()
        if not choices:
            return None
        labels = [text for text, _key in choices]
        index = next((i for i, (_t, key) in enumerate(choices)
                      if key == self.current_theme_name()), 0)
        text, ok = QInputDialog.getItem(self, title, label, labels, index, False)
        if not ok:
            return None
        for display, key in choices:
            if display == text:
                return key
        return None

    def import_theme(self):
        """导入主题文件（严格校验：颜色 / 字段 / 名称都会被检查）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.import_theme"), "",
            i18n.t("common.theme_file_filter")
        )
        if not file_path:
            return

        ok, key, errors, warnings = self.theme_manager.import_theme_file(file_path)

        # 同名主题：先问清楚再覆盖（绝不静默覆盖用户自己调好的配色）
        if not ok and self._has_error(errors, "theme_error.name_exists"):
            if QMessageBox.question(
                    self, i18n.t("theme_manager.overwrite_title"),
                    i18n.t("theme_manager.overwrite_confirm", name=key),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                return
            ok, key, errors, warnings = self.theme_manager.import_theme_file(
                file_path, overwrite=True)

        # 文件名撞上了系统保留名（CON、NUL…）：让用户改个名字
        if not ok and self._has_error(errors, "theme_error.reserved_name"):
            new_name, accepted = QInputDialog.getText(
                self, i18n.t("theme_manager.rename_title"),
                i18n.t("theme_manager.rename_label"),
                text=self.theme_manager.next_available_name(key))
            if not accepted or not new_name.strip():
                return
            ok, key, errors, warnings = self.theme_manager.import_theme_file(
                file_path, name=new_name.strip())

        if not ok:
            QMessageBox.warning(self, i18n.t("common.error"),
                                describe_theme_errors(errors))
            return

        self.update_theme_menu()
        message = i18n.t("theme_manager.imported", name=theme_display_label(
            self.theme_manager, key, False))
        if warnings:
            # 多余字段不致命，但要说清楚被忽略了什么
            message += "\n\n" + describe_theme_errors(warnings)
        message += "\n\n" + i18n.t("theme_manager.ask_apply")
        if QMessageBox.question(self, i18n.t("common.success"), message,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes) == QMessageBox.Yes:
            self.change_theme(key)

    def export_theme(self):
        """导出主题为 JSON 文件（可导出内置主题，方便改一份自己的配色）"""
        theme_name = self.pick_theme(i18n.t("dialog.export_theme"),
                                     i18n.t("theme_manager.export_label"))
        if theme_name is None:
            return

        display = theme_display_label(self.theme_manager, theme_name,
                                      self.theme_manager.is_builtin(theme_name))
        file_path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dialog.export_theme"), f"{display}.json",
            i18n.t("common.theme_file_filter")
        )
        if not file_path:
            return

        ok, errors = self.theme_manager.export_theme_file(
            theme_name, file_path, display_name=display)
        if not ok:
            QMessageBox.warning(self, i18n.t("common.error"),
                                describe_theme_errors(errors))
            return
        QMessageBox.information(self, i18n.t("common.success"),
                               i18n.t("theme_manager.exported", path=file_path))

    def open_theme_manager(self):
        """打开主题管理对话框（新建 / 编辑 / 复制 / 改名 / 删除 / 导入导出）"""
        current = self.current_theme_name()
        family, size, spacing, paragraph = self.resolve_typography(
            self.theme_manager.get_theme(current))
        dialog = ThemeManagerDialog(
            self.theme_manager, current, self,
            ui_theme=self.theme_manager.get_theme(current),
            titlebar_theme=self.dialog_titlebar_theme(),
            font_family=family, font_size=size, line_spacing=spacing,
            paragraph_spacing=paragraph)
        dialog.exec_()
        # 对话框只记录「之后要应用哪个主题」，配置与主窗口由这里统一更新
        self.theme_manager.reload()
        self.update_theme_menu()
        if dialog.applied_theme:
            self.change_theme(dialog.applied_theme)
        else:
            current = self.config_manager.get("theme", DEFAULT_THEME)
            if not self.theme_manager.exists(current):
                # 当前主题被删掉了 / 改了名：回落到默认主题
                self.logger.log(f"当前主题 {current!r} 已不存在，回落到 {DEFAULT_THEME}",
                                "WARN")
                self.change_theme(DEFAULT_THEME)

    @staticmethod
    def _has_error(errors, code):
        """错误列表里是否含某个语言键（形如 (code, params) 或裸字符串）"""
        for error in errors or ():
            if (error[0] if isinstance(error, (tuple, list)) else error) == code:
                return True
        return False

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
            "about.feature_tts": {},
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
    
    # ---------------- 朗读（v1.3.5） ----------------

    def speech_available(self):
        """这台机器有没有可用的朗读引擎（结论只问一次系统）

        只查「系统里有哪些引擎」（``QTextToSpeech.availableEngines()``），
        **不**创建引擎对象 —— 没点过朗读就不加载系统语音，启动速度不受影响。
        """
        if self._tts_available is None:
            self._tts_available = bool(available_engines())
            if not self._tts_available:
                self.logger.log("系统没有可用的朗读引擎，朗读功能已置灰", "WARN")
        return self._tts_available

    def speech_active(self):
        """是否正在朗读 / 暂停中（失焦计时、关窗口都用它判断）"""
        queue = self._tts_queue
        return bool(queue is not None and queue.active)

    def speech_queue(self):
        """懒创建朗读队列（含本机语音引擎）；不可用时返回 ``None``"""
        if self._tts_queue is not None:
            return self._tts_queue
        if not self.speech_available():
            return None

        engine = self.speech_engine()
        backend = create_backend(engine or None)
        if backend is None and engine:
            # 用户上次指定的引擎没了（卸了 sherpa-onnx / 模型删光了 / 换了台机器）
            # → 改回「自动挑一个」，别把整个朗读功能锁死
            self.logger.log(f"朗读引擎 {engine} 现在用不了，改回自动选择", "WARN")
            engine = ""
            self.config_manager.set("tts_engine", "")
            backend = create_backend()
        if backend is None:
            self._tts_available = False
            self.update_speech_controls()
            return None

        changed = getattr(backend, "voices_changed", None)
        if changed is not None:
            # 在线音色清单是异步拉的；拉回来了就同步到开着的音色窗口
            changed.connect(self.refresh_voice_dialog)

        queue = SpeechQueue(backend, self)
        queue.sentence_changed.connect(self.on_speech_sentence_changed)
        queue.state_changed.connect(self.on_speech_state_changed)
        queue.finished.connect(self.on_speech_finished)
        queue.failed.connect(self.on_speech_failed)
        self._tts_backend = backend
        self._tts_queue = queue
        queue.set_rate(self.speech_rate())
        queue.set_volume(self.speech_volume())
        self.apply_speech_voice()
        if DEBUG_MODE:
            self.logger.debug(f"朗读引擎就绪: {backend.name}")
        return queue

    # ---- 配置 ----

    def speech_engine(self):
        """用户指定的朗读引擎名（空串 = 程序自己挑，见 ``available_engines``）"""
        return str(self.config_manager.get("tts_engine", "") or "")

    def speech_rate(self):
        """配置里的朗读语速（-1.0 ~ 1.0，取最接近的档位值）"""
        return nearest_rate(self.config_manager.get("tts_rate", 0.0))

    def speech_max_chars(self):
        """单句最长字符数（超长句子会被再切一刀）"""
        try:
            limit = int(self.config_manager.get("tts_split_max_chars",
                                                DEFAULT_MAX_CHARS))
        except (TypeError, ValueError):
            limit = DEFAULT_MAX_CHARS
        return limit

    def speech_volume(self):
        """配置里的朗读音量（0.0 ~ 1.0）"""
        return quantize_volume(self.config_manager.get("tts_volume", 1.0))

    def speech_bar_collapsed(self):
        """朗读条是否收起（收起后只留状态那一行，正文多看清两行）"""
        return bool(self.config_manager.get("tts_bar_collapsed", False))

    def speech_highlight_enabled(self):
        """是否高亮正在朗读的那一句"""
        return bool(self.config_manager.get("tts_highlight", True))

    def speech_auto_scroll_enabled(self):
        """是否跟着高亮自动滚动（高亮关了就没有滚动可言）"""
        return self.speech_highlight_enabled() and bool(
            self.config_manager.get("tts_auto_scroll", True))

    def speech_auto_next_enabled(self):
        """读完这章是否自动读下一章"""
        return bool(self.config_manager.get("tts_auto_next_chapter", True))

    def apply_speech_settings(self):
        """把朗读相关配置套到朗读条与队列上（apply_settings 末尾调用）"""
        rate = self.speech_rate()
        volume = self.speech_volume()
        self.tts_bar.set_rate(rate)
        self.tts_bar.set_volume(volume)
        self.tts_bar.set_collapsed(self.speech_bar_collapsed())
        self.tts_bar.set_auto_next(self.speech_auto_next_enabled())
        self.tts_bar.set_highlight(self.speech_highlight_enabled())
        for action, checked in (
                (getattr(self, "speech_auto_next_action", None),
                 self.speech_auto_next_enabled()),
                (getattr(self, "speech_highlight_action", None),
                 self.speech_highlight_enabled())):
            if action is not None:
                action.setChecked(checked)
        queue = self._tts_queue
        if queue is not None:
            queue.set_rate(rate)
            queue.set_volume(volume)
        self.update_speech_controls()

    def update_speech_controls(self):
        """按「有没有引擎」刷新朗读菜单、工具栏与朗读条"""
        enabled = self.speech_available()
        self.tts_bar.set_available(enabled)
        for action_id in ("tts.play_pause", "tts.stop", "tts.prev_sentence",
                          "tts.next_sentence", "tts.range_chapter",
                          "tts.range_cursor", "tts.range_selection",
                          "tts.range_chapters"):
            action = self._actions.get(action_id)
            if action is not None:
                action.setEnabled(enabled)
        for action in (getattr(self, "speech_auto_next_action", None),
                       getattr(self, "speech_highlight_action", None),
                       getattr(self, "speech_voice_action", None)):
            if action is not None:
                action.setEnabled(enabled)
        engine_menu = getattr(self, "speech_engine_menu", None)
        if engine_menu is not None:
            engine_menu.setEnabled(enabled)
        return enabled

    # ---- 语音 ----

    def apply_speech_voice(self):
        """按界面语言挑一个语音（用户手动选过的优先）

        朗读进行中不立刻换 —— 换语音会打断当前这句 —— 先记下来，等队列
        回到空闲再换（见 :meth:`on_speech_state_changed`）。
        """
        backend = self._tts_backend
        if backend is None:
            return
        voice = pick_voice(backend.voices(), i18n.current_language(),
                           self.config_manager.get("tts_voice_name", ""))
        if voice is None or voice.voice_id == backend.current_voice_id():
            return
        if self.speech_active():
            self._tts_voice_pending = voice.voice_id
            return
        backend.set_voice(voice.voice_id)
        self._tts_voice_pending = ""
        if DEBUG_MODE:
            self.logger.debug(f"朗读语音: {voice_label(voice)}")

    def select_speech_voice(self, voice_id):
        """用户在菜单里手动指定语音（记进配置，下次启动照旧）"""
        self.config_manager.set("tts_voice_name", voice_id)
        backend = self._tts_backend
        if backend is None:
            return
        if not self._ensure_voice_model(voice_id):
            return
        if self.speech_active():
            self._tts_voice_pending = voice_id
            return
        backend.set_voice(voice_id)

    def _ensure_voice_model(self, voice_id):
        """离线音色的模型没下载时问一句「现在下吗？」

        返回 ``False`` 表示先别换音色（模型还没到位）。下完之后
        :meth:`_on_tts_models_changed` 会把用户点的这个音色自动换上。
        """
        backend = self._tts_backend
        if (not voice_id or backend is None
                or backend.name != NEURAL_ENGINE or "|" not in voice_id):
            return True
        model_id = voice_id.rpartition("|")[0]
        if tts_models.is_installed(model_id):
            return True
        self._tts_voice_after_download = voice_id
        self.tts_model_dialog().prompt_download(model_id, self)
        return False

    # ---- 语音菜单 ----

    @staticmethod
    def engine_label(engine):
        """引擎在界面上的名字（没翻译就退回引擎标识，总比空着强）"""
        return i18n.t(f"tts.engine.{engine}", default=engine)

    def switch_speech_engine(self, engine):
        """换朗读引擎：停朗读 → 丢旧引擎 → 按新引擎重建队列"""
        if engine == self.speech_engine() and self._tts_backend is not None \
                and self._tts_backend.name == engine:
            return
        was_active = self.speech_active()
        self.stop_speech()
        self.shutdown_speech()          # 顺便把旧引擎的线程 / 临时文件收掉
        self.config_manager.set("tts_engine", engine)
        self._tts_voice_pending = ""
        queue = self.speech_queue()
        if queue is None:
            self.logger.log(f"切到朗读引擎 {engine} 失败", "WARN")
            self.config_manager.set("tts_engine", "")
            queue = self.speech_queue()
        if queue is not None:
            backend = self._tts_backend
            self.logger.log(f"朗读引擎已切换到 {backend.name}"
                            f"（{len(backend.voices())} 个音色）")
            if backend.name == EDGE_ENGINE and not backend.voices_ready():
                backend.refresh_async()     # 在线音色第一次用要拉清单
        self.update_speech_controls()
        if was_active:
            self.logger.log(i18n.t("tts.engine.switched",
                                   default="换了朗读引擎，朗读已停止"))

    def update_speech_engine_menu(self):
        """重建「朗读引擎」子菜单（打开菜单时才枚举，避免启动就加载引擎）"""
        menu = getattr(self, "speech_engine_menu", None)
        if menu is None:
            return
        menu.clear()
        if not self.speech_available():
            menu.menuAction().setVisible(False)
            return
        if self._tts_backend is None:
            # 用户点开了引擎菜单，说明要用朗读，这时候建引擎是值得的
            self.speech_queue()
        backend = self._tts_backend
        if backend is None:
            menu.menuAction().setVisible(False)
            return
        visible = self._fill_engine_menu(menu, backend)
        menu.menuAction().setVisible(visible)

    def _fill_engine_menu(self, menu, backend):
        """引擎单选组（系统 / 离线神经 / 在线）；返回有没有东西可显示"""
        engines = available_engines()
        if len(engines) < 2:
            return False
        for engine in engines:
            action = menu.addAction(self.engine_label(engine))
            action.setCheckable(True)
            action.setChecked(engine == backend.name)
            action.triggered.connect(
                lambda _checked=False, name=engine: self.switch_speech_engine(name))
        return True

    # ---- 音色选择窗口 ----

    def speech_voice_snapshot(self):
        """给「选择音色」窗口现取一份数据（引擎、可选引擎、音色表、当前音色）

        窗口每次 ``refresh()`` 都会调这里，所以刚下完的模型、刚拉回来的
        在线清单都能立刻看到。
        """
        if self._tts_backend is None and self.speech_available():
            self.speech_queue()
        backend = self._tts_backend
        if backend is None:
            return VoiceSnapshot()
        engine = backend.name
        ready = True
        note = ""
        if engine == EDGE_ENGINE:
            ready = bool(backend.voices_ready())
            if not ready:
                note = i18n.t("tts.voice.loading")
        elif engine == NEURAL_ENGINE and not backend.voices():
            note = i18n.t("tts.voice.empty_neural")
        return VoiceSnapshot(
            engine=engine,
            engine_label=self.engine_label(engine),
            engines=tuple((name, self.engine_label(name))
                          for name in available_engines()),
            voices=tuple(backend.voices()),
            current_id=backend.current_voice_id(),
            ready=ready,
            note=note)

    def tts_voice_dialog(self):
        """懒创建「选择音色」窗口（非模态；界面语言变了就重建）"""
        lang = i18n.current_language()
        if (self._tts_voice_dialog is not None
                and getattr(self, "_tts_voice_lang", lang) != lang):
            self._tts_voice_dialog.shutdown()
            self._tts_voice_dialog = None
        if self._tts_voice_dialog is None:
            dialog = TtsVoiceDialog(
                self,
                ui_theme=self.theme_manager.get_theme(self.current_theme_name()),
                titlebar_theme=self.dialog_titlebar_theme(),
                snapshot=self.speech_voice_snapshot)
            dialog.voice_selected.connect(self.select_speech_voice)
            dialog.engine_selected.connect(self.on_voice_dialog_engine)
            dialog.refresh_requested.connect(self.refresh_edge_voices)
            dialog.manage_requested.connect(self.open_tts_model_dialog)
            self._tts_voice_dialog = dialog
            self._tts_voice_lang = lang
        return self._tts_voice_dialog

    def open_tts_voice_dialog(self):
        """打开「选择音色」窗口（朗读菜单里的入口）"""
        if not self.speech_available():
            self.tts_bar.set_notice(i18n.t("menu.tts_unavailable"))
            return
        dialog = self.tts_voice_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def tts_pron_dialog(self):
        """懒创建「读音纠正」窗口（非模态；界面语言变了就重建）"""
        lang = i18n.current_language()
        if (self._tts_pron_dialog is not None
                and getattr(self, "_tts_pron_lang", lang) != lang):
            self._tts_pron_dialog.shutdown()
            self._tts_pron_dialog = None
        if self._tts_pron_dialog is None:
            dialog = TtsPronDialog(
                self,
                ui_theme=self.theme_manager.get_theme(self.current_theme_name()),
                titlebar_theme=self.dialog_titlebar_theme())
            dialog.changed.connect(self.on_pron_dictionary_changed)
            self._tts_pron_dialog = dialog
            self._tts_pron_lang = lang
        return self._tts_pron_dialog

    def open_tts_pron_dialog(self):
        """打开「读音纠正」窗口（朗读 / 设置菜单里的入口）"""
        dialog = self.tts_pron_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def on_pron_dictionary_changed(self):
        """词典改了：正在读的这一句不动，下一句起用新词典。

        ``SpeechQueue`` 已经把下一句预合成好了（音色 / 语速 / 文本三者一缓存），
        这里没有「丢掉预合成」的口子，但预合成只提前一句，影响也就是一句，
        不值得为它加一套失效逻辑。
        """
        self.logger.log("读音纠正词典已更新", "DEBUG")

    def refresh_voice_dialog(self):
        """窗口开着的话同步一下列表（模型下载完、在线清单拉回来时用）"""
        dialog = self._tts_voice_dialog
        if dialog is not None and dialog.isVisible():
            dialog.refresh()

    def on_voice_dialog_engine(self, engine):
        """用户在音色窗口里换了引擎：切完把列表刷成新引擎的音色"""
        self.switch_speech_engine(engine)
        self.refresh_voice_dialog()

    # ---- 音色模型管理 ----

    def tts_model_dialog(self):
        """懒创建「音色管理」窗口（非模态，下载线程归主窗口所有）

        窗口里的文案是构建时翻的，切了界面语言就把旧窗扔掉重建（下载中
        不扔，免得把用户的下载打断）。
        """
        lang = i18n.current_language()
        if (self._tts_model_dialog is not None
                and getattr(self, "_tts_model_lang", lang) != lang
                and not self._tts_model_dialog.worker().busy()):
            self._tts_model_dialog.shutdown()
            self._tts_model_dialog = None
        if self._tts_model_dialog is None:
            dialog = TtsModelDialog(
                self,
                ui_theme=self.theme_manager.get_theme(self.current_theme_name()),
                titlebar_theme=self.dialog_titlebar_theme())
            dialog.installed_changed.connect(self._on_tts_models_changed)
            # 下载要几分钟，进度也丢一份到朗读条上（不必盯着那个窗口）
            dialog.worker().progress.connect(self.on_tts_model_progress)
            dialog.worker().finished.connect(self.on_tts_model_finished)
            self._tts_model_dialog = dialog
            self._tts_model_lang = lang
        return self._tts_model_dialog

    def on_tts_model_progress(self, model_id, phase, done, total):
        """下载音色模型：把进度写到朗读条那一行"""
        info = tts_models.model_info(model_id)
        name = info.name if info is not None else model_id
        if phase == "unpack":
            text = i18n.t("tts.model.bar_unpack", default="正在解压「{name}」…",
                          name=name)
        else:
            percent = int(done * 100 / total) if total else 0
            text = i18n.t("tts.model.bar_progress",
                          default="正在下载「{name}」{percent}%",
                          name=name, percent=percent)
        self.tts_bar.set_notice(text)

    def on_tts_model_finished(self, model_id, ok, message):
        """下载结束（成不成）都把朗读条那行恢复回去"""
        self.tts_bar.set_notice("")
        if not ok and message:
            self.logger.log(f"音色模型下载未完成: {message}", "WARN")

    def open_tts_model_dialog(self):
        """打开「音色管理」（从朗读菜单进来）"""
        dialog = self.tts_model_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_tts_models_changed(self):
        """装了 / 删了模型：让神经引擎重扫一遍音色，并把欠着的音色换上"""
        backend = self._tts_backend
        if backend is not None and backend.name == NEURAL_ENGINE:
            try:
                backend.refresh()
            except Exception as e:
                self.logger.log(f"刷新离线音色失败: {e}", "WARN")
        voice_id, self._tts_voice_after_download = \
            self._tts_voice_after_download, ""
        if not voice_id:
            return
        if not tts_models.is_installed(voice_id.rpartition("|")[0]):
            return
        self.config_manager.set("tts_voice_name", voice_id)
        if self._tts_backend is not None:
            self._tts_backend.set_voice(voice_id)
        self.logger.log(f"音色模型已就绪，切到 {voice_id}")
        self.refresh_voice_dialog()

    def refresh_edge_voices(self):
        """手动刷新在线音色清单（音色窗口的「刷新在线音色」也走这里）"""
        backend = self._tts_backend
        if backend is None or backend.name != EDGE_ENGINE:
            self.refresh_voice_dialog()
            return
        backend.refresh_async()
        self.logger.log("正在获取在线音色清单…")

    # ---- 句子表 ----

    def speech_sentences(self):
        """当前正文的朗读句子表（每句还带着它在文档里的位置，供高亮用）

        逐 ``QTextBlock`` 取文本并保留 ``block.position()``，所以含图片 /
        表格的章节也能和高亮位置对齐 —— 不用手拼全文再回头找偏移。

        设了朗读范围时只取范围内的句子（见 :meth:`speech_range_span`）。
        """
        document = self.reader_display.document()
        blocks = []
        block = document.begin()
        while block.isValid():
            text = block.text()
            if text and text.strip():
                blocks.append((block.position(), text))
            block = block.next()
        return sentences_for_blocks(blocks, max_chars=self.speech_max_chars(),
                                    char_range=self.speech_range_span())

    def ensure_speech_spans(self):
        """确保队列里有当前正文的句子表（首次朗读 / 空闲时翻句都要用）"""
        queue = self.speech_queue()
        if queue is not None and not queue.sentence_count:
            queue.load(self.speech_sentences(), 0)
        return queue

    def sync_speech_content(self):
        """正文重渲染后同步朗读内容（``display_content`` 末尾调用）

        * 正在朗读 / 暂停 → 换一份句子表并从章首接着读（自动翻章靠这个）；
        * 空闲 → 只清掉旧句子，下次点朗读时按当前章节重新生成。
        """
        queue = self._tts_queue
        if queue is None:
            return
        continues = self._tts_continues
        self._tts_continues = False
        if not (queue.active or continues):
            if queue.sentence_count:
                queue.load([], 0)
            return
        queue.load(self.speech_sentences(), 0)
        if continues and not queue.active:
            queue.start(0)

    # ---- 播放控制 ----

    def toggle_speech(self):
        """开始 / 暂停 / 继续朗读（空格、朗读条、菜单、工具栏共用）"""
        if self.current_reader is None:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return
        queue = self.ensure_speech_spans()
        if queue is None:
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("msg.tts_unavailable"))
            return
        if not queue.sentence_count:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.tts_empty"))
            return
        queue.toggle()

    def stop_speech(self):
        """停止朗读（记住当前句在哪，下次从这里接着读）"""
        queue = self._tts_queue
        if queue is not None:
            queue.stop()

    def previous_sentence(self):
        """上一句"""
        queue = self.ensure_speech_spans()
        if queue is not None:
            queue.previous_sentence()

    def next_sentence(self):
        """下一句"""
        queue = self.ensure_speech_spans()
        if queue is not None:
            queue.next_sentence()

    def speech_rate_up(self):
        """朗读语速加快一档"""
        self.step_speech_rate(1)

    def speech_rate_down(self):
        """朗读语速减慢一档"""
        self.step_speech_rate(-1)

    def step_speech_rate(self, step):
        """语速加减一档（档位见 :data:`enm.ui.tts_bar.RATE_PRESETS`）"""
        index = RATE_PRESETS.index(self.speech_rate()) + int(step)
        index = max(0, min(len(RATE_PRESETS) - 1, index))
        self.set_speech_rate(RATE_PRESETS[index])

    def set_speech_rate(self, rate):
        """设置朗读语速：写配置、刷新朗读条；正在读就重读当前句立即生效"""
        rate = nearest_rate(rate)
        self.config_manager.set("tts_rate", rate)
        self.tts_bar.set_rate(rate)
        queue = self._tts_queue
        if queue is not None:
            queue.set_rate(rate, restart=queue.state == SpeechQueue.PLAYING)

    def set_speech_volume(self, volume):
        """设置朗读音量（0.0 ~ 1.0）：写配置 + 立刻生效（不用重读当前句）"""
        value = quantize_volume(volume)
        self.config_manager.set("tts_volume", value)
        self.tts_bar.set_volume(value)
        queue = self._tts_queue
        if queue is not None:
            queue.set_volume(value)

    def set_speech_bar_collapsed(self, collapsed):
        """收起 / 展开朗读条（收起状态记进配置，下次启动照旧）

        收起只是把控件藏起来，朗读本身一点不受影响 —— 空格、快捷键都照常。
        """
        collapsed = bool(collapsed)
        self.config_manager.set("tts_bar_collapsed", collapsed)
        self.tts_bar.set_collapsed(collapsed)

    # ---- 朗读范围（v1.3.7） ----

    def _speech_anchor(self):
        """当前阅读位置 ``(文件序号, 章节序号)``（未打开书籍时是 ``(None, None)``）

        文件夹模式下「章节序号」是当前内层文件的，所以光有它不够，还得带上
        文件序号才能判断「是不是同一处」。
        """
        reader = self.current_reader
        if reader is None:
            return (None, None)
        if isinstance(reader, FolderReader):
            return (reader.current_file_index, self.current_chapter_index())
        return (0, self.current_chapter_index())

    def _active_speech_range(self):
        """当前生效的朗读范围（已经对不上的返回 ``None``）

        字符偏移那种范围（选中 / 光标）记着开读时那一章：用户中途手动翻章后
        偏移量在新章里毫无意义（还可能正好落在别的字上），这里直接作废并说一声。
        """
        rng = self._speech_range
        if not rng:
            return None
        anchor = self._speech_anchor()
        if rng["kind"] in ("cursor", "span"):
            if rng.get("anchor") != anchor:
                self._speech_range = None
                self.logger.log("朗读范围已作废（章节或文件已切换）")
                return None
        elif rng.get("file") != anchor[0]:
            self._speech_range = None
            self.logger.log("朗读范围已作废（章节或文件已切换）")
            return None
        return rng

    def speech_range_span(self):
        """朗读范围在当前正文里的字符区间（整章 / 跨章范围返回 ``None``）"""
        rng = self._active_speech_range()
        if rng is None:
            return None
        if rng["kind"] == "cursor":
            # 从光标处一直读到章末
            return (rng["start"], None)
        if rng["kind"] == "span":
            return (rng["start"], rng["end"])
        return None

    def speech_range_active(self):
        """当前是不是在读某个范围（朗读条 / 界面上想提示时用得上）"""
        return self._active_speech_range() is not None

    def start_speech_range(self, rng):
        """按给定范围从头开始朗读（``rng`` 为 ``None`` 表示整章）

        范围自带「从当前章开始」的语义，所以这里总是从第一句读起 —— 想让
        用户接着上次的位置读，那是「继续朗读」（空格）的事。
        """
        if self.current_reader is None:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return False
        queue = self.speech_queue()
        if queue is None:
            QMessageBox.warning(self, i18n.t("common.warning"),
                                i18n.t("msg.tts_unavailable"))
            return False

        if rng is not None:
            # 字符偏移范围记下「当时是哪一章」，翻章后就能认出偏移已经没意义了
            if rng["kind"] in ("cursor", "span"):
                rng["anchor"] = self._speech_anchor()
            else:
                rng["file"] = self._speech_anchor()[0]
            # 「读完本章停」定时和「指定起止章节」是打架的（都是「到章末干嘛」），
            # 跨章朗读说了算：把那个一次性定时取消掉，免得第 1 章读完就不动了
            if rng["kind"] == "chapters" and self._speech_timer_mode == "chapter":
                self.logger.log("开始跨章朗读，已取消「读完本章停」定时")
                self._clear_speech_timer()

        self._speech_range = rng
        spans = self.speech_sentences()
        if not spans:
            self._speech_range = None
            QMessageBox.information(
                self, i18n.t("common.info"),
                i18n.t("tts.range.empty") if rng is not None
                else i18n.t("msg.tts_empty"))
            return False

        # 这一次是「从头读」，别让 display_content 里的续读逻辑插一脚
        self._tts_continues = False
        queue.load(spans, 0)
        if queue.state != SpeechQueue.PLAYING:
            queue.start(0)
        if DEBUG_MODE:
            self.logger.debug(f"朗读范围: {rng or '整章'}（{len(spans)} 句）")
        return True

    def sentence_start_near(self, position):
        """``position`` 所在那一句的句首（后面没有句子时返回 ``None``）

        光标常常停在句子中间，从那儿开口会先蹦出半句。这里向前对齐到句首，
        读起来才自然。实现在「整章句子表」上找，所以调用前得先清掉范围。
        """
        try:
            position = int(position)
        except (TypeError, ValueError):
            position = 0
        for span in self.speech_sentences():
            if span.end > position:
                return span.start
        return None

    def speak_whole_chapter(self):
        """「整章朗读」：丢掉范围，从本章开头重读"""
        self.start_speech_range(None)

    def show_reader_context_menu(self, pos):
        """阅读区右键菜单：朗读命令 + 复制 / 全选

        换掉 QTextEdit 自带的那份（里面一个朗读项都没有）。右键的地方就是用户
        想开读的地方，所以没选区时顺手把光标挪过去，「从光标处开始朗读」才对
        得上；有选区时一点都不动，保住「只读选中内容」。
        """
        display = self.reader_display
        if not display.textCursor().hasSelection():
            display.setTextCursor(display.cursorForPosition(pos))

        menu = QMenu(self)
        for action_id in ("tts.play_pause", "tts.stop"):
            action = self._actions.get(action_id)
            if action is not None:
                menu.addAction(action)
        menu.addSeparator()

        range_menu = menu.addMenu(i18n.t("menu.tts_range"))
        for action_id in ("tts.range_selection", "tts.range_cursor",
                          "tts.range_chapter", "tts.range_chapters"):
            action = self._actions.get(action_id)
            if action is not None:
                range_menu.addAction(action)
        # 没选中内容时「只读选中」必然无效，索性置灰，省得点了弹提示
        selection_action = self._actions.get("tts.range_selection")
        if selection_action is not None:
            selection_action.setEnabled(
                self.speech_available() and display.textCursor().hasSelection())

        menu.addSeparator()
        copy_action = menu.addAction(i18n.t("menu.copy"))
        copy_action.setEnabled(display.textCursor().hasSelection())
        copy_action.triggered.connect(display.copy)
        select_all_action = menu.addAction(i18n.t("menu.select_all"))
        select_all_action.triggered.connect(display.selectAll)
        try:
            menu.exec_(display.mapToGlobal(pos))
        finally:
            # 上面借用了共享动作（这样才有快捷键提示），用完把状态还回去
            self.update_speech_controls()

    def speak_from_cursor(self):
        """「从光标处开始」：从光标所在的那一句读到本章末尾（一次性）"""
        if self.current_reader is None:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return
        # 算句首要按整章算，先清掉上一次的范围
        self._speech_range = None
        start = self.sentence_start_near(self.reader_display.textCursor().position())
        if start is None:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("tts.range.cursor_empty"))
            return
        self.start_speech_range({"kind": "cursor", "start": start})

    def speak_selection(self):
        """「只读选中内容」：只朗读正文里选中的那一段（一次性）"""
        if self.current_reader is None:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return
        cursor = self.reader_display.textCursor()
        if not cursor.hasSelection():
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("tts.range.no_selection"))
            return
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        self.start_speech_range({"kind": "span", "start": start, "end": end})

    def speak_chapter_range(self):
        """「指定起止章节」：选两章，从起始章一路读到结束章末尾（一次性）

        章节范围以**当前文件**为准（文件夹模式下就是当前这一篇的章节），
        因为跨文件的章节序号没有共同的参照物。
        """
        if self.current_reader is None:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return
        reader = self.current_reader
        if isinstance(reader, FolderReader):
            reader = reader.get_current_reader()
        titles = self.reader_titles(reader) if reader is not None else []
        if not titles:
            QMessageBox.information(self, i18n.t("common.info"),
                                    i18n.t("msg.no_book_opened"))
            return

        dialog = SpeechRangeDialog(titles, self.current_chapter_index(), self,
                                   ui_theme=self._current_theme,
                                   titlebar_theme=self.dialog_titlebar_theme())
        if dialog.exec_() != QDialog.Accepted:
            return
        first, last = dialog.selected_range()
        self.jump_to_chapter(first)
        self.start_speech_range({"kind": "chapters", "from": first, "to": last})

    def end_speech_range(self, reason=None):
        """结束一次性朗读范围：复位成整章，并丢掉按范围切出来的句子表

        句子表必须清掉（而不是留着）：它只有范围里那几句，留着的话下次按
        空格会从「范围的第一句」接着读，看起来就像范围还生效。
        """
        if self._speech_range is None:
            return
        self._speech_range = None
        if reason:
            self.logger.log(reason)
        queue = self._tts_queue
        if queue is not None and not self._tts_continues and queue.sentence_count:
            queue.load([], 0)

    def _on_speech_range_finished(self, rng):
        """范围读完：跨章范围就翻下一章接着读，否则收摊并复位成整章"""
        if rng["kind"] == "chapters" and self.current_chapter_index() < rng["to"]:
            # 跨章朗读时不管「自动读下一章」开关：范围本身就是「连着读」的意思
            self._pending_scroll_percent = 0.0
            self._tts_continues = True
            try:
                self.next_chapter()
            finally:
                self._tts_continues = False
            return
        self.end_speech_range("朗读范围读完，停止朗读")

    # ---- 定时停止 ----

    def set_speech_timer(self, option):
        """设置朗读定时（0 = 不定时，正数 = 分钟数，:data:`TIMER_CHAPTER` = 读完本章停）

        「读完本章停」不是计时，而是在章末拦一次（见 :meth:`on_speech_finished`）：
        哪怕开着「自动读下一章」也不翻页。两种定时都是一次性的，到点/到章自动复位。
        """
        option = int(option)
        if option == TIMER_CHAPTER:
            self._speech_timer_mode = "chapter"
            self._speech_timer_remaining = 0
        elif option > 0:
            self._speech_timer_mode = "minutes"
            self._speech_timer_remaining = option * 60
        else:
            self._speech_timer_mode = None
            self._speech_timer_remaining = 0
        self.tts_bar.set_timer(option)
        self._sync_speech_timer()

    def ask_speech_timer_minutes(self):
        """「自定义…」：问一个分钟数（取消则保持原样）

        取消时**不**调 :meth:`set_speech_timer` —— 朗读条已经把下拉框拨回原档位了。
        """
        minutes, ok = QInputDialog.getInt(
            self, i18n.t("tts.timer.custom_title"),
            i18n.t("tts.timer.custom_prompt"), TIMER_DEFAULT_MINUTES,
            TIMER_MIN_MINUTES, TIMER_MAX_MINUTES, 1)
        if not ok:
            return
        self.set_speech_timer(minutes)

    def _clear_speech_timer(self):
        """把定时复位成「不定时」（到点 / 读完本章时用）"""
        self._speech_timer_mode = None
        self._speech_timer_remaining = 0
        self._speech_timer.stop()
        self.tts_bar.set_timer(TIMER_OFF)
        self.tts_bar.set_timer_remaining(0)

    def _sync_speech_timer(self):
        """按「有没有定时 + 是不是在读」把秒表跑起来或停下"""
        if self._speech_timer_mode == "chapter":
            self._speech_timer.stop()
            self.tts_bar.set_timer_remaining(0, chapter=True)
            return
        if self._speech_timer_mode != "minutes":
            self._speech_timer.stop()
            self.tts_bar.set_timer_remaining(0)
            return
        self.tts_bar.set_timer_remaining(self._speech_timer_remaining)
        if (self._speech_state == SpeechQueue.PLAYING
                and self._speech_timer_remaining > 0):
            if not self._speech_timer.isActive():
                self._speech_timer.start()
        else:
            self._speech_timer.stop()

    def _on_speech_timer_tick(self):
        """每秒一响：走完就停朗读（只在朗读中才会被启动，见 _sync_speech_timer）"""
        if self._speech_timer_mode != "minutes":
            self._speech_timer.stop()
            return
        self._speech_timer_remaining -= 1
        if self._speech_timer_remaining > 0:
            self.tts_bar.set_timer_remaining(self._speech_timer_remaining)
            return
        self.logger.log("朗读定时到点，停止朗读")
        self._clear_speech_timer()
        self.stop_speech()

    def toggle_speech_auto_next(self, checked):
        """切换「读完这章自动读下一章」"""
        enabled = bool(checked)
        self.config_manager.set("tts_auto_next_chapter", enabled)
        self.tts_bar.set_auto_next(enabled)
        action = getattr(self, "speech_auto_next_action", None)
        if action is not None:
            action.setChecked(enabled)

    def toggle_speech_highlight(self, checked):
        """切换「朗读时高亮并滚动到当前句」"""
        enabled = bool(checked)
        self.config_manager.set("tts_highlight", enabled)
        self.tts_bar.set_highlight(enabled)
        action = getattr(self, "speech_highlight_action", None)
        if action is not None:
            action.setChecked(enabled)
        # 关掉就把高亮清掉，打开就按当前句重新标上
        self.apply_speech_highlight(self._tts_highlight_index)

    def has_next_chapter(self):
        """后面还有章节吗（文件夹模式下可跨文件，与 ``next_chapter`` 判定一致）"""
        reader = self.current_reader
        if reader is None:
            return False
        if isinstance(reader, FolderReader):
            inner = reader.get_current_reader()
            if inner is not None:
                try:
                    if inner.current_chapter < inner.get_chapter_count() - 1:
                        return True
                except Exception:
                    pass
            # 当前文件读到头了：后面还有文件就算还有下一章
            # （文件可能是空的 / 打不开的，交给 next_chapter 自己往后跳）
            return reader.current_file_index < len(reader.files) - 1
        try:
            return reader.current_chapter < reader.get_chapter_count() - 1
        except Exception:
            return False

    def shutdown_speech(self):
        """停掉朗读并释放引擎（关窗口时调用）"""
        queue = self._tts_queue
        self._tts_queue = None
        self._tts_backend = None
        self._tts_voice_pending = ""
        if queue is None:
            return
        try:
            queue.shutdown()
        except Exception as e:
            self.logger.log(f"释放朗读引擎失败: {e}", "WARN")

    # ---- 高亮 ----

    def apply_speech_highlight(self, index):
        """高亮正在朗读的那一句，并（可选）滚动到它"""
        display = self.reader_display
        span = None
        queue = self._tts_queue
        if queue is not None and index >= 0:
            spans = queue.spans
            if 0 <= index < len(spans):
                span = spans[index]
        if span is None or not self.speech_highlight_enabled():
            self._tts_highlight_index = -1
            if display.extraSelections():
                display.setExtraSelections([])
            return

        self._tts_highlight_index = index
        document = display.document()
        last = max(0, document.characterCount() - 1)
        cursor = QTextCursor(document)
        cursor.setPosition(min(span.start, last))
        cursor.setPosition(min(span.end, last), QTextCursor.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        text_format = QTextCharFormat()
        text_format.setBackground(QColor(self.speech_highlight_color()))
        selection.format = text_format
        display.setExtraSelections([selection])

        if self.speech_auto_scroll_enabled():
            # 光标挪到句首再让它可见：句子还在视野里时不会真的滚动，
            # 所以不会每句都把页面猛拽一下
            caret = QTextCursor(document)
            caret.setPosition(min(span.start, last))
            display.setTextCursor(caret)
            display.ensureCursorVisible()

    def speech_highlight_color(self):
        """高亮底色：优先用主题的 highlight，其次 selection"""
        theme = self._current_theme or {}
        return (theme.get("highlight") or theme.get("selection")
                or theme.get("accent") or "#E3F2FD")

    # ---- 信号处理 ----

    def on_speech_sentence_changed(self, index):
        """换到第几句：刷新高亮、滚动与朗读条上的进度"""
        self.apply_speech_highlight(index)
        queue = self._tts_queue
        total = queue.sentence_count if queue is not None else 0
        self.tts_bar.set_position(index, total)

    def on_speech_state_changed(self, state):
        """朗读状态变化：刷新按钮文案与朗读条，并维护阅读时长计时"""
        self._speech_state = state
        self.tts_bar.set_state(state)
        self._refresh_speech_action_text()
        # 系统媒体面板上的播放 / 暂停状态（也决定系统送回 PLAY 还是 PAUSE）
        self.refresh_media_panel()
        # 托盘提示上的朗读状态
        self._refresh_tray()
        # 倒计时只在朗读中走：暂停 / 停止时把秒表冻住
        self._sync_speech_timer()
        if state != SpeechQueue.IDLE:
            return
        # 停下来了就别留着上一句的底色，否则看起来像还在读
        # （自动翻章接着读时会马上重新标上新章的第一句）
        self.apply_speech_highlight(-1)
        # 朗读期间用户换过语音的话，现在换掉（这时不在开口，不会打断句子）
        if self._tts_voice_pending and self._tts_backend is not None:
            pending, self._tts_voice_pending = self._tts_voice_pending, ""
            self._tts_backend.set_voice(pending)
        # 失焦状态下读完最后一句：到这里为止的时长结算掉，别继续空转计时
        if not self.isActiveWindow():
            self.finish_reading_session()
            if (self.current_reader is not None
                    and self.config_manager.get("auto_save", True)):
                self.save_reading_progress()

    def on_speech_finished(self):
        """整章读完：先看朗读范围与定时拦不拦，都不拦才按「自动读下一章」翻章"""
        rng = self._active_speech_range()
        if rng is not None:
            self._on_speech_range_finished(rng)
            return
        if self._speech_timer_mode == "chapter":
            self.logger.log("朗读已读完本章，按定时设置停下")
            self._clear_speech_timer()
            return
        if not (self.speech_auto_next_enabled() and self.has_next_chapter()):
            self.logger.log("朗读完毕")
            return
        # 自动翻章时别恢复上一章的章内位置，否则新章会跳到中间去
        self._pending_scroll_percent = 0.0
        self._tts_continues = True
        try:
            self.next_chapter()
        finally:
            # sync_speech_content 正常会把它清掉，这里是「翻章没换成」的兜底
            self._tts_continues = False

    def on_speech_failed(self, message):
        """朗读出错：提示一次并复位界面"""
        self.logger.log(f"朗读失败: {message}", "ERROR")
        self.apply_speech_highlight(-1)
        self.tts_bar.set_state(SpeechQueue.IDLE)
        self._speech_state = SpeechQueue.IDLE
        self._refresh_speech_action_text()
        QMessageBox.warning(self, i18n.t("common.warning"), message)

    def _speech_play_key(self):
        """「开始 / 暂停 / 继续朗读」的文案键（随播放状态变，交给 bind_text 复用）"""
        if self._speech_state == SpeechQueue.PLAYING:
            return "menu.tts_pause"
        if self._speech_state == SpeechQueue.PAUSED:
            return "menu.tts_resume"
        return "menu.tts_play"

    def _refresh_speech_action_text(self):
        """刷新「开始 / 暂停朗读」动作的文案与提示（它随状态变，不在 bind 里）"""
        action = self._actions.get("tts.play_pause")
        if action is None:
            return
        action.setText(i18n.t(self._speech_play_key()))
        self.update_action_hint("tts.play_pause")

    def _connect_speech_bar(self):
        """朗读条按钮 / 开关 → 朗读逻辑"""
        bar = self.tts_bar
        bar.play_clicked.connect(self.toggle_speech)
        bar.stop_clicked.connect(self.stop_speech)
        bar.previous_clicked.connect(self.previous_sentence)
        bar.next_clicked.connect(self.next_sentence)
        bar.rate_changed.connect(self.set_speech_rate)
        bar.volume_changed.connect(self.set_speech_volume)
        bar.auto_next_changed.connect(self.toggle_speech_auto_next)
        bar.highlight_changed.connect(self.toggle_speech_highlight)
        bar.collapsed_changed.connect(self.set_speech_bar_collapsed)
        bar.timer_changed.connect(self.set_speech_timer)
        bar.custom_timer_requested.connect(self.ask_speech_timer_minutes)
        for action_id, widget in bar.shortcut_widgets().items():
            self.bind_hint(widget, action_id)

    def closeEvent(self, event):
        """关闭事件"""
        # 「关闭窗口时隐藏到托盘」：藏起来而不是退出（朗读会继续，v1.3.9）
        if self.should_hide_to_tray():
            event.ignore()
            self.hide()
            self._show_tray_notice()
            return

        # 保存窗口设置
        self.config_manager.set("window_size", [self.width(), self.height()])
        self.config_manager.set("window_position", [self.x(), self.y()])
        # 侧边栏宽度：拖完 400ms 内就关窗口的话防抖定时器还没跑，这里补一次
        self._save_sidebar_width()
        
        # 保存阅读进度
        self.save_reading_progress()
        
        # 结算本次阅读时长并停止计时
        self.finish_reading_session()
        
        # 停止自动保存定时器
        self.auto_save_timer.stop()
        self.sidebar_width_timer.stop()
        self._speech_timer.stop()

        # 停掉朗读并释放系统语音引擎（不释放的话进程可能压在句子里退不掉）
        self.shutdown_speech()

        # 全局媒体键有自己的线程与消息泵，退出前先让它收摊
        self._shutdown_media_keys()

        # 音色管理窗口的下载线程也得收（正在下就让它断在半路，.part 留着）
        dialog = self._tts_model_dialog
        self._tts_model_dialog = None
        if dialog is not None:
            try:
                dialog.shutdown()
            except Exception as e:  # noqa: BLE001
                self.logger.log(f"关闭音色管理窗口失败: {e}", "WARN")

        # 音色选择窗口（它自己不占线程 / 文件，关掉就行）
        voice_dialog = self._tts_voice_dialog
        self._tts_voice_dialog = None
        if voice_dialog is not None:
            try:
                voice_dialog.shutdown()
            except Exception as e:  # noqa: BLE001
                self.logger.log(f"关闭音色选择窗口失败: {e}", "WARN")

        # 读音纠正窗口（同样不占线程 / 文件）
        pron_dialog = self._tts_pron_dialog
        self._tts_pron_dialog = None
        if pron_dialog is not None:
            try:
                pron_dialog.shutdown()
            except Exception as e:  # noqa: BLE001
                self.logger.log(f"关闭读音纠正窗口失败: {e}", "WARN")
        
        # 释放阅读器（清理 ZIP/JAR/MOBI 等解压出来的临时文件）
        self.release_current_reader()
        
        # 托盘图标（连带它自己建的那份菜单）
        self._shutdown_tray()

        self.logger.log(f"{PROJECT_NAME} 正常退出")
        event.accept()

    def release_current_reader(self):
        """释放当前阅读器及其占用的临时资源"""
        # 先停朗读：句子表是按旧书的文档切出来的，留着会念错内容
        # （关窗口时 shutdown_speech 已经跑过，这里是换书路径）
        self.stop_speech()

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
            self.refresh_media_panel()
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
        # 系统媒体面板上的书名也跟着走
        self.refresh_media_panel()
