@echo off
chcp 65001 >nul

echo ========================================
echo EpubNovelMaster - Nuitka 打包脚本
echo ========================================
echo.

REM 检查是否安装了Nuitka
python -m nuitka --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] Nuitka 未安装，正在使用镜像源安装...
    set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
    python -m pip install --disable-pip-version-check --timeout 30 --retries 3 -i %PIP_INDEX% --upgrade nuitka
    if %errorlevel% neq 0 (
        echo [警告] 镜像源安装失败，尝试默认 PyPI ...
        python -m pip install --disable-pip-version-check --upgrade nuitka
    )
    python -m nuitka --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] Nuitka 安装失败，请手动安装: pip install -i %PIP_INDEX% nuitka
        pause
        exit /b 1
    )
    echo [成功] Nuitka 安装完成
)

echo [信息] 开始打包 EpubNovelMaster...
echo.

REM 设置打包参数
set "APP_NAME=EpubNovelMaster"
set "MAIN_FILE=EpubNovelMaster.py"
set "OUTPUT_DIR=dist"
set "ICON_FILE=icon\icon.ico"

REM 检查主文件是否存在
if not exist "%MAIN_FILE%" (
    echo [错误] 主文件 %MAIN_FILE% 不存在
    pause
    exit /b 1
)

REM 检查图标文件是否存在
if not exist "%ICON_FILE%" (
    echo [警告] 图标文件 %ICON_FILE% 不存在，将使用默认图标
    set "ICON_OPTION="
) else (
    set "ICON_OPTION=--windows-icon-from-ico=%ICON_FILE%"
)

REM 创建输出目录
if not exist "%OUTPUT_DIR%" (
    mkdir "%OUTPUT_DIR%"
)

REM Nuitka 打包命令
echo [信息] 开始编译...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-console-mode=disable ^
    --output-dir=%OUTPUT_DIR% ^
    %ICON_OPTION% ^
    --product-name="%APP_NAME%" ^
    --file-version=1.0.0 ^
    --product-version=1.0.0 ^
    --company-name="Aaze_wu" ^
    --file-description="EpubNovelMaster - 现代化小说阅读器" ^
    --nofollow-import-to=*.tests ^
    --enable-plugin=pyqt5 ^
    --include-package=enm ^
    --include-package=ebooklib ^
    --include-package=chardet ^
    --include-package=PIL ^
    --include-package=pypdf ^
    --include-package=docx ^
    --include-data-dir=lang=lang ^
    --include-data-dir=icon=icon ^
    --windows-uac-admin ^
    --remove-output ^
    %MAIN_FILE%

if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo [成功] 打包完成！
echo.
echo 输出文件: %OUTPUT_DIR%\%APP_NAME%.exe
echo.
echo 注意事项:
echo 1. 首次运行可能需要几秒钟初始化
echo 2. 确保目标计算机安装了必要的运行库
echo 3. 程序数据将保存在用户AppData目录
echo.

REM 询问是否打开输出目录
set /p "open_dir=是否打开输出目录? (y/n): "
if /i "%open_dir%"=="y" (
    start "" "%OUTPUT_DIR%"
)

pause