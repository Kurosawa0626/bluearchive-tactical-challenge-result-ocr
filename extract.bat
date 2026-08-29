@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。setup.bat を先に実行してください。
  pause
  exit /b 1
)
python extract_names.py
pause
