"""F3 — Cola de inversiones en PROCESOS separados (local-first, sin Redis).

El problema que mata al producto: /v2/load-package era SÍNCRONO → una inversión
joint de 96k vóxeles (20+ min) revienta el proxy ("error interno del proxy") y
deja al usuario sin feedback. Aquí load-package pasa a ENCOLAR y devolver de
inmediato; el progreso viaja por el mecanismo NATIVO que ya usa el flujo
directo (update_run_status → schedule.json → GET /geophysics-status).

Diseño (decisión F1 §5: vía nativa, cero infraestructura):
  - Worker = `multiprocessing.Process` (spawn) por corrida, con un máximo de
    TQ_INVERSION_WORKERS (default 1) simultáneos y una cola FIFO en memoria.
    CPU-bound: el GIL castiga threads; un proceso aparte además permite
    CANCELAR de verdad (terminate) sin tocar el motor físico validado.
    (El plan sugería ProcessPoolExecutor; se usa Process directo porque el
    pool no permite cancelar un trabajo en curso — la cancelación real del
    gate F3 manda.)
  - El hijo importa services.run_queue_service (no main.py): el bootstrap de
    spawn solo carga este módulo y sus imports.
  - Cancelación en dos capas: archivo cooperativo `cancel.requested` en el
    run_dir (se consulta antes de arrancar y puede consultarlo el orquestador)
    + terminate() del proceso como garantía (sin tocar exploration/solvers).
  - Al terminar (done/error/cancelled) el hijo escribe schedule.json y el
    historial SQLite (project_store); un watcher en el padre libera el slot,
    lanza el siguiente de la cola y marca "interrumpida" si el hijo murió sin
    despedirse (crash duro).

Presupuesto de vóxeles: ANTES de encolar se estima tiempo por (ruta, #vóxeles)
con coeficientes MEDIDOS (ver _BUDGET_COEFFS) y se avisa si excede umbral —
nunca más un joint de 96k vóxeles sorpresa.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
from collections import deque
from typing import Any, Dict, Optional, Tuple

from core.logging import get_logger

_log = get_logger(__name__)

CANCEL_FILENAME = "cancel.requested"

_MAX_WORKERS = max(1, int(os.getenv("TQ_INVERSION_WORKERS", "1")))

_LOCK = threading.Lock()
_ACTIVE: "Dict[Tuple[str, str], mp.Process]" = {}
_PENDING: "deque[Tuple[dict, str, str]]" = deque()
_WATCHER_STARTED = False

# ── Presupuesto de vóxeles/tiempo ────────────────────────────────────────────
# Base MEDIDA (máquina de referencia, scripts/validation/):
#   - joint: 7,16 ms/vóxel — GATE F3 2026-07-05 (96.768 vóxeles, 256 est.,
#     malla auto 48×42×48, worker de proceso). MEDIDO.
#   - gravity/magnetic: HEURÍSTICO (mitad del joint). La calibración
#     2026-07-06 (f3_budget_calibration.py) DEMOSTRÓ que un coeficiente
#     constante por vóxel NO existe para estas rutas: con bloques chicos
#     (52 m) la gravedad de 10,6k vóxeles midió 82,7 ms/vóxel (11× el joint)
#     y dos mallas murieron con SOLVER_KERNEL_TOO_DENSE (catalogado): el
#     costo real lo dominan la DENSIDAD del kernel (cutoff/block) y la RAM
#     disponible en el momento, no el nº de vóxeles ni de físicas.
# Por eso el estimado se comunica como ORIENTATIVO sin cifra de precisión, y
# las garantías duras del flujo son otras: progreso visible + cancelable +
# guardia de memoria catalogada. La matriz sistemática por régimen es F8.
_BUDGET_COEFFS_S_PER_VOXEL = {
    "gravity": 0.0036,
    "magnetic": 0.0036,
    "joint": 0.0072,
}
_BUDGET_BASIS = {
    "gravity": "heurístico (½ del joint medido; matriz sistemática en F8)",
    "magnetic": "heurístico (½ del joint medido; matriz sistemática en F8)",
    "joint": "medido (gate F3: 96.768 vóxeles → 7,16 ms/vóxel)",
}
_BUDGET_BASE_S = 8.0            # arranque del worker (spawn + imports pesados)
_BUDGET_WARN_MINUTES = 5.0      # umbral de aviso previo


def estimate_inversion_budget(route: str, voxel_count: int) -> Dict[str, Any]:
    """Estimación previa de costo: #vóxeles + tiempo aproximado + aviso.

    Honesto por diseño: el estimado se declara orientativo (±2×) y su base
    medida queda en el mensaje. El objetivo es que NINGUNA inversión larga
    sorprenda al usuario (gate F3), no predecir al segundo.
    """
    kind = "joint" if "joint" in (route or "") else (
        "magnetic" if "magnetic" in (route or "") else "gravity"
    )
    est_s = _BUDGET_BASE_S + voxel_count * _BUDGET_COEFFS_S_PER_VOXEL[kind]
    est_min = est_s / 60.0
    warning = None
    if est_min > _BUDGET_WARN_MINUTES:
        warning = (
            f"Inversión grande: ~{voxel_count:,} vóxeles por la ruta {kind} → "
            f"estimado ~{est_min:.0f} min (orientativo: el costo real depende "
            "de la densidad del kernel y la memoria disponible). Puede "
            "continuar (el progreso es visible y cancelable), reducir la "
            "resolución de la malla, o usar una malla más gruesa."
        )
    return {
        "voxel_count": int(voxel_count),
        "route_kind": kind,
        "estimated_seconds": round(est_s, 1),
        "estimated_minutes": round(est_min, 1),
        # Honestidad: de dónde sale el número (medido vs heurístico).
        "basis": _BUDGET_BASIS[kind],
        "warning": warning,
    }


# ── Worker (corre EN EL PROCESO HIJO) ────────────────────────────────────────
def _worker_entry(payload: dict, project_id: str, run_id: str) -> None:
    """Entrada del proceso worker. Solo imports de servicios (no main/api).

    Escribe SIEMPRE un estado terminal (done/error/cancelled) en schedule.json
    y en el historial SQLite antes de morir — el contrato nunca-sin-feedback.
    """
    # Imports adentro: el bootstrap de spawn ejecuta este módulo en frío.
    from services.block_model_store import get_run_dir, update_run_status
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services import project_store
    from services.geophysics_service import run_geophysics_inversion

    def _cancelled() -> bool:
        try:
            return (get_run_dir(project_id, run_id) / CANCEL_FILENAME).exists()
        except Exception:
            return False

    # Hook de test E2E (F3): retardo artificial ANTES de resolver, para que los
    # tests de progreso/cancelación tengan una ventana determinista. Inocuo en
    # producción (sin la variable no duerme).
    _slow_s = float(os.getenv("TQ_TEST_SLOW_BEFORE_SOLVE_S", "0") or 0)
    if _slow_s > 0:
        deadline = time.monotonic() + _slow_s
        while time.monotonic() < deadline:
            if _cancelled():
                break
            time.sleep(0.2)

    if _cancelled():
        update_run_status(
            project_id=project_id, run_id=run_id, status="cancelled",
            progress=0.0, stage="cancelled",
            message="Corrida cancelada por el usuario antes de resolver.",
        )
        project_store.mark_run(project_id, run_id, project_store.STATUS_CANCELLED)
        return

    try:
        params = GeophysicsInvertInput(**payload)
        project_store.mark_run(project_id, run_id, project_store.STATUS_RUNNING)
        # El orquestador/solver ya reportan etapas reales por update_run_status
        # (loading_data → malla/kernel → solving_lsqr con heartbeat 5 s →
        # postproceso) — el progreso del paquete viaja por el MISMO canal que
        # el flujo directo.
        run_geophysics_inversion(params)
        update_run_status(
            project_id=project_id, run_id=run_id, status="done",
            progress=1.0, stage="done",
            message="Inversión del paquete completada. Modelo persistido.",
        )
        project_store.mark_run(project_id, run_id, project_store.STATUS_DONE)
    except Exception as exc:  # noqa: BLE001 — estado terminal SIEMPRE
        error_details = None
        try:
            from core.errors import TerraquantumError

            if isinstance(exc, TerraquantumError):
                error_details = exc.to_error_details(
                    source="run_queue_service", stage="solving"
                )
        except Exception:
            pass
        try:
            update_run_status(
                project_id=project_id, run_id=run_id, status="error",
                progress=0.0, stage="error",
                message=f"Error en la inversión del paquete: {str(exc)[:300]}",
                error=str(exc)[:1000],
                error_details=error_details,
            )
        finally:
            project_store.mark_run(
                project_id, run_id, project_store.STATUS_ERROR, error=str(exc)
            )


# ── Cola y watcher (proceso PADRE / servidor) ────────────────────────────────
def _spawn(payload: dict, project_id: str, run_id: str) -> None:
    ctx = mp.get_context("spawn")
    proc = ctx.Process(
        target=_worker_entry, args=(payload, project_id, run_id), daemon=True,
        name=f"tq-invert-{run_id[:12]}",
    )
    proc.start()
    _ACTIVE[(project_id, run_id)] = proc
    _log.info("run_queue_spawned", project_id=project_id, run_id=run_id, pid=proc.pid)


def _watcher_loop() -> None:
    from services.block_model_store import get_run_schedule_path
    from services import project_store

    import json

    while True:
        time.sleep(1.0)
        with _LOCK:
            finished = [(key, p) for key, p in _ACTIVE.items() if not p.is_alive()]
            for key, proc in finished:
                del _ACTIVE[key]
                project_id, run_id = key
                # ¿El hijo murió SIN estado terminal? (crash duro / terminate
                # sin despedida) → interrumpida, jamás colgada en running.
                terminal = False
                try:
                    path = get_run_schedule_path(project_id, run_id)
                    if path is not None and path.exists():
                        status = json.loads(path.read_text(encoding="utf-8")).get("status")
                        terminal = status in ("done", "error", "cancelled")
                except Exception:
                    pass
                if not terminal:
                    reason = "El proceso de inversión terminó sin estado final."
                    try:
                        from services.block_model_store import update_run_status

                        update_run_status(
                            project_id=project_id, run_id=run_id,
                            status="interrumpida", progress=0.0,
                            stage="interrumpida", message=reason,
                        )
                    except Exception:
                        pass
                    project_store.mark_run(
                        project_id, run_id,
                        project_store.STATUS_INTERRUPTED, error=reason,
                    )
                _log.info("run_queue_finished", project_id=project_id,
                          run_id=run_id, terminal=terminal)
            while _PENDING and len(_ACTIVE) < _MAX_WORKERS:
                payload, project_id, run_id = _PENDING.popleft()
                _spawn(payload, project_id, run_id)


def _ensure_watcher() -> None:
    global _WATCHER_STARTED
    if not _WATCHER_STARTED:
        threading.Thread(target=_watcher_loop, daemon=True, name="tq-run-queue-watcher").start()
        _WATCHER_STARTED = True


def submit_package_inversion(
    payload: dict, project_id: str, run_id: str,
    route: Optional[str] = None, config: Optional[dict] = None,
) -> Dict[str, Any]:
    """Encola la inversión del paquete y devuelve DE INMEDIATO.

    `payload` = GeophysicsInvertInput.model_dump() (picklable para spawn).
    El estado inicial queda en schedule.json (queued) y en el historial.
    """
    from services.block_model_store import get_run_dir, update_run_status
    from services import project_store

    # Limpia una bandera de cancelación previa (re-encolar tras cancelar).
    try:
        cancel_file = get_run_dir(project_id, run_id) / CANCEL_FILENAME
        if cancel_file.exists():
            cancel_file.unlink()
    except Exception:
        pass

    project_store.record_run(
        project_id, run_id, status=project_store.STATUS_QUEUED,
        source="package", route=route, config=config,
    )
    update_run_status(
        project_id=project_id, run_id=run_id, status="queued",
        progress=0.0, stage="queued",
        message="Inversión del paquete en cola de procesamiento.",
    )
    _ensure_watcher()
    with _LOCK:
        if len(_ACTIVE) < _MAX_WORKERS:
            _spawn(payload, project_id, run_id)
            position = 0
        else:
            _PENDING.append((payload, project_id, run_id))
            position = len(_PENDING)
    return {"queued": True, "queue_position": position}


def cancel_run(project_id: str, run_id: str) -> Dict[str, Any]:
    """Cancela una corrida del flujo de paquete.

    Dos capas: bandera cooperativa (cancel.requested, la ve el worker antes de
    resolver) + terminate() del proceso si está corriendo (garantía dura sin
    tocar el motor). El watcher y esta función dejan estado terminal
    'cancelled' en schedule.json + historial.
    """
    from services.block_model_store import get_run_dir, update_run_status
    from services import project_store

    try:
        run_dir = get_run_dir(project_id, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / CANCEL_FILENAME).write_text("1", encoding="utf-8")
    except Exception as exc:
        return {"cancelled": False, "reason": f"No se pudo marcar la cancelación: {exc}"}

    outcome = "flag"
    with _LOCK:
        # ¿Estaba en cola sin arrancar? — sale de la cola directamente.
        for item in list(_PENDING):
            if item[1] == project_id and item[2] == run_id:
                _PENDING.remove(item)
                outcome = "dequeued"
                break
        proc = _ACTIVE.pop((project_id, run_id), None)
    if proc is not None and proc.is_alive():
        proc.terminate()
        proc.join(timeout=10)
        outcome = "terminated"

    update_run_status(
        project_id=project_id, run_id=run_id, status="cancelled",
        progress=0.0, stage="cancelled",
        message="Corrida cancelada por el usuario.",
    )
    project_store.mark_run(project_id, run_id, project_store.STATUS_CANCELLED)
    _log.info("run_queue_cancelled", project_id=project_id, run_id=run_id, outcome=outcome)
    return {"cancelled": True, "outcome": outcome}


def queue_snapshot() -> Dict[str, Any]:
    """Estado de la cola (diagnóstico/UI)."""
    with _LOCK:
        return {
            "max_workers": _MAX_WORKERS,
            "active": [
                {"project_id": p, "run_id": r, "pid": proc.pid, "alive": proc.is_alive()}
                for (p, r), proc in _ACTIVE.items()
            ],
            "pending": [
                {"project_id": p, "run_id": r} for _, p, r in list(_PENDING)
            ],
        }
