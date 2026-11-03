@echo off
cd /d "%~dp0"
python open_workbench.py
if errorlevel 1 pause
