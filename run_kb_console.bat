@echo off
setlocal
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

pushd "%~dp0"
set "PROJECT_ROOT=%CD%"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"

"%PYTHON_EXE%" -m streamlit run "%PROJECT_ROOT%\streamlit_app.py" --server.address 127.0.0.1

endlocal
