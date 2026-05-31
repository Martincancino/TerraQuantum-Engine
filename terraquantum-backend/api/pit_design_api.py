from fastapi import APIRouter, HTTPException

from core.logging import get_logger
from schemas.pit_design_schema import PitRequest
from services.pit_design_service import generate_pit_design

router = APIRouter()
_log = get_logger(__name__)


@router.post("/generate")
async def generate_pit(req: PitRequest):
    _log.info("request_received", endpoint="/generate", project_id=req.project_id, run_id=req.run_id)

    try:
        return generate_pit_design(req)
    except Exception as exc:
        _log.error("generate_pit_unexpected_error", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Error interno generando el diseño de mina.",
        )
