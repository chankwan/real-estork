@echo off
REM ===================================================================
REM RealEstork — Bot Start Headless (manual)
REM Dung sau khi bot-stop, hoac khi muon chay headless ma khong reboot.
REM Terminal: bot-start-headless    |    Explorer: double-click
REM ===================================================================

title RealEstork Bot - Start Headless
set PYTHONUTF8=1
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo [X] Khong tim thay venv. Chay setup-full.bat truoc.
    pause
    exit /b 1
)

REM Dang co bot chay -> hoi truoc khi chay de (tranh 2 bot song song).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bot-guard.ps1" -Mode headless
if errorlevel 1 (
    pause
    exit /b 0
)

echo Khoi dong bot HEADLESS ^(khong cua so^)...
start "" "%~dp0venv\Scripts\pythonw.exe" -X utf8 -m cli.main start --source manual-headless

REM Cho 5s de bot ghi PID vao lock file
timeout /t 5 >nul

if exist .orchestrator.lock (
    set /p NEW_PID=<.orchestrator.lock
    echo [OK] Bot dang chay headless ^(PID %NEW_PID%^).
    echo      Xem log:  logs\orchestrator.log
    echo      Dung bot: bot-stop.bat ^(hoac bot-stop^)
) else (
    echo [!] Bot khong start duoc. Kiem tra logs\orchestrator.log
)

echo.
pause
