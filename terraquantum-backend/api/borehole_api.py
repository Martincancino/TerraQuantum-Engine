"""
Router FastAPI — Sondajes (FASE 20: Borehole Integration).

Endpoints (capa de carga/validación; la física de anclaje vive en el solver):

    POST /borehole/parse-csv
        Recibe el texto crudo de un CSV de sondajes (+ unidades/CRS) y devuelve
        el BoreholeSurvey validado, listo para previsualizar y para alimentar la
        inversión (campo `boreholes` de /geophysics-invert). Convierte unidades
        (pies→metros), auto-detecta columnas y reporta filas inválidas.

    GET /borehole/lithology-properties
        Tabla petrofísica (densidad/susceptibilidad por litología) que usa el
        frontend para colorear los sondajes y para los priors PGI.

NOTA (Regla de Oro): el parseo y la tabla petrofísica viven SOLO aquí (backend).
El frontend NO reimplementa esta lógica; la consume vía estos endpoints.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from core.logging import get_logger
from schemas.geophysics_schema import BoreholeSurvey
from services.borehole_service import (
    LITHOLOGY_PROPERTIES,
    lithology_properties,
    parse_borehole_csv,
)
from services.borehole_view_service import build_borehole_view_response

router = APIRouter(prefix="/borehole", tags=["Borehole (Fase 20)"])
_log = get_logger(__name__)

# FASE 12 — tope del OMF subido. Es binario comprimido con el block model de otro
# software dentro, así que no comparte techo con el CSV de sondajes (20 MB, más
# arriba): un OMF de una malla mediana los supera sin ser sospechoso.
OMF_MAX_BYTES = 200 * 1024 * 1024


class ParseBoreholeCsvRequest(BaseModel):
    csv_text: str = Field(..., description="Contenido crudo del CSV de sondajes.")
    length_units: str = Field(
        "m", description="Unidad de longitud de entrada: 'm', 'ft' o 'auto'.",
    )
    crs: str = Field("local", description="Sistema de referencia (metadato).")
    datum_elevation_m: float = Field(0.0, description="Elevación del datum local (m).")


class ParseBoreholeCsvResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    survey: BoreholeSurvey
    n_holes: int
    n_samples: int
    n_with_density: int
    n_with_susceptibility: int
    n_with_lithology: int
    lithologies_detected: List[str]
    unrecognized_lithologies: List[str]


# ── F2B — Desurvey por curvatura mínima + QA/QC + compositación ─────────────
class SurveyStation(BaseModel):
    md: float = Field(..., ge=0.0, description="Profundidad medida [m].")
    azimuth_deg: float = Field(..., ge=0.0, le=360.0)
    dip_deg: float = Field(
        ..., ge=-90.0, le=90.0,
        description="Grados BAJO la horizontal, positivo hacia abajo (90=vertical).",
    )


class DesurveyHole(BaseModel):
    hole_id: str
    collar_x_m: float
    collar_z_m: float
    total_depth_m: Optional[float] = None
    survey: List[SurveyStation]
    intervals: List[dict] = Field(default_factory=list)


class DesurveyRequest(BaseModel):
    holes: List[DesurveyHole]
    composite_length_m: Optional[float] = Field(default=None, gt=0.0, le=1000.0)


@router.post("/desurvey")
def desurvey_endpoint(req: DesurveyRequest):
    """F2B — Traza 3D verdadera (curvatura mínima) + QA/QC + compositación.

    Devuelve por pozo la traza desurveyada (para dibujarla), los intervalos
    posicionados en el contrato del ancla (x_m/z_m del punto medio +
    profundidades verticales verdaderas), el reporte QA/QC con fila y
    severidad, y opcionalmente los composites al largo pedido.
    """
    from core.utils import sanitize_nan
    from services.borehole_desurvey_service import (
        DesurveyInputError,
        composite_intervals,
        desurvey_minimum_curvature,
        position_intervals_on_trace,
        qaqc_intervals,
    )

    if not req.holes:
        raise HTTPException(status_code=422, detail="Se requiere al menos 1 pozo.")

    all_intervals: List[dict] = []
    holes_out: List[dict] = []
    for hole in req.holes:
        try:
            trace = desurvey_minimum_curvature(
                hole.hole_id,
                [s.md for s in hole.survey],
                [s.azimuth_deg for s in hole.survey],
                [s.dip_deg for s in hole.survey],
                total_depth_m=hole.total_depth_m,
            )
        except DesurveyInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        positioned = position_intervals_on_trace(
            trace, hole.collar_x_m, hole.collar_z_m,
            [{**iv, "hole_id": hole.hole_id} for iv in hole.intervals],
        )
        all_intervals.extend(
            {**iv, "hole_id": hole.hole_id} for iv in hole.intervals
        )
        holes_out.append({
            "hole_id": hole.hole_id,
            "trace": [
                {
                    "md": float(trace.md[i]),
                    "x_m": hole.collar_x_m + float(trace.east[i]),
                    "z_m": hole.collar_z_m + float(trace.north[i]),
                    "depth_m": float(trace.depth[i]),
                }
                for i in range(len(trace.md))
            ],
            "intervals_positioned": positioned,
            "warnings": trace.warnings,
        })

    qaqc = qaqc_intervals(all_intervals)

    composites = None
    composite_warnings: List[str] = []
    if req.composite_length_m:
        composites, composite_warnings = composite_intervals(
            all_intervals, req.composite_length_m
        )

    return sanitize_nan({
        "holes": holes_out,
        "qaqc": qaqc,
        "composites": composites,
        "composite_warnings": composite_warnings,
    })


def _survey_summary(survey: BoreholeSurvey) -> dict:
    """Conteos y litologías de un survey ya construido.

    F12: se extrae de `_build_parse_response` para que la importación de OMF
    produzca EXACTAMENTE los mismos conteos que la de CSV, sin reimplementarlos.
    """
    holes = survey.holes
    lithos = [h.lithology for h in holes if h.lithology]
    distinct_lithos = sorted({l.strip().lower() for l in lithos})
    return {
        "survey": survey,
        "n_holes": len({h.hole_id for h in holes}),
        "n_samples": len(holes),
        "n_with_density": sum(1 for h in holes if h.density_t_m3 is not None),
        "n_with_susceptibility": sum(1 for h in holes if h.susceptibility_si is not None),
        "n_with_lithology": len(lithos),
        "lithologies_detected": distinct_lithos,
        "unrecognized_lithologies": sorted({
            l for l in distinct_lithos if lithology_properties(l) is None
        }),
    }


def _build_parse_response(
    csv_text: str, length_units: str, crs: str, datum_elevation_m: float
) -> ParseBoreholeCsvResponse:
    try:
        survey = parse_borehole_csv(
            csv_text,
            length_units=length_units,
            crs=crs,
            datum_elevation_m=datum_elevation_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return ParseBoreholeCsvResponse(**_survey_summary(survey))


@router.post("/parse-csv", response_model=ParseBoreholeCsvResponse)
def parse_csv(req: ParseBoreholeCsvRequest) -> ParseBoreholeCsvResponse:
    return _build_parse_response(
        req.csv_text, req.length_units, req.crs, req.datum_elevation_m
    )


@router.post("/parse-csv-file", response_model=ParseBoreholeCsvResponse)
async def parse_csv_file(
    file: UploadFile = File(...),
    length_units: str = Form("m"),
    crs: str = Form("local"),
    datum_elevation_m: float = Form(0.0),
) -> ParseBoreholeCsvResponse:
    """F2B — variante MULTIPART: los BYTES llegan intactos y el encoding lo
    decide el sniffer (UTF-8/UTF-16/cp1252/latin-1).

    Cierra el gap del reviewer F2: la variante csv_text recibe texto YA
    decodificado como UTF-8 por el navegador — un CSV latin-1 con litologías
    con ñ/acentos llegaba con mojibake y bypasseaba el sniffer.
    """
    from services.csv_sniffer_service import detect_encoding

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV de sondajes > 20 MB.")
    enc = detect_encoding(content)
    csv_text = content.decode(enc.value, errors="replace")
    resp = _build_parse_response(csv_text, length_units, crs, datum_elevation_m)
    _log.info("borehole_parse_csv_file", encoding=enc.value, n_samples=resp.n_samples)
    return resp


# ── FASE 12 — Importar sondajes desde Open Mining Format ────────────────────

class OmfElementInfo(BaseModel):
    """Una línea del inventario del OMF: qué venía dentro y si se usó."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    name: str
    kind: str
    n_vertices: int
    n_primitives: int
    attributes: List[str]
    consumed: bool
    note: str


class OmfImportBounds(BaseModel):
    """Caja envolvente en las coordenadas ORIGINALES del fichero.

    Se publica siempre: es lo que deja ver de un vistazo si el OMF venía en UTM
    absoluto o en metros locales, sin que el backend lo adivine con un umbral.
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


class ImportOmfBoreholesResponse(ParseBoreholeCsvResponse):
    """Mismos conteos que la importación de CSV, más lo específico del OMF."""
    inventory: List[OmfElementInfo]
    warnings: List[str]
    n_elements: int
    deviated_holes_skipped: int
    origin_easting_applied: float
    origin_northing_applied: float
    bounds_raw: Optional[OmfImportBounds] = None


@router.post("/import-omf", response_model=ImportOmfBoreholesResponse)
async def import_omf(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    run_id: Optional[str] = Form(None),
    origin_easting: Optional[float] = Form(None),
    origin_northing: Optional[float] = Form(None),
    surface_z: Optional[float] = Form(None),
    density_attribute: Optional[str] = Form(None),
    lithology_attribute: Optional[str] = Form(None),
    crs: str = Form("local"),
) -> ImportOmfBoreholesResponse:
    """FASE 12 — Lee un `.omf` de terceros y devuelve sus SONDAJES.

    Devuelve el mismo `BoreholeSurvey` que `/borehole/parse-csv`, así que el
    sondaje importado alimenta el anclaje de la inversión por el camino que ya
    existe. Del resto del fichero (volúmenes, superficies, nubes de puntos) se
    devuelve un inventario y se declara que TerraQuantum aún no los consume.

    Lo que NO hace, a propósito: aplastar sondajes desviados a la vertical (los
    descarta y los nombra), adivinar el origen UTM, ni inventar el datum vertical.
    """
    from services.omf_import_service import OmfImportError, import_omf_boreholes

    content = await file.read()
    if len(content) > OMF_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Fichero OMF > {OMF_MAX_BYTES // (1024 * 1024)} MB.",
        )
    try:
        result = import_omf_boreholes(
            content,
            project_id=project_id,
            run_id=run_id,
            origin_easting=origin_easting,
            origin_northing=origin_northing,
            surface_z=surface_z,
            density_attribute=density_attribute,
            lithology_attribute=lithology_attribute,
            crs=crs,
        )
    except OmfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stats = result.stats
    origin = stats.get("origin_applied") or {}
    bounds = stats.get("bounds_raw")
    _log.info(
        "borehole_import_omf",
        n_samples=len(result.survey.holes),
        n_elements=stats.get("n_elements", 0),
        deviated=stats.get("deviated_holes", 0),
    )
    return ImportOmfBoreholesResponse(
        **_survey_summary(result.survey),
        inventory=[
            OmfElementInfo(
                name=item.name,
                kind=item.kind,
                n_vertices=item.n_vertices,
                n_primitives=item.n_primitives,
                attributes=list(item.attributes),
                consumed=item.consumed,
                note=item.note,
            )
            for item in result.inventory
        ],
        warnings=result.warnings,
        n_elements=int(stats.get("n_elements", 0)),
        deviated_holes_skipped=int(stats.get("deviated_holes", 0)),
        origin_easting_applied=float(origin.get("easting", 0.0)),
        origin_northing_applied=float(origin.get("northing", 0.0)),
        bounds_raw=OmfImportBounds(**bounds) if bounds else None,
    )


class LithologyEntry(BaseModel):
    name: str
    density_t_m3: float
    susceptibility_si: float


@router.get("/lithology-properties", response_model=List[LithologyEntry])
def lithology_table() -> List[LithologyEntry]:
    """Devuelve la tabla petrofísica (densidad/susc por litología)."""
    return [
        LithologyEntry(
            name=name,
            density_t_m3=props["density_t_m3"],
            susceptibility_si=props["susceptibility_si"],
        )
        for name, props in LITHOLOGY_PROPERTIES.items()
    ]


@router.get("/view")
async def get_borehole_view(project_id: str, run_id: str):
    """Sondajes de la corrida en coordenadas del visor 3D (Fase F4.4).

    Devuelve los intervalos ya centrados + flip-Y (mismo espacio que vóxeles e
    isosuperficies) para dibujarlos como cilindros, con contraste de densidad para
    colorear con el mismo Viridis. El frontend NO calcula coordenadas ni física.
    """
    print(f"[BOREHOLE-API] GET /borehole/view project_id={project_id} run_id={run_id}")
    try:
        return build_borehole_view_response(project_id=project_id, run_id=run_id)
    except Exception as exc:  # nunca-crashea: error catalogado en el payload
        print(f"[BOREHOLE-API] Error inesperado en /view: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Error interno al construir la vista de sondajes.",
        )
