@echo off
setlocal
pushd "%~dp0"
if "%~1"=="" (
  echo Usage: Vision-Enrich.cmd SUMMARY_JSON [VISION_CONFIG]
  echo Example: Vision-Enrich.cmd "C:\Pictures\.nsfw-guard\latest-summary.json" vision.toml
  popd
  exit /b 2
)
set "CONFIG=%~2"
if "%CONFIG%"=="" set "CONFIG=vision.toml"
if not exist ".venv\Scripts\nsfw-guard.exe" (
  echo NSFW Guard is not installed. Run Install.cmd first.
  popd
  exit /b 2
)
".venv\Scripts\nsfw-guard.exe" vision enrich "%~1" --config "%CONFIG%"
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
