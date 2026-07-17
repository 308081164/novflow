# -*- coding: utf-8 -*-
"""Generate start-dlc.ps1 with UTF-8 BOM for Windows PowerShell 5.1."""
from pathlib import Path

CONTENT = r'''# NovFlow Image Engine launcher (Start Menu / double-click)
# Encoding: UTF-8 BOM required for Windows PowerShell 5.1
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
    Write-Host $Message -ForegroundColor Red
    if ($env:NOVFLOW_NO_UI -eq "1") { return }
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
            Read-Host "Press Enter to close"
        }
    }
}

function Test-EngineDeps([string]$PythonExe) {
    & $PythonExe -c "import uvicorn, fastapi, PIL, cryptography, pydantic" 1>$null 2>$null
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
        Write-Host "    $Label via $($mirror.Name)..."
        & $PythonExe @pipArgs *>> $LogFile
        if ($LASTEXITCODE -eq 0) { return $true }
        Write-Host "    $Label failed on $($mirror.Name), trying next..." -ForegroundColor Yellow
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
    # Prefer bundled portable runtime (installer), then local .venv (source/dev).
    $runtimePy = Join-Path $Root "runtime\Scripts\python.exe"
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"

    if ((Test-Path -LiteralPath $runtimePy) -and (Test-EngineDeps $runtimePy)) {
        return $runtimePy
    }
    if ((Test-Path -LiteralPath $venvPy) -and (Test-EngineDeps $venvPy)) {
        return $venvPy
    }
    # Runtime present but incomplete — still prefer it only if deps ok; otherwise bootstrap .venv
    return $null
}

function Ensure-EnginePython {
    $ready = Resolve-EnginePython
    if ($ready) { return $ready }

    $runtimePy = Join-Path $Root "runtime\Scripts\python.exe"
    if (Test-Path -LiteralPath $runtimePy) {
        $nl = [Environment]::NewLine
        $msg = "安装目录中的 runtime 不完整（缺少 uvicorn 等依赖）。" + $nl + "请重新运行 NovFlowImageEngineDLCSetup.exe 安装。" + $nl + $nl + "日志：$LogFile"
        Show-EngineError $msg
        exit 1
    }

    # Source / dev: create .venv and install requirements (China mirror fallback).
    Write-Host "正在准备运行环境（首次启动可能需要几分钟）..."
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

Write-EngineLog "=== NovFlow Image Engine start ==="
Write-EngineLog "APP_DIR=$Root"

$Python = Ensure-EnginePython
Write-EngineLog "Python=$Python"

Write-Host ""
Write-Host "NovFlow 本地生图引擎"
Write-Host "地址: http://127.0.0.1:17860"
Write-Host "日志: $LogFile"
Write-Host "关闭本窗口将停止引擎。"
Write-Host ""

Write-EngineLog "Starting image_engine with $Python"
try {
    & $Python -u -m image_engine
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
'''

path = Path(__file__).with_name("start-dlc.ps1")
path.write_text(CONTENT, encoding="utf-8-sig")
print(f"wrote {path} ({path.stat().st_size} bytes, BOM=utf-8-sig)")
