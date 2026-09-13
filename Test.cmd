@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -e ".[dev]"
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" scripts\validate_local.py
exit /b %errorlevel%
