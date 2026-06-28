# NovFlow · Docker 一键启动（Windows）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "检查 Docker 引擎..." -ForegroundColor Cyan
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "daemon not running" }
} catch {
    Write-Host ""
    Write-Host "Docker 引擎未运行。" -ForegroundColor Red
    Write-Host "请先打开 Docker Desktop，等待左下角显示 Engine running，再重新运行本脚本。" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "正确命令（在 novflow 目录下，无需 cd docker 子目录）：" -ForegroundColor Gray
    Write-Host "  docker compose build" -ForegroundColor Gray
    Write-Host "  docker compose up -d" -ForegroundColor Gray
    Write-Host "或一条命令：" -ForegroundColor Gray
    Write-Host "  docker compose up -d --build" -ForegroundColor Gray
    exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "已创建 .env，请编辑 DEEPSEEK_API_KEY 后重新运行（可选）" -ForegroundColor Yellow
}

Write-Host "构建并启动容器..." -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "NovFlow 已启动：" -ForegroundColor Green
Write-Host "  前端     http://localhost"
Write-Host "  API 文档 http://localhost:8000/docs"
Write-Host "  MinIO    http://localhost:9001  (账号 novflow / novflowsecret)"
Write-Host ""
Write-Host "查看状态: docker compose ps"
Write-Host "查看日志: docker compose logs -f backend"
