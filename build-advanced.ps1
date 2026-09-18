#Requires -Version 5.1
<#
.SYNOPSIS
    NovelMaster 高级打包脚本（PowerShell 版，对应 build-advanced.bat）。

.DESCRIPTION
    提供更多打包选项：打包模式（单文件 / 独立目录 / 调试）与优化级别
    （默认 / LTO 最大优化）。未通过参数指定时会交互式询问。

.PARAMETER Mode
    打包模式：onefile（单文件）、standalone（独立目录）、debug（调试）。

.PARAMETER Optimize
    优化级别：default（默认）、full（启用 --lto=yes）。

.PARAMETER Python
    指定 Python 解释器的命令或完整路径，默认为 PATH 中的 python。

.PARAMETER UseVenv
    优先使用项目目录下的 .venv\Scripts\python.exe。

.PARAMETER OutputDir
    输出目录名（相对项目根目录），默认为 dist。

.PARAMETER NuitkaPython
    指定用于打包的 Python 解释器的命令或路径。
    不指定时自动选择：优先使用当前解释器；若当前解释器没有 Nuitka，
    则自动改用本机环境中已安装 Nuitka 的解释器。

.PARAMETER NoFallback
    禁用"自动回退到本机环境 Nuitka"的行为。
    指定后若当前解释器没有 Nuitka，则直接尝试为其安装。

.PARAMETER Mirror
    pip 镜像源。可选 auto（默认，自动测速选择）、tuna、aliyun、
    ustc、tencent、pypi，也可直接传入完整 URL。
    也可用环境变量 ENM_PIP_INDEX 覆盖。

.PARAMETER SkipNuitkaCheck
    跳过 Nuitka 检测与自动安装，直接使用当前解释器。

.PARAMETER OpenOutput
    构建完成后直接打开输出目录，不再询问。

.PARAMETER NonInteractive
    非交互模式：使用默认选项且不询问任何问题。

.PARAMETER DryRun
    只显示将要执行的构建命令，不实际编译。

.PARAMETER NoPause
    结束后不等待按键。

.EXAMPLE
    .\build-advanced.ps1

.EXAMPLE
    .\build-advanced.ps1 -Mode standalone -Optimize full

.EXAMPLE
    .\build-advanced.ps1 -Mode onefile -NonInteractive -NoPause

.NOTES
    若提示"在此系统上禁止运行脚本"，可执行：
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
[CmdletBinding()]
param(
    [ValidateSet('onefile', 'standalone', 'debug')]
    [string]$Mode,

    [ValidateSet('default', 'full')]
    [string]$Optimize,

    [string]$Python = 'python',
    [switch]$UseVenv,
    [string]$NuitkaPython,
    [string]$OutputDir = 'dist',
    [string]$Mirror = 'auto',
    [switch]$NoFallback,
    [switch]$SkipNuitkaCheck,
    [switch]$OpenOutput,
    [switch]$NonInteractive,
    [switch]$DryRun,
    [switch]$NoPause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ProjectRoot = $PSScriptRoot
$AppName = 'NovelMaster'
$MainFileName = "$AppName.py"
$MainFile = Join-Path $ProjectRoot $MainFileName
$IconFile = Join-Path $ProjectRoot 'icon\icon.ico'
$OutputDirPath = Join-Path $ProjectRoot $OutputDir
$DefaultDescription = 'NovelMaster - 现代化小说阅读器'

function Write-Info { param([string]$Message) Write-Host "[信息] $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "[成功] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[警告] $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "[错误] $Message" -ForegroundColor Red }

function Wait-Exit {
    if ($NoPause) { return }
    [void](Read-Host '按回车键关闭此窗口')
}

function Invoke-Quiet {
    <# 运行外部命令并捕获输出与退出码（避免 native stderr 触发 ErrorActionPreference=Stop） #>
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $code = 0
    try {
        $output = & $Exe @Arguments 2>&1
        if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{
        ExitCode = $code
        Output   = (($output | Out-String).Trim())
    }
}

# ---------------- pip 镜像源 ----------------

$script:PipMirrorTable = [ordered]@{
    'tuna'    = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    'aliyun'  = 'https://mirrors.aliyun.com/pypi/simple/'
    'tencent' = 'https://mirrors.cloud.tencent.com/pypi/simple/'
    'ustc'    = 'https://mirrors.ustc.edu.cn/pypi/simple/'
    'pypi'    = 'https://pypi.org/simple/'
}

function Measure-MirrorLatency {
    <# 探测镜像可用性并返回毫秒延迟，不可用返回 $null #>
    param([Parameter(Mandatory = $true)][string]$Uri)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $null = Invoke-WebRequest -Uri $Uri -Method Head -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        $watch.Stop()
        return $watch.Elapsed.TotalMilliseconds
    }
    catch {
        return $null
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Get-PipIndexCandidates {
    <#
        返回按"最合适优先"排序的 pip 索引地址列表。
        auto：按测速结果排序；显式指定：该镜像排在最前。
        两种情况下官方 PyPI 都作为最后兜底（某个镜像 403/断流时自动换下一个）。
    #>
    param([string]$MirrorName = 'auto')

    $preferred = $null
    if ($env:ENM_PIP_INDEX) { $preferred = $env:ENM_PIP_INDEX }
    elseif (-not [string]::IsNullOrWhiteSpace($MirrorName) -and $MirrorName -ne 'auto') {
        if ($script:PipMirrorTable.Contains($MirrorName)) { $preferred = $script:PipMirrorTable[$MirrorName] }
        else { $preferred = $MirrorName }
    }

    if ($preferred) {
        $rest = @($script:PipMirrorTable.GetEnumerator() |
                Where-Object { $_.Value.TrimEnd('/') -ne $preferred.TrimEnd('/') } |
                Select-Object -ExpandProperty Value)
        return @($preferred) + $rest
    }

    $measured = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $script:PipMirrorTable.GetEnumerator()) {
        if ($entry.Key -eq 'pypi') { continue }
        $ms = Measure-MirrorLatency -Uri $entry.Value
        if ($null -eq $ms) { continue }
        $null = $measured.Add([pscustomobject]@{ Url = $entry.Value; Ms = $ms })
    }

    $fastest = $measured | Sort-Object -Property Ms | Select-Object -First 1
    $ordered = @($measured | Sort-Object -Property Ms | Select-Object -ExpandProperty Url)
    $ordered += $script:PipMirrorTable['pypi']

    if ($fastest) {
        Write-Info ("已选择 pip 镜像源: {0} ({1:N0} ms)" -f $fastest.Url, $fastest.Ms)
    }
    else {
        Write-Warn '所有镜像源探测失败，回退到默认 PyPI'
    }

    return $ordered
}

function Get-PipIndexUrl {
    <# 取最优镜像（用于展示/预览） #>
    param([string]$MirrorName = 'auto')
    $list = @(Get-PipIndexCandidates -MirrorName $MirrorName)
    return $list[0]
}

function Install-NuitkaWithMirror {
    <# 依次尝试各镜像源安装 Nuitka，返回成功使用的镜像地址；全部失败返回 $null #>
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$IndexUrls
    )

    $index = 0
    foreach ($url in $IndexUrls) {
        $index++
        if ($index -gt 1) {
            Write-Warn "改用镜像源重试（$index/$($IndexUrls.Count)）: $url"
        }

        $pipArgs = @('-m', 'pip', 'install', '--upgrade', 'nuitka',
            '--disable-pip-version-check', '--timeout', '30', '--retries', '3', '-i', $url)
        $result = Invoke-Quiet -Exe $Exe -Arguments $pipArgs
        if ($result.ExitCode -eq 0) { return $url }

        Write-Warn "Nuitka 安装失败（退出码 $($result.ExitCode)，镜像: $url）"
        $script:LastPipOutput = $result.Output
    }

    return $null
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

function Get-PythonCandidates {
    <# 候选解释器（去重）：-NuitkaPython → 项目 .venv → PATH 中的 python/python3/py #>
    $candidates = New-Object System.Collections.Generic.List[string]

    $add = {
        param([string]$Path)
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        if (-not (Test-Path -LiteralPath $Path)) { return }
        if (-not $candidates.Contains($Path)) { $null = $candidates.Add($Path) }
    }

    if (-not [string]::IsNullOrWhiteSpace($NuitkaPython)) {
        $explicit = Get-Command -Name $NuitkaPython -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($explicit) { & $add $explicit.Source }
        elseif (Test-Path -LiteralPath $NuitkaPython) { & $add ((Resolve-Path -LiteralPath $NuitkaPython).Path) }
    }

    & $add (Join-Path $ProjectRoot '.venv\Scripts\python.exe')

    foreach ($name in @($Python, 'python', 'python3', 'py')) {
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { & $add $command.Source }
    }

    return $candidates
}

function Test-NuitkaAvailable {
    <# 返回该解释器的 Nuitka 版本号（首行），不可用则返回 $null #>
    param([Parameter(Mandatory = $true)][string]$Exe)

    $result = Invoke-Quiet -Exe $Exe -Arguments @('-m', 'nuitka', '--version')
    if ($result.ExitCode -ne 0) { return $null }

    $line = $result.Output -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($line)) { return '未知版本' }
    return $line.Trim()
}

function Test-RuntimeDependencies {
    <# 检查打包含入的第三方依赖在该解释器中是否可用，返回缺失模块列表 #>
    param([Parameter(Mandatory = $true)][string]$Exe)

    $probe = @'
import importlib.util, sys
try:
    ok = importlib.util.find_spec(sys.argv[1]) is not None
except Exception:
    ok = False
sys.exit(0 if ok else 1)
'@

    $modules = @('PyQt5', 'PyQt5.QtWebEngineWidgets', 'ebooklib', 'lxml', 'chardet', 'PIL', 'pypdf', 'docx')
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($module in $modules) {
        $result = Invoke-Quiet -Exe $Exe -Arguments @('-c', $probe, $module)
        if ($result.ExitCode -ne 0) { $null = $missing.Add($module) }
    }
    return $missing
}

function Resolve-BuildInterpreter {
    <#
        选择真正用于打包的解释器：
        1. 首选解释器自带 Nuitka     → 直接使用；
        2. 否则在候选解释器中寻找自带 Nuitka 的本机环境 → 自动回退；
        3. 都找不到                    → 返回未就绪状态，由调用方决定是否安装。
    #>
    param([Parameter(Mandatory = $true)][string]$Preferred)

    $info = [pscustomobject]@{
        Preferred     = $Preferred
        BuildPython   = $null
        NuitkaVersion = $null
        FellBack      = $false
        Searched      = @()
    }

    $version = Test-NuitkaAvailable -Exe $Preferred
    if ($version) {
        $info.BuildPython = $Preferred
        $info.NuitkaVersion = $version
        return $info
    }

    if ($NoFallback) { return $info }

    foreach ($candidate in (Get-PythonCandidates)) {
        if ($candidate -eq $Preferred) { continue }
        $info.Searched += $candidate
        $version = Test-NuitkaAvailable -Exe $candidate
        if ($version) {
            $info.BuildPython = $candidate
            $info.NuitkaVersion = $version
            $info.FellBack = $true
            break
        }
    }

    return $info
}

function Read-ProjectMetadata {
    $meta = @{
        Version     = '1.0.0'
        Company     = 'Aaze_wu'
        Description = $DefaultDescription
    }

    $constants = Join-Path $ProjectRoot 'enm\constants.py'
    if (-not (Test-Path -LiteralPath $constants)) { return $meta }

    $text = Get-Content -LiteralPath $constants -Raw -Encoding UTF8
    $mapping = @{ Version = 'VERSION'; Company = 'AUTHOR_NAME' }

    foreach ($key in $mapping.Keys) {
        $pattern = '(?m)^\s*{0}\s*=\s*(.+?)\s*$' -f $mapping[$key]
        $match = [regex]::Match($text, $pattern)
        if (-not $match.Success) { continue }
        $value = $match.Groups[1].Value.Trim().Trim("'", '"')
        if ($value) { $meta[$key] = $value }
    }

    return $meta
}

Write-Host '========================================' -ForegroundColor DarkGray
Write-Host 'NovelMaster - 高级打包脚本 (PowerShell)' -ForegroundColor DarkGray
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''

# ---------------- 交互式选择打包模式 ----------------

if ([string]::IsNullOrWhiteSpace($Mode)) {
    if ($NonInteractive) {
        $Mode = 'onefile'
    }
    else {
        Write-Host '请选择打包模式:'
        Write-Host '  1. 单文件模式 (推荐)'
        Write-Host '  2. 独立目录模式'
        Write-Host '  3. 调试模式'
        Write-Host ''
        while (-not $Mode) {
            $answer = Read-Host '请选择 (1/2/3, 默认1)'
            if ([string]::IsNullOrWhiteSpace($answer)) { $answer = '1' }
            switch ($answer) {
                '1' { $Mode = 'onefile' }
                '2' { $Mode = 'standalone' }
                '3' { $Mode = 'debug' }
                default { Write-Warn '请输入 1 / 2 / 3' }
            }
        }
        Write-Host ''
    }
}

if ([string]::IsNullOrWhiteSpace($Optimize)) {
    if ($NonInteractive) {
        $Optimize = 'default'
    }
    else {
        Write-Host '请选择优化级别:'
        Write-Host '  1. 默认优化'
        Write-Host '  2. 最大优化 (启用 LTO，可能增加编译时间)'
        Write-Host ''
        while (-not $Optimize) {
            $answer = Read-Host '请选择 (1/2, 默认1)'
            if ([string]::IsNullOrWhiteSpace($answer)) { $answer = '1' }
            switch ($answer) {
                '1' { $Optimize = 'default' }
                '2' { $Optimize = 'full' }
                default { Write-Warn '请输入 1 / 2' }
            }
        }
        Write-Host ''
    }
}

# ---------------- 环境检查 ----------------

$pythonExe = Resolve-Python
if (-not $pythonExe) {
    Write-Err '未找到 Python 解释器，请安装 Python 3.8+ 并加入 PATH。'
    Wait-Exit
    exit 1
}

# ---------------- 选择打包解释器（支持回退到本机环境） ----------------

$buildPython = $pythonExe
$nuitkaVersion = $null

if ($SkipNuitkaCheck) {
    Write-Info "Python  : $pythonExe"
    Write-Warn '已跳过 Nuitka 检测（-SkipNuitkaCheck），将直接使用当前解释器'
}
else {
    $build = Resolve-BuildInterpreter -Preferred $pythonExe

    if ($build.BuildPython) {
        $buildPython = $build.BuildPython
        $nuitkaVersion = $build.NuitkaVersion

        if ($build.FellBack) {
            Write-Warn "当前解释器未安装 Nuitka: $pythonExe"
            Write-Warn "已自动改用本机环境解释器: $buildPython"
            Write-Info "Nuitka  : $nuitkaVersion"
            Write-Host ''

            $missing = @(Test-RuntimeDependencies -Exe $buildPython)
            if ($missing.Count -gt 0) {
                Write-Err "该解释器缺少运行依赖: $($missing -join ', ')"
                Write-Warn '请先在该环境执行: .\install.ps1 -Python <该解释器路径>'
                Write-Warn '或手动执行: pip install -r requirements.txt -i <镜像源>'
                Write-Warn '构建将继续，但可能失败或生成不可用的程序。'
            }
            else {
                Write-Ok '该解释器的运行依赖完整'
            }
        }
        else {
            Write-Info "Python  : $pythonExe"
            Write-Info "Nuitka  : $nuitkaVersion"
        }
    }
    else {
        Write-Info "Python  : $pythonExe"
        Write-Warn '当前解释器与本机环境中均未找到 Nuitka'

        if ($build.Searched.Count -gt 0) {
            Write-Host '已检查的解释器:' -ForegroundColor DarkGray
            foreach ($candidate in $build.Searched) {
                Write-Host "  - $candidate" -ForegroundColor DarkGray
            }
        }

        Write-Info "正在为当前解释器安装 Nuitka: $pythonExe"
        $indexUrls = @(Get-PipIndexCandidates -MirrorName $Mirror)

        if ($DryRun) {
            Write-Warn 'DryRun 模式：未实际安装 Nuitka'
            Write-Host "  $pythonExe -m pip install --upgrade nuitka -i <镜像源>" -ForegroundColor DarkGray
            Write-Info "镜像源尝试顺序: $($indexUrls -join '  ->  ')"
            $nuitkaVersion = '（DryRun 未安装）'
        }
        else {
            $usedIndex = Install-NuitkaWithMirror -Exe $pythonExe -IndexUrls $indexUrls
            if (-not $usedIndex) {
                Write-Err 'Nuitka 安装失败（所有镜像源均已尝试）'
                if ($script:LastPipOutput) { Write-Host $script:LastPipOutput -ForegroundColor DarkGray }
                Write-Warn ("可手动执行: pip install -i {0} --upgrade nuitka" -f $indexUrls[0])
                Wait-Exit
                exit 1
            }
            Write-Info "Nuitka 已从镜像源安装: $usedIndex"

            $nuitkaVersion = Test-NuitkaAvailable -Exe $pythonExe
            if (-not $nuitkaVersion) {
                Write-Err 'Nuitka 安装后仍无法调用，请检查该解释器环境。'
                Wait-Exit
                exit 1
            }
            Write-Ok "Nuitka 安装完成: $nuitkaVersion"
        }
    }
}

if (-not (Test-Path -LiteralPath $MainFile)) {
    Write-Err "主文件不存在: $MainFile"
    Wait-Exit
    exit 1
}

$meta = Read-ProjectMetadata

# ---------------- 组装构建命令 ----------------

$nuitkaArgs = @('-m', 'nuitka', '--standalone')

if ($Mode -eq 'onefile') { $nuitkaArgs += '--onefile' }
if ($Mode -eq 'debug') { $nuitkaArgs += '--debug' }
if ($Optimize -eq 'full') { $nuitkaArgs += '--lto=yes' }

$nuitkaArgs += @(
    '--windows-console-mode=disable'
    '--windows-uac-admin'
)

if (Test-Path -LiteralPath $IconFile) {
    $nuitkaArgs += "--windows-icon-from-ico=$IconFile"
}

$nuitkaArgs += @(
    "--product-name=$AppName"
    "--file-version=$($meta.Version)"
    "--product-version=$($meta.Version)"
    "--company-name=$($meta.Company)"
    "--file-description=$($meta.Description)"
    "--output-dir=$OutputDirPath"
    '--enable-plugin=pyqt5'
    '--include-package=enm'
    '--include-package=ebooklib'
    '--include-package=chardet'
    '--include-package=PIL'
    '--include-package=pypdf'
    '--include-package=docx'
    '--include-data-dir=lang=lang'
    '--include-data-dir=icon=icon'
    '--nofollow-import-to=*.tests'
    '--nofollow-import-to=*.test'
    '--remove-output'
    $MainFileName
)

Write-Host '========================================' -ForegroundColor DarkGray
Write-Host '构建配置:'
Write-Host "  模式    : $Mode"
Write-Host "  优化    : $Optimize"
Write-Host "  版本号  : $($meta.Version)"
Write-Host "  输出目录: $OutputDirPath"
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''
Write-Host "  $buildPython $($nuitkaArgs -join ' ')" -ForegroundColor DarkGray
Write-Host ''

# ---------------- 确认并执行 ----------------

if ($DryRun) {
    Write-Warn 'DryRun 模式：仅显示命令，未实际编译'
    Wait-Exit
    exit 0
}

if (-not $NonInteractive) {
    Write-Host '即将开始构建，这可能需要几分钟时间...'
    $confirm = Read-Host '是否继续? (y/n, 默认y)'
    if ([string]::IsNullOrWhiteSpace($confirm)) { $confirm = 'y' }
    if ($confirm -notmatch '^[Yy]') {
        Write-Warn '构建已取消'
        Wait-Exit
        exit 0
    }
}

if (-not (Test-Path -LiteralPath $OutputDirPath)) {
    $null = New-Item -ItemType Directory -Path $OutputDirPath -Force
}

Write-Info '开始构建...'
Write-Host ''

Push-Location -LiteralPath $ProjectRoot
try {
    & $buildPython @nuitkaArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($null -eq $exitCode) { $exitCode = 0 }

Write-Host ''
if ($exitCode -ne 0) {
    Write-Err '构建失败'
    Wait-Exit
    exit $exitCode
}

Write-Host '========================================' -ForegroundColor DarkGray
Write-Ok '构建完成!'
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''

if ($Mode -eq 'onefile') {
    $exePath = Join-Path $OutputDirPath "$AppName.exe"
    if (Test-Path -LiteralPath $exePath) {
        $sizeMb = (Get-Item -LiteralPath $exePath).Length / 1MB
        Write-Host "  输出文件: $exePath"
        Write-Host ('  文件大小: {0:N2} MB' -f $sizeMb)
    }
    else {
        Write-Warn "未找到输出文件: $exePath"
    }
}
else {
    Write-Host "  输出目录: $(Join-Path $OutputDirPath $AppName)"
}

Write-Host ''
Write-Host '使用说明:'
Write-Host "1. 单文件模式: 直接运行 $AppName.exe"
Write-Host "2. 独立目录模式: 运行 $AppName\$AppName.exe"
Write-Host '3. 首次运行可能需要几秒钟初始化'
Write-Host '4. 程序数据保存在用户 AppData 目录'
Write-Host ''

$shouldOpen = [bool]$OpenOutput
if (-not $shouldOpen -and -not $NonInteractive) {
    $answer = Read-Host '是否打开输出目录? (y/n)'
    $shouldOpen = ($answer -match '^[Yy]')
}
if ($shouldOpen) {
    Invoke-Item -LiteralPath $OutputDirPath
}

Wait-Exit
exit 0
