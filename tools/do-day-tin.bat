@echo off
REM ===================================================================
REM Do "muaban co tu day hang loat tin luc giao ngay khong"
REM Goi boi Task Scheduler 2 lan/dem: 23:30 (truoc) va 00:30 (sau).
REM Tham so: truoc | sau | bao-cao
REM ===================================================================
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist "logs\muaban_day_tin" mkdir "logs\muaban_day_tin"
echo ---- %DATE% %TIME% : %1 ---- >> "logs\muaban_day_tin\chay.log"
"%~dp0..\venv\Scripts\python.exe" -m tools.do_day_tin_muaban %1 >> "logs\muaban_day_tin\chay.log" 2>&1
