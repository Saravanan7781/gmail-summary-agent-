@echo off
cd /d "%~dp0"
echo Running one-time Google Gmail OAuth flow...
.\.venv\Scripts\python.exe main.py --auth-only
pause
