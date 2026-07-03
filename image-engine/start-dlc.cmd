@echo off
setlocal
cd /d "%~dp0"
set NOVFLOW_INSTALL_DIR=%~dp0
set NOVFLOW_DATA_DIR=%LOCALAPPDATA%\NovFlow\data
set PYTHONPATH=%~dp0;%~dp0..
if exist "%~dp0..\runtime\Scripts\python.exe" (
  "%~dp0..\runtime\Scripts\python.exe" -m image_engine
) else (
  py -3 -m image_engine
)
