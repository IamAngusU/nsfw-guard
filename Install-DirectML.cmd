@echo off
setlocal
cd /d "%~dp0"
python scripts\bootstrap.py --runtime directml
exit /b %errorlevel%
