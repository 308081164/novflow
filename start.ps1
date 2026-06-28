$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "已创建 .env，请填入 DEEPSEEK_API_KEY 后重新运行（规则质检可不填）"
}

$venv = Join-Path $Root "backend\.venv"
if (-not (Test-Path $venv)) {
    python -m venv $venv
}
& "$venv\Scripts\pip.exe" install -r backend\requirements.txt -q

Set-Location frontend
if (-not (Test-Path "node_modules")) { npm install }
npm run build
Set-Location $Root

Write-Host "启动 NovFlow: http://127.0.0.1:8000"
& "$venv\Scripts\uvicorn.exe" app.main:app --app-dir backend --host 127.0.0.1 --port 8000