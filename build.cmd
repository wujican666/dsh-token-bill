@echo off
rem Build a Windows folder build (exe + _internal) with PyInstaller.
rem Requires: Python 3.14+ (for the stdlib compression.zstd module) and
rem   python -m pip install pyinstaller
rem Output: dist\dsh-token-bill\dsh-token-bill.exe  -- zip this folder and ship it.
rem
rem Why not --onefile: on some machines the onefile bootloader fails with
rem   "[PYI-xxxx:ERROR] Could not create temporary directory!" (reproduced on
rem   Windows 11 build 26200 + PyInstaller 6.22 + Python 3.15, even with a fresh
rem   %TEMP%). The folder build has no extraction step, starts faster and trips
rem   antivirus heuristics far less often. See README "自己打包".
setlocal
cd /d "%~dp0"

set PY=python
where py >nul 2>nul && set PY=py -3

%PY% -m pip show pyinstaller >nul 2>nul || (
  echo [1/2] Installing PyInstaller ...
  %PY% -m pip install pyinstaller || goto :fail
)

echo [2/2] Building dist\dsh-token-bill\dsh-token-bill.exe ...
%PY% -m PyInstaller --noconfirm --onedir --console ^
  --name dsh-token-bill ^
  --icon "%~dp0assets\icons\coin.ico" ^
  --hidden-import compression.zstd --hidden-import _zstd ^
  --distpath dist --workpath build --specpath build ^
  token_bill.py || goto :fail

copy /y "token-bill.config.example.json" "dist\dsh-token-bill\" >nul
copy /y "使用说明.txt" "dist\dsh-token-bill\" >nul
copy /y "token_bill.py" "dist\dsh-token-bill\" >nul
copy /y "run-source.cmd" "dist\dsh-token-bill\" >nul
xcopy /y /i /e "assets\icons" "dist\dsh-token-bill\assets\icons\" >nul

echo.
echo Done: %~dp0dist\dsh-token-bill\dsh-token-bill.exe
echo Zip the whole dist\dsh-token-bill folder to ship it.
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. Screenshot this window for help.
pause
exit /b 1
