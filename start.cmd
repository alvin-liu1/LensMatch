@echo off
chcp 65001 >nul
cd /d "%~dp0"
python match.py --gui
if errorlevel 1 pause
