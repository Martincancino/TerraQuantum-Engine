<#
  TerraQuantum — GATE de la Fase 28: el updater o apunta bien, o lo dice.

  Este script DECIDE (exit 0 / exit 1).

  ── Por que el gate del plan no bastaba ─────────────────────────────────────
  El plan pedia: "«Buscar actualizaciones» distingue TRES estados —al dia / hay
  version nueva / no se pudo comprobar— y no confunde el tercero con los otros
  dos". Medido contra el codigo de HEAD, ese liston YA PASABA antes de tocar
  nada: el payload de error llevaba state:"error", distinto de "current" y de
  "available". Y sin embargo el defecto era real.

  Lo que fallaba no era que los estados no se distinguieran entre si: era que
  DOS DE LOS TRES ERAN INALCANZABLES y el unico alcanzable MENTIA sobre su
  causa. Con el endpoint apuntando a un repositorio ajeno, toda comprobacion
  daba 404, y el 404 se le presentaba al usuario como "si no tienes internet es
  lo esperable" — con internet perfecto.

  Asi que este gate no pregunta "¿son distintos?" sino tres cosas mas duras:
    (1) ¿el endpoint es NUESTRO, y https, y termina en latest.json?
    (2) ¿que estado produce HOY el endpoint real, medido contra la red?
    (3) ¿la clasificacion sigue separando 404 de falta de red, y ninguno de los
        textos culpa a la conexion cuando el servidor SI contesto?

  ── Lo que este gate NO observa, y por que ──────────────────────────────────
  No pilota la ventana real recorriendo los cuatro desenlaces. `Updater::check()`
  exige un AppHandle de Tauri, y construirlo en un test obliga a activar la
  feature `test` del crate `tauri` — una dependencia nueva, que la regla del
  proyecto no permite tomar sin permiso expreso. Lo que si se ejercita entero es
  la clasificacion (18 tests) y el contrato del manifiesto (el generador real).
  El tramo no cubierto es el que va de "el crate devuelve X" a "nuestra funcion
  recibe X", y ese esta medido por lectura, citado en `outcome_of_error`.
  La comprobacion manual equivalente esta en docs/04, seccion 6.

  Uso:
      powershell -ExecutionPolicy Bypass -File scripts/f28_gate_updater.ps1
      #   -SkipNetwork   omite la sonda (2), para correr sin salida a internet
#>
[CmdletBinding()]
param([switch]$SkipNetwork)

$ErrorActionPreference = "Stop"
$Root     = Split-Path -Parent $PSScriptRoot
$SrcTauri = Join-Path $Root "terraquantum-web\src-tauri"
$Conf     = Join-Path $SrcTauri "tauri.conf.json"

$script:Failures = 0
$script:Results  = @()

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Check($name, $ok, $detail) {
    $script:Results += [pscustomobject]@{ Comprobacion = $name; Estado = $(if ($ok) { "OK" } else { "FALLA" }); Detalle = $detail }
    if (-not $ok) { $script:Failures++ }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("  [{0}] {1} — {2}" -f $(if ($ok) { "OK" } else { "XX" }), $name, $detail) -ForegroundColor $color
}

# ── (1) El endpoint ──────────────────────────────────────────────────────────
Section "1/4  A donde apunta el updater"

$conf = Get-Content $Conf -Raw | ConvertFrom-Json
$endpoints = @($conf.plugins.updater.endpoints)

Check "hay al menos un endpoint" ($endpoints.Count -ge 1) "$($endpoints.Count) declarado(s)"

foreach ($e in $endpoints) {
    Check "https" ($e -like "https://*") $e
    # H-20 en su forma literal. `api.github.com/users/TerraQuantum` devuelve 200:
    # es la cuenta de un TERCERO REAL (id 90737998), no una organizacion nuestra.
    Check "no apunta a la cuenta de un tercero" ($e -notlike "*/TerraQuantum/terraquantum/*") $e
    Check "apunta al remoto real" ($e -like "*/Martincancino/TerraQuantum-Engine/*") $e
    Check "el manifiesto se llama latest.json" ($e -like "*/latest.json") $e
}
Check "hay pubkey para verificar la firma" (-not [string]::IsNullOrWhiteSpace($conf.plugins.updater.pubkey)) "minisign"

# ── (2) Que ve el usuario HOY contra la red real ─────────────────────────────
Section "2/4  El estado real de hoy, medido contra la red"

if ($SkipNetwork) {
    Write-Host "  (omitido por -SkipNetwork)" -ForegroundColor DarkGray
} else {
    foreach ($e in $endpoints) {
        $status = $null
        try {
            $resp = Invoke-WebRequest -Uri $e -Method Get -TimeoutSec 25 -MaximumRedirection 5 -ErrorAction Stop
            $status = [int]$resp.StatusCode
        } catch [System.Net.WebException] {
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        } catch {
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        }

        if ($null -eq $status) {
            Write-Host "  .. sin respuesta: el estado de hoy seria UPDATE_SIN_RED" -ForegroundColor Yellow
        } elseif ($status -eq 200) {
            Write-Host "  .. HTTP 200: hay manifiesto. El estado sera UPDATE_AL_DIA o UPDATE_DISPONIBLE" -ForegroundColor Green
        } elseif ($status -eq 404) {
            # Este es el estado de hoy y NO es un fallo del gate: es exactamente
            # lo que la fase hace decir en voz alta. Lo que si seria un fallo es
            # que se presentara como falta de internet.
            Write-Host "  .. HTTP 404: no hay ninguna version publicada todavia." -ForegroundColor Yellow
            Write-Host "     El usuario vera UPDATE_SIN_PUBLICAR, que es la verdad." -ForegroundColor Yellow
            Write-Host "     Recordatorio: el repositorio es PRIVADO (medido 2026-09-05), asi que" -ForegroundColor DarkGray
            Write-Host "     esto seguira dando 404 aunque se publique. Ver .github/workflows/release.yml" -ForegroundColor DarkGray
        } else {
            Write-Host "  .. HTTP ${status}: se clasificara como UPDATE_SIN_PUBLICAR" -ForegroundColor Yellow
        }
        $script:Results += [pscustomobject]@{ Comprobacion = "sonda de red"; Estado = "MEDIDO"; Detalle = "$e -> $(if($null -eq $status){'sin respuesta'}else{"HTTP $status"})" }
    }
}

# ── (3) La clasificacion y los textos ────────────────────────────────────────
Section "3/4  Los tests del shell (clasificacion, textos, endpoint)"

Push-Location $SrcTauri
try {
    # OJO con `2>&1` sobre un .exe en Windows PowerShell 5.1: envuelve cada linea
    # de stderr en un ErrorRecord y, con ErrorActionPreference=Stop, LANZA aunque
    # el proceso devuelva 0. cargo escribe su progreso por stderr, asi que sin
    # esto el gate fallaba por como se lee la salida, no por lo que mide.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $out = (& cargo test --lib 2>&1 | Out-String)
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP

    $ok = ($code -eq 0)
    if ($out -match "test result: ok\. (\d+) passed") { $n = $Matches[1] } else { $n = "?" }
    Check "cargo test --lib" $ok "$n tests"
    if (-not $ok) { Write-Host $out -ForegroundColor DarkGray }
} finally { Pop-Location }

# ── (4) El contrato del manifiesto, contra el generador REAL ─────────────────
Section "4/4  El manifiesto que publicara la release"

$gen = Join-Path $Root "scripts\release\make_latest_json.py"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("tq_f28_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
# Mismo motivo que arriba: python escribe por stderr y `2>&1` con Stop lanza.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $sig = Join-Path $tmp "setup.exe.sig"
    [System.IO.File]::WriteAllText($sig, "dW50cnVzdGVkIGNvbW1lbnQ6IGZpcm1hIGRlIHBydWViYQo=",
                                   (New-Object System.Text.UTF8Encoding($false)))
    $out = Join-Path $tmp "latest.json"

    # Camino sano: el generador real produce un manifiesto que el validador real acepta.
    & python $gen --version "0.3.0" --url "https://github.com/Martincancino/TerraQuantum-Engine/releases/download/v0.3.0/TerraQuantum_0.3.0_x64-setup.exe" --signature-file $sig --out $out 2>&1 | Out-Null
    $genOk = ($LASTEXITCODE -eq 0) -and (Test-Path $out)
    Check "el generador produce un manifiesto valido" $genOk "make_latest_json.py"

    if ($genOk) {
        $m = Get-Content $out -Raw | ConvertFrom-Json
        # La clave tiene que ser `windows-x86_64` a secas: `get_urls` solo prueba
        # la variante `-nsis` cuando el binario lleva marcador de bundle, y el de
        # `cargo` no lo lleva. Con la clave a secas funcionan los dos.
        Check "la clave de plataforma es windows-x86_64" ($null -ne $m.platforms.'windows-x86_64') "clave del manifiesto"
        Check "la version es semver completo" ($m.version -match '^\d+\.\d+\.\d+') $m.version
    }

    # Controles negativos. OJO con el liston: exigir solo "exit != 0" NO vale.
    # Medido por mutacion: al anular la comprobacion de plataforma, el validador
    # seguia saliendo distinto de cero... con un KeyError. Un traceback tambien
    # es exit 1, asi que el control pasaba en verde con la guarda ROTA. Se exige
    # ademas el DIAGNOSTICO, que es lo que distingue rechazar de estrellarse.
    # (Mismo escape que se cazo en la Fase 27.)
    # `Set-Content -Encoding utf8` de PowerShell 5.1 escribe **con BOM**, y eso
    # hacia reventar a json.loads: los controles negativos pasaban por el
    # traceback en vez de por el diagnostico. Se escribe sin BOM, y ademas el
    # generador lee con utf-8-sig para que un BOM ajeno no vuelva a disfrazarse
    # de rechazo.
    $sinBom = New-Object System.Text.UTF8Encoding($false)
    function Rechaza($etiqueta, $json, $esperado) {
        $f = Join-Path $tmp ("neg_" + [guid]::NewGuid().ToString("N") + ".json")
        [System.IO.File]::WriteAllText($f, $json, $sinBom)
        $salida = (& python $gen --validate $f 2>&1 | Out-String)
        $rechaza = ($LASTEXITCODE -ne 0)
        $explica = ($salida -match [regex]::Escape($esperado))
        $traceback = ($salida -match "Traceback")
        Check $etiqueta ($rechaza -and $explica -and -not $traceback) `
            $(if ($traceback) { "rechaza con TRACEBACK, no con diagnostico" } else { "control negativo" })
    }

    # OJO: los textos esperados van en comillas SIMPLES. El diagnostico del
    # generador lleva backticks de markdown, y entre comillas dobles PowerShell
    # los interpreta como caracter de escape.
    Rechaza "rechaza un manifiesto sin nuestra plataforma" `
        '{"version":"0.3.0","platforms":{"darwin-aarch64":{"url":"https://x/y","signature":"z"}}}' `
        'no trae ''windows-x86_64'''

    Rechaza "rechaza una version que no es semver completo" `
        '{"version":"0.3","platforms":{"windows-x86_64":{"url":"https://x/y","signature":"z"}}}' `
        'no es semver completo'

    Rechaza "rechaza una firma vacia" `
        '{"version":"0.3.0","platforms":{"windows-x86_64":{"url":"https://x/y","signature":"  "}}}' `
        'vacía'
} finally {
    $ErrorActionPreference = $prevEAP
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

# ── Veredicto ────────────────────────────────────────────────────────────────
Section "RESULTADO"
$script:Results | Format-Table -AutoSize | Out-String | Write-Host

if ($script:Results.Count -eq 0) {
    Write-Host "GATE FASE 28: FALLA — no se ejecuto ninguna comprobacion" -ForegroundColor Red
    exit 1
}
if ($script:Failures -gt 0) {
    Write-Host "GATE FASE 28: FALLA ($script:Failures comprobaciones)" -ForegroundColor Red
    exit 1
}
Write-Host "GATE FASE 28: PASA — el updater apunta a nuestro repositorio y dice la verdad sobre lo que encuentra" -ForegroundColor Green
exit 0
