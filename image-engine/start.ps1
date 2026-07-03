# NovFlow Image Engine stub launcher
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating venv..."
    python -m venv .venv
    & $VenvPython -m pip install -r requirements.txt -q
}

Write-Host "Starting stub on http://127.0.0.1:17860"
& $VenvPython -m image_engine
