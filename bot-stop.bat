@echo off
REM ===================================================================
REM RealEstork — Bot Stop
REM Terminal: bot-stop   |   Explorer: double-click
REM ===================================================================

title RealEstork Bot Stop
set PYTHONUTF8=1
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".orchestrator.lock" (
    echo [!] Bot khong chay (khong tim thay .orchestrator.lock^).
    pause
    exit /b 0
)

set /p PID=<.orchestrator.lock
echo Dang dung bot (PID %PID%^)...

taskkill /PID %PID% /F >nul 2>&1
if errorlevel 1 (
    echo [!] Khong kill duoc PID %PID% -- co the bot da dung roi.
) else (
    echo [OK] Bot (PID %PID%^) da dung.
)

del .orchestrator.lock 2>nul
echo.
pause
