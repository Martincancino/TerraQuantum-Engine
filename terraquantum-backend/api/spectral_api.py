from fastapi import APIRouter, HTTPException, Query

from schemas.spectral_schema import SpectralIndicesResponse
from services.spectral_service import get_spectral_indices


router = APIRouter(prefix="/projects", tags=["Spectral"])


@router.get("/{project_id}/satellite-indices", response_model=SpectralIndicesResponse)
async def get_project_satellite_indices(
    project_id: str,
    refresh: bool = Query(False),
):
    try:
        return get_spectral_indices(project_id, force_refresh=refresh)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron calcular indices espectrales satelitales.",
        ) from exc
