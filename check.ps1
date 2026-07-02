# TerraQuantum — CI mínima local (F1). Corre esto antes de cada commit.
# Uso:  .\check.ps1            (rápido: compile + lint + tsc)
#       .\check.ps1 -Tests     (+ suite pytest completa, ~minutos)
param([switch]$Tests)

$ErrorActionPreference = "Stop"
$fail = $false
$root = $PSScriptRoot

Write-Host "[1/4] compileall backend..." -ForegroundColor Cyan
Push-Location "$root\terraquantum-backend"
python -m compileall -q api services exploration core schemas workers scripts
if ($LASTEXITCODE -ne 0) { $fail = $true; Write-Host "  FALLO compileall" -ForegroundColor Red }
Pop-Location

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
