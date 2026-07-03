# NovFlow Windows offline installer one-click packager
# Output: dist/NovFlowSetup.exe, dist/novflow-installer-stage/
#
# Usage:
#   .\package-desktop.ps1              # full pack (staging + Inno Setup)
#   .\package-desktop.ps1 -StageOnly   # staging only, no installer

param(
    [switch]$StageOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Stage = Join-Path $Root "dist\novflow-installer-stage"
$SetupExe = Join-Path $Root "dist\NovFlowSetup.exe"
$IssFile = Join-Path $Root "installer\novflow.iss"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
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

function Test-CommandExists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Format-FileSize([long]$Bytes) {
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

Write-Host "NovFlow offline installer pack" -ForegroundColor Green
Write-Host "Root: $Root" -ForegroundColor Gray

Write-Step "Checking prerequisites"
$missing = @()
if (-not (Test-CommandExists "node")) { $missing += "Node.js - https://nodejs.org/" }
if (-not (Test-CommandExists "npm")) { $missing += "npm (bundled with Node.js)" }

$hasPython = $false
foreach ($ver in @("3.12", "3.11", "3.13")) {
    try {
        & py "-$ver" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $hasPython = $true; break }
    } catch { }
}
if (-not $hasPython) {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd -and $pyCmd.Source -notmatch "msys|mingw|ucrt64") {
        $hasPython = $true
    }
}
if (-not $hasPython) {
    $missing += "Python 3.11+ from python.org (avoid MSYS python on PATH)"
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing dependencies:" -ForegroundColor Red
    foreach ($item in $missing) { Write-Host "  - $item" -ForegroundColor Yellow }
    exit 1
}
Write-Host "  Node / npm / Python OK" -ForegroundColor Gray

if (-not $StageOnly) {
    $iscc = Resolve-InnoSetupCompiler
    if (-not $iscc) {
        Write-Host ""
        Write-Host "Inno Setup 6 (ISCC.exe) not found." -ForegroundColor Red
        Write-Host "Install: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
        Write-Host "Or staging only: .\package-desktop.ps1 -StageOnly" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  Inno Setup: $iscc" -ForegroundColor Gray
}

Write-Step "Building staging (frontend + backend + NovFlow.exe)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "desktop\build.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path (Join-Path $Stage "NovFlow.exe"))) {
    Write-Host "NovFlow.exe not found in staging. Build failed." -ForegroundColor Red
    exit 1
}

if ($StageOnly) {
    Write-Host ""
    Write-Host "Staging ready:" -ForegroundColor Green
    Write-Host "  $Stage\NovFlow.exe"
    Write-Host ""
    Write-Host "For installer, install Inno Setup 6 and run: .\package-desktop.ps1"
    exit 0
}

Write-Step "Compiling installer (Inno Setup)"
& $iscc $IssFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path $SetupExe)) {
    Write-Host "Setup exe not found: $SetupExe" -ForegroundColor Red
    exit 1
}

$setupInfo = Get-Item $SetupExe
$launcherInfo = Get-Item (Join-Path $Stage "NovFlow.exe")

Write-Host ""
Write-Host "Pack complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Installer (for distribution):" -ForegroundColor White
Write-Host "  $($setupInfo.FullName)" -ForegroundColor Gray
Write-Host "  Size: $(Format-FileSize $setupInfo.Length)  Time: $($setupInfo.LastWriteTime)"
Write-Host ""
Write-Host "Portable (no install, local debug):" -ForegroundColor White
Write-Host "  $($launcherInfo.FullName)" -ForegroundColor Gray
Write-Host "  Size: $(Format-FileSize $launcherInfo.Length)"
Write-Host ""
Write-Host "Notes:" -ForegroundColor Gray
Write-Host "  - Launcher uses pywebview (WebView2); falls back to system browser"
Write-Host "  - User data: %LocalAppData%\NovFlow\"
Write-Host "  - Reinstall keeps existing books"
Write-Host "  - Version: edit MyAppVersion in installer\novflow.iss"
