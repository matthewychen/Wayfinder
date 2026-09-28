@echo off
setlocal
rem Battle Cats Pull Planner - local launcher.
rem Double-click this file (or run:  run.bat [port]). First run creates .venv and installs the requirements.
cd /d "%~dp0"
set PORT=%1
if "%PORT%"=="" set PORT=8501

rem A .venv copied from another computer points at that computer's Python: rebuild it.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo The .venv folder does not work on this computer; rebuilding it ...
        rmdir /s /q ".venv"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the virtual environment ...
    py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv || python3 -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Could not create .venv. Install Python 3.10 or newer from python.org and try again.
        pause
        exit /b 1
    )
)

echo Checking requirements ...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo Installing requirements failed. It needs Python 3.10 or newer and an internet connection.
    pause
    exit /b 1
)

echo Starting the planner on http://localhost:%PORT%  (close this window to stop it)
".venv\Scripts\python.exe" -m streamlit run app.py --server.port %PORT% --server.headless false --browser.gatherUsageStats false
pause
