@echo off
chcp 65001 >nul

setlocal enabledelayedexpansion

echo ========================================
echo NovelMaster - 高级打包脚本
echo ========================================
echo.

REM 基本配置
set "APP_NAME=NovelMaster"
set "MAIN_FILE=NovelMaster.py"
set "ICON_FILE=icon\icon.ico"
set "VERSION=1.0.0"
set "COMPANY=Aaze_wu"
set "DESCRIPTION=现代化小说阅读器"

REM 检查Nuitka安装
call :check_nuitka
if !errorlevel! neq 0 exit /b 1

REM 选择打包模式
echo 请选择打包模式:
echo 1. 单文件模式 (推荐)
echo 2. 独立目录模式
echo 3. 调试模式
echo.
set /p "mode=请选择 (1/2/3, 默认1): "
if "!mode!"=="" set "mode=1"
if "!mode!"=="1" set "MODE=onefile"
if "!mode!"=="2" set "MODE=standalone"
if "!mode!"=="3" set "MODE=debug"

REM 选择优化级别
echo.
echo 请选择优化级别:
echo 1. 默认优化
echo 2. 最大优化 (可能增加编译时间)
echo.
set /p "opt=请选择 (1/2, 默认1): "
if "!opt!"=="" set "opt=1"
if "!opt!"=="1" set "OPT_LEVEL=default"
if "!opt!"=="2" set "OPT_LEVEL=full"

REM 设置输出目录
set "OUTPUT_DIR=dist"
if not exist "!OUTPUT_DIR!" mkdir "!OUTPUT_DIR!"

REM 构建Nuitka命令
set "NUITKA_CMD=python -m nuitka"

REM 基本选项
set "NUITKA_CMD=!NUITKA_CMD! --standalone"
if "!MODE!"=="onefile" set "NUITKA_CMD=!NUITKA_CMD! --onefile"
if "!MODE!"=="debug" set "NUITKA_CMD=!NUITKA_CMD! --debug"

REM 优化选项
if "!OPT_LEVEL!"=="full" set "NUITKA_CMD=!NUITKA_CMD! --lto=yes"

REM Windows特定选项
set "NUITKA_CMD=!NUITKA_CMD! --windows-console-mode=disable"
set "NUITKA_CMD=!NUITKA_CMD! --windows-uac-admin"

REM 图标和版本信息
if exist "!ICON_FILE!" (
    set "NUITKA_CMD=!NUITKA_CMD! --windows-icon-from-ico=!ICON_FILE!"
)

set "NUITKA_CMD=!NUITKA_CMD! --product-name=!APP_NAME!"
set "NUITKA_CMD=!NUITKA_CMD! --file-version=!VERSION!"
set "NUITKA_CMD=!NUITKA_CMD! --product-version=!VERSION!"
set "NUITKA_CMD=!NUITKA_CMD! --company-name=!COMPANY!"
set "NUITKA_CMD=!NUITKA_CMD! --file-description=!DESCRIPTION!"

REM 输出目录
set "NUITKA_CMD=!NUITKA_CMD! --output-dir=!OUTPUT_DIR!"

REM 插件和包含选项
set "NUITKA_CMD=!NUITKA_CMD! --enable-plugin=pyqt5"
set "NUITKA_CMD=!NUITKA_CMD! --include-package=enm"
set "NUITKA_CMD=!NUITKA_CMD! --include-package=ebooklib"
set "NUITKA_CMD=!NUITKA_CMD! --include-package=chardet"
set "NUITKA_CMD=!NUITKA_CMD! --include-package=PIL"
set "NUITKA_CMD=!NUITKA_CMD! --include-package=pypdf"
set "NUITKA_CMD=!NUITKA_CMD! --include-package=docx"

REM 包含数据文件
set "NUITKA_CMD=!NUITKA_CMD! --include-data-dir=lang=lang"
set "NUITKA_CMD=!NUITKA_CMD! --include-data-dir=icon=icon"

REM 排除不必要的模块
set "NUITKA_CMD=!NUITKA_CMD! --nofollow-import-to=*.tests"
set "NUITKA_CMD=!NUITKA_CMD! --nofollow-import-to=*.test"

REM 清理选项
set "NUITKA_CMD=!NUITKA_CMD! --remove-output"

REM 显示构建信息
echo.
echo ========================================
echo 构建配置:
echo   模式: !MODE!
echo   优化: !OPT_LEVEL!
echo   输出: !OUTPUT_DIR!\
echo ========================================
echo.

REM 确认构建
echo 即将开始构建，这可能需要几分钟时间...
set /p "confirm=是否继续? (y/n, 默认y): "
if "!confirm!"=="" set "confirm=y"
if /i not "!confirm!"=="y" (
    echo 构建已取消
    pause
    exit /b 0
)

REM 开始构建
echo [信息] 开始构建...
echo 命令: !NUITKA_CMD! !MAIN_FILE!
echo.

!NUITKA_CMD! "!MAIN_FILE!"

if !errorlevel! neq 0 (
    echo [错误] 构建失败
    pause
    exit /b 1
)

REM 构建成功
echo.
echo ========================================
echo [成功] 构建完成!
echo ========================================
echo.

REM 显示输出文件信息
if "!MODE!"=="onefile" (
    echo 输出文件: !OUTPUT_DIR!\!APP_NAME!.exe
    echo 文件大小: 
    for /f %%i in ('dir /-c "!OUTPUT_DIR!\!APP_NAME!.exe" ^| find "!APP_NAME!.exe"') do echo        %%i
) else (
    echo 输出目录: !OUTPUT_DIR!\!APP_NAME!\
)

echo.
echo 使用说明:
echo 1. 单文件模式: 直接运行 !APP_NAME!.exe
echo 2. 独立目录模式: 运行 !APP_NAME!\!APP_NAME!.exe
echo 3. 首次运行可能需要几秒钟初始化
echo 4. 程序数据保存在用户AppData目录
echo.

REM 询问是否打开输出目录
set /p "open_dir=是否打开输出目录? (y/n): "
if /i "!open_dir!"=="y" (
    start "" "!OUTPUT_DIR!"
)

pause
exit /b 0

REM 函数: 检查Nuitka安装
:check_nuitka
python -m nuitka --version >nul 2>&1
if !errorlevel! equ 0 (
    echo [成功] Nuitka 已安装
    exit /b 0
)

echo [信息] Nuitka 未安装
echo.
echo 正在使用镜像源安装 Nuitka...
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
python -m pip install --disable-pip-version-check --timeout 30 --retries 3 -i !PIP_INDEX! --upgrade nuitka
if !errorlevel! neq 0 (
    echo [警告] 镜像源安装失败，尝试默认 PyPI ...
    python -m pip install --disable-pip-version-check --upgrade nuitka
)
python -m nuitka --version >nul 2>&1
if !errorlevel! neq 0 (
    echo [错误] Nuitka 安装失败
    echo.
    echo 请手动安装: pip install -i !PIP_INDEX! nuitka
    exit /b 1
)

echo [成功] Nuitka 安装完成
exit /b 0