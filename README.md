# NovelMaster - 现代化小说阅读器

一个功能强大的小说阅读器，支持多种格式和丰富的自定义选项。

## 功能特性

- 📚 **多格式支持**: EPUB、TXT、PDF、MOBI、AZW、AZW3、PRC、UMD、DOCX、FB2、HTML/HTM/XHTML、JAR、ZIP
- 📦 **压缩包阅读**: 直接打开 ZIP / JAR，自动挑选其中的电子书文件
- 🖼️ **内嵌图片**: 自动显示书中嵌入的封面与插图，并随窗口宽度自适应缩放
- 📁 **文件夹模式**: 支持直接打开文件夹批量阅读
- 💾 **自动保存**: 自动保存阅读记录和进度
- 🔖 **继续阅读**: 独立的阅读记录面板，按最后阅读时间排序，支持搜索、删除与清理失效记录
- 🔗 **多版本共用进度**: 同一本书换了文件 / 追加了新章节，凭书名与章节指纹自动认出来，
  共用同一份阅读进度（章节名是自动编号的书会先问一次）
- 📊 **阅读统计**: 记录打开次数、阅读时长、已读章节数与最远章节
- 📍 **位置记忆**: 重新打开书籍时回到上次的章节，并可记住章内滚动位置
- 🔊 **朗读（TTS）**: 用系统语音把当前章节读出来，逐句高亮 + 自动滚动、语速五档、
  音量、定时停止（15/30/45/60/90 分钟 / 自定义 / 读完本章停）、朗读范围
  （只读选中 / 从光标处 / 指定起止章节），读完自动接着读下一章；装了 `pywin32`
  还能多看到 OneCore 语音库里的 Kangkang / Yaoyao；
  **v1.3.8 起多了两套更好的嗓子**——**离线神经音色**（Piper / Kokoro，共 106 个音色，
  不联网、免费）与**在线音色**（微软 322 个在线音色），模型首次使用时在程序内按需下载
  （带进度、续传与镜像），安装包不会变大
- 🎨 **主题系统**: 内置浅色 / 深色，13 个颜色字段 + 可选排版，16 套预设配色与一键派生，
  支持新建、复制、重命名、导入导出- 📐 **排版可调**: 行距与段间距独立可调（`Ctrl+Shift+P`），“设置 → 排版设置”里拖一下就实时试排，
  也可以写进主题里跟着主题走
- 🪟 **标题栏上色**: 可让 Windows 11 原生标题栏跟随主题配色（默认关闭）
- 📌 **系统托盘（v1.3.9）**: 托盘图标默认就开着，可选“关闭窗口时隐藏到托盘”，
  右键菜单能显示 / 隐藏窗口、控制朗读、切音色、真退出；悬停提示显示书名与朗读状态
- ⏯ **全局媒体键（v1.3.9）**: 在设置里打开“媒体键控制朗读”后，键盘上的播放/暂停、
  上一句 / 下一句直接控制朗读，任务栏媒体浮层（SMTC）显示**书名 + 当前章节**
  （需要可选的 `winrt` 投影包，缺了会自动置灰；浮层上的应用名要靠安装包写进开始
  菜单快捷方式，绿色版会显示「未知应用」，见[下文](#全局媒体键smtc)）
- ⌨️ **自定义快捷键**: 全部功能可改键（含方向键翻章，鼠标侧键 / 中键也能绑），
  自动检测按键冲突
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

以下依赖都**不装也能正常使用**，缺了只是少些增强：

| 依赖 | 用途 | 不装会怎样 |
| --- | --- | --- |
| `mobi` | MOBI/AZW/AZW3/PRC 增强解析（**GPL-3.0-only**，与本项目 MIT 许可不兼容，故不列为必需） | 用内置解析器，功能基本一致 |
| `pywin32>=306` | 朗读走 `sapi-com`，能看到 OneCore 语音库（中文多出 Kangkang / Yaoyao） | 回落 `QTextToSpeech`，功能一样齐全，音色少一些 |
| `sherpa-onnx>=1.13.8` | 朗读的**离线神经音色**（Piper / Kokoro，Apache-2.0，轮子自带 onnxruntime） | 菜单里没有“离线神经音色” |
| `edge-tts>=7.2.8` | 朗读的**在线音色**（微软 322 个在线音色，需联网，MIT） | 菜单里没有“在线音色” |
| `winrt-runtime` / `winrt-Windows.*` | **全局媒体键**（v1.3.9）：媒体键控制朗读 + 任务栏媒体浮层显示书名/章节（pywinrt 投影，MIT） | 设置里的“媒体键控制朗读”置灰 |

想一次装齐：

```bash
pip install pywin32 sherpa-onnx edge-tts
```

媒体键那一组包名字较多，需要时单独装（`winrt` 与 `winsdk` 是两个不同项目，
**本项目用的是前者**）：

```bash
pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections \
    winrt-Windows.Media winrt-Windows.Media.Core winrt-Windows.Media.Control \
    winrt-Windows.Media.Playback winrt-Windows.Storage winrt-Windows.Storage.Streams
```

> 语音**模型**不在依赖里，也不进安装包：首次使用时在“朗读 → 音色管理…”里按需下载
> （Piper 小模型 13 MB / Kokoro 140 MB），存在 `%APPDATA%\NovelMaster\tts_models\`，
> 随时可删。详见「朗读功能 → 引擎与音色」。

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
6. **字体设置**: 点击"视图" → "字体设置"（`Ctrl+Shift+F`），调整字体和大小
7. **排版设置**: 点击"视图" → "排版设置"（`Ctrl+Shift+P`），调行距与段间距，
   拖动过程中阅读区实时试排；详见[排版设置](#排版设置行距与段间距)
8. **位置记忆**: "视图" → "记住章内阅读位置"可开关章内滚动位置的记忆
9. **快捷键**: 点击"视图" → "快捷键设置"（`Ctrl+Shift+K`）可修改任意功能的按键
10. **语言切换**: 点击"视图" → "语言"，选择"简体中文 / English"，界面立即刷新
11. **朗读**: 点“朗读”菜单（或按 `Space`）开始 / 暂停，阅读区下方的朗读条上有
    停止、上一句 / 下一句、语速与两个开关；详见[朗读功能](#朗读功能tts)

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
| 开始 / 暂停朗读 | `Space` | 阅读区 |
| 停止朗读 | （默认不绑定） | 阅读区 |
| 上一句 | `Ctrl+↑` | 阅读区 |
| 下一句 | `Ctrl+↓` | 阅读区 |
| 朗读语速加快 | `Ctrl+Shift+↑` | 阅读区 |
| 朗读语速减慢 | `Ctrl+Shift+↓` | 阅读区 |
| 整章朗读 | （默认不绑定） | 阅读区 |
| 从光标处开始朗读 | （默认不绑定） | 阅读区 |
| 只读选中内容 | （默认不绑定） | 阅读区 |
| 指定起止章节 | （默认不绑定） | 阅读区 |
| 显示/隐藏章节列表 | `Ctrl+B` | 窗口内 |
| 字体增大 | `Ctrl+=` | 窗口内 |
| 字体减小 | `Ctrl+-` | 窗口内 |
| 字体设置 | `Ctrl+Shift+F` | 窗口内 |
| 排版设置 | `Ctrl+Shift+P` | 窗口内 |
| 浅色主题 | `Ctrl+Shift+L` | 窗口内 |
| 深色主题 | `Ctrl+Shift+D` | 窗口内 |
| 快捷键设置 | `Ctrl+Shift+K` | 窗口内 |

除了键盘，**鼠标键也能改**：改键面板每行右侧的下拉框可以把鼠标的**侧键**
（后退 / 前进）或**中键**绑到同一个动作上，与键盘绑定**各存一套、互不影响**
（同一个动作可以键盘和鼠标同时用）：

| 功能 | 默认鼠标键 |
| --- | --- |
| 上一章 | 鼠标后退键 |
| 下一章 | 鼠标前进键 |

- 鼠标键和键盘是**两套槽**：给某个动作绑了鼠标键不会影响它原有的键盘键
  （反之亦然），“恢复默认”会把这一项的两套绑定一起还原。
- 冲突也是**分别判定**的：键盘绑 `PgUp` 与鼠标绑「后退键」不算冲突，
  但两个动作不能绑同一个鼠标键。
- 没绑过的鼠标键保持系统原样（比如中键不绑时还是原来的行为）。
- 鼠标键在**主窗口是当前窗口**时才生效（对话框、菜单开着时不会误触发），
  在输入框 / 下拉框里按下也不会翻章。

- **窗口内**：在章节列表、工具栏、阅读区任意位置都能触发（如 `Ctrl+O`）。
- **阅读区**：只在阅读区获得焦点时生效，且方向键直接用来翻章，
  在该区域内不再移动光标；不会在章节列表或输入框里抢按键。
  长按不会连续翻章，避免一不小心翻掉几十章。
- `Ctrl+Home` / `Ctrl+End` 优先用于"跳到章首/章尾"，不再是 `QTextEdit`
  自带的"文档首/文档尾"。
- `Space` 是**阅读区级**按键：只在阅读区获得焦点时切换朗读，不会在章节列表、
  输入框里抢空格；“停止朗读”默认不占按键（朗读条上的按钮随时可点），
  想用键盘停就在改键面板里录一个。
- 改键面板里点击输入框后直接按组合键即可录制，按 `Delete` 可清空（即不绑定按键）；
  有重复按键时会提示冲突并拒绝保存，每行右侧的"恢复默认"可单独回退。
- 鼠标键用每行右侧的下拉框选（第一项是「未绑定」），键盘那格按 `Delete`
  可清空绑定；鼠标键默认只给「上一章 / 下一章」绑了后退 / 前进键，其余不占键。
- 绑定保存在 `config.json` 的 `shortcuts`（键盘）与 `shortcuts_mouse`（鼠标）
  两个字段里，都只记录与默认值不同的项，下次启动自动生效。

## 排版设置（行距与段间距）

"视图" → "排版设置"（`Ctrl+Shift+P`）里可以单独调阅读区正文的**行距**与**段间距**，
两者都不跟随主题、只作用在正文上：

| 项目 | 范围 | 默认 | 说明 |
| --- | --- | --- | --- |
| 行距 | 1.0 ~ 4.0 倍 | 1.8 | 行与行之间的高度倍数 |
| 段间距 | 0 ~ 80 px | 24 | 相邻两段之间的空白；上下各分一半 |

- 拖动数值时**阅读区实时试排**，按"取消"会原样还原，不会脏掉配置；
- 段间距默认 **24 px**，就是 Qt 自己给 `<p>` 的上下边距（12 + 12），
  所以第一次打开时看到的还是原来的样子；
- 两项都保存在 `config.json` 的 `line_spacing` / `paragraph_spacing` 里，
  和字体设置一样属于**全局排版**；
- 如果当前主题自带行距 / 段间距、并且"排版跟随主题"开着，
  对话框里对应的输入框会置灰并提示"由主题决定"——想自己调就先关掉那个开关。

> **实现提示**：Qt 的样式表**不支持** `line-height`（写了也不生效），
> 所以行距与段间距一律走 `QTextBlockFormat`：行距用
> `setLineHeight(n, ProportionalHeight)`，段间距用上下边距，
> 再由 `enm/ui/reader_typography.py` 把块格式套到整个 `QTextDocument` 上。
> 因为套用块格式会**覆盖** HTML 自带的段落边距，每次重新渲染正文后都会重套一遍。

## 主题功能

### 内置主题

- **浅色主题**（`Ctrl+Shift+L`）: 明亮的阅读环境
- **深色主题**（`Ctrl+Shift+D`）: 护眼的暗色模式

两个内置主题在"视图" → "主题"里是**勾选项**，当前用的是哪个一眼就能看出来。

### 自定义主题

主题由 13 个颜色字段组成，其中 5 个必需、8 个可选（留空即按必需色自动推导）：

| 分组 | 字段 | 说明 |
| --- | --- | --- |
| 基础色（必需） | `background` | 底色 |
| | `foreground` | 文字 |
| | `accent` | 强调色（工具栏 / 进度条 / 选中项） |
| | `highlight` | 高亮 / 悬停 |
| | `border` | 边框 |
| 窗口与标题栏 | `titlebar` | 标题栏底色（也用于窗口标题栏上色） |
| | `titlebar_text` | 标题栏文字色 |
| | `sidebar` | 侧边栏底色 |
| | `tooltip` | 提示气泡色 |
| 交互状态 | `selection` | 选中项色 |
| | `disabled` | 禁用色 |
| | `scrollbar` | 滚动条色 |
| 阅读区 | `reader` | 阅读区底色（留空则用 `background`） |

主题还可以可选地带上排版（`font_family` / `font_size` / `line_spacing` / `paragraph_spacing`）。

1. 点击"视图" → "主题" → "主题管理"（或菜单里的"导入主题"）
2. 在管理面板里点"新建"打开主题编辑器
3. 三种起手方式任选：
   - **选预设**：内置 16 套配色预设（Visual Studio Dark / Solarized Light /
     Solarized Dark / GitHub Light / Nord / Gruvbox Dark / Sepia / High Contrast 等）；
   - **以其它主题为起点**：挑一个已有主题铺进字段（一次性复制，保存后与它再无关联）；
   - **一键派生**：只挑一个主色，其余 12 个颜色与深浅方向自动算出来
4. 颜色字段都是色块按钮 + `#RRGGBB` 输入框，可选字段留空 = 自动推导；
   右侧是**真实控件**做的实时预览（标题栏、标签、按钮、禁用按钮、输入框、
   进度条、列表、下拉框、阅读区）
5. 需要的话勾选"这套主题同时指定字体 / 字号 / 行距 / 段间距"，让主题自带排版
6. 保存后主题会出现在"视图" → "主题" → "自定义主题"子菜单里，点一下即可切换

### 标题栏跟随主题

"视图"菜单里的 **"标题栏跟随主题（Windows 11）"**（默认关闭）会把主题的
`titlebar` / `titlebar_text` 颜色推给 Windows 原生标题栏（`DwmSetWindowAttribute`）。

- 需要 Windows 11（Build 22000+），旧系统上菜单项自动置灰；
- 关掉开关会立刻恢复系统默认标题栏；
- 系统不支持自定义颜色时，会退化成按主题明暗切深色 / 浅色标题栏；
- 主题编辑器、主题管理面板、继续阅读面板、快捷键设置面板会一起用同一个标题栏配色；
- **Qt 自己建的对话框也一样**：字体 / 颜色 / 输入框 / 消息框（`QFontDialog.getFont()`、
  `QMessageBox.about()` 这类静态函数建出来的窗口）外层拿不到引用，
  换由应用级事件过滤器（`enm/ui/dialog_titlebar.py`）在它们第一次 `show()` 时上色；
- 完全不依赖 Qt 样式表（Windows 原生标题栏本来就不吃 QSS），
  也**不会修改任何系统设置**，只影响本窗口。

### Qt 自带对话框的语言

字体选择、颜色选择、输入框、消息框的标题与内部标签来自 **Qt 自带的翻译目录**
（`qt_zh_CN.qm` 之类），不在 `lang/*.json` 里，所以另由
`enm/ui/qt_translations.py` 按当前语言装卸；字体对话框标题也改成显式取
`menu.font_settings`（即"字体设置"）。

- 目录从 `QLibraryInfo.TranslationsPath` 和 PyQt5 自带的 `Qt5/translations` 两处找；
- `zh_CN` 用整体目录 `qt_zh_CN.qm`，`zh_TW` 用的是 `qtbase_zh_TW.qm`（目录拆法不同）；
- **英文只卸载、不加载**：Qt 自带的英文目录（`qtbase_en.qm`）里每条文案都是
  显式空串，装上反而会把标题和按钮全部变空白；
- Qt 的中文目录里没有 `QPlatformTheme` 一节（标准按钮 `OK` / `Cancel` 的文案在那），
  由一个小翻译器补上 `common.ok` / `common.cancel` / `common.close` /
  `common.yes` / `common.no` 五个语言键；
- 缺翻译目录（精简过的 PyQt5 安装）时静默跳过，Qt 界面回到英文，功能不受影响。

### 导入/导出主题

- **导入**: "视图" → "主题" → "导入主题"，选择主题 JSON 文件。主题名依次取
  命令里指定的名字 → JSON 里的 `name` → 文件名；同名时先问是否覆盖，
  撞上内置主题名时会让你换一个名字
- **导出**: "视图" → "主题" → "导出主题"，先从列表里选要导出哪个主题
  （内置主题同样可以导出成模板），默认文件名就是主题显示名

主题文件放在 `%APPDATA%\NovelMaster\themes\` 下，一个 JSON 一个主题，内容是
`name` 加最多 13 个颜色字段（可选）、再可选地带排版字段；**文件始终是自包含的**——
即使是用"以其它主题为起点"或"一键派生"做出来的，保存时也会铺开成完整字段，
不会留下对其它主题的引用。**导入前会严格校验**：不是对象、缺必需字段、颜色不是
`#RGB` / `#RRGGBB`、字号 / 行距 / 段间距超范围一律拒绝并说明是哪个字段有问题；多出来的字段
只警告不报错；只有一个必需色字段的老主题文件也能直接导入（其余颜色自动推导）；
单个文件坏掉只跳过它，不会连累同目录下其它主题。

### 主题管理面板

"视图" → "主题" → "主题管理"打开的面板把内置主题和自定义主题分组列出：

- 内置主题只读（不能改名/删除），可以"复制"成自定义主题后再改；
- 自定义主题可以应用、编辑、复制、重命名、删除、导入、导出；
- 删除或改名当前正在用的主题时会自动跟随（改名）或回落到浅色主题（删除）；
- 列表右侧的预览会随选中项实时更新，"应用"会立刻把主题铺到主窗口上。

## 朗读功能（TTS）

把书籍读出来。引擎一共四套，程序按“能离线出声的优先”自动挑一个，
也可以自己选（“朗读” → “朗读引擎”菜单里就是引擎列表）：

- **`sherpa`（离线神经音色，v1.3.8 新增）**：Piper / Kokoro 神经网络音色，共 106 个，
  音质接近真人，**完全离线、不联网**。需要 `pip install sherpa-onnx` + 在程序内下载模型
  （见下文）；
- **`sapi-com`（系统语音增强版）**：装了 `pywin32` 时直接驱动 SAPI 的 `SpVoice`。好处是能看到
  **OneCore 语音库**（`HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices`），
  中文多出 Kangkang（男声）/ Yaoyao（女声）；
- **`sapi`（系统语音）**：用 `PyQt5.QtTextToSpeech`，只列得出经典
  语音库（本机通常只有 Huihui 一个中文音色）。不用装任何东西；
- **`edge`（在线音色，v1.3.8 新增）**：微软 Azure 的 322 个在线音色（中文 8 个），
  音质是四套里最好的，但**需要联网**。需要 `pip install edge-tts`。

### 怎么用

- **开始 / 暂停**：`Space`，或“朗读”菜单的“开始/暂停朗读”，或阅读区下方朗读条上的按钮；
- **停止**：朗读条的“停止”按钮（菜单里也有这一项）；
- **上一句 / 下一句**：`Ctrl+↑` / `Ctrl+↓`，或朗读条上的按钮；
- **调语速**：朗读条上的下拉框（很慢 / 慢 / 正常 / 快 / 很快），
  或 `Ctrl+Shift+↑` / `Ctrl+Shift+↓`；
- **调音量**：朗读条上的音量滑块；
- **收起朗读条**：朗读条右端的 `▾` / `▴` 按钮，收起来后朗读照常，状态与剩余时间还在；
- **换语音**：“朗读” → “选择音色…”打开一个独立窗口（音色太多，塞进菜单会把屏幕铺满）：
  顶部是**引擎**下拉框（换引擎列表跟着换），下面可以**搜索**（音色名 / 语言 / 模型都能搜，
  比如 `xiaoxiao`、`zh`、`kokoro`）和**按模型筛选**（Kokoro 一家就有 103 个音色，
  不筛的话一屏看不完），列表三列分别是音色 / 语言 / 模型（离线音色会标“已下载 / 未下载”）。
  **双击一行就能用**，也可以选中后点“使用这个音色”；正在用的那个是**粗体**，
  窗口下方还会写一行“当前使用：xxx”。名字后面带着性别与语种。
  本机系统语音例：`Huihui 女声 (zh_CN)`、`David 男声 (en_US)`、`Zira 女声 (en_US)`、
  `Haruka 女声 (ja_JP)`；装了 `pywin32` 还会多出 `Kangkang 男声 (zh_CN)` / `Yaoyao 女声 (zh_CN)`；
- **管音色 / 下模型**：同一个窗口里 —— 离线神经音色时按钮是“音色管理…”（下模型 / 删模型），
  在线音色时按钮是“刷新在线音色”，见下文“引擎与音色”；
- **定时停止**：朗读条上的“定时”下拉框，见下文“定时停止”；
- **朗读范围**：“朗读” → “朗读范围”，或**在阅读区点右键**，见下文“朗读范围”；
- **自动接着读下一章**：“朗读” → “读完自动读下一章”（默认开启）；
- **逐句高亮**：“朗读” → “朗读时高亮当前句”（默认开启），高亮会跟着朗读走，
  并自动滚动到当前句；这两个开关也同步在朗读条上，点一下就能改。

朗读条在阅读区正下方，没有可用语音引擎时整条置灰、“朗读”菜单里的项也一起禁用。

### 引擎与音色（v1.3.8）

| 引擎 | 菜单里的名字 | 说明 | 需要什么 |
| --- | --- | --- | --- |
| `sherpa` | 离线神经音色 | Piper（超文 / 小雅 / 华言）+ Kokoro（103 个音色），共 106 个音色，**不联网** | `pip install sherpa-onnx` + 下载模型 |
| `sapi-com` | 系统语音 | 直驱 `SAPI.SpVoice`，能看到 OneCore 语音库 | `pywin32` |
| `sapi` | 系统语音 | `QTextToSpeech`，只用经典语音库 | 无（PyQt5 自带） |
| `edge` | 在线音色 | 微软 322 个在线音色（中文 8 个，如 Xiaoxiao / Yunxi / Yunyang），音质最好 | `pip install edge-tts` + 联网 |

自动挑的顺序就是上表从上到下，并在配置里记住你手动选过的那个（`tts_engine`）。
选中的引擎当时用不了（卸了库 / 模型删了 / 换了台机器）会自动退回自动选择并写一条日志，
不会把朗读锁死。

**模型按需下载**：代码里不带语音模型，第一次点到没下载的音色时会先问一句“现在下吗？”，
也可以随时在“朗读” → **“选择音色…”** 窗口里点**“音色管理…”** 手动管理：

- 列出 4 个可选模型与体积、是否已下载；
- 下载带**进度百分比**（窗口里与朗读条上各显示一份，`正在下载「超文」 46%`）、
  **断点续传**与失败重试，GitHub 直连不行时自动走镜像；
- 窗口**不是模态**的：关掉窗口下载照常继续，你可以接着看书；
- 已下载的可“删除”（也可直接删目录），底部显示目录位置与总占用。

模型存在 `%APPDATA%\NovelMaster\tts_models\<模型 id>\`：Piper 小模型约 13 MB，
Kokoro 约 140 MB（解压后 200 MB 上下）。只有解压后的模型目录会被用到，
下载的压缩包会自动清掉。

- **在线音色**第一次用会异步拉一次音色清单（约 1 秒），清单缓存 7 天；
  窗口里的“刷新在线音色”可手动重拉，清单没拉回来时列表会显示一行“正在获取在线音色清单…”，
  拉回来后**窗口不用重开**，列表自己就填上了；断网时合成失败会**明确提示**，不会静默无声。
- **自然语音**：Windows 11 的“自然语音”（设置 → 辅助功能 → 讲述人 → 添加自然语音）
  装好后同样属于 OneCore 语音库，会自动出现在“选择音色…”窗口里 —— 本机实测默认
  **没有**装，想更好听的中文系统音色就去那里加。
- **语速**：神经音色把五档映射到 0.4x ~ 1.6x（`length_scale` / `rate`），
  与系统语音的听感基本一致；改语速、换音色会从当前句重读（原因见“常见问题”）。

### 定时停止

朗读条上的“定时”下拉框（只有朗读条上有，菜单里没有）：**不定时** / 15 / 30 / 45 / 60 / 90 分钟 /
自定义分钟数 / **读完本章停**。选了分钟数后朗读条右侧会显示 `剩余 mm:ss` 倒计时，
到点自动停止；选“读完本章停”则读完当前章就停（即使“读完自动读下一章”是开着的）。
定时只为**这一次朗读**服务，暂停不会继续倒数，停止或重开后自动归零；退出程序也会停表。

### 朗读范围

四种范围，命令在“朗读” → “朗读范围”子菜单里，**阅读区右键菜单里也放了一份**
（右键菜单还会把光标定位到点击处，所以“从光标处开始”就是对上你右键的那一句）：

| 命令 | 行为 |
| --- | --- |
| 整章朗读 | 清掉范围，从本章开头重读（也就是默认行为） |
| 从光标处开始 | 从光标所在**那一句的句首**读起，读到本章末尾就停 |
| 只读选中内容 | 只读正文里选中的那一段，**可以跨句、跨段**，读完就停 |
| 指定起止章节… | 弹窗选两章（下拉列表里是真实章节名），从起始章一路读到结束章末尾，中间每章整章读完 |

范围是**一次性**的：读完（或读到本章末尾）就自动回到“整章朗读”，下次按 `Space`
还是从当前章头读；手动翻了章或换了文件，范围也会随之作废（程序记着这条范围属于哪一章，
对不上就不再生效，不会把旧位置的偏移套到新章节上）。
“指定起止章节”与“读完本章停”定时是冲突的，开读跨章范围时会自动取消那个定时；
反过来，跨章范围不受“读完自动读下一章”开关影响 —— 它本身就是“连着读几章”的意思。

右键菜单里除了朗读命令还有“复制”“全选”（没选中内容时“复制”与“只读选中内容”置灰）。

### 相关配置

配置保存在 `config.json`，改键面板之外的部分可直接手改（重启生效）：

| 配置键 | 默认值 | 说明 |
| --- | --- | --- |
| `tts_rate` | `0.0` | 语速，取值 `-1.0` ~ `1.0`（落到五档里最近的一档） |
| `tts_volume` | `1.0` | 音量 |
| `tts_voice_name` | `""` | 上次用的音色 id：系统语音形如 `zh_CN\|Microsoft Huihui`（竖线分隔），离线神经音色形如 `kokoro-multi-lang\|3`，在线音色是 edge 的原始名 `zh-CN-XiaoxiaoNeural` |
| `tts_engine` | `""` | 指定的朗读引擎（`sherpa` / `sapi-com` / `sapi` / `edge`）；**空串 = 程序自己挑**（`sherpa` → `sapi-com` → `sapi` → `edge`） |
| `tts_auto_next_chapter` | `true` | 读完本章是否自动读下一章 |
| `tts_highlight` | `true` | 朗读时是否高亮当前句并自动滚动 |
| `tts_auto_scroll` | `true` | 是否随朗读滚动阅读区 |
| `tts_split_max_chars` | `120` | 单句最大长度，超长的句子按标点再拆（`20` ~ `600`） |
| `tts_bar_collapsed` | `false` | 朗读条是否收起（收起只是藏起控件，朗读照常） |

### 常见问题

- **为什么中文只有一个 “Huihui” 音色？** 因为 Windows 默认只预装这一个中文语音。
  到“设置” → “时间和语言” → “语音”里添加其它中文语音（微软商店里那几个
  `Microsoft ... Online` 语音也可以），装完重启程序就会出现在“选择音色…”窗口里，
  本项目不需要改配置。装了 `pywin32` 时还能看到系统 OneCore 语音库里的
  Kangkang / Yaoyao，不用额外装东西。
- **为什么只能逐句高亮，不能逐词？** 现有的 SAPI 接口只回报“开始说 / 说完了”，
  不提供逐词边界回调，拿不到每个词的时间点；所以高亮粒度就是句子。
- **为什么改语速 / 换语音会从当前句重读？** 已经开口的那一句不能中途变速、换嗓子，
  所以程序会把当前句停掉、用新参数重读一遍（不跳句、也不从头开始）。
  音量是例外，滑块拖动时即时生效，不会打断你正在听的那一句。
  （顺带说明：逐句“喂”给引擎本身并不慢 —— 实测每句只多 24 ms，引擎在朗读态会自行排队，
  所以本程序不需要先把整段合成为音频再播。）
- **为什么长句子会被拆开读？** 过长的一句会让某些语音引擎读到一半就不出声，
  所以按 `。！？` 等标点拆成不超过 `tts_split_max_chars` 的小段依次读；
  万一某个小段真的卡住（引擎不回调），还有看门狗按估算时长跳过它，
  不会整本书卡死。
- **会自动翻章吗？** 只在“这一章读完了”时自动翻；手动停止、暂停、或引擎报错
  都不会翻章，所以停下来之后不会莫名其妙跑掉。
- **为什么用神经音色要联网下载模型？在哪儿删？** 安装包带上 Kokoro 会直接胖 200 MB，
  而大多数人根本不用，所以模型做成“首次使用时在程序内下载”（Piper 13 MB /
  Kokoro 140 MB）。下载位置：`%APPDATA%\NovelMaster\tts_models\<模型 id>\`；
  在“朗读 → 选择音色…” → “音色管理…”里点“删除”，或直接把 `tts_models` 目录删掉都行，
  删了下次要用会再问你要不要下。
- **为什么在线音色的声音比本机好听，但有时会卡 / 报错？** 在线音色（`edge`）把文本
  发到微软服务器合成，音质最好但要联网；公司代理、断网、或服务器限流时会合成失败，
  程序会明确提示“在线音色合成失败，请检查网络后重试”，状态回到空闲，**不会卡死**。
  想完全稳定就用离线神经音色或系统语音。另外，v1.3.8 修掉了一个**跟网络无关**的
  误报：换句时临时 MP3 文件可能被删早了一步，然后弹一个空错误的“音频播放失败”，
  现在不会了 —— 如果你在旧版本上见过它，升级就好。
- **离线神经音色切到下一句为什么几乎没停顿？** 神经音色合成本身比朗读快（Piper 实测
  RTF 0.15、Kokoro 0.7），而且程序会在读当前句时**提前合成下一句**，所以基本接得上；
  预合成用的是独立线程，合成期间界面照常响应（实测最大卡顿 0.07 秒）。
- **想在看书时同时做别的事，有托盘 / 媒体键吗？** v1.3.9 起都有：见
  [托盘与全局媒体键](#托盘与全局媒体键v139)。托盘图标**默认就开着**，
  “关闭窗口时隐藏到托盘”要手动开；“媒体键控制朗读”**默认关**，
  在“设置”菜单里打开（需要可选的 `winrt` 投影包）。

## 托盘与全局媒体键（v1.3.9）

两件事相互独立，都在“设置”菜单里开关：

| 菜单项 | 默认 | 说明 |
| --- | --- | --- |
| 「显示托盘图标」 | **开** | 关掉之后托盘图标和菜单一起收摊（窗口会先显示出来，不会藏得找不回来） |
| 「关闭窗口时隐藏到托盘」 | 关 | 打开后点 X 只是藏起来，程序继续跑；真正退出用托盘菜单的「退出程序」 |
| 「媒体键控制朗读」 | 关 | 键盘媒体键 + 任务栏媒体浮层，需要可选的 `winrt`；没装就置灰 |

### 托盘图标

- **悬停提示**：`NovelMaster · 空闲/朗读中/已暂停`，开了书的话第二行是书名
- **右键菜单**（11 项）：显示 / 隐藏主窗口、开始 / 暂停朗读、停止朗读、上一句、
  下一句、朗读语音、快捷键设置、退出程序；朗读那几项直接复用主窗口的动作，
  所以按键提示、启用 / 禁用状态跟菜单里完全一致
- **左键双击 / 单击**：显示或隐藏主窗口（隐藏时会把窗口恢复成正常大小并抬到前面）
- **第一次收进托盘会冒一个气泡**（“程序仍在后台运行”），只提示一次，
  之后不再打扰；记在配置的 `tray_notice_shown` 里
- 系统没有托盘时（少数精简版系统）只写一条日志，不建图标，功能不影响

### 全局媒体键（SMTC）

打开「媒体键控制朗读」后：

| 键盘按键 | 效果 |
| --- | --- |
| 播放 / 暂停 | 开始或暂停朗读（按当前状态决定） |
| 停止 | 停止朗读 |
| 下一曲 / 上一曲 | 下一句 / 上一句 |

同时任务栏弹出 / Windows 的媒体面板（`Win+` 音量、锁屏界面、蓝牙耳机上的按键等）
会显示**书名 + 当前章节名**，封面位就是程序图标。

- **它是全局的**：不要求窗口在前台，最小化到托盘也生效；也不需要管理员权限
- **同时只能有一个播放器占用**：如果浏览器 / 音乐软件正占着媒体会话，
  系统的媒体键可能先给它们，可以关掉那边的标签页 / 暂停一下
- **会多一条静音音频会话**：媒体会话需要有个“正在播放”的音源撑着，
  程序在内部生成一段 10 秒静音 WAV 循环播（写在 `%TEMP%\NovelMaster_silence.wav`）。
  所以音量合成器里会多一条 NovelMaster，**不出声、不占声卡**，关程序就一起退。
  这是预期现象，不是 bug
- **浮层上的应用名是安装程序写进快捷方式的**：Windows 把「AUMID → 应用名」记在
  **带 `AppUserModelID` 属性的开始菜单快捷方式**上。光给进程设 AUMID、或者只往注册表
  `HKCU\Software\Classes\AppUserModelId\<AUMID>` 写 `DisplayName`，系统都**翻不出**这个
  应用叫什么，浮层标题就会写成「未知应用」——所以安装包会在开始菜单快捷方式上写
  `Aaze_wu.NovelMaster.MediaKeys`。**用安装包装一次**（覆盖安装即可）浮层就显示
  NovelMaster；直接跑 `dist` 里的绿色版没有快捷方式，会显示「未知应用」。注册表那份
  `DisplayName` / `IconUri` 也照写（跟随界面语言，取 `app.name`；MuseHub、Watt Toolkit
  这类桌面应用都这么登记），只影响提示类界面，**不需要管理员权限**，失败也不影响按键
- **没用 `winrt` 时怎么办**：开关会置灰，鼠标悬停有说明；
  不装也不影响其它任何功能（模块 `enm/managers/media_keys.py` 是懒导入，
  只有开关打开且真要用时才 `import winrt`，所以没装也不会拖慢启动）
- **实现要点**（给想改的人）：媒体键回调必须跑在**单独的 STA 线程 + 自己的消息泵**上，
  Qt 的事件循环收不到这些回调；另外要先把 `player.command_manager.is_enabled`
  关掉再开 `smtc.is_enabled`，否则会话建起来也不响应按键

### 相关配置

| 配置键 | 默认值 | 说明 |
| --- | --- | --- |
| `tray_enabled` | `true` | 是否显示托盘图标 |
| `tray_close_to_tray` | `false` | 关窗是否收进托盘 |
| `tray_notice_shown` | `false` | 第一次收进托盘的气泡提示是否已经提示过 |
| `media_keys_enabled` | `false` | 是否启用全局媒体键 |

## 多语言支持

程序内置简体中文、繁体中文与英语，可在"视图" → "语言"中切换，**切换后界面立即刷新**
（无需重启）。当前语言会写入 `config.json` 的 `language` 字段，下次启动自动沿用。

语言菜单按**语系相邻**排序：同语系的语言排在一起，内置语言排在同语系前面，即
简体中文 / 繁體中文 / English。

覆盖范围：

- 菜单、工具栏、按钮、侧边栏等全部界面静态文案；
- 运行时提示（文件格式不支持、加载失败、继续阅读面板、快捷键设置、主题管理面板等）；
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
│   └── ui/                   # 主窗口、朗读条与朗读范围对话框、音色选择/音色管理、继续阅读面板、快捷键设置、
│                             # 主题编辑/管理对话框与共享样式表
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

- `config.json`: 程序配置（含 `language` 界面语言、`shortcuts` 键盘快捷键绑定、
  `shortcuts_mouse` 鼠标键绑定（侧键 / 中键，见「快捷键」）、
  `titlebar_follow_theme` / `typography_follow_theme` 两个开关（均默认关闭）、
  `share_progress_versions`（同名书籍共用阅读进度，默认开启）与
  `progress_share_ignored`（用户选择过「各自独立」的记录）），
  `tray_enabled` / `tray_close_to_tray` / `tray_notice_shown` /
  `media_keys_enabled`（托盘与全局媒体键，见「托盘与全局媒体键」），
  以及朗读相关的 `tts_rate` / `tts_volume` / `tts_voice_name` / `tts_engine` /
  `tts_auto_next_chapter` / `tts_highlight` / `tts_auto_scroll` /
  `tts_split_max_chars` / `tts_bar_collapsed`（见「朗读功能」）
  （朗读的**定时停止档位**只在内存里，不会写进配置文件）
- `tts_models/`: 朗读的离线神经音色模型（按需下载，v1.3.8 起；可整个删掉，
  删了下次要用会重新问你要不要下）
- `tts_voices_edge.json`: 在线音色清单缓存（v1.3.8 起，7 天后自动重拉）
- `themes/`: 自定义主题文件
- `saves/`: 阅读进度记录
- 日志文件

> 项目名曾为 `EpubNovelMaster`，因此旧版本的数据目录是 `%APPDATA%\EpubNovelMaster\`。
> 启动时若发现旧目录，程序会把它**逐项合并**进来（配置、自定义主题与阅读记录一并保留；
> 新旧目录出现同名文件时以新目录为准），并写一条“已从旧数据目录迁移”的日志；
> 搬动失败（跨盘、被占用）时只是跳过该项，程序照常在当前目录下工作。

`saves/` 下每个 JSON 记录优先用**书本身份**作为标识（归一化书名 + 作者 + 开头几章
标题的指纹），因此重新导出、追加章节、换格式、换来源，只要还是同一本书，都能接着读：

- 电子书文件：`book:<身份 MD5>`（同一本书的不同版本 / 不同副本共用同一条记录）
- 弱身份：书名能取到但章节名是自动编号的（算不出指纹），只有
  `book:<书名 MD5>`，命中的记录**一定先问用户**是不是同一本书
- 连书名都取不到：`file:<内容 MD5>`（行为与旧版本一致）
- 文件夹模式：`dir:<路径 MD5>`
- 文件不可读等异常情况回退：`path:<路径 MD5>`

升级前基于内容哈希（`file:<md5>`）的记录会在第一次打开该书时自动迁移到书本身份上
（旧键写进 `aliases` 并删除旧记录文件），无需手动处理。为避免每次自动保存都重算哈希，
管理器缓存了 `(mtime, size) → 文件键 / 内容哈希` 的映射，只有文件真正变化时才会重新计算。

每条记录的内容：

| 字段 | 说明 |
| --- | --- |
| `filename` | 文件名（文件夹模式为文件夹名） |
| `md5` | 记录键摘要；`key_type` 为 `book` 时即书本身份 |
| `novelname` | 书名，缺元数据时回退文件名 |
| `author` | 作者（无则为空字符串） |
| `key_type` | `book` / `file` / `dir` / `path`，说明 `md5` 的含义 |
| `file_md5` | 文件**内容** MD5（与记录键无关，用于区分同一本书的不同版本） |
| `title_key` / `author_key` | 归一化后的书名 / 作者，判断「同一本书」用 |
| `chapter_fingerprint` / `fingerprint_titles` | 章节标题指纹与参与取样的标题（自动编号的章节为空） |
| `book_id` | 书本身份；章节名是自动编号时为空串，只能靠书名 + 用户确认共用 |
| `aliases` | 已合并进本记录的其它记录键，避免以后反复询问 |
| `versions` | 这本书见过的各个文件（文件名 / 路径 / 内容 MD5 / 大小 / 章节数） |
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
│   ├── book_identity.py  # 书本身份：书名/作者归一化、章节标题指纹与匹配强度
│   ├── progress.py       # ReadingProgressManager：阅读进度、记录键规划与合并、记录清理
│   ├── tts.py            # 朗读后端：引擎工厂（系统 / 离线神经 / 在线）、断句、语音挑选与朗读队列
│   ├── tts_audio.py      # 音频播放层：AudioClip / PCM 推流播放 / MP3（QtMultimedia）播放 / 预合成线程
│   ├── tts_neural.py     # SherpaBackend：离线神经音色（Piper / Kokoro）
│   ├── tts_edge.py       # EdgeBackend：在线音色（edge-tts，MP3 + 清单缓存）
│   ├── tts_models.py     # 模型管理：体积/URL/镜像、断点续传下载、解压、占用与删除
│   ├── media_keys.py     # 全局媒体键：SMTC 会话（独立 STA 线程 + 消息泵），winrt 可选
│   └── theme.py          # ThemeManager：主题的校验/加载/保存/导入导出，以及内置主题与预设配色
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
    ├── tts_bar.py        # TtsBar：阅读区下方的朗读条（播放/停止/上下句/语速/音量/开关/定时）
    ├── tts_range_dialog.py  # SpeechRangeDialog：指定起止章节的小对话框（两个章节下拉列表）
    ├── tts_model_dialog.py  # TtsModelDialog「音色管理」：模型列表/体积/状态/下载进度/删除（非模态）
    ├── tts_voice_dialog.py  # TtsVoiceDialog「选择音色」：搜索 + 模型筛选 + 引擎下拉的音色列表（非模态）
    ├── chapter_tree.py   # ChapterTree：章节名被截断时悬停显示全名
    ├── tray.py          # TrayIcon：托盘图标、右键菜单、关窗收托盘与一次性气泡提示
    ├── book_merge_dialog.py  # BookMergeDialog：同名书籍共用记录前询问用户
    ├── continue_dialog.py  # ContinueReadingDialog「继续阅读」面板
    ├── shortcut_dialog.py  # ShortcutSettingsDialog 快捷键设置面板
    ├── titlebar.py       # Windows 原生标题栏上色（DWM，原生 API 失败时静默跳过）
    ├── dialog_titlebar.py  # 应用级事件过滤器：给 Qt 自建对话框的标题栏上色
    ├── qt_translations.py  # 装卸 Qt 自带 qt_*.qm，并补 Qt 目录里缺的标准按钮文案
    ├── theme_qss.py      # build_style_sheet() 样式表 + build_palette() 调色板（主窗口与对话框共用）
    ├── theme_dialog.py   # ThemeEditorDialog 主题编辑器 + ThemePreviewWidget 实时预览
    └── theme_manager_dialog.py  # ThemeManagerDialog 主题管理面板（新建/编辑/复制/改名/删除/导入/导出）
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
- **鼠标键**（侧键 `XButton1` / `XButton2` 与中键）`QKeySequence` 表达不了，
  所以用自定义记号 `MouseBack` / `MouseForward` / `MouseMiddle` 存进
  `shortcuts_mouse`：`normalise_sequence()` 对记号原样放行（否则会被
  `QKeySequence` 解析成空序列而丢失，`key_sequence()` 对它返回空序列）。
  派发用装在 `QApplication` 上的 `eventFilter`（`MouseButtonPress`）：
  鼠标键没有焦点概念，只要主窗口是当前窗口就生效，落点在输入框 / 下拉框 /
  可编辑文本区里则放行给控件，避免打字时误翻章。

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

### v1.3.11

本版是三个修复，不动书库数据、没有依赖变化：文件夹模式下朗读的「读完自动接着读下一章」
不再卡在当前文件、文件夹模式翻章遇到空文件 / 坏文件不再把状态挪偏、
托盘右键菜单跟上主题配色。

- **修复文件夹模式朗读不自动读下一章**（`enm/ui/main_window.py` 的
  `has_next_chapter()`）：原先在文件夹模式下先 `reader = reader.get_current_reader()`
  只检查内层文件，而 `next_chapter()` 本身是能跨文件的 —— 当前文件读到最后一章
  就被判成「没有下一章」，朗读在文件边界停住（单文件打开的书不受影响，
  所以只在文件夹模式暴露）；现在先问内层文件读没读到头，读到头再看外层
  还有没有下一个文件，判定与 `next_chapter()` 的实际行为一致
- **修复文件夹模式翻章把文件索引挪偏**（同文件的 `next_chapter()` /
  `previous_chapter()`）：往后（前）扫描可用文件时是逐格改动
  `current_file_index` 的，一个都没找到（后面全是空的 / 坏文件）时直接返回，
  索引却留在最后探测过的那个文件上 —— 界面显示的还是原来那篇、状态已经指到别处，
  之后的「上一章 / 下一章」与阅读进度都会跟着偏；现在进扫描循环前记下起点，
  确认「没翻动」时把索引退回去
- **修复托盘右键菜单在深色 / 自定义主题下不跟主题**（`enm/ui/tray.py`）：
  主题样式表是设在**主窗口**上的（`QApplication` 上只设了调色板），
  而 Qt 样式表**沿父子链继承**；托盘菜单是 `QMenu()` 没挂 parent，
  不在主窗口的子树里，`QMenu` / `QMenu::item` / `QMenu::separator` 那组规则
  一条都命中不了，只能退回 Windows 原生样式绘制 —— 底色、行距、边框、选中条
  全跟应用内其它菜单对不上（同一份菜单内容实测宽 247 px vs 216 px、
  底色 `#2e2e2e` vs 主题的 `#2b2b2b`）；浅色主题下白底白看不出来，
  只有深色与自定义主题会露。现在改成 `QMenu(window)` 跟着主窗口的样式表走
  （阅读区的右键菜单本来就是 `QMenu(self)` 这么写的）

### v1.3.10

本版给**快捷键加上鼠标键**：改键面板里除了键盘按键，还能把鼠标的
**侧键**（后退 / 前进）或**中键**绑到任意动作上。

- **新增鼠标键绑定槽** `enm/shortcuts.py`：`QKeySequence` 表达不了鼠标键，
  所以自定义三个记号 `MouseBack` / `MouseForward` / `MouseMiddle`，
  存在 `config.json` 的 `shortcuts_mouse` 字段里（键盘那套仍是 `shortcuts`）。
  - 两套槽**各自独立**：给某个动作绑鼠标键不会顶掉它的键盘键（反之亦然），
    同一个动作可以键盘鼠标同时用
  - `normalise_sequence()` 对记号原样放行（否则会被 `QKeySequence` 解析成
    空序列而丢失），`key_sequence()` 对它返回空序列（不参与菜单的按键显示）
  - 默认只绑两项：**上一章 = 后退键**、**下一章 = 前进键**；其余动作默认不绑，
    不占用户的鼠标（中键不绑时保持系统原样）
  - 冲突**分槽判定**：键盘绑 `PgUp` 与鼠标绑后退键不算冲突，
    两个动作绑同一个鼠标键才算；启动自检 `invalid_mouse_defaults()` 一并跑
- **改键面板**（`enm/ui/shortcut_dialog.py`）：每行右侧多一个下拉框
  （未绑定 / 鼠标后退键 / 鼠标前进键 / 鼠标中键），面板相应加宽到 780 px；
  「恢复默认」与「全部恢复默认」会把**两套绑定一起**还原；
  保存时的冲突提示里鼠标键显示为键位名（「鼠标后退键」），不是内部记号
- **运行时派发**（`enm/ui/main_window.py`）：装在 `QApplication` 上的
  **应用级 `eventFilter`** 处理 `MouseButtonPress`（鼠标键不像键盘那样跟焦点走），
  三层防误触：
  - 主窗口不是当前活动窗口时不响应（对话框、弹出菜单开着时按侧键不会翻章）
  - 落点在 `QLineEdit` / 微调框 / `QComboBox` / 可编辑文本区里时放行给控件
    （阅读区是只读的 `QTextEdit`，照常响应）
  - 同一个鼠标键 60 ms 内连发去抖（鼠标没有 `isAutoRepeat`，按住侧键的
    连发 Press 会被吃掉），不会一口气翻掉几十章
- **提示文本**：菜单 / 工具栏 / 朗读条的提示改为「键盘 / 鼠标」都显示，
  如「下一章（PgDown / 鼠标前进键）」（`ShortcutManager.display_all()`）
- **顺手修的一个老 bug**：`enm/ui/tts_bar.py` 的 `shortcut_widgets()` 里
  「上一句」写成了按钮文案键 `tts.previous_sentence`，而动作 id 是
  `tts.prev_sentence` —— 导致该按钮的提示一直显示原始 id，也拿不到快捷键提示
- **语言文件**：三份同步新增 `shortcut.mouse.back` / `.forward` / `.middle` /
  `.hint` / `.default`，并更新了快捷键面板顶部提示；
  三份文件逐键对称，各 **512** 个叶子键
- **配置**：`enm/managers/config.py` 默认配置新增 `shortcuts_mouse`（空表，
  只保存与默认值不同的项，与 `shortcuts` 一致）

### v1.3.9

本版做两件“看书时干别的事”的事：**系统托盘**与**全局媒体键**。
两件都是纯增量，**没有任何必需依赖变化**；媒体键的 `winrt` 是可选依赖，
没装时开关自动置灰，其余功能一字不差。

- **新增系统托盘图标** `enm/ui/tray.py`（托盘图标默认**开**）：
  - 右键菜单 11 项：显示 / 隐藏主窗口、开始 / 暂停朗读、停止朗读、上一句、下一句、
    朗读语音、快捷键设置、退出程序 —— 朗读那几项直接复用主窗口的 `QAction`，
    所以按键提示与启用状态跟主菜单里完全一致，不会跑偏
  - 悬停提示两行：`NovelMaster · 空闲/朗读中/已暂停` + 书名；
    切语言、显隐窗口、朗读状态变化时都会刷新
  - **可选“关闭窗口时隐藏到托盘”**（默认关）：打开后点 X 只是藏起来，
    真正退出走托盘菜单的「退出程序」（`_quitting_from_tray` 标记，不会被“收托盘”截住）
  - **第一次收进托盘冒一次气泡**（“程序仍在后台运行”），只提示一次，
    记在 `tray_notice_shown` 里；免得用户以为已经退了
  - 托盘关掉时会把窗口先显示出来再拆图标，不会把程序藏得找不回来；
    系统没有托盘时只写一条日志
- **新增全局媒体键（SMTC）** `enm/managers/media_keys.py`（默认**关**，
  在“设置 → 媒体键控制朗读”里打开）：
  - 键盘 **播放/暂停 → 开始/暂停朗读**、**停止 → 停止朗读**、
    **上一曲/下一曲 → 上一句/下一句**；播放与暂停都映射成“切换”，
    因为会话的 `playback_status` 跟朗读状态是同步的，系统自然只发该发的那一个
  - **任务栏媒体浮层显示书名 + 当前章节**（`music_properties.title` / `.artist`，
    各截到 128 字符），封面位是程序图标；翻章、开关书、朗读状态变化都会实时刷新
  - 分发是**全局**的：窗口不必在前台，最小化到托盘也照收；不需要管理员权限，
    也没有用 `RegisterHotKey`（那会真占住键盘热键，别的播放器就用不了了）
  - **踩过的两个坑**（都写进注释了）：媒体键回调必须跑在**单独的 STA 线程 +
    自己的 `PeekMessage` 消息泵**上（Qt 的事件循环根本收不到；MTA 与主线程创建
    都是 0 命中，实测 18/18 可用、延迟约 0.1 秒）；另外必须先把
    `player.command_manager.is_enabled` 关掉再开 `smtc.is_enabled`，顺序反了会话在
    任务栏看得见但按键不响应
  - **会话靠一段自生成的 10 秒静音 WAV 循环**撑着（写在 `%TEMP%` 下），
    所以音量合成器里会多一条**静音**的 NovelMaster 会话 —— 预期现象，
    不出声、不占声卡，退出时一并收摊
  - **浮层上的应用名靠安装程序写在快捷方式上**：Windows 把「AUMID → 应用名」记在
    **带 `AppUserModelID` 属性的开始菜单快捷方式**里。实测只调
    `SetCurrentProcessExplicitAppUserModelID`、或者只往注册表
    `HKCU\Software\Classes\AppUserModelId\<AUMID>` 写 `DisplayName`，shell 的
    `AppsFolder` 都**查不到**这个 ID，标题照旧是「未知应用」；写进快捷方式后立刻能查到。
    所以 `InstallerMakerScript/NovelMaster-Release.iss` 的 `[Icons]` 带
    `AppUserModelID: "Aaze_wu.NovelMaster.MediaKeys"`（与代码里的 `APP_USER_MODEL_ID`
    必须一致）；注册表那份 `DisplayName`（跟随界面语言，取 `app.name`）与 `IconUri`
    也照写，只影响提示类界面，值一样就不动注册表，失败只影响显示名
  - `winrt` 一律**懒导入**（先 `find_spec` 探测再真导入），没装时开关置灰 +
    悬停说明 + 点一下弹说明框，启动速度不受影响
- **适配**：`changeEvent`、`closeEvent`、`update_window_title()`、
  `display_content()`、`on_speech_state_changed()`、`retranslate_ui()` 都接上了
  托盘刷新与媒体面板刷新；`closeEvent` 里先停媒体键（它有自己的线程，
  退出前必须收摊），再关托盘
- **语言文件**：三份同步新增 `menu.tray_icon` / `menu.tray_close_hide` /
  `menu.media_keys` / `menu.media_keys_unavailable`、整个 `tray.*` 段（7 条）
  与 `msg.media_keys_missing` / `msg.media_keys_failed`；
  顺手清掉了一条 v1.3.8 遗留的占位键 `menu.share_progress_placeholder`。
  三份文件逐键对称，各 **507** 个叶子键（`tts.*` 下共 111 条）
- **打包**：两个打包脚本会先探测打包解释器里有没有 `winrt`，装了才加上
  `--include-package=winrt` / `--include-package-data=winrt`；没装就跳过，
  **可选依赖缺失不会让打包失败**。`requirements.txt` 与 `PACKAGING.md` 都补了说明

### v1.3.8

本版只做**音色**：系统语音之外新增**离线神经音色**与**在线音色**两套引擎，
外加按需下载的模型管理。托盘与全局媒体键留到 v1.3.9。

- **新增离线神经音色引擎 `sherpa`**（依赖可选的 `sherpa-onnx`）：4 个模型、
  **106 个音色** —— Piper（`超文` / `小雅` / `华言`，13 ~ 64 MB）与 **Kokoro**
  （103 个音色，中英多语言）。**完全离线**、免费、音质接近真人。
  模型按需下载，代码与安装包**不带**语音模型（Kokoro 解压后 174 MB，
  带上会让安装包白白变胖）。新模块 `enm/managers/tts_neural.py`，
  `available_engines()` 把它排在第一位
- **新增在线音色引擎 `edge`**（依赖可选的 `edge-tts`）：微软 Azure 的
  **322 个在线音色**（中文 8 个，如 Xiaoxiao / Yunxi / Yunyang），音质四套里最好，
  但需联网。新模块 `enm/managers/tts_edge.py`：音色清单异步拉取 + 本地缓存 7 天、
  后台线程跑 asyncio、失败写清原因（“在线音色合成失败，请检查网络后重试”）
  - 实测 edge 只给 **MP3**（请求 PCM 会被服务端拒成 `NoAudioReceived`），
    所以这条线用 `QMediaPlayer` + 临时文件播放
- **新增音频播放层** `enm/managers/tts_audio.py`：`AudioClip`（PCM/MP3 + 采样率 + 声道）、
  `PcmPlayer`（`QAudioOutput` 推模式播放，**暂停/续播不丢位置**）、`Mp3Player`
  （`QMediaPlayer`）、以及 **`ClipWorker` 预合成线程** —— 读当前句时就把下一句合成好，
  实测命中后 **speak → 出声只要 80 ms**（Piper）/ 79 ms（edge），整章 6 句连读 24.7 秒；
  合成全在子线程，主界面实测最大卡顿 0.07 秒
- **神经音色的语速与超时**：`TtsBackend` 新增 `timeout_factor`，Piper ×2 / Kokoro ×3 /
  edge ×2（神经合成本身比朗读慢，原来的看门狗会误判“卡住”）；语速五档映射到
  `length_scale` / `rate` 的 0.4x ~ 1.6x
- **新增「音色管理」对话框** `enm/ui/tts_model_dialog.py`：“朗读” → “选择音色…” →
  “音色管理…”。列出 4 个模型与体积、是否已下载，下载带**百分比进度**
  （窗口里 + 朗读条上各一份）、**断点续传**、失败重试与**镜像回退**；
  窗口**非模态** —— 关掉窗口下载继续，可以接着看书；已下载的可删除（带占用统计与目录）
  - 模型存 `%APPDATA%\NovelMaster\tts_models\<模型 id>\`，下载的压缩包会自动清掉
- **音色选择改成独立窗口** `enm/ui/tts_voice_dialog.py`：“朗读” → “选择音色…”。
  以前音色是直接铺在菜单里的，可在线音色有 **322 个**、离线神经音色有 **106 个**，
  菜单一拉开就从屏幕顶排到底，翻起来还容易点错。现在是一个非模态窗口：
  **搜索框**（音色名 / 语言 / 模型都能搜，`xiaoxiao`、`zh`、`kokoro` 都行）、
  **模型筛选下拉**（Kokoro 一家 103 个音色，筛一下清净很多）、**引擎下拉**
  （换引擎不用退回菜单，列表跟着换）、三列列表（音色 / 语言 / 模型，离线音色标
  “已下载 / 未下载”）、**双击即用**、当前音色**粗体** + 底部一行“当前使用：xxx”。
  窗口每次显示 / 刷新都向主窗口**现取**数据，所以刚下完的模型、刚拉回来的在线清单
  立刻就能看到（清单没拉回来时列表显示“正在获取在线音色清单…”）；窗口开着也不影响
  朗读，边听边换都行。新增配置 `tts_engine`
  （空串 = 自动挑：`sherpa` → `sapi-com` → `sapi` → `edge`）；配置里的引擎当时用不了
  会自动退回自动选择，**不会把朗读锁死**
- **点到没下载的音色会先问一句**：`_ensure_voice_model()` 弹确认框并直接打开音色管理，
  下载完自动把用户点的那个音色换上（不用再点一次）
- **修掉在线音色（MP3）偶发的“音频播放失败”**：换句时 `Mp3Player` 会在
  `EndOfMedia` 里先发 `finished`（**同步**回调，下一句的临时文件已经 `setMedia` 进去了），
  再回头删“自己那个”临时文件 —— 删到的其实是**正在播的新文件**，Windows 后端随即
  异步报 `InvalidMedia` / `ResourceError`（`errorString()` 还是空的），用户看到的就是
  莫名其妙的“音频播放失败”。另外 `stop()` 里清空媒体（`setMedia(QMediaContent())`）
  会让后端补一个迟到的 `ResourceError`，正好算到下一句头上。现在：删文件在 `finished`
  **之前**、`stop()` 不再清媒体、`_on_error` 先比对“报错的媒体还是不是当前这一句”
- **语言文件**：三份同步新增 `menu.tts_engine`、`tts.engine.*`、`tts.model.*`（30 条）、
  `tts.voice.*`（选择音色窗口的 20 条：窗口标题 / 提示 / 搜索 / 三列表头 /
  模型与来源 / 状态 / 计数 / 按钮…）与 6 条 `tts.error.*`；
  删除已不再使用的 `menu.tts_voice_refresh` / `menu.tts_voice_manage`
  （它们变成了窗口里的按钮），`menu.tts_voice` 从子菜单标题改成
  「选择音色…」这一条动作。三份文件逐键对称，各 **494** 个叶子键
  （其中 492 条是可翻译文案，另 2 条是 `lang.name` / `lang.code`；`tts.*` 下共 111 条）
- **打包**：`build.ps1` / `build-advanced.ps1` 会先探测打包解释器里有没有
  `sherpa-onnx` / `edge-tts`，装了才加上 `--include-package=sherpa_onnx` /
  `--include-package-data=sherpa_onnx`（原生 DLL 不在依赖图里，必须显式带上）与
  `--include-package=edge_tts`；没装就跳过，**可选依赖缺失不会让打包失败**。
  `requirements.txt` 与 `PACKAGING.md` 都补了对应说明
- 说明：**没有任何必需依赖变化**，不联网 / 不装新库时程序照常启动，朗读也照常可用
  （自动回落系统语音）

### v1.3.7

- **新增 `sapi-com` 朗读引擎（进阶版）**：装了 `pywin32` 时用 `SAPI.SpVoice` 直驱语音，
  **能看到 OneCore 语音库**（`HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens`），
  并与经典库合并去重（同名只留音质更好的 OneCore 那份）——本机中文音色从 1 个
  （Huihui）变成 3 个（Huihui / Kangkang / Yaoyao）。`available_engines()` 把
  `sapi-com` 排在第一，`create_backend()` 建不出来就自动降级回 `QTextToSpeech`；
  枚举走 `winreg`，`sapi_com_available()` 只做 `find_spec` + 扫注册表（约 1 ms），
  **启动路径上不加载要 100 ms 的 `win32com`**。新依赖 `pywin32>=306` 写进了
  `requirements.txt`，但**没装也能用**（自动回落，功能一样齐全）
  - 实测“逐句喂 SAPI”不需要预合成：同一段文本，逐句喂 10.46 s / 预合成后播放
    10.56 s，每句只多 24 ms（Qt 的 `say()` 在 Speaking 态本来就会排队）。所以
    本版**不加** `AudioClip` / `ClipPlayer` 那套两段式流水线，真需要 PCM 的神经
    音色引擎留到下一版一起做
- **朗读条补欠账**：新增**音量滑块**（写 `tts_volume`；`theme_qss.py` 补上了
  `QSlider` 的 groove / sub-page / handle 样式，以前根本没这条规则）与
  **收起 / 展开按钮**（`▾` / `▴`，状态记 `tts_bar_collapsed`）。收起只是把控件藏起来，
  朗读、空格键、快捷键都照常，倒计时那行故意不跟着收
- **新增定时停止**：朗读条的“定时”下拉框（**不定时 / 15 / 30 / 45 / 60 / 90 分钟 /
  自定义 / 读完本章停**），选分钟数后右侧显示 `剩余 mm:ss`，到点自动停止；
  “读完本章停”优先于“读完自动读下一章”，读完这一章就停住不翻。定时是**会话级**的：
  暂停不继续倒数，停止、重开或退出程序都会收掉那只 `QTimer`；切语言时倒计时文案
  会跟着重画（记下剩余秒数后重渲染，而不是只在设置那一刻翻译一次）
- **新增朗读范围**（“朗读” → “朗读范围”，**阅读区右键菜单里也有一份**）：

  | 命令 | 行为 |
  | --- | --- |
  | 整章朗读 | 清掉范围，从本章开头重读 |
  | 从光标处开始 | 从光标所在**那一句的句首**读起，读到本章末尾停下 |
  | 只读选中内容 | 只读正文里选中的那一段，可跨句、跨段 |
  | 指定起止章节… | 弹窗选两章，从起始章连读到结束章末尾（新对话框 `enm/ui/tts_range_dialog.py`，下拉列表里是真实章节名） |

  范围是**一次性**的：读完（或读到章末）就自动回到“整章朗读”；手动翻章、换文件时
  立刻作废（字符偏移在新章里已经没有意义）。“指定起止章节”与“读完本章停”是冲突的，
  开读跨章范围时会自动取消那个定时；跨章范围也不受“读完自动读下一章”开关影响。
  实现上 `sentences_for_blocks()` 新增 `char_range` 参数，按**文档字符区间**切句子
  （与 `QTextCursor.position()` 同坐标系，含图片 / 空块的章节也不会错位），
  所以范围切分与逐句高亮共用同一套绝对位置
- **新增阅读区右键菜单**（`show_reader_context_menu`）：换掉 `QTextEdit` 自带那份，
  改成 开始/暂停朗读、停止朗读、朗读范围子菜单（只读选中 / 从光标处 / 整章 /
  指定起止章节）、复制、全选。右键时若没有选区会把光标挪到点击处，这样
  “从光标处开始朗读”就对得上你右键的那一句；无选区时“复制”与“只读选中内容”置灰；
  菜单收起时把借用的共享动作状态还给 `update_speech_controls()`
- **快捷键新增 4 项**（`GROUP_AUDIO`，均默认不绑定、只在阅读区生效）：整章朗读 /
  从光标处开始朗读 / 只读选中内容 / 指定起止章节
- **语言文件**：三份同步新增 `menu.tts_range*`、`menu.copy`、`menu.select_all`、
  `tts.range.*`（含对话框文案与“没选中 / 光标后面没字 / 这段读不出内容”三种提示）、
  `shortcut.action.tts_range_*.label / .hint`。三份文件逐键对称，各 **425** 个叶子键
  （其中 423 条是可翻译文案，另 2 条是语言自身的 `lang.name` / `lang.code`）

### v1.3.6

- **新增「排版设置」**（"视图" → "排版设置"，`Ctrl+Shift+P`）：行距与段间距都可以
  自己调了，拖动时阅读区**实时试排**，按"取消"原样还原
  - 新增 `enm/ui/typography_dialog.py`，行距 1.0~4.0 倍、段间距 0~80 px
    （默认 24，正是 Qt 给 `<p>` 的上下边距，所以默认外观和以前一样）
  - 两个值都以**全局排版**的身分存进 `config.json`
    （`line_spacing` / `paragraph_spacing`），和字体设置同级
  - 当前主题自带这两项且"排版跟随主题"打开时，对应输入框置灰并说明"由主题决定"
- **修掉一个一直没生效的 bug：行距以前根本没用**。旧代码把 `line-height` 写进
  样式表（`enm/ui/theme_qss.py`），但 **Qt 样式表不支持 `line-height`**，
  写了等于没写——也就是说 `config.json` 的 `line_spacing` 与主题自带的行距
  从来没真正落到正文上。现在改成走 `QTextBlockFormat`
- **新增 `enm/ui/reader_typography.py`**：唯一负责把行距 / 段间距套到
  `QTextDocument` 上的模块——行距用 `setLineHeight(n, ProportionalHeight)`
  （实测文档高度 160 px → 290 px），段间距用 `setTopMargin()` / `setBottomMargin()`
  （上下各分一半），整篇一次性 `mergeBlockFormat()` 套用。
  `display_content()` 的三条渲染分支、`apply_theme()` 与两处预览控件都接了线
  （`setHtml()` 会冲掉块格式，所以每次重新渲染后都要重套）
- **段间距也进了主题**：`enm/managers/theme.py` 的排版字段从 3 个变 4 个
  （`font_family` / `font_size` / `line_spacing` / `paragraph_spacing`），
  主题编辑器多一个"段间距"输入框，主题管理面板的预览也会跟着走
- **校验与文案**：`normalise_paragraph_spacing()` 与 `invalid_paragraph_spacing`
  错误码（**0 是合法值**，调用方不能拿 `or` 兜默认值）；三份语言文件同步新增
  `typography.*` 分组、`theme_editor.paragraph_spacing_label`、
  `shortcut.action.view_typography_dialog.*` 等键

### v1.3.5

- **新增完整的朗读（TTS）功能**：新增 `enm/managers/tts.py` 与 `enm/ui/tts_bar.py`，
  用 `PyQt5.QtTextToSpeech` 调系统自带的语音引擎（Windows 上是离线的 SAPI5），
  **不加任何第三方依赖、不联网**；系统里没有语音引擎时朗读相关界面整体置灰，
  其它功能不受影响
  - 断句朗读：按 `。！？!?…；;` 等句末标点切句（收尾的引号、括号跟着前一句），
    过长的句子再按 `，、：` 等软停顿拆，默认单句不超过 120 字（`tts_split_max_chars`）；
    图片占位符之类不可发音的内容直接跳过
  - 逐句高亮 + 自动滚动到当前句，颜色跟随主题（高亮 → 选中 → 强调色逐级回落）
  - 语速五档（很慢 / 慢 / 正常 / 快 / 很快）、音量、语音选择都可调，
    换语音时自动切到该语音对应的语言，重启后沿用
  - 读完一章可以自动接着读下一章（默认开启），手动停止 / 暂停 / 引擎报错都不会翻章
  - 阅读区下方新增朗读条：播放-暂停、停止、上一句、下一句、语速下拉与两个开关，
    附带“第 3/128 句”的进度提示；按钮上的快捷键提示会跟着改键实时刷新
- **新增朗读快捷键分组**（`enm/shortcuts.py` 的 `GROUP_AUDIO`，共 6 项，全部只在
  阅读区生效）：`Space` 开始/暂停、`Ctrl+↑` / `Ctrl+↓` 上一句 / 下一句、
  `Ctrl+Shift+↑` / `Ctrl+Shift+↓` 调速；“停止朗读”默认不绑定按键，可自行录制
- **主窗口接线**：朗读条、“朗读”菜单（开始/暂停、停止、上一句/下一句、
  朗读语音、读完自动读下一章、朗读时高亮当前句）与工具栏按钮，
  切换书籍 / 重新渲染正文 / 换主题 / 换语言时都会同步朗读状态，
  退出时关闭引擎
- **打包**：`build.ps1` / `build-advanced.ps1` 增加
  `--include-qt-plugins=texttospeech`（Nuitka 的 pyqt5 插件默认不带这个插件，
  漏掉的话打包出来的程序朗读会静默无声），并把 `PyQt5.QtTextToSpeech` 加进
  依赖收集列表

### v1.3.4

- **同一本书的不同版本 / 更新版可以共用阅读进度了**：新增
  `enm/managers/book_identity.py`，用「书名 + 作者 + 开头若干章标题的指纹」
  算出书籍身份（`book_id`），记录键从「文件内容哈希」升级为
  `book:<book_id>`
  - 换了个文件、多加了章节、换了个来源，只要还是同一本书，就自动落到
    同一条记录上，阅读位置不用重新找
  - 书名与章节标题都会先归一化再比对：全角半角、大小写、空白、
    `[作者]`/`（全本）`/`《》` 之类的前后缀、章节编号的写法差异都能对上，
    避免因为标点差异把同一本书认成两本
  - 老记录（`file:<md5>`）在第一次打开时**自动迁移**到新的书本身份键上：
    阅读位置、阅读统计、书签式进度全部保留，旧键写进 `aliases`，
    旧记录文件删掉，整个过程不需要用户操作
  - 认得出身份的书，多个版本之间**静默合并**，不再重复询问
- **认不出章节指纹的书改成「弱身份」+ 询问用户**：章节名是程序自动编号的
  （章节标题形如「第1章」「第2章」，常见于缺章节标题的 UMD 与按
  「第N章」切分的 TXT），只能靠书名判断
  - 弱身份（`weak_id`）只用书名算，命中的记录**一律先问用户**：
    对话框会说明「书名一样，但章节名是自动编号的、没法比对」，
    让用户确认是不是同一本书；选「各自独立」就退回自己的内容键，
    原记录一动不动
  - 同一份记录里既记 `content_key`（别名）也记 `versions`（各版本的
    文件名 / 摘要 / 章节数），所以哪怕章节名不能比，也能凭「当前文件是不是
    已经在记录里」认出自己
- **新增「同名书籍共用阅读进度」开关**（「设置」菜单，配置键
  `share_progress_versions`，默认开启）：
  - 关掉后不再弹合并询问，但仍然会读自己那份记录（身份对得上就直接用）
  - 用户对某本书的「各自独立」选择会被记住（`progress_share_ignored`，
    最多 100 条，按「书名 + 记录」匹配），下次打开不再打扰
- **继续阅读面板会标出同书的其它版本**：书名前面出现 `⇄` 标记就说明这本书
  还有别的记录（通常是同一本书的另一个版本），悬停可以看到都是哪些文件，
  打开任意一份都接同一处进度
- **合并策略偏保守**：合并两份记录时取「更靠后的阅读位置、更多的已读章节、
  更长的阅读时长」，并把两边的别名与版本足迹并集起来；任何异常都只记日志，
  不影响书能不能打开

### v1.3.3

- **标题栏可以跟着主题变色了**：新增 `enm/ui/titlebar.py`，用 Windows 原生
  DWM 接口（`DwmSetWindowAttribute`，属性 34/35/36）把主题的 `titlebar` /
  `titlebar_text` 颜色推给原生标题栏
  - 新增"视图" → "标题栏跟随主题（Windows 11）"开关，**默认关闭**，配置键
    `titlebar_follow_theme`；不支持的系统上菜单项自动置灰
  - 需要 Windows 11（Build 22000+）；系统不支持自定义颜色时自动退化为
    按主题明暗切深色 / 浅色标题栏（`DWMWA_USE_IMMERSIVE_DARK_MODE`）
  - 关掉开关会立刻恢复系统默认标题栏（`DWMWA_COLOR_DEFAULT`）；
    顺带把边框色对齐主题、窗口圆角设为系统默认
  - 主题编辑器、主题管理面板、继续阅读面板、快捷键设置面板会一起用
    同一个标题栏配色（`apply_to_widget()`）
  - 原生调用全部包在 `try/except` 里并检查 `HRESULT`，任何失败都只是静默跳过，
    绝不会影响启动或阅读
- **主题从 5 个颜色扩展到 13 个**（`enm/managers/theme.py`）：必需色仍是
  `background` / `foreground` / `accent` / `highlight` / `border`，新增 8 个可选色
  `titlebar`、`titlebar_text`、`selection`、`disabled`、`scrollbar`、`tooltip`、
  `sidebar`、`reader`；可选色留空时由新增的 `derive_missing()` 按必需色自动推导
  （`shift_lightness` / `mix` / `contrast_text` / HSL 计算全部与 Qt 无关，纯数学）
- **主题编辑器大幅加料**（`enm/ui/theme_dialog.py`）：颜色字段按
  "基础色 / 窗口与标题栏 / 交互状态 / 阅读区"四组折叠展示；新增三种起手方式
  （16 套预设配色、以其它主题为起点的一次性复制、只给一个主色就自动派生整套配色）；
  新增可选的字体 / 字号 / 行距字段；预览区加上标题栏与阅读区样张；
  字段旁的提示改用行内文字而不是弹窗
- **排版跟随主题**：主题可以自带 `font_family` / `font_size` / `line_spacing`，
  但要打开"视图" → "排版跟随主题"（配置键 `typography_follow_theme`，默认关闭）
  才会覆盖"设置 → 字体设置"里的全局排版；默认关闭时主题只负责颜色
- **主题文件保持自包含**：主题继承只是编辑器里的一次性起点，
  保存时会把字段完整铺开写进 JSON，不会留下对其它主题的引用；
  只有一个必需色字段的旧主题文件仍可直接导入（其余颜色自动推导）
- **修掉深色主题下「继续阅读」列表的白色隔行**：开了隔行变色的表格，隔行底色
  取的是 Qt 调色板里的 `AlternateBase`（系统浅色），样式表里的
  `background-color` 管不到它，于是深色主题下隔行变成白底浅字；
  现在样式表显式给出 `alternate-background-color`（底色向文字色混 8%，
  明暗主题都自动得到合适的一档）
- 表头排序方向改用文字标记：Qt 的系统排序箭头是调色板画的、样式表换不了颜色，
  深色主题下表头会出现一块白斑；现在藏掉箭头，改在表头文字后用 `↑` / `↓`
  表示排序方向（符号与语言无关，不占语言键）
- **修掉深色主题下二级窗口的浅色底**：Qt 的调色板与样式表是两套通道，
  样式表管不到的控件（下拉列表、菜单、表头、内建的滚动区）走的是调色板里
  的系统浅色；新增 `build_palette()` 按主题算出整份 `QPalette` 并在
  `apply_theme()` 里一并设给 `QApplication`，主题编辑器、快捷键设置、
  继续阅读、主题管理等对话框不再出现 `#F0F0F0` 灰块
- **修掉主题编辑器里字号 / 行距输入框的白底**（`QSpinBox` / `QDoubleSpinBox`）：
  它们的基类是 `QAbstractSpinBox`，跟 `QLineEdit` 没有继承关系，样式表里那条
  `QLineEdit` 规则管不到；而样式表**一条规则都没碰**某个控件时，Windows
  原生样式会拿自己的主题去画，调色板灌成纯黑它们照样是白底（禁用时浅灰）。
  现在 `build_style_sheet()` 里显式给出数字框的底色 / 文字色 / 边框 / 焦点态，
  跟同面板的输入框对齐。上下按钮**故意不上色**，交给原生样式按调色板画箭头
  （深色主题下是白的）；一旦连 `::up-button` / `::down-button` 一起上色，
  Qt 就不再画箭头（`::up-arrow` 只能指向图片文件，本项目不放这类素材），
  按钮会变成一个没有箭头的色块
- 语言文件同步到 308 个键（三语一一对应），新增编辑器分组 / 起点 / 派生 /
  排版 / 校验错误等 38 个键，以及 Qt 标准按钮的 `common.yes` / `common.no`
- **Qt 自带对话框的标题栏与语言**：新增 `enm/ui/dialog_titlebar.py`
  （应用级事件过滤器，给 `QFontDialog` / `QColorDialog` / `QInputDialog` /
  `QMessageBox` 这些由 Qt 内部创建的窗口上色）与 `enm/ui/qt_translations.py`
  （按语言装卸 Qt 自带的 `qt_*.qm`，补上 Qt 目录里缺的标准按钮文案）；
  "字体设置"对话框改成实例化 `QFontDialog`，标题显式取语言键，
  不再是永远的 `Select Font`
- **章节列表悬停看全名**：侧边栏默认只有 300px 宽，长章节名一律被
  `Qt.ElideRight` 截成「第1234章 我打造了末日安…」。新增 `enm/ui/chapter_tree.py`
  的 `ChapterTree`（`QTreeWidget` 子类），在 `viewportEvent` 里拦下
  `QEvent.ToolTip`，用 `QFontMetrics` 量一下这一行的文字到底画不画得下，
  **只有真的被截断才弹提示**，短名字悬停时保持安静——Qt 自带的
  `setToolTip()` 是每个条目无条件生效的，用它会连「第1章 开局」也一起弹，很吵
- **侧边栏宽度可以拖、而且记得住**：章节列表与阅读区之间换成 `QSplitter`，
  拖中间那条分隔条就能改宽度（限制在 160–720px，并保证阅读区至少留 280px），
  松手 400ms 后写回配置键 `sidebar_width`，下次启动按上次的宽度恢复；
  分隔条原先由系统样式画成一道灰白缝（深色主题下很扎眼），
  现在显式上色跟随主题（`QSplitter::handle`，悬停换成强调色）

### v1.3.2

- 重做主题系统（导入导出与主题编辑）：
  - **主题编辑器**（`ThemeEditorDialog`）：5 个颜色字段（背景 / 文字 / 强调 / 高亮 / 边框）
    各自一个色块按钮 + `#RRGGBB` 输入框，内置 8 套预设配色（Visual Studio Dark、
    Solarized Light/Dark、GitHub Light、Nord、Gruvbox Dark、Sepia、High Contrast），
    手动改色后下拉自动回到"自定义"；右侧预览改用**真实控件**（标签 / 按钮 / 禁用按钮 /
    输入框 / 进度条 / 列表 / 下拉框），改一个颜色整块预览立刻跟着变
  - **主题管理面板**（`ThemeManagerDialog`，新增 `enm/ui/theme_manager_dialog.py`）：
    内置 / 自定义分组列出，内置主题只读但可"复制"成自定义主题；自定义主题支持
    应用 / 编辑 / 复制 / 重命名 / 删除 / 导入 / 导出；删的是当前主题自动回落浅色主题，
    重命名的是当前主题则当前主题跟着改名
  - **主菜单可直接切换自定义主题**：新增"视图" → "主题" → "自定义主题"子菜单
    （按名字排序、当前项勾选），空时显示一条禁用的"（暂无自定义主题）"占位项；
    内置主题也改成勾选项，切主题后菜单状态即时同步
  - **主题数据层重写**（`enm/managers/theme.py`）：`validate_theme()` 严格校验
    （必须是对象、5 个字段齐全、颜色必须是 `#RGB`/`#RRGGBB`；多余字段只警告），
    加载时坏文件只跳过自己而不是整批放弃；`get_theme()` 永远返回字段齐全的主题
    （缺失字段按浅色主题补齐）并支持 `fallback=None`，避免 `config.json` 里存了
    坏主题名导致启动即崩；内置主题名（浅色/深色）不允许被自定义主题占用，
    主题名会做文件名安全化（非法字符去掉、Windows 保留名加下划线、超长截断）；
    新增 `rename_theme()` / `duplicate_theme()` / `import_theme_file()` /
    `export_theme_file()`，导入时主题名按"显式指定 → JSON 里的 `name` → 文件名"取值，
    每个失败场景都有独立的错误码（`theme_error.*`）供界面翻译
  - **样式表集中到 `enm/ui/theme_qss.py`**：`build_style_sheet(theme, font_size, line_spacing)`
    由主窗口和主题管理面板共用，不再在 `apply_theme()` 里内联一大段 QSS；
    菜单栏、菜单、工具栏、进度条、滚动条、输入框、下拉框、工具提示等规则一次性补齐
  - 语言文件同步到 268 个键（三语一一对应），新增主题编辑器 / 主题管理 / 主题错误
    三组键，删掉原有的"主题生成器"相关死键
  - 深色主题下的文字可见性修复也随之收进 `theme_qss.py`：`#sidebar QLabel`
    （侧栏"章节列表"与"阅读进度"标签）、`QProgressBar` 及 `QProgressBar::chunk`、
    `QMenuBar` / `QMenu` / `QToolBar` / `QToolButton`

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
