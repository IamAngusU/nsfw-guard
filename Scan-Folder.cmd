@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\nsfw-guard.exe" (
  echo Run Install.cmd or Install-DirectML.cmd first.
  exit /b 2
)
set "TARGET=%~1"
if not defined TARGET set /p "TARGET=Folder to scan: "
if not defined TARGET exit /b 2
set "PROVIDER=cpu"
if /i "%~2"=="directml" set "PROVIDER=directml"
if /i "%~2"=="cuda" set "PROVIDER=cuda"
if /i "%PROVIDER%"=="cuda" (
  ".venv\Scripts\nsfw-guard.exe" folder "%TARGET%" --provider cuda --cuda-arena-limit-mib 64 --links
) else (
  ".venv\Scripts\nsfw-guard.exe" folder "%TARGET%" --provider "%PROVIDER%" --links
)
exit /b %errorlevel%
