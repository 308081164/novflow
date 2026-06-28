@echo off
chcp 65001 >nul
echo ========================================
echo   NovFlow 小说 AI 写作台
echo ========================================
echo.

cd /d "%~dp0"

if not exist ".env" (
  echo [提示] 未找到 .env，从 .env.example 复制...
  copy .env.example .env >nul
  echo [提示] 请编辑 novflow\.env 填入 DEEPSEEK_API_KEY
)

echo [1/3] 启动后端 (端口 8000)...
start "NovFlow Backend" cmd /k "cd backend && python -m venv venv 2>nul && call venv\Scripts\activate && pip install -r requirements.txt -q && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

timeout /t 3 /nobreak >nul

echo [2/3] 启动前端 (端口 5173)...
start "NovFlow Frontend" cmd /k "cd frontend && npm install && npm run dev"

echo.
echo [3/3] 完成！
echo   前端: http://localhost:5173
echo   后端: http://localhost:8000/api/health
echo   演示账号: demo@novflow.local / demo123456
echo.
pause
