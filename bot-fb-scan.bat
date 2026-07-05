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

set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "PROFILE=Default"
REM Group dau tien trong danh sach userscript; kem sort chronological (bai moi len dau).
set "URL=https://www.facebook.com/groups/239359157957166?sorting_setting=CHRONOLOGICAL"
set "FLAGS=--disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding"

if not exist "%CHROME%" (
  echo [LOI] Khong tim thay Chrome tai: %CHROME%
  echo       Sua bien CHROME trong file .bat cho dung.
  pause
  exit /b 1
)

REM --- Chi canh bao khi CUM CAPTURE (Google Chrome that, profile Default) dang mo.
REM     Bo qua "Google Chrome for Testing" = browser Playwright cua bot scan portal
REM     (chay tu ...\ms-playwright\..., user-data-dir rieng) =^> KHONG chan co, KHONG dong.
set "CAPRUN=0"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "@(Get-CimInstance Win32_Process).Where({ $_.Name -eq 'chrome.exe' -and $_.CommandLine -match 'Chrome\\User Data' -and $_.CommandLine -notmatch 'playwright' -and $_.CommandLine -notmatch 'for Testing' -and $_.CommandLine -notmatch '--type=' }).Count"`) do set "CAPRUN=%%C"

if not "%CAPRUN%"=="0" (
  echo.
  echo   [CANH BAO] Chrome CAPTURE ^(Google Chrome, profile Default^) DANG mo
  echo              =^> 3 co chong throttling se BI BO QUA.
  echo              Dong HET cua so "Google Chrome" thuong ^(nut X^) roi chay lai .bat nay.
  echo              LUU Y: "Google Chrome for Testing" = bot scan portal, KHONG duoc dong.
  echo.
  pause
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
