@echo off
cd /d "%~dp0"

where py >nul 2>nul
if "%ERRORLEVEL%" NEQ "0" (
    echo Python nao encontrado no PATH.
    echo Instale o Python e tente novamente.
    pause
    exit /b 1
)

powershell -NoProfile -Command "$bot = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '(^|\s)bot\.py($|\s)' }; if ($bot) { Write-Host 'A Santos ja esta ligada. Nao abri uma segunda copia.'; exit 1 }"
if errorlevel 1 exit /b 0

:iniciar
echo.
echo [%date% %time%] Iniciando a Santos...
py -u bot.py
set CODIGO_SAIDA=%ERRORLEVEL%
if "%CODIGO_SAIDA%"=="17" (
    echo Outra janela da Santos ja esta aberta. Este iniciador sera fechado.
    exit /b 0
)
echo.
echo [%date% %time%] A Santos encerrou. Reiniciando em 5 segundos...
timeout /t 5 /nobreak >nul
goto iniciar
