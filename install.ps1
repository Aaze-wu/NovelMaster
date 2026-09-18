#Requires -Version 5.1
<#
.SYNOPSIS
    NovelMaster 环境安装脚本（PowerShell 版）。

.DESCRIPTION
    一键准备开发/打包环境：
      1. 解析本机基础 Python（不会使用 .venv 自身）；
      2. 若虚拟环境不存在则自动创建（默认 .venv）；
      3. 自动测速选择最快的 pip 镜像源；
      4. 升级 pip / setuptools / wheel；
      5. 安装 requirements.txt 中的全部依赖；
      6. 可选把打包工具 Nuitka 一并装入虚拟环境（-WithNuitka）。

.PARAMETER Python
    用于创建虚拟环境的基础 Python 命令或完整路径，默认为 PATH 中的 python。
    脚本会跳过虚拟环境自身的解释器，避免"用虚拟环境创建虚拟环境"。

.PARAMETER VenvDir
    虚拟环境目录（相对项目根目录），默认 .venv。

.PARAMETER Mirror
    pip 镜像源。可选 auto（默认，自动测速选择）、tuna、aliyun、
    ustc、tencent、pypi，也可直接传入完整 URL。
    也可用环境变量 ENM_PIP_INDEX 覆盖（优先级最高）。

.PARAMETER Requirements
    依赖清单文件名（相对项目根目录），默认 requirements.txt。

.PARAMETER Recreate
    删除已存在的虚拟环境后重新创建。

.PARAMETER WithNuitka
    额外在虚拟环境中安装 Nuitka（打包用，同样使用镜像源）。

.PARAMETER SkipPipUpgrade
    跳过 pip / setuptools / wheel 的升级。

.PARAMETER DryRun
    只显示将要执行的命令，不创建环境、不安装任何东西。

.PARAMETER NonInteractive
    非交互模式：不询问任何问题（例如 -Recreate 时不再确认）。

.PARAMETER NoPause
    结束后不等待按键。

.EXAMPLE
    .\install.ps1

.EXAMPLE
    .\install.ps1 -Recreate -WithNuitka

.EXAMPLE
    .\install.ps1 -Mirror aliyun -DryRun -NoPause

.NOTES
    若提示"在此系统上禁止运行脚本"，可执行：
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$VenvDir = '.venv',
    [string]$Mirror = 'auto',
    [string]$Requirements = 'requirements.txt',
    [switch]$Recreate,
    [switch]$WithNuitka,
    [switch]$SkipPipUpgrade,
    [switch]$DryRun,
    [switch]$NonInteractive,
    [switch]$NoPause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot $VenvDir
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'
$RequirementsPath = Join-Path $ProjectRoot $Requirements

function Write-Info { param([string]$Message) Write-Host "[信息] $Message" -ForegroundColor Cyan }
function Write-Ok { param([string]$Message) Write-Host "[成功] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[警告] $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "[错误] $Message" -ForegroundColor Red }
function Write-Cmd { param([string]$Message) Write-Host "  $Message" -ForegroundColor DarkGray }

function Wait-Exit {
    if ($NoPause) { return }
    [void](Read-Host '按回车键关闭此窗口')
}

function Invoke-Native {
    <# 运行外部命令：输出实时透传到控制台，只返回退出码 #>
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $code = 0
    try {
        & $Exe @Arguments | Out-Host
        if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return [int]$code
}

function Invoke-Quiet {
    <# 运行外部命令并捕获输出与退出码 #>
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
        auto：探测各镜像延迟后按快慢排序；显式指定：该镜像排在最前。
        两种情况下官方 PyPI 都作为最后兜底（某个镜像 403/断流时自动换下一个）。
    #>
    param([string]$MirrorName = 'auto')

    $preferred = $null
    if ($env:ENM_PIP_INDEX) {
        $preferred = $env:ENM_PIP_INDEX
        Write-Info "使用环境变量指定的 pip 镜像源: $preferred（失败时自动回退其它镜像）"
    }
    elseif (-not [string]::IsNullOrWhiteSpace($MirrorName) -and $MirrorName -ne 'auto') {
        if ($script:PipMirrorTable.Contains($MirrorName)) {
            $preferred = $script:PipMirrorTable[$MirrorName]
            Write-Info "使用指定的 pip 镜像源: $preferred（失败时自动回退其它镜像）"
        }
        else {
            $preferred = $MirrorName
            Write-Info "使用自定义 pip 镜像源: $preferred（失败时自动回退其它镜像）"
        }
    }

    if ($preferred) {
        $rest = @($script:PipMirrorTable.GetEnumerator() |
                Where-Object { $_.Value.TrimEnd('/') -ne $preferred.TrimEnd('/') } |
                Select-Object -ExpandProperty Value)
        return @($preferred) + $rest
    }

    Write-Info '正在探测可用的 pip 镜像源...'
    $measured = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $script:PipMirrorTable.GetEnumerator()) {
        if ($entry.Key -eq 'pypi') { continue }
        $ms = Measure-MirrorLatency -Uri $entry.Value
        if ($null -eq $ms) {
            Write-Cmd "跳过（不可用）: $($entry.Value)"
            continue
        }
        Write-Cmd ("可用 {0,6:N0} ms  {1}" -f $ms, $entry.Value)
        $null = $measured.Add([pscustomobject]@{ Url = $entry.Value; Ms = $ms })
    }

    $fastest = $measured | Sort-Object -Property Ms | Select-Object -First 1
    $ordered = @($measured | Sort-Object -Property Ms | Select-Object -ExpandProperty Url)
    $ordered += $script:PipMirrorTable['pypi']

    if ($fastest) {
        Write-Ok ("已选择 pip 镜像源: {0} ({1:N0} ms)" -f $fastest.Url, $fastest.Ms)
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

function Install-PipRequirements {
    <#
        依次尝试各镜像源执行 pip 安装；某个镜像失败（403/超时/断流）
        时自动切换到下一个，全部失败才返回 $false。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$PipTarget,
        [Parameter(Mandatory = $true)][string[]]$IndexUrls,
        [string]$Label = '依赖'
    )

    $index = 0
    foreach ($url in $IndexUrls) {
        $index++
        if ($index -gt 1) {
            Write-Warn "改用镜像源重试（$index/$($IndexUrls.Count)）: $url"
        }

        $args = @('-m', 'pip', 'install') + $PipTarget + @(
            '--disable-pip-version-check', '--timeout', '30', '--retries', '3', '-i', $url
        )
        $code = Invoke-Native -Exe $Exe -Arguments $args
        if ($code -eq 0) { return $true }

        Write-Warn "$Label 安装失败（退出码 $code，镜像: $url）"
    }

    return $false
}

# ---------------- 解释器与环境 ----------------

function Resolve-BasePython {
    <# 选择用于创建虚拟环境的基础 Python（排除虚拟环境自身） #>
    $candidates = New-Object System.Collections.Generic.List[string]

    $add = {
        param([string]$Path)
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        if (-not (Test-Path -LiteralPath $Path)) { return }
        if (-not $candidates.Contains($Path)) { $null = $candidates.Add($Path) }
    }

    if (-not [string]::IsNullOrWhiteSpace($Python)) {
        $command = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { & $add $command.Source }
        elseif (Test-Path -LiteralPath $Python) { & $add ((Resolve-Path -LiteralPath $Python).Path) }
    }

    foreach ($name in @('python', 'python3', 'py')) {
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { & $add $command.Source }
    }

    foreach ($candidate in $candidates) {
        # 不能用虚拟环境自身的解释器去创建虚拟环境
        if ($candidate -like "$VenvPath*") { continue }

        $probe = Invoke-Quiet -Exe $candidate -Arguments @(
            '-c', 'import venv, sys; print(sys.version.split()[0])'
        )
        if ($probe.ExitCode -eq 0) {
            return [pscustomobject]@{ Path = $candidate; Version = $probe.Output.Trim() }
        }
    }

    return $null
}

function Test-InstalledModules {
    <# 返回指定解释器中缺失的模块列表 #>
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Modules
    )

    $probe = 'import importlib.util, sys; print(",".join([m for m in sys.argv[1].split(",") if importlib.util.find_spec(m) is None]))'
    $result = Invoke-Quiet -Exe $Exe -Arguments @('-c', $probe, ($Modules -join ','))
    if ($result.ExitCode -ne 0) { return @() }

    $missing = $result.Output.Trim()
    if ([string]::IsNullOrWhiteSpace($missing)) { return @() }
    return @($missing -split ',')
}

# ---------------- 主流程 ----------------

Write-Host '========================================' -ForegroundColor DarkGray
Write-Host 'NovelMaster - 环境安装脚本 (PowerShell)' -ForegroundColor DarkGray
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''

if (-not (Test-Path -LiteralPath $RequirementsPath)) {
    Write-Err "依赖清单不存在: $RequirementsPath"
    Wait-Exit
    exit 1
}

$indexUrls = @(Get-PipIndexCandidates -MirrorName $Mirror)
$indexUrl = $indexUrls[0]
Write-Host ''

# ---- 1. 基础解释器 ----
$base = Resolve-BasePython
if (-not $base) {
    Write-Err "未找到可用的基础 Python（已尝试: $Python / python / python3 / py）。"
    Write-Warn '请安装 Python 3.8+ 并加入 PATH，或用 -Python 指定完整路径。'
    Wait-Exit
    exit 1
}
Write-Info "基础解释器: $($base.Path) (Python $($base.Version))"
Write-Info "虚拟环境  : $VenvPath"

# ---- 2. 创建 / 复用虚拟环境 ----
$venvExists = Test-Path -LiteralPath $VenvPython
$brokenVenv = (-not $venvExists) -and (Test-Path -LiteralPath $VenvPath)

if ($venvExists -and $Recreate) {
    if ($DryRun) {
        Write-Warn "DryRun 模式：将删除并重建虚拟环境 $VenvPath"
        $venvExists = $false
    }
    else {
        $doDelete = $true
        if (-not $NonInteractive) {
            $answer = Read-Host "将删除已存在的虚拟环境 $VenvPath，是否继续? (y/N)"
            $doDelete = ($answer -match '^(y|yes)$')
        }
        if (-not $doDelete) {
            Write-Warn '已取消重建，改为复用现有虚拟环境'
        }
        else {
            Write-Info "正在删除旧虚拟环境: $VenvPath"
            Remove-Item -LiteralPath $VenvPath -Recurse -Force
            $venvExists = $false
        }
    }
}

if ($venvExists) {
    Write-Ok '虚拟环境已存在，跳过创建（如需重装请加 -Recreate）'
}
elseif ($brokenVenv) {
    Write-Warn "虚拟环境目录不完整（缺少 Scripts\python.exe），将重新创建"
}

if (-not $venvExists) {
    $createArgs = @('-m', 'venv', $VenvPath)
    if ($DryRun) {
        Write-Warn "DryRun 模式：未执行 $($base.Path) $($createArgs -join ' ')"
    }
    else {
        Write-Info '正在创建虚拟环境...'
        $createCode = Invoke-Native -Exe $base.Path -Arguments $createArgs
        if ($createCode -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
            Write-Err "虚拟环境创建失败（退出码 $createCode）"
            Wait-Exit
            exit 1
        }
        Write-Ok '虚拟环境创建完成'
    }
}

if ($DryRun) {
    Write-Host ''
    Write-Info 'DryRun 模式：以下为将要执行的安装命令'
    Write-Cmd "$VenvPython -m pip install --upgrade pip setuptools wheel"
    Write-Cmd "$VenvPython -m pip install -r $RequirementsPath"
    if ($WithNuitka) { Write-Cmd "$VenvPython -m pip install --upgrade nuitka" }
    Write-Cmd "（以上命令均追加: -i <镜像源> --timeout 30 --retries 3）"
    Write-Info "镜像源尝试顺序: $($indexUrls -join '  ->  ')"
    Wait-Exit
    exit 0
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Err "虚拟环境解释器不存在: $VenvPython"
    Wait-Exit
    exit 1
}

# ---- 3. 升级 pip / setuptools / wheel ----
if ($SkipPipUpgrade) {
    Write-Warn '已跳过 pip / setuptools / wheel 升级（-SkipPipUpgrade）'
}
else {
    Write-Info '正在升级 pip / setuptools / wheel ...'
    $ok = Install-PipRequirements -Exe $VenvPython `
        -PipTarget @('--upgrade', 'pip', 'setuptools', 'wheel') `
        -IndexUrls $indexUrls -Label 'pip 升级'
    if ($ok) {
        Write-Ok 'pip / setuptools / wheel 已是最新'
    }
    else {
        Write-Warn 'pip 升级失败，将继续安装依赖（可稍后手动重试）'
    }
}

# ---- 4. 安装依赖 ----
Write-Host ''
Write-Info "正在安装依赖: $Requirements"
$reqOk = Install-PipRequirements -Exe $VenvPython `
    -PipTarget @('-r', $RequirementsPath) `
    -IndexUrls $indexUrls -Label '依赖'
if (-not $reqOk) {
    Write-Err '依赖安装失败（所有镜像源均已尝试）'
    Write-Warn '可稍后重试，或手动执行:'
    Write-Cmd "$VenvPython -m pip install -r $RequirementsPath -i $indexUrl"
    Wait-Exit
    exit 1
}
Write-Ok '依赖安装完成'

# ---- 5. 可选安装 Nuitka ----
if ($WithNuitka) {
    Write-Host ''
    Write-Info '正在安装 Nuitka（打包工具）...'
    $nuitkaOk = Install-PipRequirements -Exe $VenvPython `
        -PipTarget @('--upgrade', 'nuitka') `
        -IndexUrls $indexUrls -Label 'Nuitka'
    if (-not $nuitkaOk) {
        Write-Warn 'Nuitka 安装失败，打包时可在本机环境执行（build.ps1 会自动回退）'
    }
    else {
        $nuitkaVersion = (Invoke-Quiet -Exe $VenvPython -Arguments @('-m', 'nuitka', '--version')).Output
        Write-Ok "Nuitka 安装完成: $(($nuitkaVersion -split "`r?`n")[0])"
    }
}

# ---- 6. 校验 ----
Write-Host ''
Write-Info '正在校验环境...'
$requiredModules = @('PyQt5', 'PyQt5.QtWebEngineWidgets', 'ebooklib', 'lxml', 'chardet', 'PIL', 'pypdf', 'docx')
$missing = @(Test-InstalledModules -Exe $VenvPython -Modules $requiredModules)

$runtimeVersion = (Invoke-Quiet -Exe $VenvPython -Arguments @(
        '-c', 'import sys; print(sys.version.split()[0])'
    )).Output.Trim()
Write-Info "虚拟环境 Python: $runtimeVersion"

if ($missing.Count -gt 0) {
    Write-Err "以下模块仍缺失: $($missing -join ', ')"
    Write-Warn '请检查 requirements.txt 或手动安装后再试。'
    Wait-Exit
    exit 1
}

Write-Ok '全部依赖已就绪'
Write-Host ''
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host '后续使用:' -ForegroundColor DarkGray
Write-Cmd '.\run.ps1 -UseVenv                 # 使用虚拟环境运行'
Write-Cmd '.\build.ps1 -UseVenv               # 使用虚拟环境打包'
Write-Cmd '.\build-advanced.ps1 -UseVenv      # 高级打包'
Write-Host '========================================' -ForegroundColor DarkGray

Wait-Exit
exit 0
