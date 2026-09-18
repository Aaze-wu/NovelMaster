#Requires -Version 5.1
<#
.SYNOPSIS
    NovelMaster 清理脚本（PowerShell 版，对应 clean.bat）。

.DESCRIPTION
    清理打包产物、Nuitka 中间目录、Python 缓存与 *.spec 文件。
    默认会先列出待清理内容并请求确认；支持 -WhatIf 预演。

.PARAMETER Force
    跳过确认提示，直接清理。

.PARAMETER IncludeLogs
    一并清理 logs 目录（程序运行日志），默认不清理。

.PARAMETER NoPause
    结束后不等待按键。

.EXAMPLE
    .\clean.ps1 -WhatIf

.EXAMPLE
    .\clean.ps1

.EXAMPLE
    .\clean.ps1 -Force -NoPause

.NOTES
    若提示"在此系统上禁止运行脚本"，可执行：
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$Force,
    [switch]$IncludeLogs,
    [switch]$NoPause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ProjectRoot = $PSScriptRoot
$AppName = 'NovelMaster'
$PackageDir = Join-Path $ProjectRoot 'enm'

function Write-Info { param([string]$Message) Write-Host "[信息] $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "[成功] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[警告] $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "[错误] $Message" -ForegroundColor Red }

function Wait-Exit {
    if ($NoPause) { return }
    [void](Read-Host '按回车键关闭此窗口')
}

Write-Host '========================================' -ForegroundColor DarkGray
Write-Host 'NovelMaster - 清理脚本 (PowerShell)' -ForegroundColor DarkGray
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''

# ---------------- 收集待清理目标 ----------------

$candidateDirs = @(
    (Join-Path $ProjectRoot 'dist')
    (Join-Path $ProjectRoot 'build')
    (Join-Path $ProjectRoot "$AppName.dist")
    (Join-Path $ProjectRoot "$AppName.build")
    (Join-Path $ProjectRoot "$AppName.onefile-build")
    (Join-Path $ProjectRoot '__pycache__')
)

if ($IncludeLogs) {
    $candidateDirs += (Join-Path $ProjectRoot 'logs')
}

# 递归查找 enm 包内的 __pycache__（不触碰 .venv）
if (Test-Path -LiteralPath $PackageDir) {
    $nestedCaches = Get-ChildItem -LiteralPath $PackageDir -Recurse -Directory -Filter '__pycache__' -Force -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
    if ($nestedCaches) { $candidateDirs += $nestedCaches }
}

$targetDirs = @($candidateDirs |
    Where-Object { Test-Path -LiteralPath $_ } |
    Sort-Object -Unique)

$targetFiles = @(Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.spec' -File -Force -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName)

if ($targetDirs.Count -eq 0 -and $targetFiles.Count -eq 0) {
    Write-Info '没有需要清理的内容，目录已是干净状态。'
    Write-Host ''
    Wait-Exit
    exit 0
}

Write-Host '将要清理以下内容:'
foreach ($dir in $targetDirs) {
    Write-Host "  - $dir" -ForegroundColor DarkGray
}
foreach ($file in $targetFiles) {
    Write-Host "  - $file" -ForegroundColor DarkGray
}
Write-Host ''

# ---------------- 确认 ----------------

if (-not $Force -and -not $WhatIfPreference) {
    $confirm = Read-Host '确认清理? (y/n)'
    if ($confirm -notmatch '^[Yy]') {
        Write-Warn '清理已取消'
        Write-Host ''
        Wait-Exit
        exit 0
    }
}

# ---------------- 执行清理 ----------------

if ($WhatIfPreference) {
    Write-Warn '预演模式 (-WhatIf)：不会实际删除任何内容'
    Write-Host ''
    foreach ($dir in $targetDirs) { $null = $PSCmdlet.ShouldProcess($dir, '删除目录') }
    foreach ($file in $targetFiles) { $null = $PSCmdlet.ShouldProcess($file, '删除文件') }
    Wait-Exit
    exit 0
}

Write-Host ''
Write-Info '开始清理...'

$removedDirs = 0
$removedFiles = 0
$failed = 0

foreach ($dir in $targetDirs) {
    if (-not $PSCmdlet.ShouldProcess($dir, '删除目录')) { continue }
    try {
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction Stop
        Write-Host "  已删除目录: $dir"
        $removedDirs++
    }
    catch {
        Write-Err "删除目录失败: $dir -> $($_.Exception.Message)"
        $failed++
    }
}

foreach ($file in $targetFiles) {
    if (-not $PSCmdlet.ShouldProcess($file, '删除文件')) { continue }
    try {
        Remove-Item -LiteralPath $file -Force -ErrorAction Stop
        Write-Host "  已删除文件: $file"
        $removedFiles++
    }
    catch {
        Write-Err "删除文件失败: $file -> $($_.Exception.Message)"
        $failed++
    }
}

Write-Host ''
if ($failed -gt 0) {
    Write-Warn "清理完成，但有 $failed 项失败（可能被占用，请关闭相关程序后重试）"
}
else {
    Write-Ok "清理完成! 删除目录 $removedDirs 个、文件 $removedFiles 个"
}
Write-Host ''

# ---------------- 剩余空间 ----------------

$qualifier = Split-Path -Qualifier $ProjectRoot
$driveName = $qualifier.TrimEnd(':')
$drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
if ($drive -and $drive.Free) {
    Write-Host ('{0} 剩余空间: {1:N2} GB' -f $qualifier, ($drive.Free / 1GB))
    Write-Host ''
}

Wait-Exit
exit 0
