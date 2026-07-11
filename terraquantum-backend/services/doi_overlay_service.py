"""DOI overlay service (Fase F4.5) — el horizonte de sensibilidad para el visor 3D.

"Incertidumbre visible": bajo cierta profundidad el dato deja de restringir el
modelo (la sensibilidad cae) y lo que se ve ahí es null-space, no información.
Este servicio calcula ese horizonte y lo entrega en COORDENADAS VISUALES del
visor (mismo centrado + flip-Y que vóxeles/isosuperficies/sondajes) para que el
frontend dibuje un plano/velo de atenuación SIN calcular física.

Métodos (misma convención que el B2 depth-resolution ya validado):
  1. `sensitivity_doi_half_max_layer` (preferido): capa más profunda cuya
     sensibilidad media por capa ≥ 50% del pico de capa (columna
     `sensitivity_proxy` que persiste el solver mono-física).
  2. `doi_index_threshold` (respaldo): doi_index/doi_raw de Li & Oldenburg
     (|m1−m2| normalizado entre dos corridas de referencia): capa más profunda
     con mediana ≤ 0.4 (bajo = bien restringido).
  3. Sin columnas → error catalogado (las corridas JOINT no persisten
     sensibilidad por celda hoy; se cablea en F5 — deuda registrada).
"""

from __future__ import annotations

import logging

import numpy as np
import polars as pl

from core.block_model_store import resolve_block_model_reference
from services.isosurface_service import _axis_coords

logger = logging.getLogger(__name__)

# doi_index bajo = bien restringido. 0.4 = límite superior del rango de corte
# sugerido por Li & Oldenburg (0.1–0.4); conservador hacia mostrar MÁS incertidumbre.
_DOI_INDEX_CUTOFF = 0.4


def build_doi_overlay_response(project_id: str | None, run_id: str | None) -> dict:
    """Horizonte DOI de la corrida, listo para dibujar.

    Returns dict JSON-serializable:
        cy_horizon: Y visual del horizonte (bajo esto = null-space),
        depth_m: profundidad del horizonte en metros (+ hacia abajo),
        method, cells_below_fraction, extent (bounds visuales del modelo),
        warnings[], error?
    """
    warnings: list[str] = []

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

    ok = np.isfinite(xm) & np.isfinite(ym) & np.isfinite(zm)
    if not ok.any():
        return _empty("El block model no tiene coordenadas finitas.", warnings)
    xm, ym, zm = xm[ok], ym[ok], zm[ok]

    # y_m = profundidad (+ hacia abajo); capas = valores únicos de profundidad.
    depths = np.round(ym, 3)
    layers = np.unique(depths)
    if layers.size < 2:
        return _empty("El modelo tiene una sola capa de profundidad.", warnings)

    horizon_depth: float | None = None
    method: str | None = None

    # ── Método 1: sensibilidad por celda (mismo half-max de capa que B2). ──────
    if "sensitivity_proxy" in df.columns:
        sens = df["sensitivity_proxy"].to_numpy().astype(np.float64)[ok]
        sens = np.clip(np.nan_to_num(sens, nan=0.0), 0.0, None)
        if float(np.max(sens)) > 0.0:
            layer_mean = np.array([float(sens[depths == d].mean()) for d in layers])
            peak = float(layer_mean.max())
            if peak > 0.0:
                good = layers[layer_mean >= 0.5 * peak]
                horizon_depth = float(good.max()) if good.size else float(layers.min())
                method = "sensitivity_doi_half_max_layer"

    # ── Método 2 (respaldo): doi_index de Li & Oldenburg. ──────────────────────
    if horizon_depth is None:
        doi_col = next((c for c in ("doi_index", "doi_raw") if c in df.columns), None)
        if doi_col is not None:
            doi = df[doi_col].to_numpy().astype(np.float64)[ok]
            finite_doi = np.isfinite(doi)
            if finite_doi.any():
                layer_med = np.array([
                    float(np.nanmedian(doi[(depths == d) & finite_doi]))
                    if np.any((depths == d) & finite_doi) else np.nan
                    for d in layers
                ])
                good = layers[np.nan_to_num(layer_med, nan=np.inf) <= _DOI_INDEX_CUTOFF]
                if good.size:
                    horizon_depth = float(good.max())
                    method = "doi_index_threshold"

    if horizon_depth is None:
        return _empty(
            "Esta corrida no trae sensibilidad ni doi_index por celda "
            "(las corridas joint los incorporan en F5). El horizonte DOI "
            "no puede dibujarse sin ese dato — no se estima.",
            warnings,
        )

    # Transformación al espacio visual (idéntica a vóxeles/isosuperficie/sondajes).
    x_c = (float(np.min(xm)) + float(np.max(xm))) / 2.0
    y_c = (float(np.min(ym)) + float(np.max(ym))) / 2.0
    z_c = (float(np.min(zm)) + float(np.max(zm))) / 2.0

    cy_horizon = y_c - horizon_depth
    below = depths > horizon_depth
    cells_below_fraction = float(below.mean())

    return {
        "cy_horizon": round(cy_horizon, 3),
        "depth_m": round(horizon_depth, 2),
        "method": method,
        "cells_below_fraction": round(cells_below_fraction, 4),
        "extent": {
            "cx_min": round(float(np.min(xm)) - x_c, 3),
            "cx_max": round(float(np.max(xm)) - x_c, 3),
            "cz_min": round(float(np.min(zm)) - z_c, 3),
            "cz_max": round(float(np.max(zm)) - z_c, 3),
            "cy_min": round(y_c - float(np.max(ym)), 3),  # fondo del modelo (visual)
            "cy_max": round(y_c - float(np.min(ym)), 3),  # techo del modelo (visual)
        },
        "warnings": warnings,
        "error": None,
    }


def _empty(error: str, warnings: list[str]) -> dict:
    return {
        "cy_horizon": None,
        "depth_m": None,
        "method": None,
        "cells_below_fraction": None,
        "extent": None,
        "warnings": warnings,
        "error": error,
    }
