# NovFlow Image Engine launcher (Start Menu / double-click)
# Encoding: UTF-8 BOM required for Windows PowerShell 5.1
# Default: GUI console + system tray (no persistent CMD). Use -Console for legacy mode.
param(
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$env:NOVFLOW_INSTALL_DIR = $Root
if (-not $env:NOVFLOW_DATA_DIR) {
    $env:NOVFLOW_DATA_DIR = Join-Path $env:LOCALAPPDATA "NovFlow\data"
}

$pathEntries = New-Object System.Collections.Generic.List[string]
[void]$pathEntries.Add($Root)
$parentRoot = Split-Path -Parent $Root
if (Test-Path -LiteralPath (Join-Path $parentRoot "shared")) {
    [void]$pathEntries.Add($parentRoot)
}
$env:PYTHONPATH = [string]::Join(";", $pathEntries)

$LogDir = Join-Path $env:NOVFLOW_DATA_DIR "logs"
$LogFile = Join-Path $LogDir "image-engine.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-EngineLog([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Show-EngineError([string]$Message) {
    Write-EngineLog "ERROR: $Message"
    if ($Console -or $env:NOVFLOW_NO_UI -eq "1") {
        Write-Host $Message -ForegroundColor Red
        if ($env:NOVFLOW_NO_UI -eq "1") { return }
    }
    $title = "NovFlow " + [char]0x672C + [char]0x5730 + [char]0x751F + [char]0x56FE + [char]0x5F15 + [char]0x64CE
    try {
        Add-Type -AssemblyName PresentationFramework -ErrorAction Stop
        [System.Windows.MessageBox]::Show(
            $Message,
            $title,
            [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Error
        ) | Out-Null
    } catch {
        try {
            Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
            [System.Windows.Forms.MessageBox]::Show(
                $Message,
                $title,
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            ) | Out-Null
        } catch {
            if ($Console) { Read-Host "Press Enter to close" }
        }
    }
}

function Test-EngineDeps([string]$PythonExe) {
    & $PythonExe -c "import uvicorn, fastapi, PIL, cryptography, pydantic, pystray" 1>$null 2>$null
    $code = $LASTEXITCODE
    if ($null -eq $code) { return $false }
    return ($code -eq 0)
}

function Invoke-PipWithMirrors {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string[]]$InstallArgs,
        [string]$Label = "pip install"
    )
    $mirrors = @(
        @{ Index = $null; TrustedHost = $null; Name = "PyPI (default)" },
        @{ Index = "https://pypi.tuna.tsinghua.edu.cn/simple"; TrustedHost = "pypi.tuna.tsinghua.edu.cn"; Name = "Tsinghua mirror" },
        @{ Index = "https://mirrors.aliyun.com/pypi/simple/"; TrustedHost = "mirrors.aliyun.com"; Name = "Aliyun mirror" }
    )
    foreach ($mirror in $mirrors) {
        $pipArgs = @("-m", "pip", "install", "--default-timeout", "300")
        if ($mirror.Index) {
            $pipArgs += @("--index-url", $mirror.Index, "--trusted-host", $mirror.TrustedHost)
        }
        $pipArgs += $InstallArgs
        Write-EngineLog "$Label via $($mirror.Name)"
        if ($Console) { Write-Host "    $Label via $($mirror.Name)..." }
        & $PythonExe @pipArgs *>> $LogFile
        if ($LASTEXITCODE -eq 0) { return $true }
        if ($Console) { Write-Host "    $Label failed on $($mirror.Name), trying next..." -ForegroundColor Yellow }
    }
    return $false
}

function Resolve-SystemPython {
    foreach ($spec in @(
        @{ Cmd = "py"; Args = @("-3", "-c", "import sys; print(sys.executable)") },
        @{ Cmd = "python"; Args = @("-c", "import sys; print(sys.executable)") }
    )) {
        $cmd = Get-Command $spec.Cmd -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $exe = & $spec.Cmd @($spec.Args) 2>$null
            if ($exe -and (Test-Path -LiteralPath $exe)) { return $exe.Trim() }
        } catch {
            continue
        }
    }
    return $null
}

function Resolve-EnginePython {
    $runtimePy = Join-Path $Root "runtime\Scripts\python.exe"
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"

    if ((Test-Path -LiteralPath $runtimePy) -and (Test-EngineDeps $runtimePy)) {
        return $runtimePy
    }
    if ((Test-Path -LiteralPath $venvPy) -and (Test-EngineDeps $venvPy)) {
        return $venvPy
    }
    return $null
}

function Ensure-EnginePython {
    $ready = Resolve-EnginePython
    if ($ready) { return $ready }

    $runtimePy = Join-Path $Root "runtime\Scripts\python.exe"
    if (Test-Path -LiteralPath $runtimePy) {
        $nl = [Environment]::NewLine
        $msg = "安装目录中的 runtime 不完整（缺少 uvicorn / pystray 等依赖）。" + $nl + "请重新运行 NovFlowImageEngineDLCSetup.exe 安装。" + $nl + $nl + "日志：$LogFile"
        Show-EngineError $msg
        exit 1
    }

    if ($Console) { Write-Host "正在准备运行环境（首次启动可能需要几分钟）..." }
    Write-EngineLog "No bundled runtime; bootstrapping .venv for source run"
    $bootstrap = Resolve-SystemPython
    if (-not $bootstrap) {
        $nl = [Environment]::NewLine
        $msg = "未找到 Python 3。请安装 Python 3.10+（勾选 Add python.exe to PATH），或使用官方 DLC 安装包（自带 runtime）。" + $nl + $nl + "日志：$LogFile"
        Show-EngineError $msg
        exit 1
    }

    $VenvDir = Join-Path $Root ".venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    try {
        if (-not (Test-Path -LiteralPath $VenvPython)) {
            & $bootstrap -m venv $VenvDir
            if ($LASTEXITCODE -ne 0) { throw "venv exit $LASTEXITCODE" }
        }
        if (-not (Invoke-PipWithMirrors -PythonExe $VenvPython -Label "upgrade pip" -InstallArgs @("--upgrade", "pip", "-q"))) {
            throw "pip upgrade failed"
        }
        $req = Join-Path $Root "requirements.txt"
        if (-not (Invoke-PipWithMirrors -PythonExe $VenvPython -Label "install requirements" -InstallArgs @("-r", $req))) {
            throw "pip install requirements failed"
        }
        if (-not (Test-EngineDeps $VenvPython)) { throw "imports still failing after pip install" }
        return $VenvPython
    } catch {
        $nl = [Environment]::NewLine
        $msg = "安装依赖失败：$($_.Exception.Message)" + $nl + "请检查网络后重试。" + $nl + $nl + "日志：$LogFile"
        Show-EngineError $msg
        exit 1
    }
}

function Resolve-Pythonw([string]$PythonExe) {
    $dir = Split-Path -Parent $PythonExe
    $pythonw = Join-Path $dir "pythonw.exe"
    if (Test-Path -LiteralPath $pythonw) { return $pythonw }
    return $PythonExe
}

Write-EngineLog "=== NovFlow Image Engine start ==="
Write-EngineLog "APP_DIR=$Root"

$Python = Ensure-EnginePython
Write-EngineLog "Python=$Python"

$engineArgs = @("-u", "-m", "image_engine")
if ($Console) {
    $engineArgs += "--console"
    Write-EngineLog "Starting image_engine (console mode) with $Python"
    try {
        & $Python @engineArgs
        $rc = $LASTEXITCODE
        if ($rc -ne 0) {
            Write-EngineLog "image_engine exited with code $rc"
            exit $rc
        }
    } catch {
        $nl = [Environment]::NewLine
        $msg = "启动失败：$($_.Exception.Message)" + $nl + $nl + "日志：$LogFile"
        Show-EngineError $msg
        exit 1
    }
    exit 0
}

# GUI mode: launch without a persistent console window
$Pythonw = Resolve-Pythonw $Python
Write-EngineLog "Starting image_engine (GUI/tray) with $Pythonw"
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Pythonw
    $psi.Arguments = "-u -m image_engine"
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables["NOVFLOW_INSTALL_DIR"] = $Root
    $psi.EnvironmentVariables["NOVFLOW_DATA_DIR"] = $env:NOVFLOW_DATA_DIR
    $psi.EnvironmentVariables["PYTHONPATH"] = $env:PYTHONPATH
    if ($env:LOCALAPPDATA) { $psi.EnvironmentVariables["LOCALAPPDATA"] = $env:LOCALAPPDATA }
    if ($env:PROGRAMDATA) { $psi.EnvironmentVariables["PROGRAMDATA"] = $env:PROGRAMDATA }
    if ($env:APPDATA) { $psi.EnvironmentVariables["APPDATA"] = $env:APPDATA }
    if ($env:USERPROFILE) { $psi.EnvironmentVariables["USERPROFILE"] = $env:USERPROFILE }
    if ($env:SystemRoot) { $psi.EnvironmentVariables["SystemRoot"] = $env:SystemRoot }
    if ($env:PATH) { $psi.EnvironmentVariables["PATH"] = $env:PATH }
    $proc = [System.Diagnostics.Process]::Start($psi)
    if (-not $proc) { throw "Process.Start returned null" }
    Write-EngineLog "GUI process started pid=$($proc.Id)"
} catch {
    $nl = [Environment]::NewLine
    $msg = "启动失败：$($_.Exception.Message)" + $nl + $nl + "日志：$LogFile"
    Show-EngineError $msg
    exit 1
}
