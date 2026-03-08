@echo off
setlocal

if "%~1"=="" (
  echo Usage: run-tool.bat ^<tool^> [tool args...]
  exit /b 2
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
set "RUNNER=%ROOT%\scripts\run_tool_with_timeout.py"

where py >nul 2>&1
if not errorlevel 1 goto use_py

where python >nul 2>&1
if not errorlevel 1 goto use_python

echo Python interpreter not found. Install Python 3.9+ first.
exit /b 1

:use_py
py -3 "%RUNNER%" %*
set "CMD_EXIT=%ERRORLEVEL%"
exit /b %CMD_EXIT%

:use_python
python "%RUNNER%" %*
set "CMD_EXIT=%ERRORLEVEL%"
exit /b %CMD_EXIT%
