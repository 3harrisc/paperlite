@echo off
rem ----------------------------------------------------------------------
rem  Builds PaperLite PDF on Windows: the app folder and the installer .exe
rem  Needs: Python 3.13 (python.org) and Inno Setup 6 (jrsoftware.org)
rem  Result: installer\Output\PaperLite-PDF-Setup-<version>.exe
rem ----------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where py >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ & pause & exit /b 1)

if not exist .venv (
    echo Creating Python environment...
    py -3.13 -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
)
echo Installing requirements...
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\python -m pip install --quiet -r requirements-dev.txt || (pause & exit /b 1)

echo Building the app...
.venv\Scripts\pyinstaller --noconfirm --log-level WARN paperlite.spec || (pause & exit /b 1)

for /f "delims=" %%v in ('.venv\Scripts\python -c "import paperlite; print(paperlite.__version__)"') do set VERSION=%%v

set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo.
    echo The app is built in dist\PaperLite\PaperLite.exe
    echo To make the installer, install Inno Setup 6 from https://jrsoftware.org/isdl.php and run this again.
    pause & exit /b 0
)
echo Building the installer...
%ISCC% /Q /DAppVersion=%VERSION% installer\paperlite.iss || (pause & exit /b 1)
echo.
echo Done: installer\Output\PaperLite-PDF-Setup-%VERSION%.exe
explorer installer\Output
pause
