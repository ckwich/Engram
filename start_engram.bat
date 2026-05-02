@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "ENGRAM_ROOT=%CD%"
set "ENGRAM_PYTHON=%ENGRAM_ROOT%\venv\Scripts\python.exe"
set "ENGRAM_WEBUI=%ENGRAM_ROOT%\webui.py"
set "ENGRAM_SERVER=%ENGRAM_ROOT%\server.py"

set "ENGRAM_WEBUI_HOST_EFFECTIVE=%ENGRAM_WEBUI_HOST%"
if not defined ENGRAM_WEBUI_HOST_EFFECTIVE set "ENGRAM_WEBUI_HOST_EFFECTIVE=127.0.0.1"
set "ENGRAM_WEBUI_PORT_EFFECTIVE=%ENGRAM_WEBUI_PORT%"
if not defined ENGRAM_WEBUI_PORT_EFFECTIVE set "ENGRAM_WEBUI_PORT_EFFECTIVE=5000"

if not exist "%ENGRAM_PYTHON%" (
    echo [Engram] Missing venv\Scripts\python.exe. Run install.py first.
    pause
    exit /b 1
)

set "ENGRAM_REMOTE_CONFIG_ERROR="
set "ENGRAM_EXPOSED_WEBUI=1"
if /I "%ENGRAM_WEBUI_HOST_EFFECTIVE%"=="127.0.0.1" set "ENGRAM_EXPOSED_WEBUI=0"
if /I "%ENGRAM_WEBUI_HOST_EFFECTIVE%"=="localhost" set "ENGRAM_EXPOSED_WEBUI=0"
if /I "%ENGRAM_WEBUI_HOST_EFFECTIVE%"=="localhost.localdomain" set "ENGRAM_EXPOSED_WEBUI=0"
if "%ENGRAM_WEBUI_HOST_EFFECTIVE%"=="::1" set "ENGRAM_EXPOSED_WEBUI=0"

if "%ENGRAM_EXPOSED_WEBUI%"=="1" (
    echo [Engram] Remote WebUI bind requested: %ENGRAM_WEBUI_HOST_EFFECTIVE%:%ENGRAM_WEBUI_PORT_EFFECTIVE%
    echo [Engram] Remote or Tailscale use requires explicit read/write tokens.
    if not defined ENGRAM_WEBUI_ACCESS_TOKEN (
        echo [Engram] Missing ENGRAM_WEBUI_ACCESS_TOKEN.
        set "ENGRAM_REMOTE_CONFIG_ERROR=1"
    )
    if not defined ENGRAM_WEBUI_WRITE_TOKEN (
        echo [Engram] Missing ENGRAM_WEBUI_WRITE_TOKEN.
        set "ENGRAM_REMOTE_CONFIG_ERROR=1"
    )
    if "%ENGRAM_WEBUI_HOST_EFFECTIVE%"=="0.0.0.0" (
        if not defined ENGRAM_WEBUI_ALLOWED_HOSTS (
            echo [Engram] Missing ENGRAM_WEBUI_ALLOWED_HOSTS for wildcard bind 0.0.0.0.
            set "ENGRAM_REMOTE_CONFIG_ERROR=1"
        )
    )
    if "%ENGRAM_WEBUI_HOST_EFFECTIVE%"=="::" (
        if not defined ENGRAM_WEBUI_ALLOWED_HOSTS (
            echo [Engram] Missing ENGRAM_WEBUI_ALLOWED_HOSTS for wildcard bind ::.
            set "ENGRAM_REMOTE_CONFIG_ERROR=1"
        )
    )
)

if defined ENGRAM_REMOTE_CONFIG_ERROR (
    echo.
    echo [Engram] Generate strong tokens with:
    echo   "%ENGRAM_PYTHON%" -c "import secrets; print(secrets.token_urlsafe(32))"
    echo.
    echo [Engram] Example remote/Tailscale environment:
    echo   set ENGRAM_WEBUI_HOST=0.0.0.0
    echo   set ENGRAM_WEBUI_ALLOWED_HOSTS=your-device.tailnet-name.ts.net
    echo   set ENGRAM_WEBUI_ACCESS_TOKEN=generated-read-token
    echo   set ENGRAM_WEBUI_WRITE_TOKEN=generated-write-token
    echo.
    echo [Engram] After startup, sanity-check the backend with:
    echo   "%ENGRAM_PYTHON%" "%ENGRAM_SERVER%" --health
    echo   or from the repo root: python server.py --health
    echo.
    echo [Engram] See docs\REMOTE_WEBUI.md for the full remote-safe recipe.
    pause
    exit /b 1
)

echo [Engram] Codex launches the MCP server from its registered stdio config.
echo [Engram] Starting the WebUI only...
echo [Engram] WebUI bind: http://%ENGRAM_WEBUI_HOST_EFFECTIVE%:%ENGRAM_WEBUI_PORT_EFFECTIVE%
echo [Engram] Health check: "%ENGRAM_PYTHON%" "%ENGRAM_SERVER%" --health
echo [Engram] Repo-root equivalent: python server.py --health

start "Engram WebUI" cmd /k ""%ENGRAM_PYTHON%" "%ENGRAM_WEBUI%""
