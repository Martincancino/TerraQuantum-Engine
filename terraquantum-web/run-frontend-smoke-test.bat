@echo off
title TerraQuantum Frontend Smoke Test

echo ==========================================
echo   TERRAQUANTUM FRONTEND SMOKE TEST
echo ==========================================
echo.

cd /d C:\Users\marti\OneDrive\Documentos\terraquantum-web

echo Verificando frontend en http://localhost:3000
echo.
echo IMPORTANTE:
echo - Debes tener abierto el backend.
echo - Debes tener abierto el frontend.
echo - Puedes abrir ambos con start-terraquantum.bat.
echo.

node scripts\smoke_test_frontend.mjs

echo.
echo ==========================================
echo   TEST FINALIZADO
echo ==========================================
echo.

pause