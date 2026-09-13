@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\nsfw-guard.exe" (
  echo Run Install.cmd first.
  exit /b 2
)
if not exist ".artifacts" mkdir ".artifacts"
".venv\Scripts\nsfw-guard.exe" benchmark --runs 30 --warmups 3 --output ".artifacts\benchmark.json"
exit /b %errorlevel%
