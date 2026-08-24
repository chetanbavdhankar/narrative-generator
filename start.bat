@echo off
REM ------------------------------------------------------------------
REM KRI/KPI Context Builder Launcher
REM Double-click to start. Optionally pass a port number:
REM   start.bat 8080
REM Default port: 5000
REM ------------------------------------------------------------------

set PORT=%1
if "%PORT%"=="" set PORT=5000

cd /d "%~dp0"

echo.
echo ======================================================
echo   KRI / KPI Context Builder (Transaction Monitoring)
echo   Starting server on port %PORT%...
echo ======================================================
echo.

REM Install dependencies if missing
pip show flask pandas openpyxl >nul 2>&1
if errorlevel 1 (
    echo [Setup] Installing dependencies from requirements.txt...
    pip install -r requirements.txt --quiet
)

echo [Server] Launching at http://localhost:%PORT%
echo [Server] Close this window to stop the server.
echo.

python app.py --port %PORT%
pause
