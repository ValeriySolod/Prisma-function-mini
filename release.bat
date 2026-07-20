@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0release.ps1"
if errorlevel 1 exit /b %errorlevel%
