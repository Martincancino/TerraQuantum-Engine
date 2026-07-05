import asyncio
import json
import time
import uuid as _uuid

import numpy as np
import polars as pl

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.rate_limit import limiter
from core.logging import get_logger
from core.utils import sanitize_nan
from core.block_model_store import (
    get_run_dir,
    get_run_schedule_path,
    update_run_status,
)
from schemas.geophysics_schema import (
    GeophysicsInvertInput,
    GeophysicsInvertInputV2,
    GeophysicsLiveUpdateRequest,
    GeophysicsLiveUpdateResponse,
)
from schemas.response_schema import (
    GeophysicsInversionStartResponse,
    GeophysicsStatusResponse,
    MisfitResponse,
)
from services.geophysics_service import (
    run_geophysics_inversion,
    run_geophysics_sensitivity_sweep,
    run_geophysics_live_update,
)

router = APIRouter()
_log = get_logger(__name__)


class GeophysicsSensitivitySweepRequest(GeophysicsInvertInput):
    lambda_values: list[float] | None = None
    alpha_values: list[float] | None = None
    max_cases: int = 9


async def _run_inversion_bg(params: GeophysicsInvertInput, project_id: str, run_id: str):
    """Wrapper de background task: captura errores y persiste status=error."""
    try:
        run_geophysics_inversion(params)
    except Exception as exc:
        exc_type = type(exc).__name__
        exc_message = str(exc)
        _log.error("bg_inversion_error", project_id=project_id, run_id=run_id, error=exc_message, error_type=exc_type)

        error_details = {
            "code": exc_type,
            "message": exc_message,
            "source": "geophysics_service",
            "stage": "solving",
            "details": None,
        }

        try:
            update_run_status(
                project_id=project_id,
                run_id=run_id,
                status="error",
                progress=0.0,
                stage="error",
                message=f"Error en inversión: {exc_message}",
                error=exc_message,
                error_details=error_details,
            )
        except ValueError as exc:
            _log.error("bg_update_status_invalid_ids", project_id=project_id, run_id=run_id, error=str(exc))
        except Exception as exc:
            _log.error("bg_update_status_write_error", project_id=project_id, run_id=run_id, error=str(exc))


@router.post("/geophysics-invert", response_model=GeophysicsInversionStartResponse)
@limiter.limit("10/minute")
async def invert_geophysics(
    request: Request,
    params: GeophysicsInvertInput,
    background_tasks: BackgroundTasks,
):
    _log.info("request_received", endpoint="/geophysics-invert")

    project_id = params.project_id or "default"
    run_id = params.run_id or _uuid.uuid4().hex[:16]

    params_with_ids = params.model_copy(update={"project_id": project_id, "run_id": run_id})

    try:
        update_run_status(
            project_id=project_id,
            run_id=run_id,
            status="queued",
            progress=0.0,
            stage="queued",
            message="Inversión registrada en cola de procesamiento.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    background_tasks.add_task(_run_inversion_bg, params_with_ids, project_id, run_id)

    return {"status": "queued", "run_id": run_id, "project_id": project_id}


@router.post("/geophysics-cancel/{project_id}/{run_id}")
async def cancel_geophysics_run(project_id: str, run_id: str):
    """F3 — Cancela una corrida del flujo de paquete (worker de proceso).

    Dos capas: bandera cooperativa + terminate() del proceso worker. Deja
    estado terminal 'cancelled' en schedule.json y en el historial SQLite.
    Para corridas del flujo DIRECTO (BackgroundTasks en el mismo proceso) solo
    aplica la bandera cooperativa: se informa el alcance con honestidad.
    """
    from services.run_queue_service import cancel_run

    try:
        result = cancel_run(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not result.get("cancelled"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "CANCEL_FAILED",
                "message": result.get("reason", "No se pudo cancelar la corrida."),
            },
        )
    return {
        "status": "cancelled",
        "project_id": project_id,
        "run_id": run_id,
        "outcome": result.get("outcome"),
    }


@router.get("/geophysics-status/{project_id}/{run_id}", response_model=GeophysicsStatusResponse)
async def get_geophysics_status(project_id: str, run_id: str):
    _log.info("request_received", endpoint="/geophysics-status",
              project_id=project_id, run_id=run_id)

    try:
        path = get_run_schedule_path(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if path is None or not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró status para project_id={project_id}, run_id={run_id}.",
        )

    try:
        return sanitize_nan(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo status: {exc}")


@router.post("/geophysics-sensitivity-sweep")
def sensitivity_sweep_geophysics(request: GeophysicsSensitivitySweepRequest):
    _log.info("request_received", endpoint="/geophysics-sensitivity-sweep")

    try:
        return run_geophysics_sensitivity_sweep(
            params=request,
            lambda_values=request.lambda_values,
            alpha_values=request.alpha_values,
            max_cases=request.max_cases,
        )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error en sweep de sensibilidad geofísica: {str(exc)}",
        )


# ── FASE 8.2: Live Update local (Woodbury / sub-octree), stateless malla core ──
@router.post("/geophysics-live-update", response_model=GeophysicsLiveUpdateResponse)
def live_update_geophysics(request: GeophysicsLiveUpdateRequest):
    _log.info("request_received", endpoint="/geophysics-live-update", mode=request.mode)

    try:
        return run_geophysics_live_update(request)

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error en live update geofísico: {str(exc)}",
        )


# ── FASE 2: Endpoint v2 — validaciones industriales estrictas ────────────────
@router.post("/v2/geophysics-invert", response_model=GeophysicsInversionStartResponse)
@limiter.limit("10/minute")
async def invert_geophysics_v2(
    request: Request,
    params: GeophysicsInvertInputV2,
    background_tasks: BackgroundTasks,
):
    """Inversión gravimétrica v2 — requiere anomalía corregida (g_raw rechazado).

    Diferencias con v1:
    - gravity_type g_raw → HTTP 422 con mensaje explicativo.
    - noise_floor_mgal + noise_pct configurables por tipo de gravímetro.
    - lambda_strategy declarable ('fixed' | 'lcurve' | 'chi2').
    - density_min permite contrastes negativos (sal, cavidades, roca alterada).
    """
    _log.info("request_received", endpoint="/v2/geophysics-invert",
              gravity_type=params.gravity_type_v2)

    project_id = params.project_id or "default"
    run_id = params.run_id or _uuid.uuid4().hex[:16]

    # Aplicar lambda_strategy al campo legacy auto_lambda + lambda_mag
    if params.lambda_strategy == "fixed":
        params = params.model_copy(update={
            "auto_lambda": False,
            "lambda_mag": params.lambda_fixed,
            "project_id": project_id,
            "run_id": run_id,
        })
    elif params.lambda_strategy in ("chi2", "lcurve"):
        params = params.model_copy(update={
            "auto_lambda": True,
            "project_id": project_id,
            "run_id": run_id,
        })
    else:
        params = params.model_copy(update={"project_id": project_id, "run_id": run_id})

    try:
        update_run_status(
            project_id=project_id,
            run_id=run_id,
            status="queued",
            progress=0.0,
            stage="queued",
            message="Inversión v2 registrada en cola de procesamiento.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    background_tasks.add_task(_run_inversion_bg, params, project_id, run_id)

    return {"status": "queued", "run_id": run_id, "project_id": project_id}


# ── FASE 2: SSE Streaming Status ─────────────────────────────────────────────
@router.get("/v2/geophysics-status/{project_id}/{run_id}/stream")
async def stream_geophysics_status(
    project_id: str,
    run_id: str,
    timeout_s: float = 600.0,
    poll_interval_s: float = 5.0,
):
    """Server-Sent Events con progreso de inversión en tiempo real.

    Emite eventos cada ``poll_interval_s`` segundos con:
    ``data: {"stage": str, "progress": float, "message": str, "elapsed_s": float}``

    El stream termina cuando status es "done", "error" o se supera timeout_s.
    """
    try:
        get_run_dir(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    async def _event_generator():
        t_start = time.monotonic()
        terminal = {"done", "error", "complete", "completed"}

        while True:
            elapsed = round(time.monotonic() - t_start, 1)
            if elapsed > timeout_s:
                payload = json.dumps({
                    "stage": "timeout",
                    "progress": 0.0,
                    "message": f"Stream timeout después de {timeout_s}s.",
                    "elapsed_s": elapsed,
                })
                yield f"data: {payload}\n\n"
                break

            try:
                path = get_run_schedule_path(project_id, run_id)
                if path is not None and path.exists():
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    status = str(raw.get("status", "unknown"))
                    payload = json.dumps({
                        "stage":     raw.get("stage", status),
                        "progress":  raw.get("progress", 0.0),
                        "message":   raw.get("message", ""),
                        "status":    status,
                        "elapsed_s": elapsed,
                    })
                    yield f"data: {payload}\n\n"
                    if status in terminal:
                        break
                else:
                    yield f"data: {json.dumps({'stage': 'queued', 'progress': 0.0, 'message': 'Esperando inicio...', 'elapsed_s': elapsed})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'stage': 'error', 'message': str(exc), 'elapsed_s': elapsed})}\n\n"
                break

            await asyncio.sleep(poll_interval_s)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── H-C2: Misfit endpoint (obs vs calc) ──────────────────────────────────────
@router.get("/geophysics-misfit/{project_id}/{run_id}", response_model=MisfitResponse)
async def get_geophysics_misfit(project_id: str, run_id: str):
    """
    Returns per-station observed vs. calculated gravity data and aggregate fit
    statistics (chi²_red, RMSE, normalised RMSE, R²) from the parquet written
    by the solver (H-C1).
    """
    _log.info("request_received", endpoint="/geophysics-misfit",
              project_id=project_id, run_id=run_id)

    try:
        run_dir = get_run_dir(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    ovc_path = run_dir / "obs_vs_calc.parquet"
    if not ovc_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"obs_vs_calc.parquet no encontrado para project_id={project_id}, "
                f"run_id={run_id}. La inversión puede no haber completado aún."
            ),
        )

    try:
        df = pl.read_parquet(str(ovc_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error leyendo obs_vs_calc.parquet: {exc}")

    d_obs     = df["d_obs"].to_numpy()
    d_pred    = df["d_pred"].to_numpy()
    residuals = df["residual"].to_numpy()
    n         = len(d_obs)

    # ── Aggregate metrics ────────────────────────────────────────────────────
    rmse        = float(np.sqrt(np.mean(residuals ** 2)))
    data_range  = max(float(np.max(d_obs) - np.min(d_obs)), 1e-30)
    norm_rmse   = rmse / data_range if data_range > 1e-10 else 0.0

    # chi²_reduced: use same adaptive sigma as the solver (_sigma_adaptive)
    sigma       = np.maximum(0.02 * np.abs(d_obs), 0.01 * data_range)
    chi2_red    = float(np.mean((residuals / sigma) ** 2))

    # R²
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((d_obs - np.mean(d_obs)) ** 2))
    r2     = 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 0.0

    # ── Per-station data ─────────────────────────────────────────────────────
    x_arr = df["x"].to_numpy() if "x" in df.columns else np.zeros(n)
    y_arr = df["y"].to_numpy() if "y" in df.columns else np.zeros(n)
    z_arr = df["z"].to_numpy() if "z" in df.columns else np.zeros(n)

    stations = [
        {
            "x":        float(x_arr[i]),
            "y":        float(y_arr[i]),
            "z":        float(z_arr[i]),
            "d_obs":    float(d_obs[i]),
            "d_pred":   float(d_pred[i]),
            "residual": float(residuals[i]),
        }
        for i in range(n)
    ]

    return {
        "stations":        stations,
        "chi2_reduced":    chi2_red,
        "rmse":            rmse,
        "normalized_rmse": norm_rmse,
        "r2":              r2,
        "n_stations":      n,
    }
