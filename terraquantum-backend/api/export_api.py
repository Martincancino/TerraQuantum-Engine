"""
FASE 11 — Export API.

Endpoints:
  GET /export/bundle/{project_id}/{run_id}
      → ZIP industrial con model.vtr, model.mod, model.msh, model.gslib, manifest.json

  GET /export/qa-diagnostics/{project_id}/{run_id}
      → JSON con config_hash, L-curve, checkerboard QA y fit_diagnostics
        para el DiagnosticPanel del frontend (GeoDashboard).

Regla de Oro: estos endpoints leen datos persistidos en disco.
NO ejecutan física ni inversión.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from services.export_service import create_run_bundle_zip, get_run_qa_diagnostics

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


@router.get(
    "/qa-diagnostics/{project_id}/{run_id}",
    summary="Datos de diagnóstico QA para el DiagnosticPanel",
)
async def get_qa_diagnostics(project_id: str, run_id: str) -> JSONResponse:
    """
    Retorna los datos de diagnóstico QA para el **DiagnosticPanel** del visor 3D.

    Incluye:
    - **config_hash** — SHA256[:16] de los parámetros físicos de inversión
    - **l_curve** — Puntos {lambda, misfit_norm, roughness_norm} para graficar la L-Curve
    - **checkerboard_qa** — Correlación Pearson r y status PASS/MARGINAL/FAIL
    - **fit_diagnostics** — Métricas de ajuste del run (RMSE, misfit %, fit_level)
    - **inversion_params_snapshot** — Snapshot de los parámetros auditados

    Los datos son leídos de los JSONs persistidos del run (sin recalcular).
    """
    try:
        data = get_run_qa_diagnostics(project_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error obteniendo diagnósticos QA: {exc}"
        ) from exc

    return JSONResponse(content=data)
