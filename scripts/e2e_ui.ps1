# F8 - UI E2E (Playwright) en un comando: build de produccion + tests.
# Uso:  .\scripts\e2e_ui.ps1            (corre los recorridos)
#       .\scripts\e2e_ui.ps1 -Update    (regenera los baselines de screenshot)
# Requiere: navegador chromium instalado (npx playwright install chromium).
# El playwright.config levanta backend (:8010) y frontend (:3000, next start) solo.
param([switch]$Update)
$ErrorActionPreference = "Stop"
$web = Join-Path $PSScriptRoot "..\terraquantum-web"

Push-Location $web
try {
    Write-Host "[1/2] next build (produccion, hidratacion fiable para E2E)..." -ForegroundColor Cyan
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "next build fallo" }

    Write-Host "[2/2] playwright test..." -ForegroundColor Cyan
    if ($Update) { npx playwright test --update-snapshots } else { npx playwright test }
    if ($LASTEXITCODE -ne 0) { Write-Host "E2E: ROJO" -ForegroundColor Red; exit 1 }
    Write-Host "E2E: VERDE" -ForegroundColor Green
}
finally { Pop-Location }
