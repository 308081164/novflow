$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$venv = Join-Path $Root "backend\.venv"
if (-not (Test-Path $venv)) {
    py -m venv $venv
    & "$venv\Scripts\python.exe" -m pip install -r backend\requirements.txt -q
}

& "$venv\Scripts\uvicorn.exe" app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
