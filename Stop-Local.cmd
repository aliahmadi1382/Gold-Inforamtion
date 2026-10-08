@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m gold_intelligence.local_launcher --stop
if errorlevel 1 pause
