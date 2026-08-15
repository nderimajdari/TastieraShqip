@echo off
REM Start Tastiera Shqip. Uses pythonw so no console window is left behind.
cd /d "%~dp0"
start "" pythonw.exe main.py
