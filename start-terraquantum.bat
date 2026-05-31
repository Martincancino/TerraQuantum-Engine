@echo off
title TerraQuantum Launcher

echo ==========================================
echo   TERRAQUANTUM INDUSTRIAL PLATFORM
echo   Launcher general
echo ==========================================
echo.

set ROOT_DIR=%~dp0
set BACKEND_DIR=%ROOT_DIR%terraquantum-backend
set FRONTEND_DIR=%ROOT_DIR%terraquantum-web

echo Abriendo Backend FastAPI...
start "TerraQuantum Backend" cmd /k "cd /d ""%BACKEND_DIR%"" && call start-backend.bat"

echo Esperando 5 segundos para que backend inicie...
timeout /t 5 /nobreak >nul

echo.
echo Abriendo Frontend Next.js...
start "TerraQuantum Frontend" cmd /k "cd /d ""%FRONTEND_DIR%"" && call start-frontend.bat"

echo Esperando 6 segundos para abrir navegador...
timeout /t 6 /nobreak >nul

echo.
echo Abriendo TerraQuantum en navegador...
start http://localhost:3000

echo.
echo TerraQuantum iniciado.
echo Backend:  http://127.0.0.1:8010
echo Frontend: http://localhost:3000
echo.
pause
