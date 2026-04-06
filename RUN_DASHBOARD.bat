@echo off
echo ============================================================
echo   Sinchi Metals Assay Analysis Dashboard
echo   Setting up environment...
echo ============================================================
echo.

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Download from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Install requirements
echo Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo WARNING: Some packages may have failed. Trying with --user flag...
    pip install -r requirements.txt --quiet --user
)

echo.
echo ============================================================
echo   Launching dashboard in your browser...
echo   Press Ctrl+C in this window to stop the server.
echo ============================================================
echo.

:: Run the app
streamlit run sinchi_dashboard.py --server.headless true --browser.gatherUsageStats false

pause
