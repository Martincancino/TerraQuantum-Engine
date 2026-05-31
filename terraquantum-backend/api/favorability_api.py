import json

from fastapi import APIRouter, HTTPException

from core.block_model_store import get_run_favorability_path
from schemas.favorability_schema import FavorabilityResult
from services.favorability_service import compute_favorability_score_from_disk


router = APIRouter()


@router.get("/favorability/{project_id}/{run_id}", response_model=FavorabilityResult)
async def get_favorability(project_id: str, run_id: str):
    try:
        favorability_path = get_run_favorability_path(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if favorability_path is not None and favorability_path.exists():
        try:
            return json.loads(favorability_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Error leyendo favorability.json: {exc}",
            ) from exc

    try:
        result = compute_favorability_score_from_disk(project_id, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error calculando favorabilidad: {exc}",
        ) from exc

    if favorability_path is not None:
        favorability_path.parent.mkdir(parents=True, exist_ok=True)
        favorability_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return result
