@echo off
title TerraQuantum Backend - FastAPI 8010

echo ==========================================
echo   TERRAQUANTUM BACKEND
echo   FastAPI puerto 8010
echo ==========================================
echo.

cd /d %~dp0

echo Carpeta actual:
cd
echo.

echo Verificando procesos antiguos en puerto 8010...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8010 ^| findstr LISTENING') do (
    echo Cerrando proceso antiguo PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo Iniciando FastAPI...
echo URL:    http://127.0.0.1:8010
echo Health: http://127.0.0.1:8010/health
echo Docs:   http://127.0.0.1:8010/docs
echo.

python -m uvicorn main:app --host 127.0.0.1 --port 8010 --log-level debug

echo.
echo El backend se cerro o fallo.
pause