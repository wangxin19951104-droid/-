@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto venv
py -3 bootstrap.py
if errorlevel 1 goto fallback
py -3 server.py
goto end
:fallback
python bootstrap.py
if errorlevel 1 goto end
python server.py
goto end
:venv
.venv\Scripts\python.exe bootstrap.py
if errorlevel 1 goto end
.venv\Scripts\python.exe server.py
:end
if errorlevel 1 pause
