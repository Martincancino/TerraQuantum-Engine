"""F7 — Endpoints de "Exportar diagnóstico" (compatible con confidencialidad).

    GET /diagnostics/manifest  — el contenido del diagnóstico como JSON (para la UI)
    GET /diagnostics/export    — descarga un ZIP con SOLO metadatos (sin datos de survey)

Nada sale de la máquina automáticamente: el usuario descarga el ZIP y lo envía
por su cuenta.
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from services import diagnostics_service

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/manifest")
def manifest():
    """Metadatos de diagnóstico (versiones, config saneada, conectividad,
    licencia, últimos errores) — sin datos de survey ni secretos."""
    return diagnostics_service.diagnostic_manifest()


@router.get("/export")
def export():
    """Genera y descarga el ZIP de diagnóstico."""
    zip_path = diagnostics_service.build_diagnostic_zip()
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )
