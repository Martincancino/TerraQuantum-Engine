"""Borehole view service (Fase F4.4) — sondajes listos para el visor 3D.

Lee los sondajes persistidos por corrida (`boreholes.json`, guardados en
load-package) y los transforma al ESPACIO VISUAL de Three.js con EXACTAMENTE el
mismo centrado + flip-Y que los vóxeles y las isosuperficies, para que los
cilindros caigan donde está el cuerpo. El frontend NO calcula coordenadas ni física.

Cada intervalo de sondaje trae x_m (este), z_m (norte), y_from_m/y_to_m
(profundidad, + hacia abajo), y opcionalmente density_t_m3 / susceptibility_si /
lithology. Se devuelve además el contraste con signo (misma escala robusta que la
isosuperficie) para poder colorear por densidad con el MISMO Viridis divergente.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import polars as pl

from core.block_model_store import resolve_block_model_reference
from services.isosurface_service import _robust_background_scale

logger = logging.getLogger(__name__)

_BOREHOLES_FILENAME = "boreholes.json"


def _model_centers_and_contrast(parquet_path) -> tuple[tuple[float, float, float], float, float] | None:
    """(centers, background, scale) del block model, igual que el visor/isosuperficie.

    centers = (x_c, y_c, z_c) = (min+max)/2 de x_m/y_m/z_m (idéntico al transporte
    Arrow que carga el visor). background/scale = mediana + escala robusta de la
    densidad invertida (para colorear los sondajes con el mismo contraste).
    """
    df = pl.read_parquet(str(parquet_path))
    if len(df) == 0:
        return None

    def _coord(names: tuple[str, ...]) -> np.ndarray | None:
        for n in names:
            if n in df.columns:
                a = df[n].to_numpy().astype(np.float64)
                if np.isfinite(a).any():
                    return a
        return None

    xm = _coord(("x_m", "x"))
    ym = _coord(("y_m", "y"))
    zm = _coord(("z_m", "z"))
    if xm is None or ym is None or zm is None:
        return None

    centers = (
        (float(np.nanmin(xm)) + float(np.nanmax(xm))) / 2.0,
        (float(np.nanmin(ym)) + float(np.nanmax(ym))) / 2.0,
        (float(np.nanmin(zm)) + float(np.nanmax(zm))) / 2.0,
    )

    bg, scale = 0.0, 1.0
    if "density" in df.columns:
        dens = df["density"].to_numpy().astype(np.float64)
        dens = dens[np.isfinite(dens)]
        if dens.size:
            bg, scale = _robust_background_scale(dens)

    return centers, bg, scale


def build_borehole_view_response(project_id: str | None, run_id: str | None) -> dict:
    """Sondajes de la corrida en coordenadas del visor 3D.

    Returns dict serializable a JSON:
        intervals[]: cada uno con cx/cz (horizontal), cy_top/cy_bot (vertical,
            top = más somero), density_t_m3, susceptibility_si, lithology,
            signed_contrast (o None). Ya centrados + flip-Y (espacio Three.js).
        colormap, background, scale, n_intervals, warnings[], error?
    """
    warnings: list[str] = []

    try:
        ref = resolve_block_model_reference(project_id=project_id, run_id=run_id)
    except ValueError as exc:
        return _empty(str(exc), warnings)

    parquet_path = ref.path
    if not parquet_path.exists():
        return _empty(f"Archivo {parquet_path} no encontrado.", warnings)

    bh_path = parquet_path.parent / _BOREHOLES_FILENAME
    if not bh_path.exists():
        return _empty(
            "Esta corrida no tiene sondajes persistidos. Vuelve a cargar el paquete "
            "(los sondajes se guardan al cargar).",
            warnings,
        )

    try:
        raw_intervals = json.loads(bh_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _empty(f"No se pudo leer {_BOREHOLES_FILENAME}: {exc}", warnings)

    if not isinstance(raw_intervals, list) or not raw_intervals:
        return _empty("Sin intervalos de sondaje.", warnings)

    centers_contrast = _model_centers_and_contrast(parquet_path)
    if centers_contrast is None:
        return _empty("El block model no tiene coordenadas utilizables.", warnings)
    (x_c, y_c, z_c), bg, scale = centers_contrast

    intervals: list[dict] = []
    skipped = 0
    for it in raw_intervals:
        try:
            x_m = float(it["x_m"])
            z_m = float(it["z_m"])
            y_from = float(it["y_from_m"])
            y_to = float(it["y_to_m"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue

        density = it.get("density_t_m3")
        susceptibility = it.get("susceptibility_si")
        lithology = it.get("lithology")

        signed_contrast = None
        if density is not None:
            try:
                signed_contrast = round((float(density) - bg) / scale, 4)
            except (TypeError, ValueError, ZeroDivisionError):
                signed_contrast = None

        intervals.append({
            "cx": round(x_m - x_c, 3),
            "cz": round(z_m - z_c, 3),
            # top = más somero (profundidad menor) → Y visual mayor (flip).
            "cy_top": round(y_c - min(y_from, y_to), 3),
            "cy_bot": round(y_c - max(y_from, y_to), 3),
            "depth_from_m": round(min(y_from, y_to), 2),
            "depth_to_m": round(max(y_from, y_to), 2),
            "density_t_m3": round(float(density), 4) if density is not None else None,
            "susceptibility_si": round(float(susceptibility), 6) if susceptibility is not None else None,
            "lithology": str(lithology) if lithology is not None else None,
            "signed_contrast": signed_contrast,
        })

    if skipped:
        warnings.append(f"{skipped} intervalo(s) sin coordenadas válidas fueron omitidos.")

    if not intervals:
        return _empty("Ningún intervalo de sondaje tenía coordenadas válidas.", warnings)

    # Collares únicos (para etiquetas / marcadores en superficie).
    collars: list[dict] = []
    seen: set[tuple[float, float]] = set()
    for iv in intervals:
        key = (iv["cx"], iv["cz"])
        if key not in seen:
            seen.add(key)
            collars.append({"cx": iv["cx"], "cz": iv["cz"], "cy_top": iv["cy_top"]})

    return {
        "intervals": intervals,
        "collars": collars,
        "n_intervals": len(intervals),
        "n_holes": len(collars),
        "colormap": "viridis_divergent",
        "background": round(bg, 6),
        "scale": round(scale, 6),
        "warnings": warnings,
        "error": None,
    }


def _empty(error: str, warnings: list[str]) -> dict:
    return {
        "intervals": [],
        "collars": [],
        "n_intervals": 0,
        "n_holes": 0,
        "colormap": "viridis_divergent",
        "background": None,
        "scale": None,
        "warnings": warnings,
        "error": error,
    }
