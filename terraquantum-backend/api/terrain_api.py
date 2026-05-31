from fastapi import APIRouter, HTTPException

from schemas.terrain_schema import TerrainResponse
from services.satellite_service import get_terrain_data


router = APIRouter(prefix="/projects", tags=["Terrain"])


@router.get("/{project_id}/terrain", response_model=TerrainResponse)
async def get_terrain(project_id: str):
    try:
        return get_terrain_data(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo generar datos de terreno para el proyecto.",
        ) from exc
