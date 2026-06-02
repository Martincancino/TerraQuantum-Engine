"""
Celery tasks for TerraQuantum.

Each task receives plain JSON-serializable dicts (Pydantic models are
reconstructed inside the task — Celery cannot serialize them directly).
"""
from celery import Task

from core.block_model_store import update_run_status
from core.logging import get_logger
from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import run_geophysics_inversion
from workers.celery_app import celery_app

_log = get_logger(__name__)


class _InversionTask(Task):
    """Base class with per-task error reporting to run_status.json."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        project_id = kwargs.get("project_id") or (args[1] if len(args) > 1 else "unknown")
        run_id = kwargs.get("run_id") or (args[2] if len(args) > 2 else "unknown")
        _log.error(
            "celery_inversion_failed",
            task_id=task_id,
            project_id=project_id,
            run_id=run_id,
            error=str(exc),
        )
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


@celery_app.task(
    bind=True,
    base=_InversionTask,
    name="terraquantum.invert_geophysics",
    max_retries=0,  # Geophysics inversions are not idempotent — never auto-retry.
)
def invert_geophysics_task(
    self,
    params_dict: dict,
    project_id: str,
    run_id: str,
) -> dict:
    """
    Run a full geophysics inversion off the main web-server process.

    Args:
        params_dict: GeophysicsInvertInput serialized as dict (.model_dump()).
        project_id:  Project ID (already validated before enqueueing).
        run_id:      Run ID (already validated before enqueueing).

    Returns:
        {"status": "completed", "project_id": ..., "run_id": ...}
    """
    self.update_state(
        state="STARTED",
        meta={"stage": "running", "progress": 0.0, "project_id": project_id, "run_id": run_id},
    )
    _log.info("celery_inversion_started", project_id=project_id, run_id=run_id)

    params = GeophysicsInvertInput(**params_dict)
    run_geophysics_inversion(params)

    _log.info("celery_inversion_completed", project_id=project_id, run_id=run_id)
    return {"status": "completed", "project_id": project_id, "run_id": run_id}
