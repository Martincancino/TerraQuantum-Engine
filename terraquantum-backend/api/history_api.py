"""F3 — Historial de corridas respaldado por SQLite (services/project_store).

La UI lista corridas anteriores (estado real: done/error/cancelled/
interrumpida) y re-abre cualquier modelo sin re-invertir. Complementa a
GET /project-runs (system_api, escaneo de disco) con estado persistente que
sobrevive reinicios del backend.
"""
from fastapi import APIRouter, Query

from core.utils import sanitize_nan
from schemas.system_schema import HistoryRunDetailResponse, HistoryRunsResponse
from services import project_store

router = APIRouter(prefix="/v2/history", tags=["History"])


@router.get("/runs", response_model=HistoryRunsResponse,
            response_model_exclude_unset=True)
def list_history_runs(
    project_id: str = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """Corridas registradas (más recientes primero), opcionalmente por proyecto."""
    runs = project_store.list_runs(project_id=project_id or None, limit=limit)
    return sanitize_nan({"runs": runs, "count": len(runs)})


@router.get("/runs/{project_id}/{run_id}", response_model=HistoryRunDetailResponse,
            response_model_exclude_unset=True)
def get_history_run(project_id: str, run_id: str):
    run = project_store.get_run(project_id, run_id)
    return sanitize_nan({"run": run, "found": run is not None})
