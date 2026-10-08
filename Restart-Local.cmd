@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m gold_intelligence.local_launcher --restart
if errorlevel 1 pause
