@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" uv sync --frozen
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\python.exe" -m gold_intelligence.local_launcher
if errorlevel 1 pause
