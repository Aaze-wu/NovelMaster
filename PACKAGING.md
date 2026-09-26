# NovelMaster 打包指南

本文档介绍如何用 Nuitka 将 NovelMaster 打包成独立目录版或单文件可执行程序。

## 📦 打包脚本说明

每个 `.bat` 脚本都有等价的 PowerShell 版本（功能与参数一致，推荐使用）。
`.bat` 只是轻量包装，会把参数原样转发给同名的 `.ps1`，因此两者行为完全一致。

| 用途 | CMD 版本 | PowerShell 版本 |
| --- | --- | --- |
| 环境安装（建 venv + 装依赖） | `install.bat` | `install.ps1` |
| 基本打包（独立目录版） | `build.bat` | `build.ps1` |
| 高级打包 | `build-advanced.bat` | `build-advanced.ps1` |
| 清理产物 | `clean.bat` | `clean.ps1` |
| 运行程序 | `run.bat` / `run_debug.bat` | `run.ps1` / `run_debug.ps1` |

### 环境安装脚本 (`install.ps1` / `install.bat`)

- 虚拟环境不存在时**自动创建** `.venv`
- **自动测速选择最快的 pip 镜像源**并安装依赖
- 镜像失效（403 / 超时 / 断流）时自动切换到下一个镜像，最后回退官方 PyPI
- 可用 `-WithNuitka` 顺手把打包工具装进虚拟环境

```powershell
.\install.ps1                 # 默认：建 venv + 装 requirements.txt
.\install.ps1 -Recreate       # 删除旧 venv 后重建
.\install.ps1 -WithNuitka     # 同时安装 Nuitka
.\install.ps1 -Mirror aliyun  # 指定镜像（auto/tuna/aliyun/ustc/tencent/pypi/自定义URL）
.\install.ps1 -DryRun -NoPause
```

> 指定镜像只改变**优先顺序**，其余镜像与官方 PyPI 仍会作为自动兜底逐级尝试。
> 镜像源也可用环境变量统一覆盖：`$env:ENM_PIP_INDEX = 'https://mirrors.aliyun.com/pypi/simple/'`

### 基本打包脚本 (`build.ps1` / `build.bat`)

- 简单易用，适合快速打包
- **独立目录版**（`--standalone`，不带 `--onefile`），产物是 `dist\NovelMaster.dist\` 整个文件夹
- 分发时必须整目录拷贝，**不能只拷 `NovelMaster.exe`**
- 安装包（Inno Setup）正是对这个目录打包的
- 自动检测 Nuitka，缺失时用镜像源自动安装
- **自动发现本机所有 Python 解释器**（py 启动器 / 注册表 / 常见安装目录 / PATH），
  默认优先使用项目 `.venv`，其次才是 PATH 与本机已安装的 Python
- **当前解释器没有 Nuitka 时，自动回退到本机环境中已安装 Nuitka 的解释器**

### 高级打包脚本 (`build-advanced.ps1` / `build-advanced.bat`)

- 提供多种打包选项（`-Mode onefile|standalone|debug`、`-Optimize default|full`）
- **不带参数运行时会依次询问**打包模式与优化级别，直接回车就是默认值
- 支持调试模式和优化级别选择
- 更详细的配置和错误处理
- 同样支持解释器自动发现、Nuitka 自动回退与镜像源安装

### 清理脚本 (`clean.ps1` / `clean.bat`)

- 清理打包过程中生成的临时文件
- 释放磁盘空间
- `clean.ps1` 支持 `-WhatIf` 预览、`-IncludeLogs`、`-Force`

## 🚀 快速开始

### 第 0 步：准备环境（推荐）

```powershell
.\install.ps1            # 自动创建 .venv 并安装依赖（自动选择镜像源）
```

### 方法一：使用基本打包脚本

```powershell
.\build.ps1              # 或双击 build.bat
```

### 方法二：使用高级打包脚本

```powershell
.\build-advanced.ps1     # 或双击 build-advanced.bat（会询问模式和优化级别）
```

### 常用参数

```powershell
.\build.ps1 -Python 3.13                       # 用本机 Python 3.13 打包
.\build.ps1 -Python 3.13.6                     # 带补丁号也支持
.\build.ps1 -Python "C:\Python313\python.exe"  # 用完整路径指定
.\build.ps1 -UseVenv                           # 用 .venv 打包（已是默认行为）
.\build.ps1 -NuitkaPython "C:\Python313\python.exe"   # 指定打包解释器
.\build.ps1 -NoFallback                        # 禁止回退到本机环境 Nuitka
.\build.ps1 -SkipNuitkaCheck                   # 跳过 Nuitka 检测与依赖自检
.\build.ps1 -Mirror tuna                       # 指定 pip 镜像源
.\build.ps1 -DryRun -NoPause                   # 只预览打包命令
.\build.ps1 -OpenOutput                        # 完成后打开输出目录
```

`-Python` 支持三种写法：**版本号**（`3.13` / `3.13.6`）、**命令名**（`python` / `python3` / `py`）、
**完整路径**。不指定时按下面的顺序自动选择。

### 解释器是怎么选的

打包脚本按以下顺序选择解释器：

1. **`-Python` 显式指定**（优先级最高）：按版本号 / 命令名 / 路径解析，解析不了会提示并改用自动发现；
2. **项目 `.venv`**：存在就用它（`install.ps1` 把依赖装在这里，打包环境与开发环境一致）；
3. **PATH 里的 `python` / `python3` / `py`**；
4. **本机扫描到的其它 Python**（py 启动器注册表 / Windows 注册表 / 常见安装目录），按版本从新到旧。

解释器找到后：

1. 自带 Nuitka → 直接使用；
2. 没有 Nuitka → 在候选解释器（`-NuitkaPython` → `.venv` → PATH → 本机扫描结果）中
   找已装 Nuitka 的，找到即**自动改用**并提示；
3. 都找不到 → 打印**本机解释器扫描结果**（每行含版本号与 Nuitka 状态），
   然后用镜像源为当前解释器安装 Nuitka；
4. `-NoFallback` 可关闭第 2 步的自动回退。

确定解释器后脚本还会做一次**依赖自检**（PyQt5 / ebooklib / lxml / chardet / PIL / pypdf / docx），
缺依赖会给出补齐命令（可用 `-SkipNuitkaCheck` 跳过）。

> `sherpa-onnx` / `edge-tts` **不在自检名单里**：它们是可选依赖，
> 有就多两套音色，没有照常用系统语音，不会拦下打包。

> 若提示"解释器缺少运行依赖"，先执行 `.\install.ps1 -Python <该解释器路径>` 补齐依赖，
> 否则打包出的程序可能无法运行。
> 首次使用若提示"在此系统上禁止运行脚本"，先执行：
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

## ⚙️ 打包选项

### 打包模式

1. **单文件模式**
   - 生成单个 `.exe` 文件
   - 便于分发和使用
   - 文件体积稍大，启动时要先解包，首次启动慢
   - `-Mode onefile`；该模式不生成安装包

2. **独立目录模式（发布推荐）**
   - 生成包含依赖的文件夹（`NovelMaster.dist\`）
   - 启动快，不存在解包开销
   - `build.ps1` 默认就是这种模式，安装包也基于它

3. **调试模式**
   - 包含调试信息
   - 便于问题排查
   - 文件体积最大

### 优化级别

1. **默认优化**
   - 平衡编译时间和性能
   - 适合大多数情况

2. **最大优化**
   - 启用LTO（链接时优化）
   - 性能更好，编译时间更长

## 📁 输出文件

### 单文件模式

```text
dist/
└── NovelMaster.exe
```

### 独立目录模式

```text
dist/
└── NovelMaster.dist/
    ├── NovelMaster.exe
    ├── lang/           # 语言文件
    ├── icon/           # 图标文件
    └── *.dll           # 依赖库
```

`build.ps1` 输出的就是这个目录，**分发要带上整个 `NovelMaster.dist` 文件夹**。
安装包也是对整个目录打包，用户装完直接能用，不需要手动搬目录。

## 🔧 依赖管理

打包脚本会自动包含以下依赖：

- **PyQt5 / PyQtWebEngine**: GUI框架
- **PyQt5.QtTextToSpeech**: 朗读（TTS）功能，调用系统自带语音引擎（Windows 为 SAPI5），
  无需额外第三方包；同时必须带上 Qt 的 `texttospeech` 插件（见下）
- **pywin32**（可选）: 朗读的**增强**依赖，装了才会启用 `sapi-com` 后端（见下）
- **sherpa-onnx**（可选）: 朗读的**离线神经音色**依赖（Apache-2.0，轮子自带 onnxruntime），
  Piper / Kokoro 音色靠它合成；**语音模型不进包**，首次使用时程序内下载（见下）
- **edge-tts**（可选）: 朗读的**在线音色**依赖（MIT），提供微软 300+ 在线音色，需联网
- **winrt-runtime / winrt-Windows.***（可选）: v1.3.9 的**全局媒体键**依赖
  （pywinrt 投影，MIT），负责建起 SMTC 媒体会话并把媒体键回调转成朗读动作
- **ebooklib**: EPUB文件处理
- **lxml**: XML/HTML解析
- **chardet**: 编码检测
- **Pillow**: 图像处理
- **python-docx**: DOCX文档处理
- **pypdf**: PDF文档处理
- **qdarkstyle**: 界面主题
- **enm**: 项目自身的模块包

## 🎯 打包优化

### 包含的资源文件

- `lang/`: 多语言翻译文件
- `icon/`: 程序图标

### Qt 插件：朗读必须显式包含 `texttospeech`

Nuitka 的 `pyqt5` 插件只自动带上 `platforms` / `imageformats` / `iconengines` 这类
**常用**插件（见 `PySidePyQtPlugin._getSensiblePlugins()`），`texttospeech` 不在其中。
漏掉它的后果是：打包后的程序能正常启动、朗读条也能点，但**一点声音都没有**
（`QTextToSpeech.availableEngines()` 为空，界面会把朗读功能置灰）。

因此两个打包脚本都带了：

```text
--include-qt-plugins=texttospeech
```

它是**追加**语义（源码里 `sensible_qt_plugins.update(include_qt_plugins)`），
不会把默认插件挤掉，可以放心和现有参数共存。验证办法：装完之后直接跑发布版，
看"朗读"菜单里能不能列出语音。

对应的运行库有：

```text
dist/NovelMaster.dist/PyQt5/Qt5/bin/Qt5TextToSpeech.dll
dist/NovelMaster.dist/PyQt5/QtTextToSpeech.pyd
dist/NovelMaster.dist/PyQt5/Qt5/plugins/texttospeech/qtexttospeech_sapi.dll
```

（单文件模式会在解包目录里出现同样三个文件。）

### 可选增强：`sapi-com` 后端（pywin32 + OneCore 语音）

v1.3.7 起，朗读还能走 `sapi-com` 后端：用 `win32com.client` 驱动 `SAPI.SpVoice`，
好处是能看到系统 **OneCore 语音库**
（`HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens`）里的额外音色——
本机中文因此从 1 个（Huihui）变成 3 个（Huihui / Kangkang / Yaoyao）。
这部分**可选：打包环境里没装 `pywin32`，冻结版就自动回落 `QTextToSpeech`，不报错。**

想做带增强的发布版，就在打包用的解释器里装上：

```powershell
.\.venv\Scripts\python.exe -m pip install "pywin32>=306"
```

随后**无需改动打包脚本**：`enm/managers/tts.py` 里对 `win32com.client` 的导入写在
函数内部、又是真导入（不是字符串拼出来的），Nuitka 顺着导入链就会收进去。
万一冻结版里没收到（表现为“朗读语音”菜单里只有经典库音色），
可以手动补上这三个模块：

```text
--include-module=win32com.client
--include-module=win32com.client.dynamic
--include-module=pythoncom
```

> 注意 `win32com` 与 `pywin32` 的 DLL（`pywintypes3X.dll` / `pythoncom3X.dll`）
> 都在 site-packages 根目录与 `win32/`、`win32com/`、`pythonwin/` 下，
> Nuitka 会一并收集。验证方法：跑发布版，看“朗读” → “朗读语音”里有没有
> Kangkang / Yaoyao 这类 OneCore 音色。
>
> 另外，程序**判断** `sapi-com` 能不能用时只用 `find_spec` + 读注册表（约 1 ms），
> 不会在启动路径上加载 `win32com`（那要 ~100 ms），所以带着 `pywin32` 启动并不变慢。

### 可选增强：离线神经音色与在线音色（sherpa-onnx / edge-tts）

v1.3.8 起朗读多两套引擎，都是**可选依赖**：缺任何一个都不影响启动与系统语音朗读。

- **离线神经音色**（引擎名 `sherpa`）：`sherpa-onnx` + Piper / Kokoro 模型，
  不联网、免费、音质远好于系统语音；两套引擎里它优先（能离线出声）
- **在线音色**（引擎名 `edge`）：`edge-tts`，微软 Azure 的 300+ 音色，音质最好但需联网；
  音频只能拿到 MP3，因此用 `QtMultimedia` 播放（需要 `PyQt5.QtMultimedia`，已随 PyQt5 带上）

在打包用的解释器里装上：

```powershell
.\.venv\Scripts\python.exe -m pip install sherpa-onnx edge-tts
```

**`sherpa-onnx` 的原生 DLL 必须显式带进包**（Python 层靠导入链能自动收到，
但 `LoadLibrary` 加载的两支 DLL 不在依赖图里）：

```text
--include-package=sherpa_onnx
--include-package-data=sherpa_onnx
```

两个打包脚本都会**先探测打包解释器里有没有这些库**，装了才把上面的参数加上，
没装就跳过（可选依赖缺失不会让打包失败）；`edge-tts` 同理带 `--include-package=edge_tts`。
所以想打带神经音色的发布版，只要在打包用的解释器里 `pip install sherpa-onnx edge-tts`
再直接跑脚本即可，**不用改脚本**。

这样 `sherpa_onnx/lib/sherpa-onnx-c-api.dll` 与 `onnxruntime.dll`（共 ~21 MB）才会进包。
本机实测：`sherpa-onnx 1.13.8` + `sherpa-onnx-core 1.13.8`（16.1 MB，**py3-none 轮子，
任意 Python 版本通用**），**自带 onnxruntime，不用单独装**。

`edge-tts` 是纯 Python，`--include-module=edge_tts` 就够；它还依赖
`aiohttp` / `certifi` / `tabulate` / `typing-extensions`（Nuitka 顺导入链会收）。

> **模型不进安装包。** Piper 小模型 13 MB、Kokoro 140 MB 都是首次使用时
> 在「朗读 → 音色管理…」里下载的（带进度、支持续传与镜像），解压到
> `%APPDATA%\NovelMaster\tts_models\<模型 id>\`，随时可删。
> 因此：带神经音色的发布版，安装包基本不变大；不联网的用户看不到任何“缺文件”。
> pip 轮子里**不带** `espeak-ng-data`，所以中文 Piper 模型靠模型自带的 `lexicon` 注音，
> 不需要额外分发音素库。

验证：跑发布版 →「朗读」→「朗读语音」，顶部「朗读引擎」里应能看到
「离线神经音色」与「在线音色」；点「音色管理…」应能列出 4 个模型（含体积与状态）。

### 可选增强：多音字读音纠正（pypinyin）

v1.4.2 起朗读支持**多音字读音纠正**（「朗读/设置 → 读音纠正（多音字）…」），
把读错的字换成读音相同、且只有这一个读音的常用字（`银行 → 银航`）。三层：

| 层 | 依赖 | 默认 | 说明 |
| --- | --- | --- | --- |
| 用户词典 | 无 | 开 | 用户自己加的条目，存 `%APPDATA%\NovelMaster\pronunciation.json` |
| 内置规则 | 无 | 开 | 源码里手写的 56 条高频词（`tts_pron.py` 的 `BUILTIN_RULES`） |
| 自动推断 | **pypinyin** | **关** | 按上下文注音，实测容易把常用字改坏，所以默认关 |

**`pypinyin` 的数据文件必须显式带进包**（`--include-package` 只收 `.py`，
词表是包内 JSON，不收就会导致自动层静默失效）：

```text
--include-package=pypinyin
--include-package-data=pypinyin
```

两个打包脚本都会先探测打包解释器里有没有 `pypinyin`，装了才加这两个参数，
所以想打带自动层的发布版，先 `pip install pypinyin` 再跑脚本即可，**不用改脚本**。

本机实测（Nuitka 4.2.1 最小工程）：加 `--include-package-data=pypinyin` 后打包日志会
打印 `Included data file 'pypinyin\phrases_dict.json'` 与 `pinyin_dict.json`
（2.5 MB + 0.77 MB），产物里 `pypinyin/` 目录下两个 JSON 齐全，独立 exe 报
「词表条数 47111」。**前两层不依赖 pypinyin**，所以冻结版里缺了它只是自动层不可用
（对话框会把那个开关置灰），不影响启动、朗读、用户词典与内置规则。

### 可选增强：全局媒体键与系统媒体面板（winrt / SMTC）

v1.3.9 起，设置里多了一项**「媒体键控制朗读」**（默认关）。打开之后：键盘上的
媒体键（播放/暂停、上一句、下一句）直接控制朗读，任务栏弹出的媒体浮层（SMTC）
上显示**书名 + 当前章节**。它靠 **pywinrt 投影**实现，是一组包，全装齐：

```powershell
.\.venv\Scripts\python.exe -m pip install winrt-runtime ^
    winrt-Windows.Foundation winrt-Windows.Foundation.Collections ^
    winrt-Windows.Media winrt-Windows.Media.Core ^
    winrt-Windows.Media.Control winrt-Windows.Media.Playback ^
    winrt-Windows.Storage winrt-Windows.Storage.Streams
```

两个打包脚本会探测打包解释器里有没有 `winrt`，装了才把下面两行加上，没装就跳过：

```text
--include-package=winrt
--include-package-data=winrt
```

`enm/managers/media_keys.py` 是**懒导入**：只有开关打开且真要用时才 `import winrt`，
所以没装的时候启动速度、其余功能都不受影响，设置里的开关会自动置灰（附说明）。

> **为什么必须 `--include-package`？** pywinrt 的投影模块虽然不在启动导入链上，
> 但冻结版要建 SMTC 会话就必须同时具备 `winrt/_winrt.pyd` 与
> `winrt/windows/media/...` 这批子包；只靠隐式收集容易漏，因此显式带上更稳。
>
> **它会多出一条静音音频会话。** SMTC 会话需要有一个正在播放的媒体源撑着，
> 所以程序在启动媒体键时会循环播放一段**内部生成的 10 秒静音 WAV**
> （写在 `%TEMP%` 下的 `NovelMaster_silence.wav`）。因此音量合成器（音量图标
> 右键 →「打开音量合成器」）里会多出一条 NovelMaster 的条目，这是**预期现象**，
> 它不发声、也不占用声卡通道；关闭程序会一并退出。
>
> **媒体浮层上的应用名由开始菜单快捷方式决定。** Windows 把「AUMID → 应用名」
> 记在**带 `AppUserModelID` 属性的开始菜单快捷方式**里。实测只调
> `SetCurrentProcessExplicitAppUserModelID`、或者只往注册表
> `HKCU\Software\Classes\AppUserModelId\<AUMID>` 写 `DisplayName`，shell 的
> `AppsFolder` 都**查不到**这个 ID，浮层标题照旧写「未知应用」。程序本身会往
> `HKCU\Software\Classes\AppUserModelId\<AUMID>` 幂等写 `DisplayName`（跟随界面
> 语言，取 `app.name`）与 `IconUri`（`icon/icon.ico`），那份只影响提示类界面，
> 不需要管理员权限，写失败也不影响按键。
>
> `APP_USER_MODEL_ID` 定义在 `enm/managers/media_keys.py`，凡是要创建快捷方式的场合
> 都得带上同一个 ID（否则浮层标题会退化成「未知应用」）。

验证：设置里打开「媒体键控制朗读」→ 打开一本书并开始朗读：按键盘媒体键应能控制朗读，
任务栏媒体浮层应显示书名与章节。若是从带 `AppUserModelID` 的开始菜单快捷方式启动，
左上角的应用名会显示 NovelMaster；直接跑 `dist` 里的绿色版没有快捷方式，
浮层仍会显示「未知应用」，媒体键本身照常可用。

### 排除的模块

- 测试文件 (`*.tests`, `*.test`)
- 不必要的开发工具

### Windows特定优化

- 禁用控制台窗口
- UAC管理员权限
- 版本信息和图标

## 🐛 常见问题

### 0. 脚本好像没用上我本机装的那个 Python

先看一眼它到底找到了哪些解释器：

```powershell
.\build.ps1 -Python 3.100 -DryRun -NoPause -NonInteractive   # 故意给个不存在的版本号
```

脚本会打印**本机解释器扫描结果**（版本号 + 是否有 Nuitka + 路径），
再用 `-Python <版本号|命令名|路径>` 指定想要的那个，例如：

```powershell
.\build.ps1 -Python 3.13.6
```

> 注意：脚本会跳过 `Microsoft\WindowsApps\python.exe`——那是应用商店别名，不是真解释器。

### 1. Nuitka 安装失败

```bash
# 手动安装（自动选择镜像）
.\install.ps1 -WithNuitka

# 或指定镜像安装
pip install -i https://mirrors.aliyun.com/pypi/simple/ --upgrade nuitka

# 或让打包脚本自动回退到本机已装 Nuitka 的环境
.\build.ps1
```

> 注意：清华镜像偶发对部分 wheel 返回 403，脚本会按测速顺序自动改用其它镜像；
> 也可用 `-Mirror aliyun` 把阿里云提到最优先（其余镜像仍自动兜底）。

### 2. 打包时间过长

- 选择"默认优化"而非"最大优化"
- 关闭其他占用CPU的程序
- 确保有足够的磁盘空间

### 3. 生成的exe文件过大

- 这是正常现象，Nuitka会包含Python解释器和所有依赖
- 单文件模式会比独立目录模式稍大
- 可以使用UPX进一步压缩（需要额外配置）

### 4. 运行时缺少依赖

- 确保使用`--standalone`选项
- 检查是否包含了所有必要的包
- 使用`--include-package`手动包含缺失的包

### 5. 打包后朗读没声音

- 确认打包参数里有 `--include-qt-plugins=texttospeech`（两个脚本都已默认带上）；
- 确认目标机器上装了至少一个语音（Windows："设置" → "时间和语言" → "语音"）；
- 拿开发环境对比一下：`python -c "from PyQt5.QtTextToSpeech import QTextToSpeech; print(QTextToSpeech.availableEngines())"`
  应该输出 `['sapi']`；打包版输出为空就是插件没进去。

### 6. 打包后音色比开发环境少（没有 Kangkang / Yaoyao）

说明冻结版在跑 `QTextToSpeech` 那条回落路线，也就是 `sapi-com` 后端没起来。
两种原因：

- **打包环境里没装 `pywin32`**：加上再重打包（见上文“可选增强：`sapi-com` 后端”）；
- **装了但 Nuitka 没收到**：按那里的说明补 `--include-module` 参数。

### 7. 打包后没有「离线神经音色」/「在线音色」

- 打包解释器里没装 `sherpa-onnx` / `edge-tts`，或装了但**原生 DLL 没进包**
  （表现为菜单里没这两项，或选了之后就提示音色不可用）；
- 补上 `--include-package=sherpa-onnx` 与 `--include-package-data=sherpa-onnx`
  （两个打包脚本在检测到该库时会自动加上），再确认 `sherpa_onnx/lib/` 下有
  `sherpa-onnx-c-api.dll`、`onnxruntime.dll`；
- 对照开发环境：`python -c "from enm.managers.tts import available_engines; print(available_engines())"`
  （开发环境应能出现 `sherpa` 与 `edge`）。

### 8. 选了神经音色，提示「这个音色的模型还没下载」

这是**正常**行为：模型按需下载，不进安装包。

- 请到「朗读 →「朗读语音」→「音色管理…」」里下载（Piper 小模型 13 MB，Kokoro 140 MB）；
- 下载中关掉窗口不会中断（下载继续，进度也同步在朗读条上）；
- 想清空间就直接删 `%APPDATA%\NovelMaster\tts_models`（或在音色管理里点「删除」）；
- 断网 / 公司网络拦 GitHub 时会给镜像重试的提示，失败可重试。

这两种情况都只是“音色少一些”，不影响朗读本身；开发环境下
`python -c "from enm.managers.tts import available_engines; print(available_engines())"`
应该把 `sapi-com` 排在第一个。

### 9. 设置里「媒体键控制朗读」是灰的，或按了媒体键没反应

- **灰的**：打包解释器里没装 `winrt` 投影包（或装了但没带进包）。对照开发环境：
  `python -c "from enm.managers.media_keys import media_keys_importable; print(media_keys_importable())"`
  应为 `True`；打包版可在安装日志里搜“全局媒体键”一行，看打包时带没带；
- **能勾但不响应**：媒体键靠 SMTC 会话回调，分发是**全局**的，不要求窗口在前台，
  但需要进程里有一个真实顶层窗口（最小化到托盘也可以）。若完全不理，
  检查是不是被别的播放器（浏览器 / 音乐软件）抢了会话；
- **任务栏浮层显示的是「未知」**：说明会话建起来了但没写元数据，确认已打开书籍
  （没开书时浮层标题为空是正常的）。

## 🔄 更新打包

### 代码更新后（发布一版）

```powershell
# 1. 清理旧文件
.\clean.ps1

# 2. 重新打包（目录版）
.\build.ps1
```

### 依赖更新后

```powershell
# 1. 更新依赖（自动选择镜像源；-Recreate 可重建环境）
.\install.ps1

# 2. 清理并重新打包
.\clean.ps1
.\build.ps1
```

> 发布前的版本号只需改一处：`enm\constants.py` 里的 `VERSION`，程序文件版本信息会跟着变。

## 📊 性能建议

### 编译优化

- 使用SSE2指令集：`--enable-sse2`
- 启用多线程编译：`--jobs=4`（根据CPU核心数调整）

### 体积优化

- 使用UPX压缩：`--plugin-enable=upx`
- 排除不必要的模块
- 移除调试符号：`--no-deployment-flag=no-debug`

## 🔒 安全考虑

### 代码保护

- Nuitka会将Python代码编译为机器码
- 提供一定程度的代码保护
- 但无法完全防止逆向工程

### 数字签名

- 建议对发布的exe文件进行数字签名
- 提高用户信任度
- 避免安全软件误报

## 📋 发布检查清单

- [ ] `enm\constants.py` 里的 `VERSION` 已改成新版本号
- [ ] 已重新打包（`.\clean.ps1` + `.\build.ps1`）
- [ ] 测试所有功能正常
- [ ] 检查文件体积是否合理
- [ ] 验证图标和版本信息
- [ ] 在不同Windows版本测试
- [ ] 使用杀毒软件扫描
- [ ] 准备发布说明文档

## 🆘 获取帮助

如果遇到打包问题：

1. 查看Nuitka文档：<https://nuitka.net/doc/user-manual.html>
2. 检查错误日志
3. 尝试简化配置
4. 在GitHub提交Issue

## 📄 许可证

打包脚本遵循MIT许可证，可以自由使用和修改。
