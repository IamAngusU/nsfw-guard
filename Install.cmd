@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -e ".[cpu]"
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\nsfw-guard.exe" model install
if errorlevel 1 exit /b %errorlevel%
echo NSFW Guard is ready.
