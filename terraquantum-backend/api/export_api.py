"""
FASE 11 — Export API.

Endpoints:
  GET /export/bundle/{project_id}/{run_id}
      → ZIP industrial con model.vtr, model.mod, model.msh, model.gslib, manifest.json
  GET /export/block-model-csv/{project_id}/{run_id}
      → CSV estándar minero (X_m, Y_m, Z_m, Density_gcm3[, Susceptibility_SI], …) — F5
  GET /export/omf/{project_id}/{run_id}
      → Open Mining Format v1 (.omf) — FASE 12

Regla de Oro: estos endpoints leen datos persistidos en disco.
NO ejecutan física ni inversión (excepción declarada: las isosuperficies del OMF
las calcula al vuelo `isosurface_service`, igual que para el visor).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from services.export_service import create_run_bundle_zip, export_block_model_to_csv
from services.omf_export_service import OmfExportError, export_run_to_omf

router = APIRouter(prefix="/export", tags=["export-fase11"])


@router.get("/bundle/{project_id}/{run_id}", summary="Bundle ZIP industrial del run")
async def get_run_bundle(project_id: str, run_id: str) -> Response:
    """
    Compila y retorna el bundle ZIP industrial del run con:

    - **model.vtr**    — VTK RectilinearGrid (ParaView / Leapfrog Geo)
    - **model.mod**    — UBC-GIF Density Model (Grav3D / SimPEG)
    - **model.msh**    — UBC-GIF Mesh Definition
    - **model.gslib**  — Stanford GSLIB / SGeMS
    - **manifest.json** — Audit trail completo (Fase 11 trazabilidad)

    El `manifest.json` incluye: versión TerraQuantum, Run ID, Config Hash SHA256,
    parámetros de inversión y disclaimer NI 43-101 / JORC / SAMREC.
    """
    try:
        zip_bytes, filename = create_run_bundle_zip(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error generando bundle: {exc}"
        ) from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(zip_bytes)),
            "X-TerraQuantum-Version": "FASE-11",
            "X-TerraQuantum-Disclaimer": "NO-JORC/NI-43-101 EXPLORATION ONLY",
        },
    )


@router.get("/block-model-csv/{project_id}/{run_id}", summary="Block model CSV estándar minero (F5)")
async def get_block_model_csv(project_id: str, run_id: str) -> Response:
    """
    CSV con X_m, Y_m, Z_m, Density_gcm3[, Susceptibility_SI] y columnas de diagnóstico
    (Sensitivity_Proxy, DOI_Index, Posterior_Std, Probability, Is_Active), leídas
    DIRECTAMENTE del block model persistido (coordenadas reales, sin recalcular física).
    """
    csv_path = export_block_model_to_csv(project_id, run_id)
    if csv_path is None:
        raise HTTPException(
            status_code=404,
            detail="Block model no disponible para esta corrida (parquet ausente o incompleto).",
        )
    content = Path(csv_path).read_bytes()
    safe = lambda s: "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in s)[:32]
    filename = f"block_model_{safe(project_id)}_{safe(run_id)}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-TerraQuantum-Disclaimer": "NO-JORC/NI-43-101 EXPLORATION ONLY",
        },
    )


# FASE 12 — OMF. Igual que `/diagnostics/export`, esta ruta NO lleva
# `response_model`: devuelve binario. Se declara el content-type real para que el
# OpenAPI no mienta y el generador de tipos del frontend la salte a propósito.
@router.get(
    "/omf/{project_id}/{run_id}",
    summary="Open Mining Format v1 (.omf) del run — FASE 12",
    responses={200: {"content": {"application/octet-stream": {}},
                     "description": "Fichero OMF v1 con block model, estaciones, "
                                    "sondajes e isosuperficies."}},
)
async def get_run_omf(
    project_id: str,
    run_id: str,
    include_surfaces: bool = Query(
        True,
        description="Incluir isosuperficies. Es lo único que se calcula al vuelo; "
                    "desactívalo si sólo quieres el block model.",
    ),
) -> Response:
    """Exporta la corrida a OMF, el formato con el que un consultor entrega a una
    minera con Leapfrog / Vulcan / Micromine.

    Contenido: `VolumeElement` (block model, ejes ya permutados a Este/Norte/arriba),
    `PointSetElement` (estaciones observado/calculado/residual), `LineSetElement`
    (sondajes con densidad y litología) y una `SurfaceElement` por isosuperficie.

    Devuelve **404** si la corrida no existe, y **422** si su block model no permite
    reconstruir la malla sin inventarla (caso medido: la tabla dispersa que escribe
    la inversión conjunta, que no guarda `ix/iy/iz` ni `inputs.json`).
    """
    try:
        payload, filename, manifest = export_run_to_omf(
            project_id, run_id, include_surfaces=include_surfaces
        )
    except OmfExportError as exc:
        status = 404 if "no encontrada" in str(exc).lower() else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando OMF: {exc}") from exc

    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
            "X-TerraQuantum-OMF-Mapping": manifest["mapping_version"],
            "X-TerraQuantum-Georeferenced": str(manifest["georeferenced"]).lower(),
            "X-TerraQuantum-Disclaimer": "NO-JORC/NI-43-101 EXPLORATION ONLY",
        },
    )


