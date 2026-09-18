# NovelMaster 打包指南

本文档介绍如何使用 Nuitka 将 NovelMaster 打包成独立的可执行文件。

## 📦 打包脚本说明

每个 `.bat` 脚本都有等价的 PowerShell 版本（功能与参数一致，推荐使用）。
`.bat` 只是轻量包装，会把参数原样转发给同名的 `.ps1`，因此两者行为完全一致。

| 用途 | CMD 版本 | PowerShell 版本 |
| --- | --- | --- |
| 环境安装（建 venv + 装依赖） | `install.bat` | `install.ps1` |
| 基本打包 | `build.bat` | `build.ps1` |
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
- 单文件模式，生成独立的 `.exe` 文件
- 自动检测 Nuitka，缺失时用镜像源自动安装
- **自动发现本机所有 Python 解释器**（py 启动器 / 注册表 / 常见安装目录 / PATH），
  默认优先使用项目 `.venv`，其次才是 PATH 与本机已安装的 Python
- **当前解释器没有 Nuitka 时，自动回退到本机环境中已安装 Nuitka 的解释器**

### 高级打包脚本 (`build-advanced.ps1` / `build-advanced.bat`)

- 提供多种打包选项
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
.\build-advanced.ps1     # 或双击 build-advanced.bat
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

> 若提示"解释器缺少运行依赖"，先执行 `.\install.ps1 -Python <该解释器路径>` 补齐依赖，
> 否则打包出的程序可能无法运行。
> 首次使用若提示"在此系统上禁止运行脚本"，先执行：
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

## ⚙️ 打包选项

### 打包模式

1. **单文件模式 (推荐)**
   - 生成单个 `.exe` 文件
   - 便于分发和使用
   - 文件体积稍大

2. **独立目录模式**
   - 生成包含依赖的文件夹
   - 便于调试和修改
   - 文件结构清晰

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
└── NovelMaster/
    ├── NovelMaster.exe
    ├── lang/           # 语言文件
    ├── icon/           # 图标文件
    └── *.dll           # 依赖库
```

## 🔧 依赖管理

打包脚本会自动包含以下依赖：

- **PyQt5 / PyQtWebEngine**: GUI框架
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

## 🔄 更新打包

### 代码更新后

```powershell
# 1. 清理旧文件
.\clean.ps1

# 2. 重新打包
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
