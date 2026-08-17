"""F7 — Endpoints de "Exportar diagnóstico" (compatible con confidencialidad).

    GET /diagnostics/manifest  — el contenido del diagnóstico como JSON (para la UI)
    GET /diagnostics/export    — descarga un ZIP con SOLO metadatos (sin datos de survey)

Nada sale de la máquina automáticamente: el usuario descarga el ZIP y lo envía
por su cuenta.
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from schemas.system_schema import DiagnosticManifestResponse
from services import diagnostics_service

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


# `/export` NO lleva `response_model` a propósito: devuelve un ZIP
# (`FileResponse`), no JSON. Declararle un esquema JSON sería documentar una
# mentira; el generador de tipos del frontend lo salta por eso mismo.
@router.get("/manifest", response_model=DiagnosticManifestResponse,
            response_model_exclude_unset=True)
def manifest():
    """Metadatos de diagnóstico (versiones, config saneada, conectividad,
    licencia, últimos errores) — sin datos de survey ni secretos."""
    return diagnostics_service.diagnostic_manifest()


@router.get(
    "/export",
    response_class=FileResponse,
    # FASE 10 — sin esto el OpenAPI declaraba `application/json` para un ZIP.
    # No es cosmético: el generador de tipos recorre las respuestas JSON, y una
    # ruta binaria disfrazada de JSON es justo el tipo fantasma que esta fase
    # existe para no fabricar.
    responses={200: {"content": {"application/zip": {}},
                     "description": "ZIP de diagnóstico (sólo metadatos)."}},
)
def export():
    """Genera y descarga el ZIP de diagnóstico."""
    zip_path = diagnostics_service.build_diagnostic_zip()
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )
