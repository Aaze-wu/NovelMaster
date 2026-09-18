@echo off
chcp 65001 >nul
setlocal

REM NovelMaster 基本打包入口（批处理包装）
REM 真正的打包逻辑在 build.ps1：它会自动扫描本机的 Python 解释器
REM （py 启动器 / 注册表 / 常见安装目录 / PATH），并优先使用项目 .venv，
REM 找不到带 Nuitka 的解释器时会打印扫描报告。
REM
REM 用法示例:
REM   build.bat
REM   build.bat -Python 3.13
REM   build.bat -Python 3.13.6 -DryRun -NoPause
REM   build.bat -OpenOutput

set "PS1=%~dp0build.ps1"
if not exist "%PS1%" (
    echo [错误] 未找到 build.ps1: %PS1%
    pause
    exit /b 1
)

where powershell >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 powershell，请直接运行 build.ps1
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
exit /b %errorlevel%
