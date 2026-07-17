@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Prefer bundled runtime; start-dlc.ps1 never relies on global uvicorn.
set "NOVFLOW_INSTALL_DIR=%CD%"
set "NOVFLOW_DATA_DIR=%LOCALAPPDATA%\NovFlow\data"
set "PYTHONPATH=%CD%"

where powershell >nul 2>&1
if errorlevel 1 (
  echo PowerShell is required to start NovFlow Image Engine.
  pause
  exit /b 1
)

rem Pass --console / -Console through for legacy foreground mode.
set "PS_ARGS=-NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dlc.ps1""
if /I "%~1"=="--console" set "PS_ARGS=%PS_ARGS% -Console"
if /I "%~1"=="-Console" set "PS_ARGS=%PS_ARGS% -Console"

if /I "%~1"=="--console" goto run_visible
if /I "%~1"=="-Console" goto run_visible

rem GUI mode: hide the launcher PowerShell window (engine runs in pythonw + tray)
start "" /b powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start-dlc.ps1"
exit /b 0

:run_visible
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dlc.ps1" -Console
exit /b %ERRORLEVEL%
