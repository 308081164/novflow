# NovFlow Windows desktop installer staging build
# Output: dist/novflow-installer-stage/ (Electron shell + Python sidecar)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $Root

$Stage = Join-Path $Root "dist\novflow-installer-stage"
$ElectronBuild = Join-Path $Root "dist\electron-build"
$ElectronDir = Join-Path $Root "desktop\electron"

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

function Get-VenvTool {
    param([string]$RuntimeRoot, [string]$Name)
    $scripts = Join-Path -Path $RuntimeRoot -ChildPath ("Scripts\" + $Name)
    if (Test-Path $scripts) { return $scripts }
    $bin = Join-Path -Path $RuntimeRoot -ChildPath ("bin\" + $Name)
    if (Test-Path $bin) { return $bin }
    return $null
}

function Invoke-PipInstall {
    param(
        [string]$PipExe,
        [string]$PythonExe,
        [Parameter(Mandatory = $true)][string[]]$InstallArgs,
        [string]$Label = "pip install"
    )
    if (-not $PipExe -and -not $PythonExe) {
        throw "Invoke-PipInstall requires PipExe or PythonExe"
    }
    $mirrors = @(
        @{ Index = $null; TrustedHost = $null; Name = "PyPI (default)" },
        @{ Index = "https://pypi.tuna.tsinghua.edu.cn/simple"; TrustedHost = "pypi.tuna.tsinghua.edu.cn"; Name = "Tsinghua mirror" },
        @{ Index = "https://mirrors.aliyun.com/pypi/simple/"; TrustedHost = "mirrors.aliyun.com"; Name = "Aliyun mirror" }
    )
    $lastError = $null
    foreach ($mirror in $mirrors) {
        $pipArgs = @("install", "--default-timeout", "300")
        if ($mirror.Index) {
            $pipArgs += @("--index-url", $mirror.Index, "--trusted-host", $mirror.TrustedHost)
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
    }
    throw "$Label failed after PyPI and mirror retries ($lastError)"
}

function Stop-StageLockingProcesses {
    param([string]$StagePath)
    $needle = "novflow-installer-stage"
    foreach ($name in @("python.exe", "pip.exe", "uvicorn.exe", "NovFlow.exe")) {
        Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue | ForEach-Object {
            $cmd = $_.CommandLine
            $exe = $_.ExecutablePath
            if (($cmd -and $cmd -like "*$needle*") -or ($exe -and $exe -like "*$needle*")) {
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

$BuildPython = Resolve-BuildPython
Write-Host "==> Using build Python: $BuildPython"

Write-Host "==> Building frontend"
Set-Location (Join-Path $Root "frontend")
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run build
Set-Location $Root

Write-Host "==> Preparing staging directory (Python sidecar)"
Remove-DirectorySafe $Stage
New-Item -ItemType Directory -Path $Stage | Out-Null

Write-Host "==> Creating portable Python runtime"
$Runtime = Join-Path $Stage "runtime"
& $BuildPython -m venv $Runtime --copies
$VenvPython = Get-VenvPython $Runtime
Write-Host "    venv python: $VenvPython"
Invoke-PipInstall -PythonExe $VenvPython -Label "upgrade pip" -InstallArgs @("--upgrade", "pip", "-q")
$VenvPip = Get-VenvTool $Runtime "pip.exe"
if (-not $VenvPip) { $VenvPip = Get-VenvTool $Runtime "pip3.exe" }
if (-not $VenvPip) { throw "pip not found in venv" }
$ReqFile = Join-Path $Root "backend\requirements.txt"
Invoke-PipInstall -PipExe $VenvPip -Label "install requirements" -InstallArgs @("--no-cache-dir", "-r", $ReqFile)
Invoke-PipInstall -PipExe $VenvPip -Label "install tkinter deps" -InstallArgs @("--no-cache-dir", "cryptography", "-q")
$handlersDir = Join-Path $Runtime "Lib\site-packages\passlib\handlers"
if (-not (Test-Path $handlersDir)) {
    Write-Host "    passlib incomplete, reinstalling..."
    Invoke-PipInstall -PipExe $VenvPip -Label "reinstall passlib/bcrypt" -InstallArgs @("--force-reinstall", "--no-cache-dir", "passlib[bcrypt]", "bcrypt>=4.0.1,<4.1", "-q")
}
if (-not (Test-Path $handlersDir)) {
    throw "passlib.handlers still missing - cannot build desktop runtime"
}

Write-Host "==> Copying shared license module"
$SharedDest = Join-Path $Stage "shared"
if (Test-Path $SharedDest) { Remove-Item -Recurse -Force $SharedDest }
Copy-Item -Recurse (Join-Path $Root "shared") $SharedDest -Force

Write-Host "==> Copying backend"
$BackendDest = Join-Path $Stage "backend"
New-Item -ItemType Directory -Path $BackendDest | Out-Null
$ExcludeDirs = @("__pycache__", ".pytest_cache", ".venv", "venv", "tests")
Get-ChildItem (Join-Path $Root "backend") | ForEach-Object {
    if ($ExcludeDirs -contains $_.Name) { return }
    Copy-Item $_.FullName -Destination $BackendDest -Recurse -Force
}

Write-Host "==> Copying frontend/dist"
$FrontendDist = Join-Path $Stage "frontend\dist"
if (Test-Path $FrontendDist) {
    Remove-Item -Recurse -Force $FrontendDist
}
New-Item -ItemType Directory -Path $FrontendDist -Force | Out-Null
Copy-Item -Recurse (Join-Path $Root "frontend\dist\*") $FrontendDist -Force
$assetsDir = Join-Path $FrontendDist "assets"
if (-not (Test-Path $assetsDir)) {
    throw "frontend/dist/assets missing after copy - build frontend first"
}

Write-Host "==> Copying desktop Python scripts"
$DesktopDest = Join-Path $Stage "desktop"
New-Item -ItemType Directory -Path $DesktopDest -Force | Out-Null
foreach ($script in @("backend_launcher.py", "license_gate.py", "license_dialog.py")) {
    Copy-Item (Join-Path $Root "desktop\$script") (Join-Path $DesktopDest $script) -Force
}

Write-Host "==> Syncing brand icons for Electron / installer"
$BrandIco = Join-Path $Root "assets\brand\icon.ico"
$BrandPng = Join-Path $Root "assets\brand\icon.png"
foreach ($required in @($BrandIco, $BrandPng)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Brand icon missing: $required"
    }
}
# electron-builder resolves win.icon from buildResources (build/) and project dir.
$ElectronBuildRes = Join-Path $ElectronDir "build"
New-Item -ItemType Directory -Force -Path $ElectronBuildRes | Out-Null
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $ElectronBuildRes "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $ElectronBuildRes "icon.png") -Force
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $ElectronDir "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $ElectronDir "icon.png") -Force

# Use ASCII-only temp path for rcedit (non-ASCII project paths can break icon embed).
$IconTempDir = Join-Path $env:TEMP "novflow-build-icons"
New-Item -ItemType Directory -Force -Path $IconTempDir | Out-Null
$IconTempIco = Join-Path $IconTempDir "icon.ico"
Copy-Item -LiteralPath $BrandIco -Destination $IconTempIco -Force

Write-Host "==> Building Electron shell"
Remove-DirectorySafe $ElectronBuild
Set-Location $ElectronDir
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run dist
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
Set-Location $Root

$ElectronUnpacked = Join-Path $ElectronBuild "win-unpacked"
$UnpackedExe = Join-Path $ElectronUnpacked "NovFlow.exe"
if (-not (Test-Path -LiteralPath $UnpackedExe)) {
    throw "Electron build did not produce NovFlow.exe in win-unpacked"
}

# Force-embed brand icon via rcedit on ASCII-only temp paths (non-ASCII project
# paths can leave the default Electron atom icon in the PE resource).
Write-Host "==> Embedding brand icon into NovFlow.exe"
$Rcedit = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "electron-builder\Cache\winCodeSign") -Recurse -Filter "rcedit-x64.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $Rcedit) {
    throw "rcedit-x64.exe not found under %LOCALAPPDATA%\electron-builder\Cache\winCodeSign (run electron-builder once to download it)"
}
$ExeTemp = Join-Path $IconTempDir "NovFlow.exe"
Copy-Item -LiteralPath $UnpackedExe -Destination $ExeTemp -Force
& $Rcedit $ExeTemp --set-icon $IconTempIco
if ($LASTEXITCODE -ne 0) { throw "rcedit failed to set NovFlow.exe icon" }
Copy-Item -LiteralPath $ExeTemp -Destination $UnpackedExe -Force

# Loose icons next to exe (Inno shortcuts) and under resources (BrowserWindow).
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $ElectronUnpacked "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $ElectronUnpacked "icon.png") -Force
$UnpackedResources = Join-Path $ElectronUnpacked "resources"
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $UnpackedResources "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $UnpackedResources "icon.png") -Force

Write-Host "==> Merging Electron output into staging"
Get-ChildItem -LiteralPath $ElectronUnpacked | ForEach-Object {
    $dest = Join-Path $Stage $_.Name
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
    }
    Copy-Item -LiteralPath $_.FullName -Destination $Stage -Recurse -Force
}

# Sidecar lives under resources/novflow; remove duplicate top-level copies from staging prep.
foreach ($name in @("runtime", "backend", "frontend", "shared", "desktop")) {
    $dup = Join-Path $Stage $name
    if (Test-Path -LiteralPath $dup) {
        Remove-Item -LiteralPath $dup -Recurse -Force
    }
}

if (-not (Test-Path (Join-Path $Stage "NovFlow.exe"))) {
    throw "NovFlow.exe missing after Electron merge"
}
if (-not (Test-Path (Join-Path $Stage "icon.ico"))) {
    throw "icon.ico missing at install root - shortcuts would fall back to wrong icon"
}
if (-not (Test-Path (Join-Path $Stage "resources\icon.ico"))) {
    throw "resources\icon.ico missing - BrowserWindow taskbar icon would be wrong"
}
if (-not (Test-Path (Join-Path $Stage "resources\novflow\runtime\Scripts\python.exe"))) {
    throw "resources/novflow runtime missing - extraResources packaging failed"
}

Write-Host ""
Write-Host "Staging complete: $Stage"
Write-Host "Next: run .\package-desktop.ps1 (or iscc installer/novflow.iss)"
