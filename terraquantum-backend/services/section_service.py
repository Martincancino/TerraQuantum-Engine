"""Section service (Fase F4.3) — la CARA del corte pintada con densidad.

Dado un plano axis-alineado (x/y/z) y una posición en COORDENADAS VISUALES del
visor (el mismo espacio centrado + flip-Y de vóxeles/isosuperficies/sondajes),
extrae la capa de celdas más cercana del block model y la rasteriza como una
grilla 2D de CONTRASTE con signo (misma definición robusta que la isosuperficie:
fondo=mediana, escala=max(P95−bg, bg−P5, piso)).

El frontend recibe el raster (base64 Float32, NaN donde no hay celda) + la
posición SNAPEADA + el extent del plano, y solo lo pinta con el mismo Viridis.
No calcula física ni coordenadas: "cortar la tierra y ver el mineral en la cara".

Convención de ejes visuales (Three.js):
    cx = x_m − x_c   (este)
    cy = y_c − y_m   (vertical, flip: y_m = profundidad + hacia abajo)
    cz = z_m − z_c   (norte)

Plano por eje (u = horizontal del raster, v = vertical del raster):
    axis "x" → plano YZ: u = cz, v = cy
    axis "y" → plano XZ (corte horizontal): u = cx, v = cz
    axis "z" → plano XY: u = cx, v = cy
"""

from __future__ import annotations

import base64
import logging

import numpy as np
import polars as pl

from core.block_model_store import resolve_block_model_reference
from services.isosurface_service import (
    _SUPPORTED_FIELDS,
    _axis_coords,
    _axis_grid,
    _extract_field_values,
    _robust_background_scale,
)

logger = logging.getLogger(__name__)

_AXES = ("x", "y", "z")
# Tope del raster denso (float64): 4M píxeles ≈ 32 MB — por encima la grilla no es regular.
_MAX_RASTER_PIXELS = 4_000_000


def _b64_f32(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype="<f4").tobytes()).decode("ascii")


def build_section_response(
    project_id: str | None,
    run_id: str | None,
    axis: str,
    position: float,
    field: str = "density",
) -> dict:
    """Raster 2D del contraste en el plano `axis`=`position` (coords visuales).

    Devuelve dict JSON-serializable:
        axis, position_snapped, u0, v0, du, dv, nu, nv,
        values_b64 (Float32 row-major [iv*nu + iu], NaN = sin celda),
        background, scale, field, warnings[], error?
    """
    warnings: list[str] = []
    axis = (axis or "").strip().lower()
    field_clean = (field or "density").strip().lower()

    if axis not in _AXES:
        return _empty(f"Eje inválido: {axis!r} (usa x, y o z).", warnings)
    if field_clean not in _SUPPORTED_FIELDS:
        return _empty(f"Campo no soportado: {field!r}.", warnings)

    try:
        ref = resolve_block_model_reference(project_id=project_id, run_id=run_id)
    except ValueError as exc:
        return _empty(str(exc), warnings)
    if not ref.path.exists():
        return _empty(f"Archivo {ref.path} no encontrado.", warnings)

    df = pl.read_parquet(str(ref.path))
    if len(df) == 0:
        return _empty("Block model vacío.", warnings)

    xm = _axis_coords(df, ("x_m", "x"))
    ym = _axis_coords(df, ("y_m", "y"))
    zm = _axis_coords(df, ("z_m", "z"))
    if xm is None or ym is None or zm is None:
        return _empty("El block model no tiene coordenadas utilizables.", warnings)

    # Solo celdas con coordenadas finitas (el rank-encoding no tolera NaN).
    coords_ok = np.isfinite(xm) & np.isfinite(ym) & np.isfinite(zm)
    if not coords_ok.any():
        return _empty("El block model no tiene coordenadas finitas.", warnings)

    raw_all = _extract_field_values(df, field_clean)
    xm, ym, zm, raw = xm[coords_ok], ym[coords_ok], zm[coords_ok], raw_all[coords_ok]

    x_c = (float(np.min(xm)) + float(np.max(xm))) / 2.0
    y_c = (float(np.min(ym)) + float(np.max(ym))) / 2.0
    z_c = (float(np.min(zm)) + float(np.max(zm))) / 2.0

    # Coordenadas visuales por celda (idéntico a vóxeles/isosuperficie/sondajes).
    cx = xm - x_c
    cy = y_c - ym
    cz = zm - z_c

    axis_arr, u_arr, v_arr = {
        "x": (cx, cz, cy),
        "y": (cy, cx, cz),
        "z": (cz, cx, cy),
    }[axis]

    # Snap de la posición pedida a la capa de celdas más cercana en ese eje.
    uniq = np.unique(np.round(axis_arr, 3))
    if uniq.size == 0:
        return _empty("El eje pedido no tiene coordenadas finitas.", warnings)
    snapped = float(uniq[np.argmin(np.abs(uniq - float(position)))])
    layer_mask = np.round(axis_arr, 3) == snapped

    # Grillas regulares de u/v sobre TODO el modelo (extent completo del plano).
    gu = _axis_grid(u_arr)
    gv = _axis_grid(v_arr)
    if gu is None or gv is None:
        return _empty("La sección es degenerada (<2 celdas en un eje del plano).", warnings)
    iu, nu, du, u0, _ = gu
    iv, nv, dv, v0, _ = gv

    # Tope anti-OOM: raster denso inviable = grilla no regular (coords continuas).
    if nu * nv > _MAX_RASTER_PIXELS:
        return _empty("La sección excede el tamaño máximo (grilla no regular).", warnings)

    # Contraste con signo (misma definición que la isosuperficie).
    finite = np.isfinite(raw)
    if not finite.any():
        return _empty(f"El campo {field_clean} no tiene valores finitos.", warnings)
    bg, scale = _robust_background_scale(raw[finite])
    signed = (raw - bg) / scale

    sel = layer_mask & finite
    if not sel.any():
        return _empty("La capa seleccionada no tiene celdas con datos.", warnings)

    raster = np.full((nv, nu), np.nan, dtype=np.float64)
    raster[iv[sel], iu[sel]] = signed[sel]

    return {
        "axis": axis,
        "field": field_clean,
        "position_snapped": snapped,
        "u0": round(float(u0), 3),
        "v0": round(float(v0), 3),
        "du": round(float(du), 3),
        "dv": round(float(dv), 3),
        "nu": int(nu),
        "nv": int(nv),
        "n_cells": int(sel.sum()),
        "values_b64": _b64_f32(raster.ravel()),
        "background": round(float(bg), 6),
        "scale": round(float(scale), 6),
        "colormap": "viridis_divergent",
        "warnings": warnings,
        "error": None,
    }


def _empty(error: str, warnings: list[str]) -> dict:
    return {
        "axis": None,
        "field": None,
        "position_snapped": None,
        "u0": None, "v0": None, "du": None, "dv": None,
        "nu": 0, "nv": 0, "n_cells": 0,
        "values_b64": "",
        "background": None,
        "scale": None,
        "colormap": "viridis_divergent",
        "warnings": warnings,
        "error": error,
    }
