@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo Python 3.11 was not found or venv creation failed. See docs\01_WINDOWS_SETUP.md.
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\check_environment.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
echo.
echo Setup and synthetic checks passed.
echo Next: edit config\project.json and run the input inventory.
echo To activate in this CMD terminal: call .venv\Scripts\activate.bat
endlocal
exit /b 0
