@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%CD%\"
set "RUNTIME=%ROOT%runtime"
set "PYTHON=%ROOT%runtime\python.exe"
set "PYTHON_VERSION=3.13.14"
set "PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%"

call :runtime_valid
if not errorlevel 1 goto launch

echo Preparing project-local Python %PYTHON_VERSION%...
if exist "%RUNTIME%" rmdir /s /q "%RUNTIME%"
mkdir "%RUNTIME%" || goto fail
set "ARCHIVE=%RUNTIME%\%PYTHON_ZIP%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing '%PYTHON_URL%' -OutFile '%ARCHIVE%.part'; if ((Get-Item '%ARCHIVE%.part').Length -lt 1000000) { throw 'Downloaded Python archive is invalid' }; Move-Item -Force '%ARCHIVE%.part' '%ARCHIVE%'" || goto rebuild_fail
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ARCHIVE%' -DestinationPath '%RUNTIME%' -Force" || goto rebuild_fail
del /q "%ARCHIVE%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Get-ChildItem '%RUNTIME%\python*._pth' | Select-Object -First 1; (Get-Content $p.FullName) -replace '^#import site$','import site' | Set-Content -Encoding Ascii $p.FullName" || goto rebuild_fail
set "GET_PIP=%RUNTIME%\get-pip.py"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%GET_PIP%.part'; if ((Get-Item '%GET_PIP%.part').Length -lt 10000) { throw 'Downloaded get-pip.py is invalid' }; Move-Item -Force '%GET_PIP%.part' '%GET_PIP%'" || goto rebuild_fail
"%PYTHON%" "%GET_PIP%" --no-warn-script-location || goto rebuild_fail
del /q "%GET_PIP%"
"%PYTHON%" -m pip install --no-warn-script-location -r "%ROOT%requirements.txt" || goto rebuild_fail
call :runtime_valid
if errorlevel 1 goto rebuild_fail

:launch
"%PYTHON%" "%ROOT%launcher.py"
exit /b %errorlevel%

:runtime_valid
if not exist "%PYTHON%" exit /b 1
"%PYTHON%" -c "import sys; raise SystemExit(sys.version_info[:3] != (3,13,14))" >nul 2>&1 || exit /b 1
"%PYTHON%" -c "import fastapi,uvicorn,openpyxl,multipart; from importlib.metadata import version; expected={'fastapi':'0.139.2','uvicorn':'0.51.0','openpyxl':'3.1.5','python-multipart':'0.0.32'}; raise SystemExit(any(version(k)!=v for k,v in expected.items()))" >nul 2>&1 || exit /b 1
exit /b 0

:rebuild_fail
echo Failed to prepare portable runtime. Delete runtime and retry when online.
if exist "%RUNTIME%" rmdir /s /q "%RUNTIME%"
:fail
exit /b 1
