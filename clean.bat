@echo off
chcp 65001 >nul

echo ========================================
echo NovelMaster - 清理脚本
echo ========================================
echo.

REM 要清理的目录和文件
set "CLEAN_DIRS=dist build NovelMaster.dist NovelMaster.build __pycache__"
set "CLEAN_FILES=*.spec"

REM 显示要清理的内容
echo 将要清理以下内容:
for %%d in (%CLEAN_DIRS%) do (
    if exist "%%d" (
        echo   - %%d
    )
)
for %%f in (%CLEAN_FILES%) do (
    if exist "%%f" (
        echo   - %%f
    )
)

echo.
set /p "confirm=确认清理? (y/n): "
if /i not "%confirm%"=="y" (
    echo 清理已取消
    pause
    exit /b 0
)

REM 开始清理
echo.
echo [信息] 开始清理...

REM 删除目录
for %%d in (%CLEAN_DIRS%) do (
    if exist "%%d" (
        echo 删除目录: %%d
        rmdir /s /q "%%d" 2>nul
    )
)

REM 删除文件
for %%f in (%CLEAN_FILES%) do (
    if exist "%%f" (
        echo 删除文件: %%f
        del /q "%%f" 2>nul
    )
)

echo.
echo [成功] 清理完成!
echo.

REM 显示剩余空间（可选）
echo 当前目录剩余空间:
dir /-c | find "可用字节"

echo.
pause