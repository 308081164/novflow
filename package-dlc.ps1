# NovFlow Image Engine DLC installer packager
# Output: dist/NovFlowImageEngineDLCSetup.exe

param(
    [switch]$StageOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$IssFile = Join-Path $Root "installer\novflow-dlc.iss"
$SetupExe = Join-Path $Root "dist\NovFlowImageEngineDLCSetup.exe"

function Resolve-InnoSetupCompiler {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Format-FileSize([long]$Bytes) {
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

Write-Host "NovFlow Image Engine DLC installer pack" -ForegroundColor Green

if (-not $StageOnly) {
    $iscc = Resolve-InnoSetupCompiler
    if (-not $iscc) {
        Write-Host "Inno Setup 6 not found." -ForegroundColor Red
        exit 1
    }
    Write-Host "==> Compiling DLC installer"
    & $iscc $IssFile
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (Test-Path $SetupExe) {
    $info = Get-Item $SetupExe
    Write-Host ""
    Write-Host "DLC installer:" -ForegroundColor Green
    Write-Host "  $($info.FullName)"
    Write-Host "  Size: $(Format-FileSize $info.Length)"
} else {
    Write-Host "Setup not found: $SetupExe" -ForegroundColor Yellow
}
