"""
Async inversion endpoints — HITO 7.

Wraps the existing synchronous geophysics inversion in a Celery task so that:
  - The web server is never blocked by heavy numpy work
  - Multiple inversions run concurrently (one per worker slot)
  - Tasks survive server restarts (persisted in Redis)

The synchronous /geophysics-invert endpoint is NOT replaced — both coexist.
Use the async endpoint for production; the sync endpoint remains for dev/testing.

Requires a running Redis instance:
    docker run -d -p 6379:6379 redis:7-alpine

Set CELERY_BROKER_URL / CELERY_RESULT_BACKEND env vars to point at your Redis.
Default: redis://localhost:6379/0 for both.
"""
import uuid as _uuid

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Request

from core.block_model_store import update_run_status
from core.logging import get_logger
from core.rate_limit import limiter
from schemas.geophysics_schema import GeophysicsInvertInput
from workers.tasks import invert_geophysics_task

router = APIRouter(prefix="/api/async", tags=["async"])
_log = get_logger(__name__)


# ── Enqueue ───────────────────────────────────────────────────────────────────

@router.post("/invert")
@limiter.limit("5/minute")
async def enqueue_inversion(request: Request, params: GeophysicsInvertInput):
    """
    Enqueue a geophysics inversion via Celery.

    Returns immediately with a task_id and a status_url to poll.
    The actual inversion runs in a separate worker process.

    Requires Redis + at least one active Celery worker:
        celery -A workers.celery_app worker --loglevel=info --concurrency=4
    """
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
            message="Inversión registrada en cola Celery.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        task = invert_geophysics_task.delay(
            params_with_ids.model_dump(),
            project_id,
            run_id,
        )
    except Exception as exc:
        _log.error("celery_enqueue_failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                f"No se pudo encolar la tarea en Celery: {exc}. "
                "Verifica que Redis esté corriendo y CELERY_BROKER_URL sea correcto."
            ),
        )

    _log.info("celery_task_enqueued", task_id=task.id, project_id=project_id, run_id=run_id)
    return {
        "task_id": task.id,
        "run_id": run_id,
        "project_id": project_id,
        "status": "queued",
        "status_url": f"/api/async/tasks/{task.id}",
    }


# ── Status polling ────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    Poll the status of a Celery task by its task_id.

    Celery states:
      PENDING  — not yet picked up by a worker (or unknown task_id)
      STARTED  — worker is executing the task
      SUCCESS  — task completed successfully
      FAILURE  — task raised an exception
      REVOKED  — task was cancelled
    """
    result = AsyncResult(task_id)
    info = result.info if isinstance(result.info, dict) else {}

    error_detail = None
    if result.failed():
        error_detail = str(result.info)

    return {
        "task_id": task_id,
        "celery_state": result.state,
        "project_id": info.get("project_id"),
        "run_id": info.get("run_id"),
        "stage": info.get("stage", result.state.lower()),
        "progress": info.get("progress", 1.0 if result.successful() else 0.0),
        "error": error_detail,
    }


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """
    Revoke a queued task. Only effective if the worker has not yet started it.
    A task already in STARTED state cannot be interrupted without SIGKILL.
    """
    result = AsyncResult(task_id)
    result.revoke(terminate=False)
    return {"task_id": task_id, "revoked": True}
