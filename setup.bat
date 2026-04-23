@echo off
if "%1"=="mb" (
    call bot setup-muaban
) else if "%1"=="nt" (
    call bot setup-nhatot
) else if "%1"=="bds" (
    call bot setup-batdongsan
) else (
    echo Usage: setup [mb^|nt^|bds]
    echo   mb  : Setup Muaban.net login
    echo   nt  : Setup Nhatot login
    echo   bds : Setup Batdongsan login
)
