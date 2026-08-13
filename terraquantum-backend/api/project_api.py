from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from core.utils import model_to_dict, utc_now_iso
from services.block_model_store import (
    clean_trace_id,
    get_project_meta_path,
    list_project_runs,
    load_project_meta,
    save_project_meta,
)
from schemas.project_schema import (
    ProjectCreate,
    ProjectFootprint,
    ProjectFootprintResponse,
    ProjectMeta,
    ProjectResponse,
    ProjectUpdate,
)


router = APIRouter(prefix="/projects", tags=["projects"])



def clean_project_id_or_400(project_id: str) -> str:
    try:
        clean_project_id = clean_trace_id(project_id, "project_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not clean_project_id:
        raise HTTPException(status_code=400, detail="project_id es requerido.")

    return clean_project_id


def get_project_dir(project_id: str):
    try:
        return get_project_meta_path(project_id).parent
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def count_project_runs(project_id: str) -> int:
    project_dir = get_project_dir(project_id)
    runs_dir = project_dir / "runs"

    if not runs_dir.exists():
        return 0

    return sum(1 for run_dir in runs_dir.iterdir() if run_dir.is_dir())


def build_project_response(project_id: str, meta: dict | None) -> ProjectResponse:
    footprint = None
    if meta:
        footprint_data = meta.get("footprint")
        if footprint_data and isinstance(footprint_data, dict):
            try:
                footprint = ProjectFootprint(**footprint_data)
            except Exception:
                footprint = None

    return ProjectResponse(
        project_id=project_id,
        latitude=meta.get("latitude") if meta else None,
        longitude=meta.get("longitude") if meta else None,
        crs=meta.get("crs", "EPSG:4326") if meta else "EPSG:4326",
        created_at=meta.get("created_at") if meta else None,
        updated_at=meta.get("updated_at") if meta else None,
        run_count=count_project_runs(project_id),
        georef_confidence=meta.get("georef_confidence", "MISSING") if meta else "MISSING",
        footprint=footprint,
    )


@router.post("", status_code=201, response_model=ProjectResponse)
async def create_project(req: ProjectCreate):
    project_id = clean_project_id_or_400(req.project_id)
    meta_path = get_project_meta_path(project_id)

    if meta_path.exists():
        raise HTTPException(status_code=409, detail="El proyecto ya existe.")

    now = utc_now_iso()
    meta = ProjectMeta(
        project_id=project_id,
        latitude=req.latitude,
        longitude=req.longitude,
        crs=req.crs,
        created_at=now,
        updated_at=now,
    )
    meta_dict = model_to_dict(meta)
    save_project_meta(project_id, meta_dict)

    return build_project_response(project_id, meta_dict)


@router.get("")
async def list_projects():
    listing = list_project_runs()
    projects = []

    for project in listing.get("projects", []):
        project_id = project.get("projectId")
        meta = project.get("projectMeta")
        response = model_to_dict(build_project_response(project_id, meta))
        response["projectId"] = project_id
        response["projectMeta"] = meta
        response["runs"] = project.get("runs", [])
        projects.append(response)

    return {
        "totalProjects": len(projects),
        "totalRuns": listing.get("totalRuns", 0),
        "projects": projects,
    }


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    project_id = clean_project_id_or_400(project_id)
    project_dir = get_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")

    return build_project_response(project_id, load_project_meta(project_id))


@router.get("/{project_id}/footprint", response_model=ProjectFootprintResponse)
async def get_project_footprint(project_id: str):
    project_id = clean_project_id_or_400(project_id)
    project_dir = get_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")

    meta = load_project_meta(project_id) or {}
    footprint_data = meta.get("footprint")
    footprint = None

    if footprint_data and isinstance(footprint_data, dict):
        try:
            footprint = ProjectFootprint(**footprint_data)
        except Exception:
            footprint = None

    georef_confidence = meta.get("georef_confidence", "MISSING")
    georef_type = meta.get("georef_type") or "local_reference"
    utm_zone = meta.get("utm_zone")

    if footprint is not None:
        warnings = list(footprint_data.get("warnings", []))
        coordinate_system_detected = footprint_data.get("source")
    else:
        warnings = [
            "Proyecto sin footprint calculado. Re-ejecutar inversión para actualizar georreferenciación."
        ]
        coordinate_system_detected = None

    return ProjectFootprintResponse(
        project_id=project_id,
        georef_confidence=georef_confidence,
        georef_type=georef_type,
        footprint=footprint,
        coordinate_system_detected=coordinate_system_detected,
        utm_zone=utm_zone,
        warnings=warnings,
        source_run_id=None,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, req: ProjectUpdate):
    project_id = clean_project_id_or_400(project_id)
    project_dir = get_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")

    existing = load_project_meta(project_id) or {}
    now = utc_now_iso()

    # Merge: start from the full existing dict so footprint/georef/CRS fields
    # are never destroyed by a partial update.
    merged = dict(existing)
    if req.latitude is not None:
        merged["latitude"] = req.latitude
    if req.longitude is not None:
        merged["longitude"] = req.longitude
    if req.crs is not None:
        merged["crs"] = req.crs
    if "created_at" not in merged:
        merged["created_at"] = now
    merged["updated_at"] = now

    save_project_meta(project_id, merged)

    return build_project_response(project_id, merged)
