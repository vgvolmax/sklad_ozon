@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" exit /b 1
"runtime\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 17843
