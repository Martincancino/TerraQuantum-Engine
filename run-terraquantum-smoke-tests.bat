@echo off
title TerraQuantum Full Smoke Test

echo ==========================================
echo   TERRAQUANTUM FULL SMOKE TEST
echo ==========================================
echo.
echo Este test revisa:
echo - Backend Python FastAPI
echo - Frontend Next.js
echo - Conexion frontend/backend
echo - Geofisica
echo - Block model
echo - Diseno de mina
echo - LOM y NPV
echo.
echo IMPORTANTE:
echo - Debes tener abierto start-terraquantum.bat antes de correr esto.
echo - Espera que backend y frontend esten listos.
echo.

set BACKEND_DIR=%~dp0terraquantum-backend
set FRONTEND_DIR=%~dp0terraquantum-web

echo ==========================================
echo   1. PROBANDO BACKEND
echo ==========================================
echo.

cd /d "%BACKEND_DIR%"

python scripts\smoke_test_backend.py

if errorlevel 1 (
    echo.
    echo ==========================================
    echo   FULL SMOKE TEST FALLO EN BACKEND
    echo ==========================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   BACKEND OK
echo ==========================================
echo.

echo ==========================================
echo   2. VALIDATION SUITE SINTETICA (opcional)
echo ==========================================
echo.

echo Validando inversion gravimetrica con cuerpos sinteticos conocidos...
echo (PASS/WARNING son normales. Solo FAIL indica error critico.)
echo.

cd /d "%BACKEND_DIR%"
python scripts\validation\synthetic_cases.py

if errorlevel 1 (
    echo.
    echo ==========================================
    echo   FULL SMOKE TEST FALLO EN VALIDATION SUITE
    echo ==========================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   3. VALIDANDO PROJECT_ID / RUN_ID
echo ==========================================
echo.
python scripts\validation\test_project_run_flow.py

if errorlevel 1 (
    echo.
    echo ==========================================
    echo   FULL SMOKE TEST FALLO EN PROJECT_RUN FLOW
    echo ==========================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   4. PROBANDO FRONTEND
echo ==========================================
echo.

cd /d "%FRONTEND_DIR%"

node scripts\smoke_test_frontend.mjs

if errorlevel 1 (
    echo.
    echo ==========================================
    echo   FULL SMOKE TEST FALLO EN FRONTEND
    echo ==========================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   TERRAQUANTUM FULL SMOKE TEST COMPLETADO
echo ==========================================
echo.
echo Backend industrial operativo.
echo Frontend conectado correctamente.
echo Flujo completo funcionando.
echo Validation Suite sintetica ejecutada.
echo Project/run storage validado.
echo.
echo SISTEMA LISTO
echo.

pause
