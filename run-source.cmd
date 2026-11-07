@echo off
rem Run dsh-token-bill from source (no exe needed).
rem Use this when Windows blocks the unsigned exe (Smart App Control / WDAC),
rem or when you simply prefer reading the code first.
setlocal
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
  where python >nul 2>nul && set PY=python
)
if not defined PY goto :nopy

echo Running: %PY% token_bill.py
echo.
%PY% token_bill.py %*
echo.
pause
exit /b 0

:nopy
echo.
echo Python not found.
echo 1. Install Python 3.12 or newer from https://www.python.org/downloads/
echo 2. Tick "Add python.exe to PATH" during setup
echo 3. Run this file again
echo.
pause
exit /b 1
