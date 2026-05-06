@echo off
setlocal
chcp 65001 >/dev/null 2>&1
pushd "%~dp0"
set "MONTH=%~1"
if "%MONTH%"=="" set "MONTH=2026-05"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
"%PYTHON_EXE%" "%~dp0kb_tool\main.py" trading-monthly-report --config "%~dp0kb_tool\config.yaml" --month "%MONTH%"
endlocal
