@echo off
setlocal
chcp 65001 >/dev/null 2>&1
pushd "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
"%PYTHON_EXE%" "%~dp0kb_tool\main.py" weekly-organize --config "%~dp0kb_tool\config.yaml"
endlocal
