import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core import config as app_config
from core.config import (
    APP_NAME,
    APP_VERSION,
    BACKEND_HOST,
    BACKEND_PORT,
    DATA_DIR,
    PROJECTS_DIR,
    TMP_DIR,
    MODELS_DIR,
    DEFAULT_BLOCK_MODEL_PATH,
)
from services.block_model_store import (
    compare_project_runs,
    export_project_run_zip,
    get_project_run_detail,
    list_project_runs,
)
from core.utils import sanitize_nan


router = APIRouter()


@router.get("/health")
async def health():
    """Latido + IDENTIDAD del proceso (Fase 2, H-19).

    Un `TcpStream::connect` sólo prueba que ALGUIEN escucha en el puerto. El
    orquestador de escritorio necesita saber que quien escucha es EL sidecar
    que él lanzó, no un zombi de un arranque anterior ni otra aplicación. Para
    eso publica dos marcas: el token de instancia que recibió por entorno y su
    PID. Ambas se omiten si no aplican, nunca se inventan.
    """
    payload = {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "pid": os.getpid(),
    }
    # Se lee del módulo (no del from-import) para que el valor sea el vigente:
    # el token lo fija el proceso padre por entorno antes de arrancar.
    token = getattr(app_config, "INSTANCE_TOKEN", "")
    if token:
        payload["instance_token"] = token
    return payload


@router.get("/system-status")
async def system_status():
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "host": BACKEND_HOST,
        "port": BACKEND_PORT,
        "paths": {
            "data_dir": str(DATA_DIR),
            "projects_dir": str(PROJECTS_DIR),
            "tmp_dir": str(TMP_DIR),
            "models_dir": str(MODELS_DIR),
            "block_model": str(DEFAULT_BLOCK_MODEL_PATH),
        },
        "exists": {
            "data_dir": DATA_DIR.exists(),
            "projects_dir": PROJECTS_DIR.exists(),
            "tmp_dir": TMP_DIR.exists(),
            "models_dir": MODELS_DIR.exists(),
            "block_model": DEFAULT_BLOCK_MODEL_PATH.exists(),
        },
    }


@router.get("/system/connectivity")
async def system_connectivity(probe: bool = False):
    """F7 — Honestidad offline: qué features necesitan internet y confirmación de
    que el camino dorado (ingesta→inversión→3D→export) funciona sin conexión.

    `probe` se acepta por compatibilidad de firma y **no sondea nada**: la
    respuesta trae `probed: false` siempre, con `probe_requested` y `probe_note`
    diciendo por qué (Fase 9 — antes devolvía `probed: true` sin tocar la red).
    """
    from services.connectivity_service import connectivity_summary
    return connectivity_summary(probe=probe)


@router.get("/project-runs")
async def project_runs():
    return list_project_runs()


@router.get("/project-run-detail")
async def project_run_detail(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
    if not project_id or not run_id:
        raise HTTPException(
            status_code=400,
            detail="project_id y run_id son requeridos.",
        )

    try:
        # Los reportes persistidos pueden contener NaN/Inf (p. ej. rms_base del
        # enfoque MS-x cuando no converge). Starlette serializa con
        # allow_nan=False, así que cualquier NaN provoca un 500. Saneamos en el
        # borde de la respuesta: NaN/Inf -> null.
        return sanitize_nan(get_project_run_detail(project_id, run_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/compare-runs")
async def compare_runs(
    base_project_id: Optional[str] = None,
    base_run_id: Optional[str] = None,
    compare_project_id: Optional[str] = None,
    compare_run_id: Optional[str] = None,
):
    if not base_project_id or not base_run_id or not compare_project_id or not compare_run_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "base_project_id, base_run_id, compare_project_id y "
                "compare_run_id son requeridos."
            ),
        )

    try:
        return sanitize_nan(compare_project_runs(
            base_project_id=base_project_id,
            base_run_id=base_run_id,
            compare_project_id=compare_project_id,
            compare_run_id=compare_run_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/export-run")
async def export_run(
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
    if not project_id or not run_id:
        raise HTTPException(
            status_code=400,
            detail="project_id y run_id son requeridos.",
        )

    try:
        zip_path = export_project_run_zip(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=zip_path.name,
    )
