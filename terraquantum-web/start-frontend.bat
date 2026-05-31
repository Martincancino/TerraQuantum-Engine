@echo off
title TerraQuantum Frontend - Next.js

echo ==========================================
echo   TERRAQUANTUM FRONTEND
echo   Next.js App
echo ==========================================
echo.

cd /d %~dp0

echo Carpeta actual:
cd
echo.

echo Configurando backend URL...
if not exist .env.local (
    > .env.local echo NEXT_PUBLIC_TERRAQUANTUM_BACKEND_URL=http://127.0.0.1:8010
    >> .env.local echo TERRAQUANTUM_BACKEND_URL=http://127.0.0.1:8010
) else (
    echo .env.local ya existe. No se sobrescribe.
)

echo.
echo Verificando procesos antiguos en puerto 3000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000 ^| findstr LISTENING') do (
    echo Cerrando proceso antiguo PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo Iniciando Next.js...
echo URL esperada: http://localhost:3000
echo.

npm run dev

echo.
echo El frontend se cerro o fallo.
pause
