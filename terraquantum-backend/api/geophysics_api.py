import json
import math
import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse

from core.rate_limit import limiter
from core.logging import get_logger
from core.block_model_store import (
    get_run_dir,
    get_run_schedule_path,
    update_run_status,
    RUN_VTK_FILENAME,
)
from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import run_geophysics_inversion, run_geophysics_sensitivity_sweep

router = APIRouter()
_log = get_logger(__name__)


def _sanitize_nan(obj):
    """Reemplaza float NaN/Inf por None para emitir JSON válido."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


class GeophysicsSensitivitySweepRequest(GeophysicsInvertInput):
    lambda_values: list[float] | None = None
    alpha_values: list[float] | None = None
    max_cases: int = 9


async def _run_inversion_bg(params: GeophysicsInvertInput, project_id: str, run_id: str):
    """Wrapper de background task: captura errores y persiste status=error."""
    try:
        run_geophysics_inversion(params)
    except Exception as exc:
        _log.error("bg_inversion_error", project_id=project_id, run_id=run_id, error=str(exc))
        try:
            update_run_status(
                project_id=project_id,
                run_id=run_id,
                status="error",
                progress=0.0,
                stage="error",
                message=f"Error en inversión: {exc}",
                error=str(exc),
            )
        except Exception:
            pass


@router.post("/geophysics-invert")
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


@router.get("/geophysics-status/{project_id}/{run_id}")
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
        return _sanitize_nan(json.loads(path.read_text(encoding="utf-8")))
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


# ── FASE 10: Descarga Industrial VTK (.vtr) ───────────────────────────────────
@router.get("/export/vtr/{project_id}/{run_id}")
async def export_vtr(project_id: str, run_id: str):
    """
    Descarga el archivo VTK Rectilinear Grid (.vtr) generado por la inversión
    gravimétrica. Compatible con ParaView, Leapfrog Geo y VTKm.

    - **project_id**: ID del proyecto (mismo usado en /geophysics-invert).
    - **run_id**: ID del run específico cuyo modelo 3D se quiere exportar.

    Retorna el archivo con `Content-Disposition: attachment` para descarga directa.
    """
    _log.info("request_received", endpoint="/export/vtr",
              project_id=project_id, run_id=run_id)

    try:
        run_dir = get_run_dir(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    vtr_path = run_dir / RUN_VTK_FILENAME

    if not vtr_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Archivo VTR no encontrado para project_id={project_id}, "
                f"run_id={run_id}. "
                "Asegúrate de que la inversión haya completado y pyevtk esté instalado."
            ),
        )

    return FileResponse(
        path=str(vtr_path),
        media_type="application/octet-stream",
        filename=f"model_{run_id}.vtr",
    )
