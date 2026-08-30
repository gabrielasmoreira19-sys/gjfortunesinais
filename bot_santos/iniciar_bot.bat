@echo off
cd /d "%~dp0"

where py >nul 2>nul
if "%ERRORLEVEL%" NEQ "0" (
    echo Python nao encontrado no PATH.
    echo Instale o Python e tente novamente.
    pause
    exit /b 1
)

echo Fechando instancias antigas do bot, se houver...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bot\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Iniciando o bot Santos...
py bot.py

if errorlevel 1 (
    echo.
    echo O bot nao iniciou corretamente.
    echo Verifique o arquivo .env e as chaves do bot.
    pause
)
