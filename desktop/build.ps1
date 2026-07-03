# NovFlow Windows desktop installer staging build
# Output: dist/novflow-installer-stage/ (ready for Inno Setup)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $Root

$Stage = Join-Path $Root "dist\novflow-installer-stage"
$BuildDir = Join-Path $Root "desktop\build"

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

function Stop-StageLockingProcesses {
    param([string]$StagePath)
    $needle = "novflow-installer-stage"
    foreach ($name in @("python.exe", "pip.exe", "pyinstaller.exe", "uvicorn.exe")) {
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

Write-Host "==> Preparing staging directory"
Remove-DirectorySafe $Stage
New-Item -ItemType Directory -Path $Stage | Out-Null

Write-Host "==> Creating portable Python runtime"
$Runtime = Join-Path $Stage "runtime"
& $BuildPython -m venv $Runtime --copies
$VenvPython = Get-VenvPython $Runtime
Write-Host "    venv python: $VenvPython"
& $VenvPython -m pip install --upgrade pip -q
$VenvPip = Get-VenvTool $Runtime "pip.exe"
if (-not $VenvPip) { $VenvPip = Get-VenvTool $Runtime "pip3.exe" }
if (-not $VenvPip) { throw "pip not found in venv" }
& $VenvPip install --no-cache-dir -r (Join-Path $Root "backend\requirements.txt") pyinstaller pywebview -q
$handlersDir = Join-Path $Runtime "Lib\site-packages\passlib\handlers"
if (-not (Test-Path $handlersDir)) {
    Write-Host "    passlib incomplete, reinstalling..."
    & $VenvPip install --force-reinstall --no-cache-dir "passlib[bcrypt]" "bcrypt>=4.0.1,<4.1" -q
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

Write-Host "==> Verifying frontend assets"
if (-not (Test-Path $assetsDir)) {
    throw "frontend/dist/assets missing after copy - build frontend first"
}

Write-Host "==> Building NovFlow.exe launcher"
Remove-DirectorySafe $BuildDir
New-Item -ItemType Directory -Path $BuildDir | Out-Null

$Launcher = Join-Path $Root "desktop\launcher.py"
$LicenseDialog = Join-Path $Root "desktop\license_dialog.py"
$PyInstaller = Get-VenvTool $Runtime "pyinstaller.exe"
if (-not $PyInstaller) { throw "pyinstaller.exe not found in venv" }
& $PyInstaller `
    --noconfirm `
    --onefile `
    --noconsole `
    --name NovFlow `
    --paths $Root `
    --paths (Join-Path $Root "desktop") `
    --hidden-import=webview `
    --hidden-import=shared.license `
    --hidden-import=shared.license.license_common `
    --hidden-import=shared.license.license_service `
    --hidden-import=shared.license.hardware_id `
    --hidden-import=shared.license.products `
    --hidden-import=shared.license.license_keys `
    --hidden-import=license_dialog `
    --hidden-import=cryptography `
    --distpath $Stage `
    --workpath $BuildDir `
    --specpath $BuildDir `
    $Launcher $LicenseDialog

if (-not (Test-Path (Join-Path $Stage "NovFlow.exe"))) {
    throw "PyInstaller did not produce NovFlow.exe"
}

Write-Host ""
Write-Host "Staging complete: $Stage"
Write-Host "Next: run .\package-desktop.ps1 (or iscc installer/novflow.iss)"
