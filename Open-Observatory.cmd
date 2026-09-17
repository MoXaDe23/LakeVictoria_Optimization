@echo off
powershell.exe -NoProfile -File "%~dp0Start-Observatory.ps1"
if errorlevel 1 pause
