@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\nsfw-guard.exe" (
  echo Run Install.cmd first.
  exit /b 2
)
".venv\Scripts\nsfw-guard.exe" chart --history benchmarks --output docs\assets\performance-history.svg
exit /b %errorlevel%
