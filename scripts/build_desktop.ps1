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
  Node.js, y las deps del backend + la cadena de build pineada:
      python -m pip install -r terraquantum-backend/requirements-build.txt

  Uso:
      powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1
      #   -SkipBackend   no re-empaqueta el backend (usa dist/ existente)
      #   -SkipFrontend  no re-construye el frontend (usa .next/standalone existente)
#>
[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root       = Split-Path -Parent $PSScriptRoot
$Backend    = Join-Path $Root "terraquantum-backend"
$Web        = Join-Path $Root "terraquantum-web"
$SrcTauri   = Join-Path $Web  "src-tauri"
$Resources  = Join-Path $SrcTauri "resources"

function Section($n) { Write-Host "`n=== $n ===" -ForegroundColor Cyan }

# ── 1) Backend -> exe (PyInstaller) ───────────────────────────────────────────
if (-not $SkipBackend) {
    Section "1/4  Empaquetando backend con PyInstaller"
    Push-Location $Backend
    try {
        # Fase 2 (H-23): el pin de PyInstaller solo sirve si alguien lo comprueba.
        # Una version distinta produce un binario distinto del mismo codigo, y este
        # binario se firma y se distribuye. Se avisa, no se bloquea: el build sigue
        # siendo posible, pero deja de ser reproducible en silencio.
        $pinned = (Select-String -Path "requirements-build.txt" -Pattern "^pyinstaller==(.+)$").Matches.Groups[1].Value
        $installed = (python -c "import PyInstaller; print(PyInstaller.__version__)").Trim()
        if ($pinned -and $installed -ne $pinned) {
            Write-Host "  AVISO: pyinstaller instalado $installed, pineado $pinned -> el binario puede diferir." -ForegroundColor Yellow
            Write-Host "         python -m pip install -r requirements-build.txt" -ForegroundColor Yellow
        } else {
            Write-Host "  pyinstaller $installed (coincide con el pin)" -ForegroundColor DarkGray
        }
        python -m PyInstaller terraquantum_backend.spec --noconfirm --log-level WARN
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
