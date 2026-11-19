@echo off
rem Double-click this file to start the Christmas Shopping Helper.
rem Keep this window open while you use the app. Close it to stop the app.
cd /d "%~dp0"

set "PY=python"
if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"

"%PY%" --version >nul 2>nul
if errorlevel 1 (
  echo Could not find Python. Open Anaconda Prompt and follow the README instead.
  pause
  exit /b 1
)

"%PY%" -c "import flask, dotenv, requests, sqlalchemy" >nul 2>nul
if errorlevel 1 (
  echo Installing what the app needs. This happens once and can take a minute...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo The install failed. Send a screenshot of this window to Claude.
    pause
    exit /b 1
  )
)

echo.
echo Starting the app. Your browser will open in a few seconds.
echo Keep this window open. Press Ctrl+C or close it to stop.
echo.
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:5000"
"%PY%" app.py

echo.
echo The app has stopped. If you did not expect that, send a screenshot of this window to Claude.
pause
