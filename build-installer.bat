@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\PrismaFunction\PrismaFunction.exe" (
    echo ERROR: Build the validated PyInstaller onedir package first.
    exit /b 1
)

python validate_package.py
if errorlevel 1 exit /b %errorlevel%

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined INNO_SETUP_COMPILER set "ISCC=%INNO_SETUP_COMPILER%"
if not exist "%ISCC%" (
    echo ERROR: Inno Setup 6 compiler not found.
    echo Set INNO_SETUP_COMPILER to the full path of ISCC.exe.
    exit /b 1
)

set "SIGN_ARG="
if defined INNO_SIGNTOOL_NAME set "SIGN_ARG=/DSignToolName=%INNO_SIGNTOOL_NAME%"

"%ISCC%" %SIGN_ARG% "PrismaFunction.iss"
if errorlevel 1 exit /b %errorlevel%

endlocal
