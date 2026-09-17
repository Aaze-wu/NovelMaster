@echo off
chcp 65001 >nul
setlocal

REM ========================================
REM EpubNovelMaster - 环境安装脚本
REM   - 虚拟环境不存在时自动创建
REM   - 自动选择合适的 pip 镜像源
REM   - 安装 requirements.txt 中的依赖
REM 参数会原样转发给 install.ps1，例如:
REM   install.bat -Recreate -WithNuitka
REM   install.bat -Mirror aliyun
REM ========================================

set "PS_SCRIPT=%~dp0install.ps1"

if not exist "%PS_SCRIPT%" (
    echo [错误] 未找到 install.ps1 : %PS_SCRIPT%
    pause
    exit /b 1
)

where powershell >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 powershell，请使用 PowerShell 5.1 及以上版本
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
set "EXIT_CODE=%errorlevel%"

if %EXIT_CODE% neq 0 (
    echo.
    echo [错误] 环境安装失败，退出码: %EXIT_CODE%
    pause
)

exit /b %EXIT_CODE%
