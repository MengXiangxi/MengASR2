@echo off
setlocal enabledelayedexpansion

echo ================================================
echo  MengASR2 Batch Transcribe Tool
echo ================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Error: Python not found
    pause
    exit /b 1
)

"%PYTHON_EXE%" "%SCRIPT_DIR%batch_transcribe.py" %*

pause