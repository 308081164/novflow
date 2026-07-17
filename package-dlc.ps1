# NovFlow 本地生图引擎 (Image Engine DLC) installer packager
# Stages a portable Python runtime (with uvicorn/fastapi/...) then builds the installer.
# Output: dist/NovFlowImageEngineDLCSetup.exe

param(
    [switch]$StageOnly,
    [switch]$BundleLite
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Stage = Join-Path $Root "dist\novflow-dlc-stage"
$IssFile = Join-Path $Root "installer\novflow-dlc.iss"
$SetupExe = Join-Path $Root "dist\NovFlowImageEngineDLCSetup.exe"
$ReqFile = Join-Path $Root "image-engine\requirements.txt"
$ReqInferenceFile = Join-Path $Root "image-engine\requirements-inference.txt"



function Resolve-BuildPython {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    foreach ($ver in @("3.12", "3.11", "3.13")) {
        try {
            $py = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
            if ($py -and (Test-Path $py)) { return $py.Trim() }
        } catch { }
    }
    $fallback = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if ($fallback -and $fallback -notmatch "msys|mingw|ucrt64") {
        return $fallback
    }
    throw "Windows Python 3.11+ not found. Install from python.org (avoid MSYS python on PATH)."
}



function Get-VenvPython {
    param([string]$RuntimeRoot)
    $scripts = Join-Path -Path $RuntimeRoot -ChildPath "Scripts\python.exe"
    if (Test-Path $scripts) { return $scripts }
    $bin = Join-Path -Path $RuntimeRoot -ChildPath "bin\python.exe"
    if (Test-Path $bin) { return $bin }
    throw "venv python.exe missing under $RuntimeRoot"
}



function Get-CertBundle {
    param([string]$PythonExe)
    try {
        $cert = & $PythonExe -c "import certifi; print(certifi.where())" 2>$null
        if ($cert -and (Test-Path -LiteralPath $cert.Trim())) { return $cert.Trim() }
    } catch { }
    return $null
}

function Repair-VenvPip {
    param([string]$PythonExe)
    Write-Host "    repairing venv pip..."
    & $PythonExe -m ensurepip --upgrade 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $PythonExe -m ensurepip --default-pip 2>$null
    }
    Invoke-PipInstall -PythonExe $PythonExe -Label "reinstall pip" -InstallArgs @("--upgrade", "pip", "setuptools", "wheel", "certifi") -SkipRepair
}

function Invoke-PipInstall {
    param(
        [string]$PipExe,
        [string]$PythonExe,
        [Parameter(Mandatory = $true)][string[]]$InstallArgs,
        [string]$Label = "pip install",
        [switch]$SkipRepair
    )
    if (-not $PipExe -and -not $PythonExe) {
        throw "Invoke-PipInstall requires PipExe or PythonExe"
    }
    $mirrors = @(
        @{ Index = $null; Name = "PyPI (default)" },
        @{ Index = "https://pypi.tuna.tsinghua.edu.cn/simple"; Name = "Tsinghua mirror" },
        @{ Index = "https://mirrors.aliyun.com/pypi/simple/"; Name = "Aliyun mirror" }
    )
    $trustedHosts = @("pypi.org", "files.pythonhosted.org", "pypi.tuna.tsinghua.edu.cn", "mirrors.aliyun.com")
    $lastError = $null
    foreach ($mirror in $mirrors) {
        $pipArgs = @("install", "--default-timeout", "600", "--retries", "5")
        foreach ($hostName in $trustedHosts) {
            $pipArgs += @("--trusted-host", $hostName)
        }
        if ($mirror.Index) {
            $pipArgs += @("--index-url", $mirror.Index)
        }
        $pipArgs += $InstallArgs
        Write-Host "    $Label via $($mirror.Name)..."
        if ($PipExe) {
            & $PipExe @pipArgs
        } else {
            & $PythonExe -m pip @pipArgs
        }
        if ($LASTEXITCODE -eq 0) { return }
        $lastError = "exit code $LASTEXITCODE"
        Write-Host "    $Label failed on $($mirror.Name), trying next source..." -ForegroundColor Yellow
        if (-not $SkipRepair -and $PythonExe) {
            Repair-VenvPip -PythonExe $PythonExe
        }
    }
    throw "$Label failed after PyPI and mirror retries ($lastError)"
}

function Test-RuntimeBase([string]$PythonExe) {
    & $PythonExe -c "import uvicorn, fastapi, PIL, cryptography, pydantic, pystray" 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-RuntimeInference([string]$PythonExe) {
    & $PythonExe -c "import torch, diffusers" 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
}




function Stop-StageLockingProcesses {
    param([string]$StagePath)
    $stageRoot = (Resolve-Path -LiteralPath $StagePath -ErrorAction SilentlyContinue).Path
    if (-not $stageRoot) { $stageRoot = $StagePath }
    $needle = "novflow-dlc-stage"
    foreach ($name in @("python.exe", "pythonw.exe", "pip.exe", "uvicorn.exe", "NovFlow.exe")) {
        Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue | ForEach-Object {
            $cmd = $_.CommandLine
            $exe = $_.ExecutablePath
            $inStage = ($cmd -and ($cmd -like "*$needle*" -or $cmd -like "*$stageRoot*")) -or ($exe -and ($exe -like "*$needle*" -or $exe -like "*$stageRoot*"))
            if ($inStage) {
                Write-Host "    stopping $($_.ProcessId): $name"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 1
}




function Remove-DirectorySafe {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Stop-StageLockingProcesses $Path
    for ($i = 1; $i -le 6; $i++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            Write-Host "    cleanup retry $i/6: $($_.Exception.Message)"
            Stop-StageLockingProcesses $Path
            Start-Sleep -Seconds 2
        }
    }
    $bakName = (Split-Path $Path -Leaf) + ".old-" + (Get-Date -Format "yyyyMMddHHmmss")
    $bakPath = Join-Path (Split-Path $Path -Parent) $bakName
    Write-Host "    rename locked dir -> $bakName"
    Rename-Item -LiteralPath $Path -NewName $bakName -ErrorAction Stop
}



function Resolve-InnoSetupCompiler {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source)) { return $cmd.Source }
    return $null
}



function Format-FileSize([long]$Bytes) {
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}



Write-Host "NovFlow 本地生图引擎 installer pack" -ForegroundColor Green

if (-not (Test-Path -LiteralPath $ReqFile)) {
    throw "Missing requirements: $ReqFile"
}

$BuildPython = Resolve-BuildPython
Write-Host "==> Using build Python: $BuildPython"
$CertBundle = Get-CertBundle $BuildPython
if ($CertBundle) {
    $env:SSL_CERT_FILE = $CertBundle
    $env:REQUESTS_CA_BUNDLE = $CertBundle
    Write-Host "    SSL cert bundle: $CertBundle"
}

Write-Host "==> Preparing DLC stage: $Stage"
Remove-DirectorySafe $Stage
New-Item -ItemType Directory -Path $Stage | Out-Null

Write-Host "==> Creating portable Python runtime (with image-engine deps)"
$Runtime = Join-Path $Stage "runtime"
& $BuildPython -m venv $Runtime --copies
$VenvPython = Get-VenvPython $Runtime
Write-Host "    venv python: $VenvPython"
Repair-VenvPip -PythonExe $VenvPython
Invoke-PipInstall -PythonExe $VenvPython -Label "install base requirements" -InstallArgs @("--no-cache-dir", "-r", $ReqFile)
if (-not (Test-RuntimeBase $VenvPython)) {
    throw "Bundled runtime missing uvicorn/fastapi/Pillow after pip install"
}
Write-Host "    base runtime OK"

if (Test-Path -LiteralPath $ReqInferenceFile) {
    Write-Host "==> Installing inference stack (torch/diffusers, may take several minutes)"
    try {
        Invoke-PipInstall -PythonExe $VenvPython -Label "install inference requirements" -InstallArgs @("--no-cache-dir", "-r", $ReqInferenceFile)
        if (Test-RuntimeInference $VenvPython) {
            Write-Host "    inference runtime OK" -ForegroundColor Green
        } else {
            Write-Host "    inference deps incomplete - engine will use placeholder mode until fixed" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "    inference install failed: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "    engine will run in placeholder mode; retry build or install torch manually" -ForegroundColor Yellow
    }
}

Write-Host "==> Copying image-engine sources"
$EngineSrc = Join-Path $Root "image-engine"
$excludeNames = @(".venv", "runtime", "__pycache__", ".pytest_cache")
Get-ChildItem -LiteralPath $EngineSrc -Force | ForEach-Object {
    if ($excludeNames -contains $_.Name) { return }
    if ($_.Name -like "_*.py") { return }
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Stage $_.Name) -Recurse -Force
}

Write-Host "==> Copying shared license module"
Copy-Item -Recurse (Join-Path $Root "shared") (Join-Path $Stage "shared") -Force

Write-Host "==> Copying license dialog"
$DesktopDest = Join-Path $Stage "desktop"
New-Item -ItemType Directory -Path $DesktopDest -Force | Out-Null
Copy-Item (Join-Path $Root "desktop\license_dialog.py") (Join-Path $DesktopDest "license_dialog.py") -Force

Write-Host "==> Copying DLC EULA for console"
Copy-Item (Join-Path $Root "installer\LICENSE-DLC.txt") (Join-Path $Stage "LICENSE-DLC.txt") -Force

Write-Host "==> Preparing models directory under install root"
$ModelsLite = Join-Path $Stage "models\lite"
New-Item -ItemType Directory -Path $ModelsLite -Force | Out-Null
$LiteFileName = "v1-5-pruned-emaonly.safetensors"
$LiteDest = Join-Path $ModelsLite $LiteFileName
$LiteMinBytes = 100MB

function Test-ValidLiteModel([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    return ((Get-Item -LiteralPath $Path).Length -ge $LiteMinBytes)
}

function Invoke-DownloadLiteModel {
    param([string]$Destination)
    $urls = @(
        "https://modelscope.cn/models/AI-ModelScope/stable-diffusion-v1-5/resolve/master/v1-5-pruned-emaonly.safetensors",
        "https://hf-mirror.com/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors"
    )
    $tmp = "$Destination.part"
    foreach ($url in $urls) {
        Write-Host "    Trying: $url"
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -TimeoutSec 3600
            if ((Get-Item -LiteralPath $tmp).Length -ge $LiteMinBytes) {
                Move-Item -LiteralPath $tmp -Destination $Destination -Force
                return $true
            }
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Host "    Failed: $($_.Exception.Message)" -ForegroundColor Yellow
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }
    return $false
}

$bundledLite = $false
if (Test-ValidLiteModel $LiteDest) {
    Write-Host "    Lite model already present in stage"
    $bundledLite = $true
} elseif ($BundleLite) {
    Write-Host "==> Bundling Lite SD 1.5 model (~4 GB, may take a while)"
    $bundledLite = Invoke-DownloadLiteModel -Destination $LiteDest
    if ($bundledLite) {
        $liteSize = Format-FileSize (Get-Item -LiteralPath $LiteDest).Length
        Write-Host "    Lite model bundled: $liteSize" -ForegroundColor Green
    } else {
        Write-Host "    Lite download failed - installer will use first-run GUI download" -ForegroundColor Yellow
    }
} else {
    Write-Host "    Lite model not bundled (pass -BundleLite to include ~4GB SD 1.5 in installer)"
}

if (-not $bundledLite) {
    @"
NovFlow Image Engine - Lite model notes
=======================================

This installer does not include the Lite SD 1.5 base model (~4 GB).

On first launch, use the Models page in the console to download Lite (ModelScope mirror).

Or build with:
  .\package-dlc.ps1 -BundleLite

Manual: copy v1-5-pruned-emaonly.safetensors into this folder.
"@ | Set-Content -Path (Join-Path $ModelsLite "README.txt") -Encoding UTF8
}

$StagePython = Get-VenvPython (Join-Path $Stage "runtime")
if (-not (Test-RuntimeBase $StagePython)) {
    throw "Stage runtime verification failed"
}
Write-Host "==> Stage ready: $Stage"

if ($StageOnly) {
    Write-Host "StageOnly: skipping Inno Setup compile"
    exit 0
}

$iscc = Resolve-InnoSetupCompiler
if (-not $iscc) {
    Write-Host "Inno Setup 6 not found." -ForegroundColor Red
    exit 1
}
Write-Host "==> Compiling NovFlow 本地生图引擎 installer"
& $iscc $IssFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (Test-Path $SetupExe) {
    $info = Get-Item $SetupExe
    Write-Host ""
    Write-Host "NovFlow 本地生图引擎 installer:" -ForegroundColor Green
    Write-Host "  $($info.FullName)"
    Write-Host "  Size: $(Format-FileSize $info.Length)"
    Write-Host "  AppName / Start Menu: NovFlow 本地生图引擎"
    Write-Host "  DefaultDir: {autopf}\NovFlowImageEngine"
    Write-Host "  Bundled: runtime\Scripts\python.exe + image-engine requirements (GUI + pystray + diffusers)"
    if (Test-Path (Join-Path $Stage "models\lite\v1-5-pruned-emaonly.safetensors")) {
        Write-Host "  Models: Lite SD 1.5 bundled under models\lite\"
    } else {
        Write-Host "  Models: first-run one-click download (models\ under install dir)"
    }
    Write-Host "  Launch: GUI console + system tray (start-dlc.cmd); --console for legacy CMD"
    Write-Host "  Languages: Simplified Chinese (default) + English"
} else {
    Write-Host "Setup not found: $SetupExe" -ForegroundColor Yellow
    exit 1
}


