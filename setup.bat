@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3 -m venv .venv
if not errorlevel 1 goto install
python -m venv .venv
if errorlevel 1 goto failed
:install
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe bootstrap.py
if errorlevel 1 goto failed
echo Setup complete. Run the launcher.
pause
exit /b 0
:failed
echo Setup failed. Check Python installation and network access.
pause
exit /b 1
