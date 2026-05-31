from fastapi import APIRouter, Request

from core.rate_limit import limiter
from schemas.scenario_sweep_schema import SweepRequest
from services.scenario_sweep_service import (
    get_scenario_progress,
    run_scenario_sweep,
)

router = APIRouter()


@router.post("/scenario-sweep")
@limiter.limit("5/minute")
async def scenario_sweep(request: Request, req: SweepRequest):
    print("[SCENARIO-SWEEP-API] POST /scenario-sweep")

    return run_scenario_sweep(req)


@router.get("/scenario-progress/{jobId}")
def scenario_progress(jobId: str):
    print(f"[SCENARIO-SWEEP-API] GET /scenario-progress/{jobId}")

    return get_scenario_progress(jobId)
