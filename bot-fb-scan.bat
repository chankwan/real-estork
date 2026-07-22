@echo off
REM ============================================================================
REM  RealEstork - FB capture launcher (bot-fb-scan.bat)
REM ----------------------------------------------------------------------------
REM  Mo Chrome (profile Default: da co via FB + Tampermonkey + userscript) kem
REM  3 co TAT background-throttling. Muc dich: tab van chay tick/scan khi cua so
REM  bi che boi app khac HOAC nam o Virtual Desktop khac => capture khong chet
REM  khi anh dung viec khac / cho vo muon may.
REM
REM  *** QUAN TRONG ***  Co launch CHI ap dung khi Chrome khoi dong MOI.
REM  Neu Chrome (profile Default) dang mo san, lenh nay chi mo them 1 tab trong
REM  tien trinh cu => 3 co BI BO QUA (throttling van con).
REM  => Phai DONG HET cua so Chrome Default truoc khi chay .bat nay.
REM
REM  VERIFY sau khi mo: vao  chrome://version  -> dong "Command Line" phai chua
REM  ca 3 co  --disable-background-timer-throttling / ...occluded-windows /
REM  ...renderer-backgrounding.  Neu KHONG co => Chrome da chay tu truoc, dong
REM  het roi chay lai.
REM
REM  Sau do: Win+Tab -> New desktop -> keo cua so Chrome nay sang Desktop 2.
REM  Vo lam viec o Desktop 1 thoai mai; bot van scan o Desktop 2.
REM ============================================================================

setlocal

REM /auto = chay tu Task Scheduler (at logon): KHONG pause (khong co nguoi bam phim).
set "AUTOMODE=0"
if /i "%~1"=="/auto" set "AUTOMODE=1"

set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "PROFILE=Default"
REM Group dau tien trong danh sach userscript; kem sort chronological (bai moi len dau).
set "URL=https://www.facebook.com/groups/239359157957166?sorting_setting=CHRONOLOGICAL"
REM --hide-crash-restore-bubble: sau cup dien/crash, Chrome KHONG treo popup
REM "Restore pages?" (popup nay che viec load trang => userscript khong chay).
set "FLAGS=--disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --hide-crash-restore-bubble"

if not exist "%CHROME%" (
  echo [LOI] Khong tim thay Chrome tai: %CHROME%
  echo       Sua bien CHROME trong file .bat cho dung.
  if "%AUTOMODE%"=="0" pause
  exit /b 1
)

REM --- Phat hien CUM CAPTURE dang chay: match theo DUONG DAN EXE (Program Files),
REM     khong theo command line — vi Chrome Startup Boost / background mode de lai
REM     process chrome.exe KHONG args (command line trong) van giu singleton =>
REM     co launch bi nuot. "Chrome for Testing" (Playwright, ...\ms-playwright\...)
REM     co ExecutablePath khac =^> khong dinh, KHONG duoc dong.
set "CAPRUN=0"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "@(Get-CimInstance Win32_Process).Where({ $_.Name -eq 'chrome.exe' -and $_.ExecutablePath -eq '%CHROME%' }).Count"`) do set "CAPRUN=%%C"

if not "%CAPRUN%"=="0" (
  if "%AUTOMODE%"=="1" (
    REM /auto chay luc vua logon — chua ai duyet web. Dong het Chrome capture con
    REM sot (ke ca process nen Startup Boost) de co launch duoc ap dung that.
    echo [AUTO] Chrome capture dang chay ^(%CAPRUN% process^) - dong de ap dung co...
    powershell -NoProfile -Command "@(Get-CimInstance Win32_Process).Where({ $_.Name -eq 'chrome.exe' -and $_.ExecutablePath -eq '%CHROME%' }) | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
    timeout /t 3 /nobreak >nul
  ) else (
    echo.
    echo   [CANH BAO] Chrome CAPTURE ^(Google Chrome that^) DANG chay - %CAPRUN% process
    echo              =^> 3 co chong throttling se BI BO QUA.
    echo              Dong HET cua so "Google Chrome" thuong ^(nut X^) roi chay lai .bat nay.
    echo              Neu khong thay cua so nao: Chrome dang chay NEN ^(Startup Boost^)
    echo              =^> mo Task Manager, End task cac "Google Chrome" ^(khong dong
    echo              "Google Chrome for Testing" = bot scan portal^).
    echo.
    pause
  )
) else (
  echo Cum Capture chua mo - an toan. ^("Chrome for Testing" cua bot van chay binh thuong.^)
)

echo Mo Chrome capture (profile %PROFILE%) voi co chong throttling...
start "" "%CHROME%" %FLAGS% --profile-directory="%PROFILE%" "%URL%"

echo.
echo Da gui lenh mo. Kiem tra ngay:
echo   1) chrome://version  -^>  dong "Command Line" phai co 3 co --disable-...
echo   2) Badge goc phai-duoi dang dem (feed / sent tang dan)
echo   3) Win+Tab -^> New desktop -^> keo cua so Chrome nay sang Desktop 2
echo.
endlocal
