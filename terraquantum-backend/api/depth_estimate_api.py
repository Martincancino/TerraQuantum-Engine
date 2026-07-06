"""F2B — Endpoint de estimación de profundidad independiente (Euler + espectro).

POST /v2/depth-estimate: estaciones dispersas (gravedad mGal o TMI nT) →
nube de soluciones de Euler (x, y, profundidad, con criterios de aceptación
estándar) + espectro de potencia radial (profundidades de ensamble) como
chequeo cruzado. La nube se dibuja en el visor 3D y se exporta CSV.

Es la estimación INDEPENDIENTE de la inversión (puente a F11): cada salida
lleva la nota de honestidad del método (±15-25% típico; ensambles, no cuerpos).
"""
from __future__ import annotations

from typing import List, Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.utils import sanitize_nan

router = APIRouter(prefix="/v2/depth-estimate", tags=["Depth Estimate"])
_log = get_logger(__name__)


class DepthEstimateRequest(BaseModel):
    stations: List[dict]
    value_column: str = "magnetic_nt"
    structural_index: float = Field(default=3.0, ge=0.0, le=3.0)
    window_cells: int = Field(default=10, ge=4, le=40)
    step_cells: int = Field(default=2, ge=1, le=10)
    max_rel_uncertainty: float = Field(default=0.15, gt=0.0, le=1.0)
    include_spectrum: bool = True
    output_format: Literal["json", "csv"] = "json"


@router.post("")
def depth_estimate_endpoint(req: DepthEstimateRequest):
    from fastapi.responses import PlainTextResponse

    from services.euler_spectral_service import (
        euler_deconvolution,
        radial_power_spectrum,
    )
    from services.potential_field_grid_service import grid_scattered

    stations = req.stations
    if len(stations) < 8:
        raise HTTPException(
            status_code=422,
            detail=f"Se necesitan ≥8 estaciones (hay {len(stations)}).",
        )
    try:
        vals = np.array([float(s[req.value_column]) for s in stations])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Columna '{req.value_column}' ausente o no numérica: {exc}",
        ) from exc
    if not all(("x_m" in s and "y_m" in s) for s in stations):
        raise HTTPException(
            status_code=422,
            detail="Cada estación debe traer x_m/y_m (metros locales del import).",
        )
    xs = np.array([float(s["x_m"]) for s in stations])
    ys = np.array([float(s["y_m"]) for s in stations])

    try:
        sg = grid_scattered(xs, ys, vals)
        euler = euler_deconvolution(
            sg,
            structural_index=req.structural_index,
            window_cells=min(req.window_cells, min(sg.nx, sg.ny)),
            step_cells=req.step_cells,
            max_rel_uncertainty=req.max_rel_uncertainty,
        )
        spectrum = radial_power_spectrum(sg) if req.include_spectrum else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if req.output_format == "csv":
        lines = [
            "# TerraQuantum Euler deconvolution — nube de soluciones",
            f"# SI={req.structural_index} ventana={req.window_cells} celdas",
            f"# {euler.report['honesty_note']}",
            "x_m,y_m,depth_m,background,rel_uncertainty",
        ]
        for s in euler.solutions:
            lines.append(
                f"{s.x_m:.2f},{s.y_m:.2f},{s.depth_m:.2f},"
                f"{s.background:.4f},{s.rel_uncertainty:.4f}"
            )
        return PlainTextResponse(
            "\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="euler_solutions.csv"'},
        )

    return sanitize_nan({
        "euler": {
            "report": euler.report,
            "solutions": [
                {
                    "x_m": s.x_m, "y_m": s.y_m, "depth_m": s.depth_m,
                    "background": s.background,
                    "rel_uncertainty": s.rel_uncertainty,
                }
                for s in euler.solutions
            ],
        },
        "spectrum": spectrum,
        "grid_meta": sg.meta(),
    })
