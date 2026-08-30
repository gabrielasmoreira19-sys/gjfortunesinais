@echo off
cd /d "%~dp0"

echo Fechando instancias antigas, se houver...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bot\.py|painel_santos\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Iniciando bot e painel em janelas separadas...
start "Bot Santos" cmd /k "py bot.py"
start "Painel Santos" cmd /k "py painel_santos.py"
