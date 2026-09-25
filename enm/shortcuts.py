# -*- coding: utf-8 -*-
"""快捷键注册表。

所有可自定义的快捷键都集中在这里定义，避免主窗口里到处散落按键字符串。

生效范围（``scope``）分两类：

* :data:`WINDOW` —— 窗口级。用 ``QAction`` + ``Qt.WindowShortcut`` 实现，
  窗口内任何位置（章节列表、工具栏、阅读区）都能触发；
* :data:`READER` —— 阅读区级。只在阅读区获得焦点时生效（由主窗口的
  ``eventFilter`` 派发），这样方向键、翻页键这类单键不会在章节列表、
  输入框等控件里抢占按键。

绑定值持久化在 ``config.json`` 的 ``shortcuts`` 字段里，只保存与默认值不同的项；
用户主动清空某个绑定（空字符串）同样会被保存下来。
"""

from collections import namedtuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence

from . import i18n
from .logger import logger

# 生效范围
WINDOW = "window"
READER = "reader"

# 分组（顺序即改键界面里的显示顺序；名字在语言文件的 shortcut.group.* 里）
GROUP_FILE = "file"
GROUP_NAV = "nav"
GROUP_AUDIO = "audio"
GROUP_VIEW = "view"
GROUP_THEME = "theme"

GROUP_ORDER = (GROUP_FILE, GROUP_NAV, GROUP_AUDIO, GROUP_VIEW, GROUP_THEME)

# 显示名与说明都放在语言文件里，这里的 label / hint 只作为缺键时的兜底。
# 一个快捷键定义：动作 id、显示名、分组、默认按键、生效范围、说明
ShortcutDef = namedtuple(
    "ShortcutDef", "action_id label group default scope hint")

ACTION_DEFS = (
    # ---- 文件操作 ----
    ShortcutDef("file.open", "打开文件", GROUP_FILE, "Ctrl+O", WINDOW,
                "打开 epub / txt 等书籍文件"),
    ShortcutDef("file.open_folder", "打开文件夹", GROUP_FILE, "Ctrl+Shift+O",
                WINDOW, "以文件夹模式连续阅读多本书"),
    ShortcutDef("file.continue", "继续阅读", GROUP_FILE, "Ctrl+R", WINDOW,
                "打开「继续阅读」面板"),
    ShortcutDef("file.quit", "退出", GROUP_FILE, "Ctrl+Q", WINDOW,
                "保存进度并关闭程序"),

    # ---- 阅读导航 ----
    # 注：Qt 的可移植键名是 PgUp / PgDn，写成 PageUp / PageDown 会解析失败
    ShortcutDef("nav.prev_chapter", "上一章", GROUP_NAV, "PgUp", READER,
                "阅读区聚焦时生效（翻页键）"),
    ShortcutDef("nav.next_chapter", "下一章", GROUP_NAV, "PgDown", READER,
                "阅读区聚焦时生效（翻页键）"),
    ShortcutDef("nav.reader_prev", "上一章（方向键）", GROUP_NAV, "Left",
                READER, "阅读区聚焦时生效（←）"),
    ShortcutDef("nav.reader_next", "下一章（方向键）", GROUP_NAV, "Right",
                READER, "阅读区聚焦时生效（→）"),
    ShortcutDef("nav.goto_chapter", "转到章节", GROUP_NAV, "Ctrl+G", WINDOW,
                "按当前文件内的章节序号跳转"),
    ShortcutDef("nav.chapter_start", "跳到章首", GROUP_NAV, "Ctrl+Home",
                WINDOW, "回到当前章节开头"),
    ShortcutDef("nav.chapter_end", "跳到章尾", GROUP_NAV, "Ctrl+End",
                WINDOW, "跳到当前章节末尾"),

    # ---- 朗读 ----
    # 全部是 READER 范围：朗读的按键（尤其空格）必须只在阅读区聚焦时生效，
    # 否则在输入框、对话框里打不出空格。空格还要抢在 QTextEdit 前面——
    # 只读的 QTextEdit 会把空格当翻页键用掉，所以主窗口的 eventFilter 负责拦截。
    ShortcutDef("tts.play_pause", "开始/暂停朗读", GROUP_AUDIO, "Space", READER,
                "阅读区聚焦时生效（空格）"),
    ShortcutDef("tts.stop", "停止朗读", GROUP_AUDIO, "", READER,
                "停止朗读并回到当前句开头（默认未绑定）"),
    ShortcutDef("tts.prev_sentence", "上一句", GROUP_AUDIO, "Ctrl+Up", READER,
                "退回上一句；刚开始读时先重读当前句"),
    ShortcutDef("tts.next_sentence", "下一句", GROUP_AUDIO, "Ctrl+Down", READER,
                "跳到下一句，读快了可以手动往前赶"),
    ShortcutDef("tts.rate_up", "朗读语速加快", GROUP_AUDIO, "Ctrl+Shift+Up",
                READER, "语速往上调一档（很慢 → 很快）"),
    ShortcutDef("tts.rate_down", "朗读语速减慢", GROUP_AUDIO, "Ctrl+Shift+Down",
                READER, "语速往下调一档（很快 → 很慢）"),

    # ---- 界面控制 ----
    ShortcutDef("view.toggle_sidebar", "显示/隐藏章节列表", GROUP_VIEW,
                "Ctrl+B", WINDOW, "收起或展开左侧章节列表"),

    # ---- 主题与设置 ----
    ShortcutDef("view.font_inc", "字体增大", GROUP_THEME, "Ctrl+=", WINDOW,
                "阅读区字号 +1"),
    ShortcutDef("view.font_dec", "字体减小", GROUP_THEME, "Ctrl+-", WINDOW,
                "阅读区字号 -1"),
    ShortcutDef("view.font_dialog", "字体设置", GROUP_THEME, "Ctrl+Shift+F",
                WINDOW, "打开字体选择对话框"),
    ShortcutDef("view.typography_dialog", "排版设置", GROUP_THEME,
                "Ctrl+Shift+P", WINDOW, "打开行距 / 段间距设置对话框"),
    ShortcutDef("view.theme_light", "浅色主题", GROUP_THEME, "Ctrl+Shift+L",
                WINDOW, "切换到浅色主题"),
    ShortcutDef("view.theme_dark", "深色主题", GROUP_THEME, "Ctrl+Shift+D",
                WINDOW, "切换到深色主题"),
    ShortcutDef("view.shortcut_config", "快捷键设置", GROUP_THEME,
                "Ctrl+Shift+K", WINDOW, "打开快捷键设置面板"),
)

DEFAULT_SHORTCUTS = {item.action_id: item.default for item in ACTION_DEFS}
DEFS_BY_ID = {item.action_id: item for item in ACTION_DEFS}
READER_ACTION_IDS = tuple(
    item.action_id for item in ACTION_DEFS if item.scope == READER)


def action_label_key(action_id):
    """动作显示名在语言文件里的键（``file.open`` -> ``shortcut.action.file_open.label``）"""
    return f"shortcut.action.{action_id.replace('.', '_')}.label"


def action_hint_key(action_id):
    """动作说明在语言文件里的键"""
    return f"shortcut.action.{action_id.replace('.', '_')}.hint"


def label_of(action_id):
    """动作的显示名（跟随当前语言，缺键时用代码里的兜底文案）"""
    definition = DEFS_BY_ID.get(action_id)
    if definition is None:
        return action_id
    return i18n.t(action_label_key(action_id), default=definition.label)


def hint_of(action_id):
    """动作的说明文字（跟随当前语言，缺键时用代码里的兜底文案）"""
    definition = DEFS_BY_ID.get(action_id)
    if definition is None:
        return ""
    return i18n.t(action_hint_key(action_id), default=definition.hint)


def group_label(group):
    """分组的显示名（跟随当前语言）"""
    return i18n.t(f"shortcut.group.{group}", default=group)


def grouped_definitions():
    """按分组返回 ``[(组 id, [定义, ...]), ...]``（便于改键界面排版）"""
    return [(group, [item for item in ACTION_DEFS if item.group == group])
            for group in GROUP_ORDER]


def invalid_definitions():
    """返回默认按键无法解析的动作 id（写错键名时的自检，如 PageUp 应为 PgUp）

    ``QKeySequence`` 对无法识别的键名会静默返回空序列，如果不自检，
    写错默认值只会表现为「快捷键不生效」，很难排查。
    """
    return [item.action_id for item in ACTION_DEFS
            if item.default and not normalise_sequence(item.default)]


def check_defaults():
    """启动时自检默认按键，有问题就写日志提醒"""
    invalid = invalid_definitions()
    if invalid:
        logger.warning(f"以下动作的默认按键无法解析，请检查键名拼写: {invalid}")
    return invalid


def normalise_sequence(value):
    """把按键值统一成可比较、可持久化的文本（如 ``Ctrl+O``）

    传入 ``None`` / 空字符串表示「未绑定」，统一返回空字符串。
    """
    if value is None:
        return ""
    if isinstance(value, QKeySequence):
        return value.toString(QKeySequence.PortableText)
    text = str(value).strip()
    if not text:
        return ""
    return QKeySequence(text).toString(QKeySequence.PortableText)


def key_sequence(value):
    """按键文本 → ``QKeySequence``（未绑定时返回空序列）"""
    text = normalise_sequence(value)
    return QKeySequence(text) if text else QKeySequence()


def display_text(value):
    """给界面显示的按键文本（未绑定时给出「未绑定」/``Unbound``）"""
    return normalise_sequence(value) or i18n.t("common.unbound",
                                              default="未绑定")


def event_key_sequence(event):
    """把键盘事件转换成可比较的 ``QKeySequence``"""
    modifiers = event.modifiers()
    # 小键盘方向键会带上 KeypadModifier，去掉才能与「Left」这类绑定匹配
    if modifiers & Qt.KeypadModifier:
        modifiers ^= Qt.KeypadModifier
    return QKeySequence(int(modifiers) | int(event.key()))


class ShortcutManager:
    """快捷键绑定的读取、修改与持久化"""

    CONFIG_KEY = "shortcuts"

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.bindings = {}
        check_defaults()
        self.reload()

    # ---------------- 读取 ----------------

    def reload(self):
        """从配置重新载入绑定（缺失项回落到默认值）"""
        stored = self.config_manager.get(self.CONFIG_KEY, {})
        if not isinstance(stored, dict):
            stored = {}
        self.bindings = {
            action_id: normalise_sequence(stored.get(action_id, default))
            for action_id, default in DEFAULT_SHORTCUTS.items()
        }

    def get(self, action_id):
        """当前绑定（未绑定时返回空字符串）"""
        return self.bindings.get(action_id, "")

    def default_of(self, action_id):
        """默认绑定"""
        return DEFAULT_SHORTCUTS.get(action_id, "")

    def is_default(self, action_id):
        """当前绑定是否就是默认值"""
        return self.get(action_id) == self.default_of(action_id)

    def display(self, action_id):
        """当前绑定的可读文本"""
        return display_text(self.get(action_id))

    def key_sequence_of(self, action_id, use_default=False):
        """绑定对应的 ``QKeySequence``（``use_default`` 时取默认值）"""
        value = self.default_of(action_id) if use_default else self.get(action_id)
        return key_sequence(value)

    # ---------------- 修改 ----------------

    def set(self, action_id, value):
        """修改单个绑定（只改内存，需调用 :meth:`save` 落盘）"""
        if action_id in DEFAULT_SHORTCUTS:
            self.bindings[action_id] = normalise_sequence(value)

    def reset(self, action_id):
        """恢复单个动作的默认绑定"""
        self.set(action_id, self.default_of(action_id))

    def reset_all(self):
        """恢复全部默认绑定"""
        self.bindings = dict(DEFAULT_SHORTCUTS)

    def apply(self, bindings):
        """一次性套用一组绑定（改键界面点「确定」时调用）"""
        for action_id, value in bindings.items():
            self.set(action_id, value)

    def save(self):
        """写回配置：只保存与默认值不同的项（含被清空的空绑定）"""
        stored = {
            action_id: value
            for action_id, value in self.bindings.items()
            if value != DEFAULT_SHORTCUTS.get(action_id)
        }
        self.config_manager.set(self.CONFIG_KEY, stored)

    # ---------------- 冲突检查 ----------------

    def find_conflict(self, value, exclude=None, bindings=None):
        """找出与 ``value`` 重复的动作 id（没有冲突时返回 ``None``）"""
        source = self.bindings if bindings is None else bindings
        target = normalise_sequence(value)
        if not target:
            return None
        for action_id, binding in source.items():
            if action_id == exclude:
                continue
            if normalise_sequence(binding) == target:
                return action_id
        return None

    def conflict_groups(self, bindings=None):
        """按按键归并冲突，返回 ``[(按键, [动作 id, ...]), ...]``"""
        source = self.bindings if bindings is None else bindings
        owners = {}
        for action_id, binding in source.items():
            text = normalise_sequence(binding)
            if text:
                owners.setdefault(text, []).append(action_id)
        return [(text, ids) for text, ids in owners.items() if len(ids) > 1]
