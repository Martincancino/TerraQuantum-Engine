<#
  TerraQuantum — Pipeline de build del instalador de escritorio (F7, camino Tauri).

  Produce un instalador NSIS nativo (.exe) que empaqueta TODO — sin exigir Python
  ni Node en la máquina destino:
    1. Backend Python  -> ejecutable onefile con PyInstaller (FastAPI + scipy/pyproj/IGRF).
    2. Frontend Next.js -> build standalone (Node) con los 40 proxies intactos.
    3. Staging          -> copia backend.exe + node.exe + frontend standalone a src-tauri/resources.
    4. Tauri build      -> compila el shell Rust y empaqueta el instalador NSIS.

  Arquitectura: la app Tauri lanza DOS sidecars (backend en 127.0.0.1:8010, frontend
  en 127.0.0.1:3000) y la ventana navega al frontend local. Los datos del usuario
  viven en %APPDATA%\TerraQuantum\data. Nada sale de la máquina.

  Requisitos (una vez): Rust (rustup), VS Build Tools con "Desktop development with C++",
  Node.js, y las deps del backend + la cadena de build pineada. OJO con el
  interprete: se usa el que declara terraquantum-backend/.python-version, que en
  esta maquina es `py -3.14` y NO el `python` del PATH (3.11.9, sin numpy).
      py -3.14 -m pip install --require-hashes -r terraquantum-backend/requirements.lock
      py -3.14 -m pip install -r terraquantum-backend/requirements-build.txt

  Uso:
      powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1
      #   -SkipBackend   no re-empaqueta el backend (usa dist/ existente)
      #   -SkipFrontend  no re-construye el frontend (usa .next/standalone existente)
      #   -InstallDeps   instala el cierre verificado (--require-hashes) antes de empaquetar

  Fase 27: este script ya no empaqueta a ciegas. Comprueba el interprete contra
  .python-version, comprueba el entorno contra requirements.lock, y propaga el
  fallo del .spec (que ahora aborta si le falta una dependencia). Antes, las tres
  cosas fallaban en silencio y el instalador salia incompleto.
#>
[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    # Fase 27: instala el cierre verificado con hashes ANTES de empaquetar. Por
    # defecto NO se instala nada: el script comprueba y aborta diciendo el
    # comando exacto. Un script de build que modifica en silencio el Python del
    # usuario es justo la clase de accion que este proyecto no permite.
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"
$Root       = Split-Path -Parent $PSScriptRoot
$Backend    = Join-Path $Root "terraquantum-backend"
$Web        = Join-Path $Root "terraquantum-web"
$SrcTauri   = Join-Path $Web  "src-tauri"
$Resources  = Join-Path $SrcTauri "resources"

function Section($n) { Write-Host "`n=== $n ===" -ForegroundColor Cyan }

# ── 0) El interprete: el que declara .python-version, no el que caiga ─────────
# Fase 27 (H-23). Hasta aqui el script llamaba a `python` a secas y NUNCA lo
# comparaba con `.python-version`. MEDIDO en la maquina de desarrollo el
# 2026-09-03: el `python` del PATH es **3.11.9 y no tiene numpy**, mientras
# `.python-version` declara **3.14.4** y `py -3.14` si lo tiene (numpy 2.4.4).
# Con `pyinstaller` instalado en ese 3.11 el build habria arrancado y producido
# un ejecutable contra un arbol de dependencias que no es el del producto.
# La version MAYOR.MENOR es fatal (decide el arbol entero de dependencias); el
# parche solo avisa, porque exigirlo bloquearia un 3.14.5 sano sin ganar nada.
function Get-PyVersion($exe, $preArgs) {
    try {
        $raw = & $exe @preArgs -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"
    } catch { return $null }
    if ($LASTEXITCODE -ne 0) { return $null }
    if (-not $raw) { return $null }
    return ($raw | Select-Object -First 1).ToString().Trim()
}

$VersionFile = Join-Path $Backend ".python-version"
if (-not (Test-Path $VersionFile)) { throw "Falta ${VersionFile}: el interprete es parte del build." }
$WantedFull = (Get-Content $VersionFile -Raw).Trim()
$WantedMM   = ($WantedFull.Split('.')[0..1]) -join '.'

$PyExe = $null; $PyArgs = @(); $PyFound = $null
$probe = Get-PyVersion "py" @("-$WantedMM")
if ($probe) { $PyExe = "py"; $PyArgs = @("-$WantedMM"); $PyFound = $probe }
else {
    $probe = Get-PyVersion "python" @()
    if ($probe) { $PyExe = "python"; $PyArgs = @(); $PyFound = $probe }
}
if (-not $PyExe) {
    throw "No se encontro ningun interprete de Python ejecutable (`py -$WantedMM` ni `python`)."
}

$FoundMM = ($PyFound.Split('.')[0..1]) -join '.'
if ($FoundMM -ne $WantedMM) {
    throw ("Interprete equivocado: se encontro Python $PyFound y .python-version exige $WantedFull.`n" +
           "  El arbol de dependencias de $FoundMM NO es el del producto (p. ej. zarr==3.x exige >=3.12).`n" +
           "  Instala Python $WantedFull y vuelve a lanzar; el script usara `py -$WantedMM` automaticamente.")
}
if ($PyFound -ne $WantedFull) {
    Write-Host "  AVISO: Python $PyFound; .python-version declara $WantedFull (mismo $WantedMM, se continua)." -ForegroundColor Yellow
}
Write-Host "  interprete: $PyExe $PyArgs -> Python $PyFound" -ForegroundColor DarkGray

# ── 1) Backend -> exe (PyInstaller) ───────────────────────────────────────────
if (-not $SkipBackend) {
    Section "1/4  Empaquetando backend con PyInstaller"
    Push-Location $Backend
    try {
        # Fase 27 (NUEVO-4): instalar —o al menos COMPROBAR— el cierre verificado
        # antes de empaquetar. Sin esto, una dependencia ausente no paraba nada:
        # el `.spec` recolectaba [] y el instalador salia sin ella, en silencio.
        if ($InstallDeps) {
            Write-Host "  instalando el cierre verificado (--require-hashes)..." -ForegroundColor DarkGray
            & $PyExe @PyArgs -m pip install --require-hashes -r requirements.lock
            if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de requirements.lock." }
        }
        & $PyExe @PyArgs scripts/ci/check_env_against_lock.py
        if ($LASTEXITCODE -ne 0) {
            throw ("El entorno no puede construir el instalador (ver arriba).`n" +
                   "  Corrigelo con:  $PyExe $PyArgs -m pip install --require-hashes -r requirements.lock`n" +
                   "  O relanza este script con -InstallDeps.")
        }

        # Fase 2 (H-23): el pin de PyInstaller solo sirve si alguien lo comprueba.
        # Una version distinta produce un binario distinto del mismo codigo, y este
        # binario se firma y se distribuye. Se avisa, no se bloquea: el build sigue
        # siendo posible, pero deja de ser reproducible en silencio.
        $pinned = (Select-String -Path "requirements-build.txt" -Pattern "^pyinstaller==(.+)$").Matches.Groups[1].Value
        $installed = $null
        try { $installed = & $PyExe @PyArgs -c "import PyInstaller; print(PyInstaller.__version__)" } catch { $installed = $null }
        if ($LASTEXITCODE -ne 0 -or -not $installed) {
            throw ("PyInstaller no esta instalado en Python $PyFound.`n" +
                   "      $PyExe $PyArgs -m pip install -r requirements-build.txt")
        }
        $installed = ($installed | Select-Object -First 1).ToString().Trim()
        if ($pinned -and $installed -ne $pinned) {
            Write-Host "  AVISO: pyinstaller instalado $installed, pineado $pinned -> el binario puede diferir." -ForegroundColor Yellow
            Write-Host "         $PyExe $PyArgs -m pip install -r requirements-build.txt" -ForegroundColor Yellow
        } else {
            Write-Host "  pyinstaller $installed (coincide con el pin)" -ForegroundColor DarkGray
        }
        & $PyExe @PyArgs -m PyInstaller terraquantum_backend.spec --noconfirm --log-level WARN
        # El .spec aborta a proposito si le falta una dependencia (Fase 27). Antes
        # este `if` era la UNICA red: miraba si el exe existia, no si estaba completo.
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo (codigo $LASTEXITCODE) — el instalador NO se construye." }
        if (-not (Test-Path "dist/terraquantum-backend.exe")) { throw "PyInstaller no produjo el exe." }
    } finally { Pop-Location }
} else { Section "1/4  Backend: omitido (usa dist/ existente)" }

# ── 2) Frontend -> standalone (Next.js) ───────────────────────────────────────
if (-not $SkipFrontend) {
    Section "2/4  Construyendo frontend standalone (Next.js)"
    Push-Location $Web
    try {
        & npm run build
        if (-not (Test-Path ".next/standalone/server.js")) { throw "El build standalone no produjo server.js." }
    } finally { Pop-Location }
} else { Section "2/4  Frontend: omitido (usa .next/standalone existente)" }

# ── 3) Staging de recursos ────────────────────────────────────────────────────
Section "3/4  Staging de sidecars + frontend en src-tauri/resources"
if (Test-Path $Resources) { Remove-Item -Recurse -Force $Resources }
New-Item -ItemType Directory -Force -Path (Join-Path $Resources "backend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Resources "node") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Resources "frontend") | Out-Null

Copy-Item (Join-Path $Backend "dist/terraquantum-backend.exe") (Join-Path $Resources "backend") -Force
$node = (Get-Command node).Source
Copy-Item $node (Join-Path $Resources "node/node.exe") -Force
Copy-Item (Join-Path $Web ".next/standalone/*") (Join-Path $Resources "frontend") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $Resources "frontend/.next") | Out-Null
Copy-Item (Join-Path $Web ".next/static") (Join-Path $Resources "frontend/.next/static") -Recurse -Force
Copy-Item (Join-Path $Web "public") (Join-Path $Resources "frontend/public") -Recurse -Force
if (-not (Test-Path (Join-Path $Resources "frontend/server.js"))) { throw "Staging incompleto: falta frontend/server.js." }
Write-Host "  recursos listos." -ForegroundColor Green

# ── 4) Tauri build -> instalador NSIS ─────────────────────────────────────────
Section "4/4  Tauri build (compila Rust + empaqueta NSIS)"
Push-Location $Web
try {
    & npx tauri build
} finally { Pop-Location }

$installer = Get-ChildItem (Join-Path $SrcTauri "target/release/bundle/nsis") -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($installer) {
    Write-Host "`nOK — instalador:" -ForegroundColor Green
    Write-Host "  $($installer.FullName)"
} else {
    Write-Host "`nBuild terminó pero no se encontró el instalador NSIS." -ForegroundColor Yellow
}
