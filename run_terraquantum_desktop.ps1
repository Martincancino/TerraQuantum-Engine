<#
  TerraQuantum — Launcher local-first "de un clic" (F7, Plan B).

  Levanta backend (FastAPI) + frontend (Next.js) en la MÁQUINA del usuario, con
  los DATOS del cliente guardados en %APPDATA%\TerraQuantum\data (fuera del árbol
  de instalación, para que sobrevivan actualizaciones y se respalden copiando
  una carpeta). Nada sale de la máquina.

  Este script NO reemplaza a start-terraquantum.bat (que sigue intacto para dev);
  es el arranque orientado a distribución local-first. No requiere Rust ni Tauri.

  Uso:
      powershell -ExecutionPolicy Bypass -File run_terraquantum_desktop.ps1
      # opciones:
      #   -SkipBuild     no reconstruye el frontend (usa el .next existente)
      #   -NoBrowser     no abre el navegador
      #   -BackendPort N / -FrontendPort N

  Requisitos de la máquina destino: Python con las deps del backend instaladas y
  Node.js. (El empaque final con Python embebido queda descrito en
  docs/04_EMPAQUE_LOCAL_FIRST.md; este launcher es la base de ese empaque.)
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$NoBrowser,
    [int]$BackendPort = 8010,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"
$RootDir     = $PSScriptRoot
$BackendDir  = Join-Path $RootDir "terraquantum-backend"
$FrontendDir = Join-Path $RootDir "terraquantum-web"

# ── Datos del usuario en %APPDATA%\TerraQuantum\data (local-first) ────────────
$DataDir = Join-Path $env:APPDATA "TerraQuantum\data"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Force -Path $DataDir | Out-Null }

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  TERRAQUANTUM — Escritorio local-first"    -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Datos del usuario : $DataDir"
Write-Host "  Backend           : http://127.0.0.1:$BackendPort"
Write-Host "  Frontend          : http://localhost:$FrontendPort"
Write-Host ""

# Variables de entorno que hacen el modo escritorio local-first:
#  - los datos viven en %APPDATA% (portable),
#  - el backend escucha SOLO en loopback (no se expone en la red),
#  - el proxy del frontend apunta al backend local.
$env:TERRAQUANTUM_DATA_DIR    = $DataDir
$env:TERRAQUANTUM_HOST        = "127.0.0.1"
$env:TERRAQUANTUM_PORT        = "$BackendPort"
$env:TERRAQUANTUM_BACKEND_URL = "http://127.0.0.1:$BackendPort"

$procs = @()

function Stop-All {
    Write-Host "`nCerrando TerraQuantum..." -ForegroundColor Yellow
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

try {
    # ── 1) Backend ────────────────────────────────────────────────────────────
    Write-Host "[1/3] Iniciando backend FastAPI..." -ForegroundColor Green
    $backend = Start-Process -FilePath "python" -ArgumentList "main.py" `
        -WorkingDirectory $BackendDir -PassThru -WindowStyle Minimized
    $procs += $backend

    # Esperar a que /health responda (hasta ~40 s).
    $healthy = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" `
                 -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $healthy = $true; break }
        } catch { }
        if ($backend.HasExited) { throw "El backend terminó inesperadamente (revisa Python y las dependencias)." }
    }
    if (-not $healthy) { throw "El backend no respondió /health en 40 s." }
    Write-Host "      Backend saludable." -ForegroundColor Green

    # ── 2) Frontend ───────────────────────────────────────────────────────────
    if (-not $SkipBuild -and -not (Test-Path (Join-Path $FrontendDir ".next"))) {
        Write-Host "[2/3] Construyendo frontend (primera vez)..." -ForegroundColor Green
        Push-Location $FrontendDir
        try { & npm run build } finally { Pop-Location }
    } else {
        Write-Host "[2/3] Usando build de frontend existente." -ForegroundColor Green
    }

    Write-Host "      Iniciando servidor Next.js..." -ForegroundColor Green
    $frontend = Start-Process -FilePath "npm" -ArgumentList "run","start","--","-p","$FrontendPort" `
        -WorkingDirectory $FrontendDir -PassThru -WindowStyle Minimized
    $procs += $frontend

    # ── 3) Navegador ──────────────────────────────────────────────────────────
    Write-Host "[3/3] Esperando al frontend..." -ForegroundColor Green
    Start-Sleep -Seconds 4
    if (-not $NoBrowser) { Start-Process "http://localhost:$FrontendPort" }

    Write-Host ""
    Write-Host "TerraQuantum en marcha. Cierra esta ventana (Ctrl+C) para apagar." -ForegroundColor Cyan
    Wait-Process -Id $backend.Id
}
finally {
    Stop-All
}
