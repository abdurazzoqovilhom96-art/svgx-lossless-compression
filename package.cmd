@echo off
rem SVG tajribasi: ZIP paket yaratish va tekshirish. Python ekvivalenti: python study.py package --run-id RUN_ID
setlocal EnableExtensions
set "SVGX_ROOT=%~dp0"
set "SVGX_CMD=package"
set "SVGX_PY=%SVGX_ROOT%.venv\Scripts\python.exe"
set "SVGX_OLDCP="
for /f "tokens=2 delims=:" %%a in ('chcp') do set "SVGX_OLDCP=%%a"
if defined SVGX_OLDCP set "SVGX_OLDCP=%SVGX_OLDCP:.=%"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SVGX_RUNNER="
if exist "%SVGX_PY%" set "SVGX_RUNNER=venv"
if not defined SVGX_RUNNER (
  where py >nul 2>nul
  if not errorlevel 1 (set "SVGX_RUNNER=py") else (set "SVGX_RUNNER=python")
)
if "%SVGX_RUNNER%"=="venv" "%SVGX_PY%" "%SVGX_ROOT%study.py" %SVGX_CMD% %*
if "%SVGX_RUNNER%"=="py" py -3 "%SVGX_ROOT%study.py" %SVGX_CMD% %*
if "%SVGX_RUNNER%"=="python" python "%SVGX_ROOT%study.py" %SVGX_CMD% %*
set "SVGX_RC=%ERRORLEVEL%"
if defined SVGX_OLDCP chcp %SVGX_OLDCP% >nul
endlocal & exit /b %SVGX_RC%
