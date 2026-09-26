"""应用配置管理（config.json）。"""

import json

from ..constants import CONFIG_PATH
from ..logger import logger


class ConfigManager:
    def __init__(self):
        self.config_file = CONFIG_PATH
        self.default_config = {
            "theme": "light",
            "language": "zh_CN",
            "font_family": "Microsoft YaHei",
            "font_size": 16,
            # 行距（倍数）/ 段间距（像素）。这两个值以前只存在配置里不生效：
            # Qt 样式表不支持 line-height，现在由 enm.ui.reader_typography 的
            # 块格式真正套到文档上（段间距上下边距各分一半，所以两个相邻
            # 段落之间的间隙就是它；24 = Qt 自带 <p> 边距，即默认外观）
            "line_spacing": 1.8,
            "paragraph_spacing": 24,
            "auto_save": True,
            "auto_save_interval": 30,
            "recent_files": [],
            "window_size": [1200, 800],
            "window_position": [100, 100],
            "sidebar_visible": True,
            # 章节列表宽度：拖动主窗口里的分隔条后写回这里（v1.3.3 之前是写死的）
            "sidebar_width": 300,
            "restore_scroll_position": True,
            # 同名书籍的不同版本（重新导出 / 追加章节）共用同一份阅读记录：
            # 打开时用书名 + 作者 + 章节标题指纹认书，认出同一本就自动合并且不弹窗；
            # 只有书名对得上、章节结构对不上（或记录太老没有指纹）时才问一次。
            # 用户回答「不再询问」的文件对会记在 progress_share_ignored 里。
            "share_progress_versions": True,
            "progress_share_ignored": [],
            # 以下两个开关都默认关闭：
            # * titlebar_follow_theme —— 让 Windows 原生标题栏跟着主题的 titlebar
            #   颜色走（Win11 22H2+ 生效；更老的系统只切深浅模式）
            # * typography_follow_theme —— 允许主题自带的字体/字号/行距/段间距
            #   覆盖全局设置
            "titlebar_follow_theme": False,
            "typography_follow_theme": False,
            # 朗读（v1.3.5）：
            # * tts_rate —— 语速档位（-1.0 很慢 / 0.0 正常 / 1.0 很快）
            # * tts_voice_name —— 用户手动指定的语音 id（空 = 按界面语言自动挑）
            # * tts_auto_next_chapter —— 读完这章自动接着读下一章
            # * tts_highlight —— 高亮正在朗读的那一句
            # * tts_auto_scroll —— 跟着高亮自动滚动（关掉只高亮不滚屏）
            # * tts_split_max_chars —— 单句最长字数，超长句子会在标点处再切一刀
            # * tts_bar_collapsed —— 朗读条收起（只留状态文字那一行）
            # v1.3.8 追加：
            # * tts_engine —— 用户指定的朗读引擎（空 = 程序自动挑，见
            #   tts.available_engines()；'sherpa' 离线神经 / 'edge' 在线
            #   / 'sapi-com' 和 'sapi' 系统语音）
            "tts_rate": 0.0,
            "tts_volume": 1.0,
            "tts_voice_name": "",
            "tts_engine": "",
            "tts_auto_next_chapter": True,
            "tts_highlight": True,
            "tts_auto_scroll": True,
            "tts_split_max_chars": 120,
            "tts_bar_collapsed": False,
            # 托盘与全局媒体键（v1.3.9）：
            # * tray_enabled —— 显示系统托盘图标（关掉就完全退回旧行为）
            # * tray_close_to_tray —— 关闭窗口时只是藏到托盘（默认关闭：默认行为
            #   必须是「点叉就是退出」，不然用户会以为程序已经关了）
            # * tray_notice_shown —— 「已藏到托盘」的提示只弹一次，弹过就记下来
            # * media_keys_enabled —— 键盘上的播放/暂停、上一首/下一首交给
            #   NovelMaster（要 winrt 组件，且会在音量合成器里多一个静音会话，
            #   所以默认关闭，由用户在设置里打开）
            "tray_enabled": True,
            "tray_close_to_tray": False,
            "tray_notice_shown": False,
            "media_keys_enabled": False,
            # 快捷键（见 enm.shortcuts）：
            # * shortcuts —— 键盘绑定（只存与默认值不同的项）
            # * shortcuts_mouse —— 鼠标键绑定（鼠标侧键 / 中键），与键盘各存一套，
            #   互不影响：同一个动作可以同时有键盘键和鼠标键
            "shortcuts": {},
            "shortcuts_mouse": {},
            # 检查更新（v1.4.4，见 enm.managers.update）：
            # * auto_check_update —— 启动时自动检查更新。**默认关闭**：不打招呼
            #   就联网不合适，想用的用户在「设置」里打开（开一次就在 config.json
            #   里记着）
            # * update_mirror —— 下载安装包用的加速前缀（空 = 只用内置镜像，
            #   见 update.MIRROR_PREFIXES）。它排在内置镜像之后，是最后的兜底
            # * update_last_check —— 上次自动检查的 unix 时间戳。一天之内不再
            #   自动问，免得每次重启都打一次 GitHub 接口
            "auto_check_update": False,
            "update_mirror": "",
            "update_last_check": 0
        }
        self.config = self.load_config()
    
    def load_config(self):
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置
                    for key, value in self.default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
        except Exception as e:
            logger.log(f"加载配置失败: {e}", "ERROR")
        
        return self.default_config.copy()
    
    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.log(f"保存配置失败: {e}", "ERROR")
    
    def get(self, key, default=None):
        return self.config.get(key, default)
    
    def set(self, key, value):
        self.config[key] = value
        self.save_config()
