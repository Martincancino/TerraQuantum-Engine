# TerraQuantum — CI mínima local (F1). Corre esto antes de cada commit.
# Uso:  .\check.ps1            (rápido: compile + lint + tsc)
#       .\check.ps1 -Tests     (+ suite pytest completa, ~minutos)
param([switch]$Tests)

$ErrorActionPreference = "Stop"
$fail = $false
$root = $PSScriptRoot

Write-Host "[1/4] compile check backend..." -ForegroundColor Cyan
Push-Location "$root\terraquantum-backend"
# Fase 3: el mismo comprobador que usa la CI. Antes esta linea llevaba su PROPIA
# lista de paquetes (sin middleware ni reporting) y la CI llevaba otra (con dos
# directorios inexistentes). Dos listas a mano, ambas mal, de formas distintas.
python scripts/ci/compile_check.py
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO compile check" -ForegroundColor Red }
# Fase 3: las guardas baratas van en el check local, no solo en la CI. Cuestan
# segundos y evitan descubrir en el PR que crecio una funcion o que un script
# nuevo de validation/ no declaro si decide o solo mide.
python scripts/ci/ast_budgets.py
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO presupuestos AST" -ForegroundColor Red }
python scripts/ci/validation_inventory.py
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO inventario de validacion" -ForegroundColor Red }
# Fase 3 (cierre): este es el unico sitio donde el cierre de dependencias puede
# fallar de verdad. En el runner lo instalado ES el cierre, asi que alli no dice
# nada; aqui detecta que el codigo importa algo que `pip install -r requirements.txt`
# no instalaria - que es como `psutil` se volvio invisible al caer `distributed`.
python scripts/ci/deps_closure.py
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO cierre de dependencias" -ForegroundColor Red }
Pop-Location

# Fase 28: el shell de escritorio tambien tiene tests que DECIDEN (arranque
# honesto H-17/H-19/H-21, y desde ahora la clasificacion del updater H-20), y
# hasta hoy no los corria NADIE: ni esta puerta ni la CI. Nueve tests escritos
# como gate y ejecutados por nadie. Con la cache templada cuesta segundos.
Write-Host "[1b/4] cargo test shell de escritorio..." -ForegroundColor Cyan
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    Push-Location "$root\terraquantum-web\src-tauri"
    # Sin esto, `2>&1` sobre un .exe en PowerShell 5.1 envuelve stderr en
    # ErrorRecords y, con ErrorActionPreference=Stop, LANZA aunque cargo salga 0.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & cargo test --lib
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    Pop-Location
    if ($code -ne 0) { $fail = $true; Write-Host "  FALLO cargo test" -ForegroundColor Red }
} else {
    Write-Host "  cargo no esta en el PATH: omitido (la CI si lo corre)" -ForegroundColor DarkGray
}

Write-Host "[2/4] tsc --noEmit frontend..." -ForegroundColor Cyan
Push-Location "$root\terraquantum-web"
npx tsc --noEmit
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO tsc" -ForegroundColor Red }

Write-Host "[3/4] eslint frontend..." -ForegroundColor Cyan
npx eslint app componentes lib workers store --max-warnings 200
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO eslint" -ForegroundColor Red }
Pop-Location

if ($Tests) {
    Write-Host "[4/4] pytest suite completa..." -ForegroundColor Cyan
    Push-Location "$root\terraquantum-backend"
    python -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO pytest" -ForegroundColor Red }
    Pop-Location
} else {
    Write-Host "[4/4] pytest omitido (usa -Tests para la suite completa)" -ForegroundColor DarkGray
}

if ($fail) { Write-Host "`nCHECK: ROJO" -ForegroundColor Red; exit 1 }
Write-Host "`nCHECK: VERDE" -ForegroundColor Green
