<#
  TerraQuantum — GATE de la Fase 2: matriz de arranque adverso.

  Este script DECIDE (exit 0 / exit 1). No es un diagnostico que imprime numeros
  para que alguien los interprete: esa era justamente la critica H-22 de la
  auditoria a dos tercios de scripts/validation.

  Que audita: los 6 casos que la Fase 2 declara como criterio de aceptacion.

    (a) puerto del backend ocupado    -> avisa y usa uno alternativo, y arranca
    (b) puerto del frontend ocupado   -> idem
    (c) backend ausente (cuarentena)  -> ERROR en espanol, con accion, sin colgarse
    (d) cierre violento a mitad       -> cero procesos huerfanos (Job Object)
    (e) cierre violento con la app en uso -> cero huerfanos
    (f) segundo arranque tras cada caso  -> vuelve a llegar a "listo"

  Como puede auditarse sin pilotar la interfaz: el orquestador escribe TODO lo
  que muestra el splash en %APPDATA%\TerraQuantum\logs\boot.jsonl. El gate lee
  ese diario. Si el splash y el diario divergieran, el bug estaria en una sola
  linea (`publish`), que escribe ambos a la vez.

  Requisito: la app compilada.
      cd terraquantum-web\src-tauri ; cargo build --release
  El gate sincroniza el mismo `resources\` que empaqueta el instalador junto al
  ejecutable (en Windows Tauri las resuelve AHI, y `cargo build` no las copia).
  Si tocaste el BACKEND, reconstruye antes su sidecar o mediras una app vieja:
      python -m PyInstaller terraquantum_backend.spec --noconfirm
  y vuelve a hacer el staging (scripts/build_desktop.ps1 pasos 1-3).

  Uso:
      powershell -ExecutionPolicy Bypass -File scripts/f2_gate_boot_matrix.ps1
      #   -Only a,c      corre solo esos casos
      #   -KeepJournals  no borra los diarios de cada caso (para inspeccion)
#>
[CmdletBinding()]
param(
    [string]$Only = "",
    [switch]$KeepJournals
)

$ErrorActionPreference = "Stop"
$Root      = Split-Path -Parent $PSScriptRoot
$SrcTauri  = Join-Path $Root "terraquantum-web\src-tauri"
$AppExe    = Join-Path $SrcTauri "target\release\app.exe"
$BackendRes= Join-Path $SrcTauri "target\release\resources\backend\terraquantum-backend.exe"
$LogsDir   = Join-Path $env:APPDATA "TerraQuantum\logs"
$Journal   = Join-Path $LogsDir "boot.jsonl"

$BOOT_TIMEOUT_S = 240
$SIDECAR_NAMES  = @("terraquantum-backend", "node")

$script:Results = @()
$script:Failures = 0

function Section($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  [OK]   $text" -ForegroundColor Green }
function Bad($text)  { Write-Host "  [FALLA] $text" -ForegroundColor Red; $script:Failures++ }
function Info($text) { Write-Host "  $text" -ForegroundColor DarkGray }

function Assert($condition, $message) {
    if ($condition) { Ok $message } else { Bad $message }
    return [bool]$condition
}

# ── Utilidades de proceso ─────────────────────────────────────────────────────

function Get-SidecarPids {
    $pids = @()
    foreach ($name in $SIDECAR_NAMES) {
        try {
            $procs = Get-Process -Name $name -ErrorAction Stop
            foreach ($p in $procs) { $pids += $p.Id }
        } catch { }
    }
    return $pids
}

function Wait-Gone($pids, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $alive = @()
        foreach ($procId in $pids) {
            if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { $alive += $procId }
        }
        if ($alive.Count -eq 0) { return @() }
        Start-Sleep -Milliseconds 400
    }
    $still = @()
    foreach ($procId in $pids) {
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { $still += $procId }
    }
    return $still
}

function Stop-Hard($process, [switch]$Tree) {
    if (-not $process) { return }
    try {
        if ($Tree) { & taskkill /F /T /PID $process.Id 2>&1 | Out-Null }
        else       { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    } catch { }
}

# ── Utilidades del diario de arranque ─────────────────────────────────────────

function Reset-Journal {
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
    Remove-Item $Journal -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $LogsDir "boot.prev.jsonl") -Force -ErrorAction SilentlyContinue
}

function Read-Journal {
    if (-not (Test-Path $Journal)) { return @() }
    $events = @()
    # -Encoding UTF8: el diario lo escribe Rust en UTF-8 y PowerShell 5.1 lee en
    # la pagina de codigos ANSI por defecto. Sin esto, "cálculo" llega como
    # "cÃ¡lculo" y la comprobacion de idioma juzgaria un texto corrompido.
    foreach ($line in (Get-Content $Journal -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if (-not $line.Trim()) { continue }
        try { $events += ($line | ConvertFrom-Json) } catch { }
    }
    return $events
}

function Wait-BootOutcome($seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($e in (Read-Journal)) {
            if ($e.stage -eq "ready" -or $e.stage -eq "error") { return $e }
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Occupy-Port([int]$port) {
    # Un listener real, en el mismo puerto y en loopback: es lo que veria el
    # orquestador si el usuario tuviera otra app ahi (o un zombi propio).
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $port)
    $listener.Start()
    return $listener
}

# ── Motor de un caso ──────────────────────────────────────────────────────────

function Start-App {
    $before = Get-SidecarPids
    $proc = Start-Process -FilePath $AppExe -PassThru
    return @{ Process = $proc; SidecarsBefore = $before }
}

function Stop-App($ctx, [switch]$Violent) {
    # Violent = como el usuario harta: matar SOLO el shell desde el Administrador
    # de Tareas. Sin Job Object, los sidecars sobreviven (H-18).
    Stop-Hard $ctx.Process
    Start-Sleep -Seconds 1
}

function Assert-NoOrphans($ctx, $label) {
    $after = Get-SidecarPids
    $new = @()
    foreach ($procId in $after) { if ($ctx.SidecarsBefore -notcontains $procId) { $new += $procId } }
    $still = Wait-Gone $new 15
    $ok = Assert ($still.Count -eq 0) "$label : cero procesos huerfanos"
    if (-not $ok) {
        Info "PIDs supervivientes: $($still -join ', ')"
        foreach ($procId in $still) { Stop-Hard (Get-Process -Id $procId -ErrorAction SilentlyContinue) -Tree }
    }
    return $ok
}

function Assert-SpanishActionableError($ev, $expectedCode) {
    $ok = $true
    $ok = (Assert ($ev.stage -eq "error") "el arranque termina en ERROR declarado (no en espera infinita)") -and $ok
    $ok = (Assert ($ev.code -eq $expectedCode) "codigo esperado $expectedCode (visto: $($ev.code))") -and $ok
    $ok = (Assert ([string]::IsNullOrWhiteSpace($ev.message) -eq $false) "hay un mensaje para el usuario") -and $ok
    $ok = (Assert ([string]::IsNullOrWhiteSpace($ev.hint) -eq $false) "el mensaje dice QUE HACER") -and $ok
    # Heuristica de idioma: el catalogo del producto es en espanol.
    $spanish = "(?i)(reinstala|antivirus|reintenta|registros|instalaci|cuarentena|puerto|no se |motor|interfaz)"
    $ok = (Assert (("$($ev.message) $($ev.hint)") -match $spanish) "el mensaje esta en espanol") -and $ok
    if ($ev.message) { Info "mensaje: $($ev.message)" }
    if ($ev.hint)    { Info "accion : $($ev.hint)" }
    return $ok
}

function Record($case, $ok) {
    $script:Results += [pscustomobject]@{ Caso = $case; Resultado = $(if ($ok) { "PASA" } else { "FALLA" }) }
}

function Invoke-SecondLaunch($case) {
    # (f) del criterio de aceptacion: tras CADA caso, el siguiente arranque
    # tiene que llegar a "listo". Es la mitad del dano de H-18: un huerfano no
    # molesta hoy, impide arrancar manana.
    Reset-Journal
    $ctx = Start-App
    $outcome = Wait-BootOutcome $BOOT_TIMEOUT_S
    $ok = Assert ($null -ne $outcome -and $outcome.stage -eq "ready") "$case (f) el segundo arranque llega a LISTO"
    if ($outcome -and $outcome.stage -eq "error") { Info "error: $($outcome.code) - $($outcome.message)" }
    Stop-App $ctx
    $ok = (Assert-NoOrphans $ctx "$case (f)") -and $ok
    return $ok
}

# ── Casos ─────────────────────────────────────────────────────────────────────

function Case-A {
    Section "(a) El puerto del backend (8010) esta ocupado"
    Reset-Journal
    $listener = Occupy-Port 8010
    try {
        $ctx = Start-App
        $outcome = Wait-BootOutcome $BOOT_TIMEOUT_S
        $ok = Assert ($null -ne $outcome) "el arranque llega a un desenlace (no se cuelga)"
        $ok = (Assert ($outcome.stage -eq "ready") "arranca igual, con puerto alternativo") -and $ok
        $warn = (Read-Journal | Where-Object { $_.code -eq "BACKEND_PORT_FALLBACK" } | Select-Object -First 1)
        $ok = (Assert ($null -ne $warn) "avisa del cambio de puerto en vez de fallar en silencio") -and $ok
        if ($warn) { Info "aviso: $($warn.message)" }
        # Que llegue a "ready" con el backend en otro puerto PRUEBA el emparejamiento:
        # la sonda del frontend es /api/backend-health y exige el token del backend.
        Stop-App $ctx
        $ok = (Assert-NoOrphans $ctx "(a)") -and $ok
    } finally { $listener.Stop() }
    $ok = (Invoke-SecondLaunch "(a)") -and $ok
    Record "a - puerto 8010 ocupado" $ok
}

function Case-B {
    Section "(b) El puerto del frontend (3000) esta ocupado"
    Reset-Journal
    $listener = Occupy-Port 3000
    try {
        $ctx = Start-App
        $outcome = Wait-BootOutcome $BOOT_TIMEOUT_S
        $ok = Assert ($null -ne $outcome) "el arranque llega a un desenlace"
        $ok = (Assert ($outcome.stage -eq "ready") "arranca igual, con puerto alternativo") -and $ok
        $warn = (Read-Journal | Where-Object { $_.code -eq "FRONTEND_PORT_FALLBACK" } | Select-Object -First 1)
        $ok = (Assert ($null -ne $warn) "avisa del cambio de puerto") -and $ok
        if ($warn) { Info "aviso: $($warn.message)" }
        if ($outcome.stage -eq "ready" -and $outcome.url) { Info "navega a: $($outcome.url)" }
        Stop-App $ctx
        $ok = (Assert-NoOrphans $ctx "(b)") -and $ok
    } finally { $listener.Stop() }
    $ok = (Invoke-SecondLaunch "(b)") -and $ok
    Record "b - puerto 3000 ocupado" $ok
}

function Case-C {
    Section "(c) El backend no esta (simula cuarentena del antivirus)"
    Reset-Journal
    $quarantine = "$BackendRes.cuarentena"
    if (-not (Test-Path $BackendRes)) { throw "No se encontro el backend empaquetado en $BackendRes" }
    Move-Item $BackendRes $quarantine -Force
    try {
        $ctx = Start-App
        $outcome = Wait-BootOutcome 60
        $ok = Assert ($null -ne $outcome) "no se queda en el splash para siempre (H-17)"
        if ($outcome) { $ok = (Assert-SpanishActionableError $outcome "BACKEND_MISSING") -and $ok }
        Stop-App $ctx
        $ok = (Assert-NoOrphans $ctx "(c)") -and $ok
    } finally { Move-Item $quarantine $BackendRes -Force }
    $ok = (Invoke-SecondLaunch "(c)") -and $ok
    Record "c - backend en cuarentena" $ok
}

function Case-D {
    Section "(d) Cierre violento del shell A MITAD del arranque"
    Reset-Journal
    $ctx = Start-App
    # Esperar a que el backend este vivo pero el arranque sin terminar.
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if ((Get-SidecarPids | Where-Object { $ctx.SidecarsBefore -notcontains $_ }).Count -gt 0) { break }
        Start-Sleep -Milliseconds 300
    }
    $spawned = (Get-SidecarPids | Where-Object { $ctx.SidecarsBefore -notcontains $_ }).Count
    $ok = Assert ($spawned -gt 0) "habia al menos un sidecar vivo cuando se mato el shell"
    Stop-App $ctx -Violent
    $ok = (Assert-NoOrphans $ctx "(d)") -and $ok
    $ok = (Invoke-SecondLaunch "(d)") -and $ok
    Record "d - kill del shell a mitad de arranque" $ok
}

function Case-E {
    Section "(e) Cierre violento con la aplicacion EN USO"
    Reset-Journal
    $ctx = Start-App
    $outcome = Wait-BootOutcome $BOOT_TIMEOUT_S
    $ok = Assert ($null -ne $outcome -and $outcome.stage -eq "ready") "la app llega a LISTO antes de la prueba"
    if ($outcome -and $outcome.url) {
        # Carga real sobre ambos sidecars: el proxy del frontend obliga al
        # backend a trabajar. NOTA HONESTA: no es una inversion completa (eso
        # exige un paquete de datos); es trafico real en vuelo, no reposo.
        try {
            1..5 | ForEach-Object {
                Invoke-WebRequest -Uri "$($outcome.url)/api/backend-health" -UseBasicParsing -TimeoutSec 10 | Out-Null
            }
            Info "trafico servido por ambos sidecars antes del cierre"
        } catch { Info "no se pudo generar trafico: $($_.Exception.Message)" }
    }
    Stop-App $ctx -Violent
    $ok = (Assert-NoOrphans $ctx "(e)") -and $ok
    $ok = (Invoke-SecondLaunch "(e)") -and $ok
    Record "e - kill del shell con la app en uso" $ok
}

# ── Main ──────────────────────────────────────────────────────────────────────

Section "GATE Fase 2 — matriz de arranque adverso"
if (-not (Test-Path $AppExe)) {
    Write-Host "No existe $AppExe" -ForegroundColor Red
    Write-Host "Compila primero:  cd terraquantum-web\src-tauri ; cargo build --release" -ForegroundColor Yellow
    exit 1
}
Info "app      : $AppExe"
Info "diario   : $Journal"
Info "sidecars vigilados: $($SIDECAR_NAMES -join ', ')"

# En Windows, Tauri resuelve `resources/` JUNTO AL EJECUTABLE. `tauri build` las
# copia al empaquetar; `cargo build --release` no. Se sincronizan aqui para que
# el gate mida la MISMA app que se distribuye y no una a medio montar.
$StagedRes = Join-Path $SrcTauri "resources"
$RunRes    = Join-Path $SrcTauri "target\release\resources"
if (-not (Test-Path $StagedRes)) {
    Write-Host "Faltan los recursos en $StagedRes — corre scripts/build_desktop.ps1 primero." -ForegroundColor Red
    exit 1
}
# La marca NO puede ser la fecha del directorio raiz: cambiar archivos DENTRO de
# sus subcarpetas no la toca, y el gate mediria una app vieja creyendola nueva.
# Se comparan los dos artefactos que definen la app: el exe del backend y el
# BUILD_ID que Next escribe en cada build del frontend.
function Stamp($base) {
    $exe = Join-Path $base "backend\terraquantum-backend.exe"
    $bid = Join-Path $base "frontend\.next\BUILD_ID"
    $a = if (Test-Path $exe) { (Get-Item $exe).LastWriteTimeUtc.Ticks } else { 0 }
    $b = if (Test-Path $bid) { (Get-Content $bid -Raw).Trim() } else { "" }
    return "$a|$b"
}
if ((-not (Test-Path $RunRes)) -or ((Stamp $StagedRes) -ne (Stamp $RunRes))) {
    Info "sincronizando recursos junto al ejecutable (~1 GB, un par de minutos)"
    & robocopy $StagedRes $RunRes /MIR /NFL /NDL /NJH /NJS /NP /MT:8 | Out-Null
    if ($LASTEXITCODE -ge 8) { Write-Host "robocopy fallo (rc=$LASTEXITCODE)" -ForegroundColor Red; exit 1 }
    if ((Stamp $StagedRes) -ne (Stamp $RunRes)) {
        Write-Host "La sincronizacion no dejo los mismos artefactos. Abortando." -ForegroundColor Red
        exit 1
    }
}
Info "sidecars medidos: $(Stamp $RunRes)"

# Preflight: la matriz OCUPA 8010 y 3000 a proposito. Si ya estan tomados por
# algo ajeno (un dev server, una instancia abierta), el gate no puede montar sus
# casos y lo dice en vez de fallar con un error de .NET a media corrida.
foreach ($p in @(8010, 3000)) {
    try {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $p)
        $l.Start(); $l.Stop()
    } catch {
        Write-Host "El puerto $p ya esta ocupado antes de empezar." -ForegroundColor Red
        Write-Host "Cierra el dev server o la instancia de TerraQuantum y vuelve a lanzar el gate." -ForegroundColor Yellow
        exit 1
    }
}

# El navegador no debe conocer la URL del backend (H-21). Es estatico e
# instantaneo, asi que va primero: si falla, la matriz ni siquiera importa.
Section "(0) Sin llamadas directas navegador->backend"
Push-Location (Join-Path $Root "terraquantum-web")
try {
    & node "scripts/check_client_backend_calls.mjs"
    $staticOk = ($LASTEXITCODE -eq 0)
} finally { Pop-Location }
[void](Assert $staticOk "ninguna llamada directa navegador->backend en codigo de cliente")
Record "0 - sin llamadas directas navegador->backend" $staticOk

$selected = if ($Only) { $Only.Split(",") | ForEach-Object { $_.Trim().ToLower() } } else { @("a","b","c","d","e") }

try {
    if ($selected -contains "a") { Case-A }
    if ($selected -contains "b") { Case-B }
    if ($selected -contains "c") { Case-C }
    if ($selected -contains "d") { Case-D }
    if ($selected -contains "e") { Case-E }
} finally {
    if (-not $KeepJournals) { Reset-Journal }
}

Section "RESULTADO"
$script:Results | Format-Table -AutoSize | Out-String | Write-Host

# Un gate que no ejecuto nada NO pasa: "verde por vacio" es la forma mas comun
# de que una puerta deje de proteger sin que nadie se entere. Y una corrida
# parcial (-Only) no puede reclamar el veredicto de la matriz completa.
$expected = 6
if ($script:Results.Count -eq 0) {
    Write-Host "GATE FASE 2: FALLA — no se ejecuto ningun caso (revisa -Only)" -ForegroundColor Red
    exit 1
}
if ($script:Failures -gt 0) {
    Write-Host "GATE FASE 2: FALLA ($script:Failures comprobaciones)" -ForegroundColor Red
    exit 1
}
if ($script:Results.Count -lt $expected) {
    Write-Host "PARCIAL: $($script:Results.Count)/$expected casos verdes (corrida con -Only)." -ForegroundColor Yellow
    Write-Host "No cuenta como gate de la Fase 2: corre el script sin -Only." -ForegroundColor Yellow
    exit 1
}
Write-Host "GATE FASE 2: PASA — $($script:Results.Count)/$expected casos de la matriz adversa" -ForegroundColor Green
exit 0
