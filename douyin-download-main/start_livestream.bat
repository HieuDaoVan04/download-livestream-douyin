@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" livestream_gui.py
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    python livestream_gui.py
  ) else (
    py -3 livestream_gui.py
  )
)
if errorlevel 1 (
  echo Cannot start. Install Python 3.10+ and run pip install -r requirements.txt.
  pause
)
