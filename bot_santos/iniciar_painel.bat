@echo off
cd /d "%~dp0"

where py >nul 2>nul
if "%ERRORLEVEL%" NEQ "0" (
    echo Python nao encontrado no PATH.
    echo Instale o Python e tente novamente.
    pause
    exit /b 1
)

echo Fechando instancias antigas do painel, se houver...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'painel_santos\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Iniciando o painel do Santos...
py painel_santos.py

if errorlevel 1 (
    echo.
    echo O painel nao iniciou corretamente.
    echo Verifique o arquivo .env e a senha do painel.
    pause
)
