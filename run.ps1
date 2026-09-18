#Requires -Version 5.1
<#
.SYNOPSIS
    NovelMaster 启动脚本（PowerShell 版，对应 run.bat）。

.DESCRIPTION
    使用 Python 启动 NovelMaster 图形界面。

.PARAMETER Python
    指定 Python 解释器的命令或完整路径，默认为 PATH 中的 python。

.PARAMETER UseVenv
    优先使用项目目录下的 .venv\Scripts\python.exe。

.PARAMETER DebugMode
    以调试模式启动（向程序传入 --debug，等价于 run_debug.ps1）。
    注意：PowerShell 自带 -Debug 公共参数，因此这里改用 -DebugMode。

.PARAMETER DryRun
    只显示将要执行的命令，不实际启动程序。

.PARAMETER NoPause
    退出后不等待按键，适合脚本化 / 自动化调用。

.EXAMPLE
    .\run.ps1

.EXAMPLE
    .\run.ps1 -UseVenv

.EXAMPLE
    .\run.ps1 -DebugMode -NoPause

.NOTES
    若提示"无法加载文件，因为在此系统上禁止运行脚本"，可执行：
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    或使用：
        powershell -ExecutionPolicy Bypass -File .\run.ps1
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$UseVenv,
    [switch]$DebugMode,
    [switch]$DryRun,
    [switch]$NoPause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 让中文在旧版控制台（Windows PowerShell 5.1）下也能正常显示
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ProjectRoot = $PSScriptRoot
$MainFileName = 'NovelMaster.py'
$MainFile = Join-Path $ProjectRoot $MainFileName

function Write-Info { param([string]$Message) Write-Host "[信息] $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "[成功] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[警告] $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "[错误] $Message" -ForegroundColor Red }

function Wait-Exit {
    if ($NoPause) { return }
    [void](Read-Host '按回车键关闭此窗口')
}

function Resolve-Python {
    if ($UseVenv) {
        $venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $venvPython) { return $venvPython }
        Write-Warn "未找到虚拟环境解释器: $venvPython，改用系统 Python"
    }
    foreach ($name in @($Python, 'python', 'py')) {
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { return $command.Source }
    }
    return $null
}

Write-Host '========================================' -ForegroundColor DarkGray
Write-Host 'NovelMaster - 启动脚本 (PowerShell)' -ForegroundColor DarkGray
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''

if (-not (Test-Path -LiteralPath $MainFile)) {
    Write-Err "找不到入口文件: $MainFile"
    Wait-Exit
    exit 1
}

$pythonExe = Resolve-Python
if (-not $pythonExe) {
    Write-Err '未找到 Python 解释器，请安装 Python 3.8+ 并加入 PATH。'
    Wait-Exit
    exit 1
}

$appArgs = @($MainFile)
if ($DebugMode) { $appArgs += '--debug' }

Write-Info "项目目录: $ProjectRoot"
Write-Info "解释器  : $pythonExe"
Write-Info "启动参数: $($appArgs -join ' ')"
Write-Host ''

if ($DryRun) {
    Write-Warn 'DryRun 模式：仅显示命令，未实际启动程序'
    exit 0
}

Push-Location -LiteralPath $ProjectRoot
try {
    & $pythonExe @appArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($null -eq $exitCode) { $exitCode = 0 }

Write-Host ''
if ($exitCode -ne 0) {
    Write-Err "程序已退出，返回代码: $exitCode"
}
else {
    Write-Ok '程序已正常退出'
}
Write-Host ''

Wait-Exit
exit $exitCode
