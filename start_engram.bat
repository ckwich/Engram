@echo off
setlocal

cd /d "%~dp0"
set "ENGRAM_ROOT=%CD%"
set "ENGRAM_PYTHON=%ENGRAM_ROOT%\venv\Scripts\python.exe"
set "ENGRAM_WEBUI=%ENGRAM_ROOT%\webui.py"

if not exist "%ENGRAM_PYTHON%" (
    echo [Engram] Missing venv\Scripts\python.exe. Run install.py first.
    pause
    exit /b 1
)

echo [Engram] Codex launches the MCP server from its registered stdio config.
echo [Engram] Starting the local WebUI only...
echo [Engram] WebUI: http://127.0.0.1:5000

start "Engram WebUI" cmd /k ""%ENGRAM_PYTHON%" "%ENGRAM_WEBUI%""
