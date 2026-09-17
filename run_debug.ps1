#Requires -Version 5.1
<#
.SYNOPSIS
    EpubNovelMaster 调试启动脚本（PowerShell 版，对应 run_debug.bat）。

.DESCRIPTION
    等价于 .\run.ps1 -DebugMode，会向程序传入 --debug 参数以开启调试日志。
    本脚本只负责转发参数，实际逻辑统一由 run.ps1 实现。

.PARAMETER Python
    指定 Python 解释器的命令或完整路径，默认为 PATH 中的 python。

.PARAMETER UseVenv
    优先使用项目目录下的 .venv\Scripts\python.exe。

.PARAMETER DryRun
    只显示将要执行的命令，不实际启动程序。

.PARAMETER NoPause
    退出后不等待按键，适合脚本化 / 自动化调用。

.EXAMPLE
    .\run_debug.ps1

.EXAMPLE
    .\run_debug.ps1 -NoPause
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$UseVenv,
    [switch]$DryRun,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$runScript = Join-Path $PSScriptRoot 'run.ps1'
if (-not (Test-Path -LiteralPath $runScript)) {
    Write-Host "[错误] 找不到 run.ps1: $runScript" -ForegroundColor Red
    if (-not $NoPause) { [void](Read-Host '按回车键关闭此窗口') }
    exit 1
}

& $runScript -Python $Python -UseVenv:$UseVenv -DebugMode -DryRun:$DryRun -NoPause:$NoPause

$exitCode = $LASTEXITCODE
if ($null -eq $exitCode) { $exitCode = 0 }
exit $exitCode
