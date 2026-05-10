@echo off
set PYTHONUTF8=1
"%~dp0venv\Scripts\python.exe" -m cli.main %*
