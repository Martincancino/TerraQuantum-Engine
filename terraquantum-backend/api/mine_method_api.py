from fastapi import APIRouter, HTTPException

from core.logging import get_logger
from schemas.mine_method_schema import MineMethodRequest
from services.mine_method_service import evaluate_mine_method

router = APIRouter()
_log = get_logger(__name__)


@router.post("/evaluate-mine-method")
async def evaluate_method(req: MineMethodRequest):
    _log.info(
        "request_received",
        endpoint="/evaluate-mine-method",
        project_id=req.project_id,
        run_id=req.run_id,
    )

    try:
        return evaluate_mine_method(req.project_id, req.run_id)
    except Exception as exc:
        _log.error("evaluate_mine_method_unexpected_error", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Error interno evaluando método de explotación.",
        )
