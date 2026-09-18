# NovelMaster - 现代化小说阅读器

一个功能强大的小说阅读器，支持多种格式和丰富的自定义选项。

## 功能特性

- 📚 **多格式支持**: EPUB、TXT、PDF、MOBI、AZW、AZW3、PRC、UMD、DOCX、FB2、HTML/HTM/XHTML、JAR、ZIP
- 📦 **压缩包阅读**: 直接打开 ZIP / JAR，自动挑选其中的电子书文件
- 🖼️ **内嵌图片**: 自动显示书中嵌入的封面与插图，并随窗口宽度自适应缩放
- 📁 **文件夹模式**: 支持直接打开文件夹批量阅读
- 💾 **自动保存**: 自动保存阅读记录和进度
- 🔖 **继续阅读**: 独立的阅读记录面板，按最后阅读时间排序，支持搜索、删除与清理失效记录
- 📊 **阅读统计**: 记录打开次数、阅读时长、已读章节数与最远章节
- 📍 **位置记忆**: 重新打开书籍时回到上次的章节，并可记住章内滚动位置
- 🎨 **主题切换**: 内置浅色和深色主题，支持自定义主题
- ⌨️ **自定义快捷键**: 全部功能可改键（含方向键翻章），自动检测按键冲突
- 🌍 **多语言支持**: 内置简体中文、繁体中文和英语，切换后界面立即刷新（无需重启）；
  往 `lang/` 里放一个 JSON 文件就能自动多出一种语言
- 🔧 **高度可定制**: 字体、颜色、布局等均可自定义
- 🖥️ **现代化界面**: 基于 PyQt5 的现代化 GUI

## 支持的文件格式

| 扩展名 | 格式 | 解析方式 |
| --- | --- | --- |
| `.epub` | EPUB 电子书 | ebooklib |
| `.txt` | 纯文本 | 标准库 + chardet 编码探测 |
| `.pdf` | PDF 文档 | pypdf（按书签分章，缺省每 10 页一章） |
| `.mobi` / `.azw` / `.azw3` / `.prc` | Kindle 电子书 | 内置 PalmDB + PalmDOC 解析器（可选 `mobi` 库增强） |
| `.umd` | 手机电子书 | 内置 UMD 解析器（纯标准库） |
| `.docx` | Word 文档 | python-docx |
| `.fb2` | FictionBook 2 | 标准库 `xml.etree` |
| `.html` / `.htm` / `.xhtml` | 网页文档 | 标准库 |
| `.jar` / `.zip` | 压缩包 | 自动解包并读取内部电子书 |

> **内嵌图片**：EPUB、DOCX、FB2、MOBI/AZW/AZW3/PRC、UMD、HTML/HTM/XHTML 以及 ZIP/JAR
> 内的图片会被转换为 `data:` URI 内联显示，超出阅读区宽度时按比例缩小，
> 无需额外临时文件，打包后同样有效。
> PDF 目前只提取文字（不解析页面内嵌图片），因此在 PDF 中看不到插图。

## 安装依赖

### 方法一：使用一键安装脚本（推荐）

Windows 下直接双击 `install.bat`，或在 PowerShell 中运行：

```powershell
.\install.ps1
```

该脚本会自动完成：

1. 检测本机基础 Python（自动排除虚拟环境自身）；
2. 若 `.venv` 不存在则**自动创建虚拟环境**；
3. **自动测速选择最快的 pip 镜像源**（清华 / 阿里云 / 腾讯云 / 中科大），
   某个镜像出现 403、超时或断流时自动切换到下一个，最后回退官方 PyPI；
4. 升级 pip / setuptools / wheel 并安装 `requirements.txt` 中的全部依赖；
5. 校验依赖是否完整，并给出后续运行/打包命令。

常用参数：

```powershell
.\install.ps1 -Recreate            # 删除旧虚拟环境并重建
.\install.ps1 -WithNuitka          # 同时安装打包工具 Nuitka
.\install.ps1 -Mirror aliyun       # 指定镜像源（auto/tuna/aliyun/ustc/tencent/pypi）
.\install.ps1 -DryRun -NoPause     # 只预览将要执行的命令
.\install.ps1 -Python "C:\Python313\python.exe"   # 指定基础解释器
```

> `-Mirror` 指定的镜像会排在最前，但其余镜像与官方 PyPI 仍作为自动兜底，
> 因此某个镜像出现 403/超时也不会中断安装。也可用环境变量统一覆盖：
> `$env:ENM_PIP_INDEX = 'https://mirrors.aliyun.com/pypi/simple/'`

### 方法二：使用 requirements.txt

```bash
pip install -r requirements.txt
# 使用国内镜像加速
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 方法三：手动安装

```bash
pip install PyQt5 PyQtWebEngine ebooklib lxml Pillow python-docx chardet qdarkstyle pypdf
```

### 可选依赖

`mobi` 库可为 MOBI/AZW/AZW3/PRC 提供额外的解析能力，但它是 **GPL-3.0-only** 许可，
与本项目的 MIT 许可不兼容，因此**不列为必需依赖**。未安装时程序使用内置解析器，
功能基本一致。

## 使用方法

### 启动程序

```bash
python NovelMaster.py
```

或者在 Windows 上双击 `run.bat`（调试模式使用 `run_debug.bat`）。

PowerShell 版本与其参数完全对应：

```powershell
.\run.ps1                 # 运行
.\run.ps1 -UseVenv        # 使用 .venv 运行
.\run.ps1 -DebugMode      # 调试模式（输出日志）
.\run.ps1 -DryRun -NoPause  # 仅预览命令
```

> 首次使用若提示"在此系统上禁止运行脚本"，先执行：
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### 基本操作

1. **打开文件**: 点击"文件" → "打开文件"，选择任意受支持的电子书文件
2. **打开文件夹**: 点击"文件" → "打开文件夹"，选择包含小说文件的文件夹
3. **继续阅读**: 点击"文件" → "继续阅读…"（或工具栏的"继续阅读"），
   在列表里双击任意记录即可接着上次的位置读；还可以搜索、删除单条记录或清理失效记录
4. **章节导航**: 使用左侧章节列表或工具栏的"上一章/下一章"按钮
5. **主题切换**: 点击"视图" → "主题"，选择喜欢的主题
6. **字体设置**: 点击"视图" → "字体设置"，调整字体和大小
7. **位置记忆**: "视图" → "记住章内阅读位置"可开关章内滚动位置的记忆
8. **快捷键**: 点击"视图" → "快捷键设置"（`Ctrl+Shift+K`）可修改任意功能的按键
9. **语言切换**: 点击"视图" → "语言"，选择"简体中文 / English"，界面立即刷新

### 快捷键

内置一套默认按键，均可在"视图" → "快捷键设置"里修改：

| 功能 | 默认按键 | 生效范围 |
| --- | --- | --- |
| 打开文件 | `Ctrl+O` | 窗口内 |
| 打开文件夹 | `Ctrl+Shift+O` | 窗口内 |
| 继续阅读 | `Ctrl+R` | 窗口内 |
| 退出 | `Ctrl+Q` | 窗口内 |
| 上一章（翻页键） | `PgUp` | 阅读区 |
| 下一章（翻页键） | `PgDn` | 阅读区 |
| 上一章（方向键） | `←` | 阅读区 |
| 下一章（方向键） | `→` | 阅读区 |
| 转到章节 | `Ctrl+G` | 窗口内 |
| 跳到章首 | `Ctrl+Home` | 窗口内 |
| 跳到章尾 | `Ctrl+End` | 窗口内 |
| 显示/隐藏章节列表 | `Ctrl+B` | 窗口内 |
| 字体增大 | `Ctrl+=` | 窗口内 |
| 字体减小 | `Ctrl+-` | 窗口内 |
| 字体设置 | `Ctrl+Shift+F` | 窗口内 |
| 浅色主题 | `Ctrl+Shift+L` | 窗口内 |
| 深色主题 | `Ctrl+Shift+D` | 窗口内 |
| 快捷键设置 | `Ctrl+Shift+K` | 窗口内 |

- **窗口内**：在章节列表、工具栏、阅读区任意位置都能触发（如 `Ctrl+O`）。
- **阅读区**：只在阅读区获得焦点时生效，且方向键直接用来翻章，
  在该区域内不再移动光标；不会在章节列表或输入框里抢按键。
  长按不会连续翻章，避免一不小心翻掉几十章。
- `Ctrl+Home` / `Ctrl+End` 优先用于"跳到章首/章尾"，不再是 `QTextEdit`
  自带的"文档首/文档尾"。
- 改键面板里点击输入框后直接按组合键即可录制，按 `Delete` 可清空（即不绑定按键）；
  有重复按键时会提示冲突并拒绝保存，每行右侧的"恢复默认"可单独回退。
- 绑定保存在 `config.json` 的 `shortcuts` 字段，只记录与默认值不同的项，
  下次启动自动生效。

## 主题功能

### 内置主题

- **浅色主题**: 明亮的阅读环境
- **深色主题**: 护眼的暗色模式

### 自定义主题

1. 点击"视图" → "主题" → "主题生成器"
2. 选择背景色、前景色、强调色
3. 保存并应用自定义主题

### 导入/导出主题

- **导入**: 点击"导入主题"，选择主题 JSON 文件
- **导出**: 点击"导出主题"，保存当前主题配置

## 多语言支持

程序内置简体中文、繁体中文与英语，可在"视图" → "语言"中切换，**切换后界面立即刷新**
（无需重启）。当前语言会写入 `config.json` 的 `language` 字段，下次启动自动沿用。

语言菜单按**语系相邻**排序：同语系的语言排在一起，内置语言排在同语系前面，即
简体中文 / 繁體中文 / English。

覆盖范围：

- 菜单、工具栏、按钮、侧边栏等全部界面静态文案；
- 运行时提示（文件格式不支持、加载失败、继续阅读面板、快捷键设置、主题生成器等）；
- 程序自动生成的占位标题（"第 N 章" / "Chapter N"、"正文" / "Body"、"全文" / "Full Text" 等），
  切换语言时会就地重生成，不会重新解析书籍；
- 不翻译书籍正文、章节标题（来自文件内容）与日志（日志固定中文，便于排查）。

### 语言文件与自动发现

翻译文件是嵌套 JSON（`lang/zh_CN.json`、`lang/zh_TW.json`、`lang/en_US.json`），
用点号路径取词。**新增一种语言不需要改代码**：把 `lang/xx_XX.json` 放进 `lang/` 目录，
在文件开头的 `lang.name` 里写上该语言自己的名字，启动时会被自动扫描并出现在语言菜单里：

```json
{
  "lang": { "name": "日本語", "code": "ja_JP" },
  "app": { "name": "NovelMaster" },
  "common": { "ok": "OK", ... }
}
```

自动发现只登记语言，不会补齐翻译：缺键会逐级回退（见下文），所以可以先把文件放进去，
再慢慢翻译。语言文件读不出来（坏 JSON）时会跳过该语言并写一条日志，不影响启动；
没写 `lang.name` 时菜单里用语言代码兜底。

代码中通过 `enm.i18n` 统一访问：

```python
from enm import i18n

i18n.t("menu.open_file")                       # 打开文件 / 開啟檔案 / Open File
i18n.t("sidebar.progress", percent="42.0")      # 阅读进度: 42.0%
i18n.set_language("zh_TW")                     # 切换语言
i18n.available_languages()                      # {"zh_CN": "简体中文", "zh_TW": "繁體中文", "en_US": "English"}
```

缺失的语言键会回退到默认语言，再回退到调用处传入的 `default`，最后返回键名本身
（同时记入 `manager().missing_keys`，便于发现漏翻）。

## 文件结构

```text
Reader-Equb/
├── NovelMaster.py             # 程序入口（仅负责启动主窗口）
├── enm/                      # 主程序包
│   ├── constants.py          # 路径与全局常量
│   ├── i18n.py               # 多语言入口（t / has / set_language）
│   ├── logger.py             # 日志工具
│   ├── shortcuts.py          # 快捷键注册表与绑定存储
│   ├── managers/             # 配置 / 主题 / 语言 / 阅读进度管理
│   ├── readers/              # 各格式阅读器与工厂
│   └── ui/                   # 主窗口、继续阅读面板、快捷键设置与主题生成器对话框
├── run.bat / run.ps1         # 启动脚本
├── run_debug.bat / run_debug.ps1   # 调试启动脚本
├── install.bat / install.ps1       # 环境安装（自动建 venv + 镜像源装依赖）
├── build.bat / build.ps1           # Nuitka 打包脚本
├── build-advanced.bat / build-advanced.ps1  # 高级打包脚本
├── clean.bat / clean.ps1           # 清理构建产物
├── requirements.txt          # 依赖列表
├── README.md                 # 说明文档
├── PACKAGING.md              # 打包说明
├── lang/                     # 语言文件目录（嵌套 JSON，点号路径取值）
│   ├── zh_CN.json            # 简体中文（默认语言）
│   ├── zh_TW.json            # 繁体中文（台湾用语）
│   ├── en_US.json            # 英语
│   └── *.json                # 放进来的语言文件会被自动发现并出现在语言菜单里
├── icon/                     # 图标目录
│   └── icon.ico              # 程序图标
└── InstallerMakerScript/     # Inno Setup 安装包脚本
```

## 配置存储

程序配置和阅读记录存储在系统应用数据目录：

- **Windows**: `%APPDATA%\NovelMaster\`
- **macOS**: `~/Library/Application Support/NovelMaster/`
- **Linux**: `~/.config/NovelMaster/`

存储内容包括：

- `config.json`: 程序配置（含 `language` 界面语言、`shortcuts` 快捷键绑定）
- `themes/`: 自定义主题文件
- `saves/`: 阅读进度记录
- 日志文件

> 项目名曾为 `EpubNovelMaster`，因此旧版本的数据目录是 `%APPDATA%\EpubNovelMaster\`。
> 启动时若发现旧目录，程序会把它**逐项合并**进来（配置、自定义主题与阅读记录一并保留；
> 新旧目录出现同名文件时以新目录为准），并写一条“已从旧数据目录迁移”的日志；
> 搬动失败（跨盘、被占用）时只是跳过该项，程序照常在当前目录下工作。

`saves/` 下每个 JSON 记录用**文件内容哈希**（整文件 MD5）作为标识，而不是文件路径，
因此移动、重命名书籍，或同一本书存在多个副本时，都能继续读到原来的进度：

- 普通文件：`file:<内容 MD5>`
- 文件夹模式：`dir:<路径 MD5>`
- 文件不可读等异常情况回退：`path:<路径 MD5>`

升级前基于路径的记录会在第一次打开该书时自动迁移到新标识（写入新记录并删除旧文件），
无需手动处理。为避免每次自动保存都重算哈希，管理器缓存了
`(mtime, size) → 内容哈希` 的映射，只有文件真正变化时才会重新计算。

每条记录的内容：

| 字段 | 说明 |
| --- | --- |
| `filename` | 文件名（文件夹模式为文件夹名） |
| `md5` | 记录键摘要；`key_type` 为 `file` 时即整文件内容 MD5 |
| `novelname` | 书名，缺元数据时回退文件名 |
| `author` | 作者（无则为空字符串） |
| `key_type` | `file` / `dir` / `path`，说明 `md5` 的含义 |
| `file_size` | 文件字节数（仅普通文件） |
| `total_chapters` | 总章节数 |
| `chapter` / `chapter_title` | 当前位置的章节下标与标题 |
| `file_index` | 文件夹模式下的当前文件下标 |
| `inner_filename` / `inner_md5` | 文件夹模式下当前内层文件的文件名与内容 MD5 |
| `scroll_percent` | 章内滚动位置（0~100），下次打开时定位到原处 |
| `open_count` | 打开次数（每次成功加载 +1） |
| `first_opened_at` / `last_opened_at` | 首次 / 最后打开时间 |
| `total_read_seconds` / `session_read_seconds` | 累计阅读时长 / 最近一次会话的阅读时长 |
| `read_chapters` | `{单元名: [已读章节下标]}`，单文件模式的单元名为文件名，文件夹模式为内层文件名 |
| `read_chapter_count` | 去重后的已读章节总数 |
| `max_chapter` | 当前单元读到的最远章节下标 |
| `file_path` | 打开时使用的完整路径 |
| `timestamp` / `saved_at` | 保存时间（时间戳 / `YYYY-mm-dd HH:MM:SS`） |
| `record_version` / `app_version` | 记录格式版本与写入时的程序版本 |

旧记录缺少的字段（`key_type` / `md5` / `filename` 以及全部统计字段）会在读取时
自动补齐，下次自动保存时落盘；`record_version` / `saved_at` 由管理器写入，调用方无需关心。

文件夹模式恢复位置时优先按 `inner_filename` 定位当前文件，
因此往文件夹里增删书籍、导致排序变化后仍能接着原来那本读。

### 阅读统计与位置记忆

- **计时口径**：只在窗口处于激活状态（且已打开书籍）时累计阅读时长，
  切到别的程序、最小化时自动暂停；失焦时会顺手保存一次，避免异常退出丢进度。
- **已读章节**：`read_chapters` 记录读到过的章节下标（去重），
  `max_chapter` / `read_chapter_count` 由它推导，因此回看旧章节不会让进度倒退。
- **章内位置**：`scroll_percent` 只在“重新打开的是同一章节”时恢复，
  翻到新章节仍从章首开始；可在“视图”菜单里关闭该行为。
- **继续阅读面板**：数据来自 `saves/` 下所有记录，
  失效判断是记录里的 `file_path` 是否还存在（只删记录，不动书籍文件）。

## 开发说明

### 模块结构

项目已按职责拆分为 `enm` 包，入口文件 `NovelMaster.py` 只负责创建 `QApplication`
并显示主窗口。

```text
enm/
├── constants.py          # 版本号、数据目录、语言/图标路径等全局常量
├── i18n.py               # 多语言入口（t / has / set_language，封装 LanguageManager）
├── logger.py             # Logger 单例，同时输出到控制台与日志文件
├── shortcuts.py          # 快捷键定义（ACTION_DEFS）与 ShortcutManager 绑定存储
├── managers/
│   ├── config.py         # ConfigManager：程序配置读写
│   ├── language.py       # LanguageManager：语言文件加载、点号取值、翻译查询
│   ├── progress.py       # ReadingProgressManager：阅读进度、阅读统计与记录清理
│   └── theme.py          # ThemeManager：主题的加载/保存/导入导出
├── readers/
│   ├── base.py           # BaseReader、ReaderError 与通用工具函数
│   ├── epub.py           # EpubReader
│   ├── txt.py            # TxtReader
│   ├── pdf.py            # PdfReader
│   ├── mobi.py           # MobiReader（MOBI/AZW/AZW3/PRC）
│   ├── umd.py            # UmdReader
│   ├── docx.py           # DocxReader
│   ├── fb2.py            # Fb2Reader
│   ├── html.py           # HtmlReader（HTML/HTM/XHTML）
│   ├── archive.py        # ArchiveReader / ZipReader / JarReader
│   ├── images.py         # 内嵌图片处理：magic 探测、data URI 内联与体积限制
│   ├── factory.py        # 扩展名注册表与 create_reader() 工厂
│   └── folder.py         # FolderReader：文件夹批量阅读
└── ui/
    ├── main_window.py    # NovelMaster 主窗口
    ├── continue_dialog.py  # ContinueReadingDialog「继续阅读」面板
    ├── shortcut_dialog.py  # ShortcutSettingsDialog 快捷键设置面板
    └── theme_dialog.py   # ThemeGeneratorDialog 主题生成器
```

### 快捷键实现要点

- 所有可改键功能集中在 `enm/shortcuts.py` 的 `ACTION_DEFS` 里定义，
  包含动作 id、显示名、分组、默认按键、生效范围与说明；
  新增功能时只需在这里加一条，改键面板与主窗口会自动包含它。
- 窗口级快捷键用 `QAction` + `Qt.WindowShortcut` 实现，菜单里会自动显示按键；
  阅读区级快捷键挂在阅读区上，并由主窗口 `eventFilter` 在
  `QEvent.KeyPress` 时派发（自动重复事件会被忽略，长按不会连续翻章）。
- `QTextEdit` 会抢先处理 `Ctrl+Home` / `Ctrl+End`、方向键等按键，
  因此 `eventFilter` 在 `QEvent.ShortcutOverride` 阶段把窗口级按键
  `ignore()` 放行，保证快捷键始终优先于控件自带行为。
- 默认按键用 Qt 的可移植键名（翻页键是 `PgUp` / `PgDown`，
  写成 `PageUp` / `PageDown` 会解析失败）；
  `invalid_definitions()` / `check_defaults()` 会在启动时自检并写日志提醒。

### 多语言实现要点

- **取词入口**：所有界面代码统一 `from .. import i18n`，
  用 `i18n.t("menu.open_file")` 这类点号键取词；语言文件是嵌套 JSON，
  `LanguageManager` 先按扁平键、再按点号路径查找，找不到时按
  “当前语言 → 默认语言（`zh_CN`）→ 调用方 `default` → 键名本身” 逐级回退。
- **切换语言**：`i18n.set_language()` 只改当前语言与文件记录；
  界面刷新由主窗口负责 —— 构造控件时用 `bind_text(widget, key)` /
  `make_action(key, ...)` / `add_menu(parent, key)` 把「控件 + 语言键」登记到
  `_text_bindings`，`retranslate_ui()` 遍历这张表重新写文案，
  所以新增控件只要记得 `bind_text` 就会自动跟随语言。
  语言键还可以是**函数**，用于「显示 / 隐藏章节列表」这类随状态变化的文案。
- **动作名与快捷键**：动作的业务 id（`file.open`）与语言键（`menu.open_file`）
  分开，`enm.shortcuts` 用 `action_label_key()` / `action_hint_key()` 把两者关联，
  并提供 `label_of()` / `hint_of()` / `group_label()`，让快捷键、工具提示
  不需要写死中文。
- **自动生成的标题**：阅读器不再拼中文标题，而是登记
  `auto_title("book.chapter_n", count=n)` 规格（键 + 参数），
  由 `BaseReader.retranslate_titles()` 按当前语言重渲染，
  切换语言时无需重新解析书籍；书籍自身的标题与正文不参与翻译。
- **日志**：`enm/logger.py` 固定输出中文（开发排查更方便），
  且刻意不在模块级导入 `enm.i18n`，避免启动阶段的循环依赖。

### 阅读器接口

所有阅读器都必须继承 `BaseReader`，并对外提供统一接口：

- `get_chapter_count()`：章节数量
- `get_chapter_title(index)`：章节标题
- `get_chapter_content(index)`：章节内容（HTML 片段，不含标题）
- `get_book_info()`：返回 `{"title": ..., "author": ...}`，缺失时用空字符串
- `close()`：释放临时资源（`BaseReader` 默认清理临时目录，可 `super().close()` 后追加清理）
- `current_chapter`：当前章节下标

书名与作者由 `_set_book_info(title=None, author=None)` 填写，只在字段为空时赋值，
因此后解析到的信息不会覆盖已有值；缺书名时由调用方回退到文件名。

### 章节标题去重

部分电子书的章节正文里自带 `<h1>`/`<title>` 标题，而渲染时
`format_chapter_html()` 又会在正文前插入 `<h3>标题</h3>`，导致标题显示两次。

为此 `BaseReader.format_chapter_html()` 会先调用 `strip_duplicate_title(body, title)`：
只检查正文**开头**（允许前面有 XML 声明 / DOCTYPE / 注释）的第一个 `<h1>`–`<h6>`，
当它的纯文本等于章节标题、或是标题的长度 ≥3 的前缀时才删除；
正文中途的小标题、文字不同的标题都不受影响。`TxtReader` 在切分章节时
也直接把标题行作为章节标题，不再写进正文。

### 扩展支持

添加新格式只需两步：

1. 在 `enm/readers/` 下新建阅读器类（继承 `BaseReader`）；
2. 在 `enm/readers/factory.py` 的 `EXTENSION_READERS` 中登记扩展名。

如需在界面中单独分组，可同时更新 `FORMAT_GROUPS`。

### 内嵌图片

若新格式带有内嵌图片，只需实现一个解析函数并复用 `enm/readers/images.py`：

```python
from .images import inline_images

def resolve(reference):
    """reference 为章节里写的 src，返回 bytes 或 (bytes, mime)，失败返回 None"""
    data = 从书中读取(reference)
    return (data, 'image/png') if data else None

html = inline_images(html, resolve)
```

`inline_images()` 会自动跳过远程地址与已有 `data:` URI，限制单张及整章
图片体积（默认 8 MB / 32 MB），并把无法解析的图片标签直接移除，
避免界面出现破损图标。

随后 `BaseReader.format_chapter_html()` 会对 HTML 调用
`isolate_block_images()`，让每张图片独占一个段落，分两种情况：

- 图片和文字在同一个 `<p>` / `<div>` 里 → 拆成 `<p>文字</p><p><img …></p>`；
- 图片根本没写在块里（`</p><img/><p>` 这种写法在电子书里很常见）→ 给图片
  补一个自己的段落。

这一步是必要的排版修正 —— 在 `QTextDocument` 中，行内图片会把**整行的
行高**撑到图片高度，导致图片附近的文字出现巨大的行间距；拆开之后图片
独占一段，行距即恢复正常（实测由约 1280 px 缩到 12 px 的段间距）。
纯文字段落与图片独立成段的写法不受影响。

## 许可证

本项目采用 MIT 许可证。

> 可选依赖 `mobi` 为 GPL-3.0-only 许可，默认不安装。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v1.3.1

- 补全多语言支持：菜单、工具栏、侧边栏、继续阅读面板、快捷键设置、主题生成器
  等原先硬编码中文的界面文案全部改走 `enm.i18n`
- 新增 `enm/i18n.py` 全局入口（`t()` / `has()` / `set_language()` /
  `available_languages()`），语言文件改为嵌套 JSON + 点号路径取值，
  `lang/zh_CN.json` / `lang/zh_TW.json` / `lang/en_US.json` 各 216 个键，键名与占位符一一对应
- 切换语言立即生效（不再提示"下次启动生效"）：主窗口用文本绑定表
  （`bind_text` / `make_action` / `add_menu` / `retranslate_ui`）统一刷新，
  侧边栏"显示/隐藏"、工具栏"显示章节列表/隐藏章节列表"这类随状态变化的文案也会同步更新
- 自动编号的章节标题（"第 N 章"、"正文"、"全文"等）改为在阅读器中登记
  "语言键 + 参数"规格，切换语言时由 `retranslate_titles()` 就地重生成，
  并保留当前章内阅读位置；书籍自身的章节标题与正文不参与翻译
- 修复启动时语言设置失效的问题：此前 `LanguageManager` 被实例化但从未参与界面渲染，
  语言菜单实际不生效；现在启动时按 `config.json` 的 `language` 初始化
- 修复切换语言时日志重复：原先 `LanguageManager.set_language()` 与
  `NovelMaster.change_language()` 各写一条几乎相同的日志；现在统一由
  `LanguageManager` 输出一条（含语言代码），重复设置同一种语言不再写日志
- 日志语言保持中文（开发排查用），不随界面语言变化
- 新增繁体中文（`lang/zh_TW.json`）：按台湾用语翻译（档案 / 资料夹 / 设定 /
  开启 / 汇入汇出 / 储存 / 搜寻 / 使用者介面 / 对话方块 / 快捷键 等）
- 新增语言文件自动发现：启动时扫描 `lang/*.json`，读 `lang.name` 登记语言，
  内置语言之外的按语系插到同语系旁边（简体中文 / 繁體中文 / English），
  新增语言只需放一个 JSON 文件，不必改代码；语言文件坏 JSON 时跳过该语言并写一条日志，
  缺 `lang.name` 时用语言代码兜底
- 项目名称由 "EpubNovelMaster" 改为 "NovelMaster"：入口脚本重命名为
  `NovelMaster.py`、主窗口类改为 `NovelMaster`、打包（`NovelMaster.dist` /
  `NovelMaster.exe`）与安装包脚本（`NovelMaster-Release.iss`）同步更新；
  数据目录随之变为 `%APPDATA%\NovelMaster\`，启动时会把旧目录的数据逐项合并过来
  （同名文件以新目录为准，不覆盖新产生的数据）
- 修复深色主题下部分文字不随主题变色（含进度条上方的"阅读进度"标签）：Qt 样式表
  只会命中写了选择器的控件，`QMainWindow { color }` 不会继承给子控件，`QLabel`、
  菜单栏、工具栏这些没写规则的控件一直是 Qt 默认的浅底黑字，深色主题下黑字压在
  深色底上几乎不可见；现在在 `apply_theme()` 里补齐规则——
  `#sidebar QLabel`（侧栏"章节列表"与"阅读进度"标签）、`QProgressBar` 及
  `QProgressBar::chunk`（槽底色跟随主题背景色、文字跟随主题前景色、填充用主题强调色）、
  `QMenuBar` / `QMenu` / `QToolBar` / `QToolButton`（Windows 样式会自己画一块浅色
  菜单栏底，必须用规则覆盖）；标签规则用 `#sidebar` 限定范围，避免样式表顺着对象树
  渗进对话框把对话框文字刷成白字；强调色上的文字色由 `color_on_accent()` 计算
  （浅强调色配深字、深强调色配白字），浅色 / 深色 / 自定义主题都会随主题变色

### v1.3.0

- 新增快捷键系统：18 项功能均可自定义按键（`enm/shortcuts.py` 统一注册，
  新增"视图" → "快捷键设置"面板，`Ctrl+Shift+K`）
- 键位分两级作用域：窗口内快捷键（`Ctrl+O` 等）与阅读区快捷键（`←` / `→` /
  `PgUp` / `PgDown`）；后者只在阅读区聚焦时生效，不会在章节列表、输入框里抢键
- 阅读区支持 `←` / `→` 直接翻章，长按不连续翻章；
  `Ctrl+Home` / `Ctrl+End` 改为"跳到章首/章尾"
- 新增"阅读"菜单：上一章 / 下一章 / 转到章节（`Ctrl+G`）/ 跳到章首 / 跳到章尾
- 新增字号调节：字体增大（`Ctrl+=`）、字体减小（`Ctrl+-`），范围限制在 8~48，
  调整后立即生效并持久化
- 改键面板按分组展示功能名、当前按键与默认值，支持单项/全部恢复默认；
  检测到重复按键时提示冲突并拒绝保存
- 绑定写入 `config.json` 的 `shortcuts` 字段，只保存与默认值不同的项，
  清空绑定（不绑定按键）同样会保存
- 工具栏与菜单的提示文本会带上当前快捷键（如"下一章（PgDown）"），改键后自动刷新

### v1.2.1

- 修复日志重复输出：`Logger` 攩为单例，重复构造不再叠加处理器
  （原先 `enm/logger.py` 与 `MainWindow` 各建一个实例，同一条日志会被打印多次），
  并关闭向 root logger 传播，避免被基础配置再输一遍
- 日志级别字符串支持 `WARN` 写法，新增 `info()` / `warning()` / `error()` 便捷方法

### v1.2.0

- 修复章节标题重复显示：正文自带的标题会被识别并去除（`strip_duplicate_title()`），
  TXT 的标题行也不再重复出现在正文中
- 统一阅读器基类：`EpubReader` / `TxtReader` / `FolderReader` 现均继承 `BaseReader`，
  `get_book_info()` 统一返回 `{"title", "author"}` 字典，`close()` 统一释放资源
- 阅读记录改为按文件内容哈希标识（移动/重命名/多副本仍能续读），
  旧的路径哈希记录在首次打开时自动迁移
- 阅读记录新增元数据：`filename`、`md5`、`novelname`、`author`、`key_type`、
  `file_size`、`total_chapters`、`chapter_title`、`inner_filename`/`inner_md5`、
  `record_version`、`saved_at`；文件夹模式按内层文件名恢复位置
- 新增「继续阅读」面板（文件菜单 / 工具栏）：按最后阅读时间倒序列出所有书籍，
  显示进度、已读章节、阅读时长与最后阅读时间，双击即可接着读；
  支持按书名/作者/文件名搜索、删除单条记录、一键清理失效记录，
  右键菜单可打开所在文件夹或复制完整路径
- 新增阅读统计：`open_count`、`first_opened_at`/`last_opened_at`、
  `total_read_seconds`/`session_read_seconds`、`read_chapters`、
  `read_chapter_count`、`max_chapter`（记录格式版本升至 3）
- 阅读时长只在窗口处于激活状态时累计，失焦自动暂停并落盘一次
- 新增章内位置记忆（`scroll_percent`）：重新打开同一章节时回到原处，
  可在"视图" → "记住章内阅读位置"关闭
- 切换书籍时先保存上一本的进度与阅读时长，避免自动保存间隔内丢数据
- 新增管理器接口：`iter_records()` / `delete_record_file()` / `format_timestamp()` /
  `record_file_key()` / `normalise_read_chapters()`

### v1.1.0

- 新增 PDF、MOBI/AZW/AZW3/PRC、UMD、DOCX、FB2、HTML/XHTML 及 ZIP/JAR 支持
- 新增内嵌图片显示：EPUB、DOCX、FB2、MOBI、UMD、HTML 与压缩包中的图片自动内联并自适应宽度
- 项目按职责拆分为 `enm` 包（常量 / 管理器 / 阅读器 / 界面）
- 新增 PowerShell 版脚本（`run.ps1` / `run_debug.ps1` / `build.ps1` / `build-advanced.ps1` / `clean.ps1`）
- 新增 `install.ps1` / `install.bat`：无虚拟环境时自动创建并安装依赖
- pip 安装自动测速选择镜像源，镜像失效时自动换源
- 打包脚本在虚拟环境缺少 Nuitka 时自动回退到本机环境

### v1.0.0

- 初始版本发布
- 支持 EPUB 和 TXT 格式
- 文件夹模式阅读
- 主题切换和自定义
- 多语言支持（简体中文、英语）
- 自动保存功能
