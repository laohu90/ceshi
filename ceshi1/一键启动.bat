@echo off
cd /d "%~dp0"
title ScreenScan RPA Desktop Launcher
echo ==========================================
echo   ScreenScan RPA AI Smart Desktop Launcher
echo ==========================================

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python and check "Add Python to PATH".
    echo ==========================================
    pause
    exit /b
)

echo [1/2] Checking required libraries (keyboard, pyautogui, opencv, pillow, winocr)...
python -c "import cv2, pyautogui, PIL, keyboard, winocr" >nul 2>&1
if errorlevel 1 (
    echo Installing required libraries for global system hooks and hardware clicking...
    python -m pip install pyautogui opencv-python numpy pillow winocr keyboard
)

echo [2/2] Starting ScreenScan RPA Desktop GUI...
echo ==========================================
pythonw app.py >> crash.log 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python app exited. See error above.
    pause
    exit /b
)
