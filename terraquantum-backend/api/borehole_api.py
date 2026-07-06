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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logging import get_logger
from schemas.geophysics_schema import BoreholeSurvey
from services.borehole_service import (
    LITHOLOGY_PROPERTIES,
    lithology_properties,
    parse_borehole_csv,
)

router = APIRouter(prefix="/borehole", tags=["Borehole (Fase 20)"])
_log = get_logger(__name__)


class ParseBoreholeCsvRequest(BaseModel):
    csv_text: str = Field(..., description="Contenido crudo del CSV de sondajes.")
    length_units: str = Field(
        "m", description="Unidad de longitud de entrada: 'm', 'ft' o 'auto'.",
    )
    crs: str = Field("local", description="Sistema de referencia (metadato).")
    datum_elevation_m: float = Field(0.0, description="Elevación del datum local (m).")


class ParseBoreholeCsvResponse(BaseModel):
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


@router.post("/parse-csv", response_model=ParseBoreholeCsvResponse)
def parse_csv(req: ParseBoreholeCsvRequest) -> ParseBoreholeCsvResponse:
    try:
        survey = parse_borehole_csv(
            req.csv_text,
            length_units=req.length_units,
            crs=req.crs,
            datum_elevation_m=req.datum_elevation_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    holes = survey.holes
    hole_ids = {h.hole_id for h in holes}
    lithos = [h.lithology for h in holes if h.lithology]
    distinct_lithos = sorted({l.strip().lower() for l in lithos})
    unrecognized = sorted({
        l for l in distinct_lithos if lithology_properties(l) is None
    })

    return ParseBoreholeCsvResponse(
        survey=survey,
        n_holes=len(hole_ids),
        n_samples=len(holes),
        n_with_density=sum(1 for h in holes if h.density_t_m3 is not None),
        n_with_susceptibility=sum(1 for h in holes if h.susceptibility_si is not None),
        n_with_lithology=len(lithos),
        lithologies_detected=distinct_lithos,
        unrecognized_lithologies=unrecognized,
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
