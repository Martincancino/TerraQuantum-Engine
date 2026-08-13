import io
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from services.block_model_store import get_run_dir
from schemas.response_schema import BlockModelResponse
from services.block_model_service import (
    build_block_model_response,
    build_block_model_arrow_bytes,
    build_block_model_profile_response,
)
from services.doi_overlay_service import build_doi_overlay_response
from services.isosurface_service import build_isosurface_response
from services.section_service import build_section_response

router = APIRouter()


@router.get("/block-model", response_model=BlockModelResponse)
async def get_block_model(
    mode: str = "exploration",
    limit: int = 5000,
    project_id: str = None,
    run_id: str = None,
):
    print(
        f"[BLOCK-MODEL-API] GET /block-model mode={mode} limit={limit} "
        f"project_id={project_id} run_id={run_id}"
    )

    return build_block_model_response(
        mode=mode,
        limit=limit,
        project_id=project_id,
        run_id=run_id,
    )


@router.get("/block-model-arrow")
async def get_block_model_arrow(
    mode: str = "exploration",
    project_id: str = None,
    run_id: str = None,
    display_factor: int = 1,
    lod: str = Query("full", pattern="^(far|medium|full)$"),
):
    """Endpoint Arrow IPC — transporte binario, sin iter_rows ni deep_sanitize_nan.

    Content-Type: application/vnd.apache.arrow.stream
    Headers extra: X-TQ-Total-Voxels, X-TQ-Bounds-Min, X-TQ-Bounds-Max, X-TQ-Run-Id, X-TQ-Lod-Level

    Query params:
      lod=far     — ~1% spatial sample, fastest
      lod=medium  — ~10% spatial sample, balanced
      lod=full    — 100% (default, respects safe_limit)
    """
    print(
        f"[BLOCK-MODEL-ARROW] GET /block-model-arrow mode={mode} lod={lod} "
        f"project_id={project_id} run_id={run_id}"
    )

    try:
        # display_factor acotado a [1, 6]: factor 6 sobre ~8k celdas ya da ~1.7M
        # vóxeles (el techo de ~2M que pidió el usuario). Evita payloads absurdos.
        _df = max(1, min(int(display_factor or 1), 6))
        ipc_bytes, tq_headers = build_block_model_arrow_bytes(
            mode=mode,
            limit=0,
            project_id=project_id,
            run_id=run_id,
            display_factor=_df,
            lod=lod,
        )
    except FileNotFoundError as exc:
        return Response(content=str(exc), status_code=404)
    except ValueError as exc:
        return Response(content=str(exc), status_code=400)
    except Exception as exc:
        print(f"[BLOCK-MODEL-ARROW] Error inesperado: {exc}")
        return Response(content="Error interno al construir Arrow payload.", status_code=500)

    response = StreamingResponse(
        io.BytesIO(ipc_bytes),
        media_type="application/vnd.apache.arrow.stream",
    )
    for key, val in tq_headers.items():
        response.headers[key] = val

    return response


@router.get("/block-model-zarr/{project_id}/{run_id}")
async def get_block_model_zarr(
    project_id: str,
    run_id: str,
    chunk_idx: Optional[int] = Query(None, ge=0),
):
    """Stream Zarr chunks for out-of-core rendering (Fase 10 v0.4.0).

    Without chunk_idx: returns metadata only (total_voxels, chunk_count, bounds).
    With chunk_idx: returns voxel slice [start, end) for that chunk.
    """
    import zarr

    run_dir = get_run_dir(project_id, run_id)
    zarr_path = run_dir / f"{run_id}_blockmodel.zarr"

    if not zarr_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Zarr store no encontrado ({zarr_path}). Grid muy pequeño (<500k vóxeles) usa Parquet.",
        )

    # zarr v3: open_group(path, mode='r') replaces DirectoryStore + open_group(store=...)
    root = zarr.open_group(str(zarr_path), mode="r")

    total_voxels = int(root.attrs["total_voxels"])
    chunk_size_voxels = int(root.attrs.get("chunk_size_voxels", 32768))
    n_chunks = int(root.attrs.get("chunk_count", 1))
    bounds = root.attrs.get("bounds", {})

    metadata = {
        "total_voxels": total_voxels,
        "chunk_count": n_chunks,
        "chunk_size_voxels": chunk_size_voxels,
        "bounds": bounds,
        "project_id": project_id,
        "run_id": run_id,
    }

    if chunk_idx is None:
        return {"metadata_only": True, **metadata}

    if chunk_idx >= n_chunks:
        raise HTTPException(
            status_code=400,
            detail=f"chunk_idx={chunk_idx} fuera de rango (n_chunks={n_chunks}).",
        )

    start = chunk_idx * chunk_size_voxels
    end = min(start + chunk_size_voxels, total_voxels)

    # Vectorised slice reads — O(1) Zarr operations, not O(chunk_size) individual reads
    cx_s = root["cx"][start:end]
    cy_s = root["cy"][start:end]
    cz_s = root["cz"][start:end]
    den_s = root["density"][start:end]
    sus_s = root["susceptibility"][start:end]
    doi_s = root["doi_index"][start:end]

    chunk_voxels = [
        {
            "cx": float(cx_s[j]),
            "cy": float(cy_s[j]),
            "cz": float(cz_s[j]),
            "density": float(den_s[j]),
            "susceptibility": float(sus_s[j]),
            "doi_index": float(doi_s[j]),
        }
        for j in range(len(cx_s))
    ]

    return {
        "chunk_idx": chunk_idx,
        "voxels": chunk_voxels,
        "voxel_count": len(chunk_voxels),
        **metadata,
    }


@router.get("/v2/isosurface")
async def get_isosurface(
    project_id: str,
    run_id: str,
    field: str = Query("density", pattern="^(density|susceptibility)$"),
    levels: Optional[str] = Query(
        None,
        description="Fracciones del pico de |contraste| separadas por coma, p.ej. '0.5,0.7,0.9'.",
    ),
    taubin_iterations: int = Query(12, ge=0, le=100),
):
    """Isosuperficies suaves del block model (Fase F4.1).

    Marching cubes sobre el campo de CONTRASTE robusto (idéntico al del visor de
    vóxeles) a 2-3 niveles (fracciones del pico), suavizadas con Taubin y ya
    transformadas al espacio visual de Three.js (centrado + flip-Y) para
    superponerse a /block-model-arrow.  El frontend NO calcula física.

    Respuesta JSON: metadata (background/scale/peak/weak_anomaly/cell_size/center)
    + levels[] con posiciones/normales/índices/contraste en base64 Float32/Uint32.
    """
    print(
        f"[ISOSURFACE-API] GET /v2/isosurface field={field} levels={levels} "
        f"project_id={project_id} run_id={run_id}"
    )

    parsed_levels = None
    if levels:
        try:
            parsed_levels = tuple(
                float(tok) for tok in levels.split(",") if tok.strip()
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="El parámetro 'levels' debe ser fracciones numéricas separadas por coma.",
            )

    try:
        return build_isosurface_response(
            project_id=project_id,
            run_id=run_id,
            field=field,
            levels=parsed_levels,
            taubin_iterations=taubin_iterations,
        )
    except Exception as exc:  # nunca-crashea: error catalogado en payload
        print(f"[ISOSURFACE-API] Error inesperado: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Error interno al construir las isosuperficies.",
        )


@router.get("/v2/section")
async def get_section(
    project_id: str,
    run_id: str,
    axis: str = Query(..., pattern="^(x|y|z)$"),
    position: float = Query(..., description="Posición del plano en coordenadas VISUALES del visor."),
    field: str = Query("density", pattern="^(density|susceptibility)$"),
):
    """Cara del corte pintada (Fase F4.3).

    Raster 2D del contraste con signo en el plano axis=position (coords visuales,
    snapeado a la capa de celdas más cercana). El frontend lo pinta con el mismo
    Viridis; NO calcula física ni coordenadas.
    """
    print(
        f"[SECTION-API] GET /v2/section axis={axis} position={position} "
        f"field={field} project_id={project_id} run_id={run_id}"
    )
    try:
        return build_section_response(
            project_id=project_id,
            run_id=run_id,
            axis=axis,
            position=position,
            field=field,
        )
    except Exception as exc:  # nunca-crashea: error catalogado en payload
        print(f"[SECTION-API] Error inesperado: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Error interno al construir la sección.",
        )


@router.get("/v2/doi-overlay")
async def get_doi_overlay(project_id: str, run_id: str):
    """Horizonte DOI para el visor 3D (Fase F4.5 — incertidumbre visible).

    Devuelve la profundidad bajo la cual el dato deja de restringir el modelo
    (sensibilidad half-max por capa, misma convención que B2), en coordenadas
    visuales, para atenuar/velar esa zona. El frontend NO calcula física.
    """
    print(f"[DOI-API] GET /v2/doi-overlay project_id={project_id} run_id={run_id}")
    try:
        return build_doi_overlay_response(project_id=project_id, run_id=run_id)
    except Exception as exc:  # nunca-crashea: error catalogado en payload
        print(f"[DOI-API] Error inesperado: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Error interno al construir el horizonte DOI.",
        )


@router.get("/v2/block-model-profile")
async def get_block_model_profile(
    project_id: str,
    run_id: str,
    x0_m: float,
    z0_m: float,
    x1_m: float,
    z1_m: float,
    halfwidth_m: float = 50.0,
    include_observations: bool = True,
):
    """Sección A-A' del modelo de bloques.

    Retorna vóxeles dentro del plano definido por (x0,z0)→(x1,z1) con ancho ±halfwidth_m.
    Incluye d_obs/d_pred/residual de las estaciones dentro del perfil si están disponibles.
    Coordenadas en sistema local del modelo [m].
    """
    return build_block_model_profile_response(
        project_id=project_id,
        run_id=run_id,
        x0_m=x0_m,
        z0_m=z0_m,
        x1_m=x1_m,
        z1_m=z1_m,
        halfwidth_m=halfwidth_m,
        include_observations=include_observations,
    )
