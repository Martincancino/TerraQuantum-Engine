@echo off
title TerraQuantum Smoke Test

echo ==========================================
echo   TERRAQUANTUM BACKEND SMOKE TEST
echo ==========================================
echo.

cd /d C:\Users\marti\OneDrive\Documentos\terraquantum-backend

echo Verificando backend en http://127.0.0.1:8010
echo.
echo IMPORTANTE:
echo - Debes tener abierto start-backend.bat antes de correr esto.
echo - Este test ejecuta geofisica, block model y diseno de mina.
echo.

python scripts\smoke_test_backend.py

echo.
echo ==========================================
echo   TEST FINALIZADO
echo ==========================================
echo.

pause