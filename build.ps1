#Requires -Version 5.1
<#
.SYNOPSIS
    NovelMaster 基本打包脚本（PowerShell 版，对应 build.bat）。

.DESCRIPTION
    使用 Nuitka 将 NovelMaster 打包为「独立目录版」可执行程序
    （--standalone，不带 --onefile），产物为输出目录下的 NovelMaster.dist 文件夹。
    脚本会自动检测 Nuitka，缺失时尝试安装。

    目录版启动更快、不需要每次解压到临时目录，也是生成安装包的前提
    （Inno Setup 脚本按 dist\NovelMaster.dist 组织文件）。
    若要「打包 + 出安装包」一次完成，请用 release.ps1 / release-advanced.ps1。

.PARAMETER Python
    指定用于打包的 Python 解释器，三种写法都支持：版本号（3.13 / 3.13.6）、
    命令名（python / python3 / py）、完整路径（C:\...\python.exe）。
    不指定时优先使用项目 .venv，其次才是 PATH 与本机已安装的 Python。

.PARAMETER UseVenv
    优先使用项目目录下的 .venv\Scripts\python.exe。
    该项目已是默认行为，参数保留仅为兼容旧命令行。

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
    打包完成后直接打开输出目录，不再询问。

.PARAMETER NonInteractive
    非交互模式：不询问任何问题。

.PARAMETER DryRun
    只显示将要执行的打包命令，不实际编译。

.PARAMETER NoPause
    结束后不等待按键。

.EXAMPLE
    .\build.ps1

.EXAMPLE
    .\build.ps1 -DryRun

.EXAMPLE
    .\build.ps1 -UseVenv -OpenOutput -NoPause

.NOTES
    若提示"在此系统上禁止运行脚本"，可执行：
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
[CmdletBinding()]
param(
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

# $Python 的默认值是 'python'，这里记住用户到底有没有显式指定（显式指定优先级最高）
$PythonWasSpecified = $PSBoundParameters.ContainsKey('Python')

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

# ---------------- 解释器发现 ----------------

$script:PythonVersionCache = @{}
$script:InstalledPythonCache = $null

# Microsoft Store 的“应用执行别名”：这个路径上的 python.exe 一运行就弹商店，
# 探测时必须跳过，否则会被当成一个“没有 Nuitka 的解释器”。
$script:FakePythonPatterns = @('\Microsoft\WindowsApps\')

function Test-UsablePythonPath {
    <# 判断一个路径是否是可以真正执行的 python.exe #>
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    foreach ($pattern in $script:FakePythonPatterns) {
        if ($Path -like "*$pattern*") { return $false }
    }
    return (Test-Path -LiteralPath $Path -PathType Leaf)
}

function Get-PythonVersion {
    <# 取解释器版本号（形如 3.13.6），取不到返回 $null #>
    param([Parameter(Mandatory = $true)][string]$Exe)

    if ($script:PythonVersionCache.ContainsKey($Exe)) { return $script:PythonVersionCache[$Exe] }

    # 注意：探针不能包含英文双引号。Windows PowerShell 5.1 不会对 native 参数转义引号，
    # 双引号会被 python.exe 的命令行解析吞掉（print(".") → print(.)），导致语法错误、
    # 进而扫不到任何解释器。这里用 chr(46) 代替 '.'，整段探针不含引号。
    $probe = 'import sys;print(*sys.version_info[:3],sep=chr(46))'
    $result = Invoke-Quiet -Exe $Exe -Arguments @('-c', $probe)
    $version = $null
    if ($result.ExitCode -eq 0) {
        $line = $result.Output -split "`r?`n" |
            Where-Object { $_ -match '^\d+\.\d+' } |
            Select-Object -First 1
        if ($line) { $version = $line.Trim() }
    }

    $script:PythonVersionCache[$Exe] = $version
    return $version
}

function Get-RealPythonPath {
    <# py.exe 只是启动器，问它要真正的解释器路径；其它情况原样返回 #>
    param([string]$Exe)

    if ([string]::IsNullOrWhiteSpace($Exe)) { return $null }
    if ([System.IO.Path]::GetFileNameWithoutExtension($Exe) -ne 'py') { return $Exe }

    $result = Invoke-Quiet -Exe $Exe -Arguments @('-c', 'import sys; print(sys.executable)')
    if ($result.ExitCode -ne 0) { return $Exe }
    $line = $result.Output -split "`r?`n" |
        Where-Object { $_ -match 'python\.exe' } |
        Select-Object -First 1
    if ($line -and (Test-UsablePythonPath -Path $line.Trim())) { return $line.Trim() }
    return $Exe
}

function Get-PyLauncherPaths {
    <# 用 py 启动器（PEP 397）列出本机注册的所有解释器 #>
    $py = Get-Command -Name 'py' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $py) { return @() }

    $result = Invoke-Quiet -Exe $py.Source -Arguments @('-0p')
    if ($result.ExitCode -ne 0) { return @() }

    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($result.Output -split "`r?`n")) {
        $match = [regex]::Match($line, '[A-Za-z]:\\[^"]*?python\.exe')
        if ($match.Success) { $null = $paths.Add($match.Value) }
    }
    return $paths
}

function Get-RegisteredPythonPaths {
    <# 读注册表里官方安装包登记的 Python（PATH 里没有时也能找到） #>
    $paths = New-Object System.Collections.Generic.List[string]
    $roots = @(
        'HKLM:\SOFTWARE\Python\PythonCore'
        'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore'
        'HKCU:\SOFTWARE\Python\PythonCore'
    )

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($tag in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
            $installKey = Join-Path $tag.PSPath 'InstallPath'
            if (-not (Test-Path -LiteralPath $installKey)) { continue }

            $item = Get-ItemProperty -LiteralPath $installKey -ErrorAction SilentlyContinue
            if (-not $item) { continue }

            foreach ($name in @('ExecutablePath', '(default)')) {
                $property = $item.PSObject.Properties[$name]
                if (-not $property) { continue }
                $value = [string]$property.Value
                if ([string]::IsNullOrWhiteSpace($value)) { continue }
                if ($value.EndsWith('\')) { $value = Join-Path $value 'python.exe' }
                $null = $paths.Add($value)
            }
        }
    }
    return $paths
}

function Get-CommonPythonPaths {
    <# 常见安装位置兜底（官方安装包默认装在用户目录） #>
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python')
        $env:LOCALAPPDATA
        'C:\'
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($root in $roots) {
        $dirs = Get-ChildItem -LiteralPath $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue
        foreach ($dir in @($dirs)) {
            $null = $paths.Add((Join-Path $dir.FullName 'python.exe'))
        }
    }
    return $paths
}

function Find-InstalledPythons {
    <#
        扫描本机所有可用的 CPython，返回 [pscustomobject]@{ Path; Version } 列表，
        版本从新到旧排序；结果会缓存，重复调用不会反复起进程。
        来源：py 启动器 → 注册表 → 常见安装目录 → PATH 里的 python/python3。
    #>
    if ($script:InstalledPythonCache) { return $script:InstalledPythonCache }

    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($path in @(Get-PyLauncherPaths) + @(Get-RegisteredPythonPaths) + @(Get-CommonPythonPaths)) {
        $null = $candidates.Add($path)
    }
    foreach ($name in @('python', 'python3')) {
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { $null = $candidates.Add($command.Source) }
    }

    $seen = New-Object System.Collections.Generic.List[string]
    $found = New-Object System.Collections.Generic.List[object]

    foreach ($path in $candidates) {
        if (-not (Test-UsablePythonPath -Path $path)) { continue }
        $full = $path
        try { $full = (Resolve-Path -LiteralPath $path).Path } catch { }
        if ($seen.Contains($full)) { continue }
        $null = $seen.Add($full)

        $version = Get-PythonVersion -Exe $full
        if (-not $version) { continue }
        $null = $found.Add([pscustomobject]@{ Path = $full; Version = $version })
    }

    $ordered = @($found | Sort-Object -Property @{ Expression = { [version]$_.Version }; Descending = $true })
    $script:InstalledPythonCache = $ordered
    return $ordered
}

function Get-InterpreterReport {
    <# 列出本机所有解释器及其 Nuitka 状态，用于排查“为什么没用上我的 Python” #>
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($info in @(Find-InstalledPythons)) {
        $null = $rows.Add([pscustomobject]@{
                Path    = $info.Path
                Version = $info.Version
                Nuitka  = Test-NuitkaAvailable -Exe $info.Path
            })
    }
    return $rows
}

function Resolve-PythonSpec {
    <#
        把 -Python / -NuitkaPython 的取值解析成解释器路径，三种写法都支持：
          1. 版本号   3.13 / 3.13.6
          2. 命令名   python / python3 / py
          3. 完整路径 C:\...\python.exe
        解析不出来返回 $null，由调用方决定是否退回自动发现。
    #>
    param([string]$Spec)

    if ([string]::IsNullOrWhiteSpace($Spec)) { return $null }

    if ($Spec -match '^\d+(\.\d+){0,2}$') {
        $py = Get-Command -Name 'py' -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($py) {
            $result = Invoke-Quiet -Exe $py.Source -Arguments @("-V:$Spec", '-c', 'import sys; print(sys.executable)')
            if ($result.ExitCode -eq 0) {
                $line = $result.Output -split "`r?`n" |
                    Where-Object { $_ -match 'python\.exe' } |
                    Select-Object -First 1
                if ($line -and (Test-UsablePythonPath -Path $line.Trim())) { return $line.Trim() }
            }
        }

        foreach ($info in @(Find-InstalledPythons)) {
            if ($info.Version -eq $Spec -or $info.Version.StartsWith("$Spec.")) { return $info.Path }
        }

        Write-Warn "本机未找到 Python $Spec"
        return $null
    }

    $command = Get-Command -Name $Spec -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) {
        if (Test-UsablePythonPath -Path $command.Source) { return (Get-RealPythonPath -Exe $command.Source) }
        return $null
    }
    if (Test-UsablePythonPath -Path $Spec) { return (Get-RealPythonPath -Exe (Resolve-Path -LiteralPath $Spec).Path) }
    return $null
}

function Resolve-Python {
    <#
        选默认解释器：
        1. -Python 显式指定 → 按它解析（版本号 / 命令名 / 路径都行）；
        2. 否则优先项目 .venv（install.ps1 把依赖装在这里，打出来的包才和开发环境一致）；
        3. 再退回 PATH 里的 python/python3/py，最后是本机扫描到的其它 Python。
    #>
    if ($PythonWasSpecified) {
        $explicit = Resolve-PythonSpec -Spec $Python
        if ($explicit) { return $explicit }
        Write-Warn "-Python $Python 无法解析，改用自动发现"
    }

    $venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (Test-UsablePythonPath -Path $venvPython) { return $venvPython }
    if ($UseVenv) { Write-Warn "未找到虚拟环境解释器: $venvPython，改用系统 Python" }

    foreach ($name in @('python', 'python3', 'py')) {
        $resolved = Resolve-PythonSpec -Spec $name
        if ($resolved) { return $resolved }
    }

    foreach ($info in @(Find-InstalledPythons)) { return $info.Path }
    return $null
}

function Get-PythonCandidates {
    <#
        回退搜索用的解释器候选（去重，保持优先级）：
        -Python / -NuitkaPython → 项目 .venv → PATH 的 python/python3 → 本机扫描到的其它 Python
    #>
    $candidates = New-Object System.Collections.Generic.List[string]

    $add = {
        param([string]$Path)
        if (-not (Test-UsablePythonPath -Path $Path)) { return }
        $full = $Path
        try { $full = (Resolve-Path -LiteralPath $Path).Path } catch { }
        if (-not $candidates.Contains($full)) { $null = $candidates.Add($full) }
    }

    & $add (Resolve-PythonSpec -Spec $NuitkaPython)
    & $add (Resolve-PythonSpec -Spec $Python)
    & $add (Join-Path $ProjectRoot '.venv\Scripts\python.exe')

    foreach ($name in @('python', 'python3')) {
        $command = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { & $add $command.Source }
    }

    foreach ($info in @(Find-InstalledPythons)) { & $add $info.Path }

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

    $modules = @('PyQt5', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtTextToSpeech', 'ebooklib', 'lxml', 'chardet', 'PIL', 'pypdf', 'docx')
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($module in $modules) {
        $result = Invoke-Quiet -Exe $Exe -Arguments @('-c', $probe, $module)
        if ($result.ExitCode -ne 0) { $null = $missing.Add($module) }
    }
    return $missing
}

function Test-OptionalModule {
    <# 可选依赖在解释器里有没有（有就把它带进包，没有就走开） #>
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string]$Module
    )

    $probe = @'
import importlib.util, sys
try:
    ok = importlib.util.find_spec(sys.argv[1]) is not None
except Exception:
    ok = False
sys.exit(0 if ok else 1)
'@

    return (Invoke-Quiet -Exe $Exe -Arguments @('-c', $probe, $Module)).ExitCode -eq 0
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

# 从 enm/constants.py 读取版本号与作者，保持与程序一致
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
Write-Host 'NovelMaster - Nuitka 打包脚本 (PowerShell)' -ForegroundColor DarkGray
Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ''

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
        }
        else {
            Write-Info "Python  : $pythonExe"
            Write-Info "Nuitka  : $nuitkaVersion"
        }
    }
    else {
        Write-Info "Python  : $pythonExe"
        Write-Warn '当前解释器与本机环境中均未找到 Nuitka'

        $report = @(Get-InterpreterReport)
        if ($report.Count -gt 0) {
            Write-Host '本机解释器扫描结果:' -ForegroundColor DarkGray
            foreach ($row in $report) {
                $state = if ($row.Nuitka) { "Nuitka $($row.Nuitka)" } else { '无 Nuitka' }
                Write-Host ("  - Python {0,-8} {1,-16} {2}" -f $row.Version, $state, $row.Path) -ForegroundColor DarkGray
            }
            Write-Host ''
            Write-Warn '可用 -Python <版本号|命令名|路径> 指定要用的解释器，例如: -Python 3.13'
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

# ---------------- 依赖自检 ----------------

# 无论最后用哪个解释器，都确认一下打包要包含的第三方依赖是否齐全：
# 缺依赖时 Nuitka 照样能编译，但打出来的 exe 一运行就崩。
if (-not $SkipNuitkaCheck) {
    $missingDeps = @(Test-RuntimeDependencies -Exe $buildPython)
    if ($missingDeps.Count -gt 0) {
        Write-Err "打包解释器缺少运行依赖: $($missingDeps -join ', ')"
        Write-Warn "请先补齐依赖: .\install.ps1 -Python `"$buildPython`""
        Write-Warn '或手动执行: pip install -r requirements.txt -i <镜像源>'
        Write-Warn '打包将继续，但可能失败或生成不可用的程序。'
    }
    else {
        Write-Ok "依赖完整: $buildPython"
    }
}

$meta = Read-ProjectMetadata
Write-Info "版本号  : $($meta.Version)"
Write-Info "作者    : $($meta.Company)"
Write-Info "输出目录: $OutputDirPath"
Write-Host ''

# ---------------- 组装打包参数 ----------------

$nuitkaArgs = @(
    '-m', 'nuitka'
    '--standalone'
    '--windows-console-mode=disable'
    "--output-dir=$OutputDirPath"
)

if (Test-Path -LiteralPath $IconFile) {
    $nuitkaArgs += "--windows-icon-from-ico=$IconFile"
}
else {
    Write-Warn "图标文件不存在: $IconFile，将使用默认图标"
}

$nuitkaArgs += @(
    "--product-name=$AppName"
    "--file-version=$($meta.Version)"
    "--product-version=$($meta.Version)"
    "--company-name=$($meta.Company)"
    "--file-description=$($meta.Description)"
    '--nofollow-import-to=*.tests'
    '--enable-plugin=pyqt5'
    # 朗读靠 QtTextToSpeech：Nuitka 的 pyqt5 插件默认不收集 texttospeech
    # 插件（见 PySidePyQtPlugin._getSensiblePlugins），不显式包含的话冻结版
    # 里 QTextToSpeech 会找不到后端，朗读静默无声
    '--include-qt-plugins=texttospeech'
    '--include-package=enm'
    '--include-package=ebooklib'
    '--include-package=chardet'
    '--include-package=PIL'
    '--include-package=pypdf'
    '--include-package=docx'
    '--include-data-dir=lang=lang'
    '--include-data-dir=icon=icon'
    # 不加 --windows-uac-admin：程序数据全在 %APPDATA%\NovelMaster，注册表只写
    # HKCU，HKLM 只读，不需要管理员；带上它只会让每次启动都弹 UAC
    '--remove-output'
    $MainFileName
)

# 朗读的两套可选引擎（打包解释器里装了才带进包，没装就静默跳过）：
#   * sherpa-onnx 的 Python 层顺着导入链能收到，但 ctypes 加载的
#     sherpa-onnx-c-api.dll / onnxruntime.dll 不在依赖图里，必须显式带包数据；
#   * 语音模型（Piper / Kokoro）**不进包**，首次使用时程序内下载到
#     %APPDATA%\NovelMaster\tts_models\，所以安装包不会变大。
if (Test-OptionalModule -Exe $buildPython -Module 'sherpa_onnx') {
    $nuitkaArgs += @('--include-package=sherpa_onnx', '--include-package-data=sherpa_onnx')
    Write-Ok '朗读离线神经音色: 已包含 sherpa-onnx'
}
else {
    Write-Info '朗读离线神经音色: 未安装 sherpa-onnx，本次不带（不影响系统语音朗读）'
}

if (Test-OptionalModule -Exe $buildPython -Module 'edge_tts') {
    $nuitkaArgs += @('--include-package=edge_tts')
    Write-Ok '朗读在线音色: 已包含 edge-tts'
}
else {
    Write-Info '朗读在线音色: 未安装 edge-tts，本次不带（不影响系统语音朗读）'
}

# 读音纠正（多音字）「自动推断」层的可选依赖（同上，没装就跳过）
if (Test-OptionalModule -Exe $buildPython -Module 'pypinyin') {
    $nuitkaArgs += @('--include-package=pypinyin', '--include-package-data=pypinyin')
    Write-Ok '读音纠正自动推断: 已包含 pypinyin'
}
else {
    Write-Info '读音纠正自动推断: 未安装 pypinyin，本次不带（用户词典与内置规则照常生效）'
}

# 全局媒体键（v1.3.9）的可选依赖：pywinrt 投影包（同上，没装就跳过）
if (Test-OptionalModule -Exe $buildPython -Module 'winrt') {
    $nuitkaArgs += @('--include-package=winrt', '--include-package-data=winrt')
    Write-Ok '全局媒体键: 已包含 winrt 投影'
}
else {
    Write-Info '全局媒体键: 未安装 winrt，本次不带（设置里的开关会自动置灰）'
}

# ---------------- 执行打包 ----------------

if (-not (Test-Path -LiteralPath $OutputDirPath)) {
    $null = New-Item -ItemType Directory -Path $OutputDirPath -Force
}

Write-Info '开始编译...'
Write-Host ''
Write-Host "  $buildPython $($nuitkaArgs -join ' ')" -ForegroundColor DarkGray
Write-Host ''

if ($DryRun) {
    Write-Warn 'DryRun 模式：仅显示命令，未实际编译'
    Wait-Exit
    exit 0
}

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
    Write-Err '打包失败'
    Wait-Exit
    exit $exitCode
}

Write-Ok '打包完成！'
Write-Host ''

$distDir = Join-Path $OutputDirPath "$AppName.dist"
$exePath = Join-Path $distDir "$AppName.exe"

if (Test-Path -LiteralPath $exePath) {
    $exeSize = (Get-Item -LiteralPath $exePath).Length
    Write-Host "输出目录  : $distDir"
    Write-Host ('  可执行文件: {0} ({1:N2} MB)' -f $exePath, ($exeSize / 1MB))

    $dirSize = (Get-ChildItem -LiteralPath $distDir -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    if ($dirSize) { Write-Host ('  目录总大小: {0:N2} MB' -f ($dirSize / 1MB)) }
}
else {
    Write-Warn "未找到输出文件: $exePath"
}

Write-Host ''
Write-Host '注意事项:'
Write-Host "1. 目录版要整个 $AppName.dist 文件夹一起分发，不能只拷 exe"
Write-Host '2. 首次运行可能需要几秒钟初始化'
Write-Host '3. 程序数据将保存在用户 AppData 目录'
Write-Host "4. 直接运行 $AppName\$AppName.exe 启动程序"
Write-Host '5. 需要安装包请用 release.ps1（打包 + Inno Setup 一体）'
Write-Host ''

# ---------------- 收尾 ----------------

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
