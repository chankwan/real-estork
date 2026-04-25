@echo off
REM ===================================================================
REM RealEstork — One-click setup for fresh PC
REM Usage: double-click setup-full.bat (or run from cmd)
REM ===================================================================

setlocal
set PYTHONUTF8=1
chcp 65001 >nul

echo.
echo ============================================================
echo  RealEstork — Setup Full
echo ============================================================
echo.

REM --- Step 1: Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python chua duoc cai dat.
    echo     Tai ve: https://www.python.org/downloads/  ^(version 3.12+^)
    echo     Khi cai, NHO tick ^"Add Python to PATH^".
    pause
    exit /b 1
)
echo [OK] Python da co
python --version

REM --- Step 2: Create venv if missing ---
if not exist venv\Scripts\python.exe (
    echo.
    echo [..] Tao virtual environment ^(venv^)...
    python -m venv venv
    if errorlevel 1 (
        echo [X] Khong tao duoc venv. Kiem tra Python install.
        pause
        exit /b 1
    )
    echo [OK] venv da tao
) else (
    echo [OK] venv da co san
)

REM --- Step 3: Upgrade pip ---
echo.
echo [..] Upgrade pip...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
echo [OK] pip up-to-date

REM --- Step 4: Install Python deps ---
echo.
if exist requirements-lock.txt (
    echo [..] Cai Python packages tu requirements-lock.txt ^(exact versions^)...
    venv\Scripts\python.exe -m pip install -r requirements-lock.txt
) else (
    echo [..] Cai Python packages tu requirements.txt...
    venv\Scripts\python.exe -m pip install -r requirements.txt
)
if errorlevel 1 (
    echo [X] Pip install that bai. Xem error o tren.
    pause
    exit /b 1
)
echo [OK] Python packages cai xong

REM --- Step 5: Install Scrapling browser engines (patchright + chromium) ---
echo.
echo [..] Cai Scrapling fetcher engines ^(patchright + browser binaries, ~200MB^)...
venv\Scripts\scrapling.exe install
if errorlevel 1 (
    echo [!] scrapling install gap loi nhung khong fatal. Tiep tuc...
)
echo [OK] Scrapling engines san sang

REM --- Step 6: Install Playwright browsers (Firefox for Camoufox + Chromium fallback) ---
echo.
echo [..] Cai Playwright browsers ^(Firefox + Chromium, ~300MB^)...
venv\Scripts\playwright.exe install firefox chromium
if errorlevel 1 (
    echo [!] playwright install gap loi nhung khong fatal. Tiep tuc...
)
echo [OK] Playwright browsers san sang

REM --- Step 7: Check .env ---
echo.
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo [!] Da tao .env tu .env.example.
        echo     CAN dien tokens/keys vao file .env truoc khi chay bot.
    ) else (
        echo [!] Khong tim thay .env hoac .env.example.
    )
) else (
    echo [OK] .env da co
)

REM --- Step 8: Run doctor ---
echo.
echo ============================================================
echo  Setup xong. Chay health check...
echo ============================================================
venv\Scripts\python.exe -m cli.main doctor

echo.
echo ============================================================
echo  Hoan tat!
echo  - Sua .env neu can ^(tokens, chat IDs^)
echo  - Chay bot:        bot start
echo  - Test 1 spider:   bot spider run nhatot
echo  - Health check:    bot doctor
echo ============================================================
pause
