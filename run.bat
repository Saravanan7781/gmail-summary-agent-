@echo off
cd /d "%~dp0"
echo Starting Gmail Summary Agent...
.\.venv\Scripts\python.exe main.py
pause
