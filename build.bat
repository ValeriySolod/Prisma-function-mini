@echo off
setlocal
cd /d "%~dp0"

if exist "build" rmdir /s /q "build"
if errorlevel 1 exit /b %errorlevel%
if exist "dist" rmdir /s /q "dist"
if errorlevel 1 exit /b %errorlevel%

python -m PyInstaller --clean --noconfirm PrismaFunctionMini.spec
if errorlevel 1 exit /b %errorlevel%

echo Build complete: dist\PrismaFunctionMini\PrismaFunctionMini.exe
