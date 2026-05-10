@echo off
REM ===================================================================
REM RealEstork — Bot Start
REM Terminal: bot-start    |   Explorer: double-click
REM Ctrl+C de dung bot.
REM ===================================================================

title RealEstork Bot
set PYTHONUTF8=1
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [X] Khong tim thay venv. Chay setup-full.bat truoc.
    pause
    exit /b 1
)

echo ============================================================
echo  RealEstork Bot dang khoi dong... ^(Ctrl+C de dung^)
echo  Log day du: logs\orchestrator.log
echo ============================================================
echo.

"%~dp0venv\Scripts\python.exe" -m cli.main start --source manual-visible

echo.
echo ============================================================
echo  Bot da dung. Bam phim bat ky de dong cua so.
echo ============================================================
pause >nul
