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

REM /T = kill ca cay process. Bot chay 2 tang (parent + child giu lock) va
REM moi cycle batdongsan de ra 1 cay browser con. Khong co /T thi chi child
REM chet, parent + browser thanh mo coi, tich luy dan sau moi lan start/stop.
taskkill /PID %PID% /F /T >nul 2>&1
if errorlevel 1 (
    echo [!] Khong kill duoc PID %PID% -- co the bot da dung roi.
) else (
    echo [OK] Bot (PID %PID%^) da dung.
)

REM Quet not process mo coi: parent cua bot KHONG nam trong lock file (lock chi
REM ghi PID child), va cac lan start/stop truoc co the da de lai process cu.
REM Dung PowerShell vi can loc theo CommandLine -- wmic/for-f parse sai khi
REM CommandLine chua dau phay.
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'cli\.main' }; if ($p) { Write-Host ('[!] Con ' + @($p).Count + ' process mo coi -- dang don...'); $p | ForEach-Object { & taskkill /PID $_.ProcessId /F /T *>$null } } else { Write-Host '[OK] Khong con process mo coi.' }"

del .orchestrator.lock 2>nul
echo.
pause
