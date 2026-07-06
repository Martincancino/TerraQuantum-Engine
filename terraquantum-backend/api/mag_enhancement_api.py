"""F2B — Endpoint de la suite de realce magnético (sala de mapas).

POST /v2/mag-enhance: TMI dispersa (estaciones) → productos de grilla
(RTP / 1VD / THD / tilt / señal analítica / continuación ascendente) +
corrección diurna opcional desde archivo de base magnética. Todo el cálculo
vive en services/mag_enhancement_service; aquí solo contrato HTTP.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.utils import sanitize_nan

router = APIRouter(prefix="/v2/mag-enhance", tags=["Magnetic Enhancement"])
_log = get_logger(__name__)


class DiurnalBase(BaseModel):
    times_utc: List[str]
    values_nt: List[float]


class MagEnhanceRequest(BaseModel):
    stations: List[dict]
    products: List[
        Literal["rtp", "vd1", "thd", "tilt", "analytic_signal", "upward_continuation"]
    ] = Field(default_factory=lambda: ["tilt", "analytic_signal"])
    tmi_column: str = "magnetic_nt"
    inclination_deg: float = Field(default=-30.0, ge=-90.0, le=90.0)
    declination_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    uc_height_m: float = Field(default=500.0, gt=0.0, le=100_000.0)
    diurnal_base: Optional[DiurnalBase] = None
    output_format: Literal["json", "csv"] = "json"
    csv_product: Optional[str] = None      # producto a exportar cuando csv


@router.post("")
def mag_enhance_endpoint(req: MagEnhanceRequest):
    from fastapi.responses import PlainTextResponse

    from services.earth_tide_service import parse_survey_timestamps
    from services.mag_enhancement_service import (
        MagEnhancementError,
        run_mag_enhancement,
    )

    stations = req.stations
    if len(stations) < 8:
        raise HTTPException(
            status_code=422,
            detail=f"Se necesitan ≥8 estaciones magnéticas (hay {len(stations)}).",
        )
    try:
        tmi = np.array([float(s[req.tmi_column]) for s in stations])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Columna TMI '{req.tmi_column}' ausente o no numérica: {exc}",
        ) from exc
    if all(("x_m" in s and "y_m" in s) for s in stations):
        xs = np.array([float(s["x_m"]) for s in stations])
        ys = np.array([float(s["y_m"]) for s in stations])
    else:
        raise HTTPException(
            status_code=422,
            detail="Cada estación debe traer x_m/y_m (metros locales del import).",
        )

    survey_times = base_times = base_vals = None
    if req.diurnal_base is not None:
        raw_times = [str(s.get("time_utc") or s.get("timestamp") or "") for s in stations]
        if all(not t.strip() for t in raw_times):
            raise HTTPException(
                status_code=422,
                detail=(
                    "La corrección diurna requiere la hora de cada lectura del "
                    "survey (columna time_utc por estación)."
                ),
            )
        survey_times = parse_survey_timestamps(raw_times)
        base_times = parse_survey_timestamps(req.diurnal_base.times_utc)
        if survey_times is None or base_times is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Timestamps ilegibles (survey o base): TODOS deben parsear "
                    "('YYYY-MM-DD HH:MM[:SS]' o ISO-8601 UTC)."
                ),
            )
        base_vals = np.asarray(req.diurnal_base.values_nt, dtype=float)

    try:
        res = run_mag_enhancement(
            xs, ys, tmi,
            products=req.products,
            inc_deg=req.inclination_deg, dec_deg=req.declination_deg,
            uc_height_m=req.uc_height_m,
            survey_times=survey_times, base_times=base_times, base_nt=base_vals,
        )
    except (MagEnhancementError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if req.output_format == "csv":
        prod = req.csv_product or (req.products[0] if req.products else None)
        if prod not in res.products:
            raise HTTPException(
                status_code=422,
                detail=f"csv_product debe ser uno de los productos pedidos: {req.products}",
            )
        g = res.products[prod]
        sg = res.grid
        lines = [f"# TerraQuantum realce magnético — producto: {prod}", "x_m,y_m,value"]
        for iy in range(sg.ny):
            for ix in range(sg.nx):
                lines.append(
                    f"{sg.x0 + ix * sg.dx:.2f},{sg.y0 + iy * sg.dy:.2f},{g[iy, ix]:.6f}"
                )
        return PlainTextResponse(
            "\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="mag_{prod}.csv"'},
        )

    grids: Dict[str, list] = {name: g.tolist() for name, g in res.products.items()}
    return sanitize_nan({
        "report": res.report,
        "grid_meta": res.grid.meta(),
        "observed_tmi": res.grid.values.tolist(),
        "products": grids,
    })
