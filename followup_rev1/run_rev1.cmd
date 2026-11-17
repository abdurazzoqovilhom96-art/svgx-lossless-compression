@echo off
rem SVGX-REV1: approved experiments on the confirmation split (R0 -> B1 -> B3 -> B2 -> analysis).
rem Nothing runs without state\approval_rev1.json bound to the current state\freeze_rev1.json.
setlocal
for /f "tokens=2 delims=:." %%a in ('chcp') do set "_OLDCP=%%a"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=D:\13.11.2026\SVG_EXPERIMENT\.venv\Scripts\python.exe"
pushd "%~dp0"
"%PY%" rev1\run_all.py %*
set "RC=%ERRORLEVEL%"
popd
chcp %_OLDCP% >nul
exit /b %RC%
