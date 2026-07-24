# -*- coding: utf-8 -*-
"""Prior de profundidad para la inversión gravimétrica (constricción aditiva).

CONTEXTO MEDIDO (docs/05_RIGOR_FISICO_Y_RED_TEAM.md, Parte B, 2026-07-24):
la gravedad-sola es ambigua en profundidad y apila la masa SOMERA (error medido
~440 m para un cuerpo a 500 m). Un PRIOR de profundidad —prohibir contraste por
encima de un horizonte que una fuente INDEPENDIENTE indica— arregla esto de forma
medida: el error de profundidad cayó de 438 m a 62 m (7×) con un buen horizonte, y
hasta el horizontal mejoró (43→11 m).

Este servicio empaqueta ESE mecanismo. NO toca la física validada: construye una matriz
de anclaje (contrato existente `boreholes` de `solve_inversion_lsqr` /
`run_geophysics_inversion`) que ancla a densidad-base las celdas por encima del horizonte.

⚠ DE DÓNDE SACAR EL HORIZONTE (honestidad medida):
- Un **sondaje** que intersecta el cuerpo (lo clava exacto — pero solo donde perforas).
- Una **estimación independiente del usuario** (sísmica, pozo cercano, su interpretación).
- **Euler/espectral (F2B)**: CONFIABLE solo para fuentes SOMERAS-moderadas (0% error a
  150-200 m medido); SUBESTIMA fuertemente las profundas (midió 65-71 m para un cuerpo
  a 500 m). NO usar Euler como fuente automática en régimen profundo.

El servicio NO adivina el horizonte: se lo tiene que dar el caller, con su procedencia.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class DepthFloorPrior:
    anchor: np.ndarray            # (n, 5) [x_m, z_m, y_from_m, y_to_m, density_t_m3]
    depth_floor_m: float
    n_columns: int
    source: str                   # procedencia del horizonte (para el reporte honesto)
    note: str


def recommend_depth_floor(depth_to_source_m: float, *, safety_fraction: float = 0.7) -> float:
    """De una profundidad-a-fuente estimada, sugiere un horizonte CONSERVADOR (techo estimado).

    Se prohíbe la masa por encima de `safety_fraction · z` (no de `z` completa) para no
    forzar el cuerpo más profundo de lo que la evidencia soporta. safety_fraction<1 deja
    margen: si la estimación yerra un poco alto, el prior no corta el cuerpo real.
    """
    if depth_to_source_m is None or not np.isfinite(depth_to_source_m) or depth_to_source_m <= 0:
        raise ValueError(f"depth_to_source_m inválido: {depth_to_source_m}")
    if not (0.0 < safety_fraction <= 1.0):
        raise ValueError(f"safety_fraction debe estar en (0, 1]: {safety_fraction}")
    return float(safety_fraction) * float(depth_to_source_m)


def build_depth_floor_prior(
    x_c: np.ndarray,
    z_c: np.ndarray,
    base_density: float,
    depth_floor_m: float,
    *,
    source: str = "unspecified",
) -> Optional[DepthFloorPrior]:
    """Construye el prior 'no hay masa somera': ancla a densidad-base todas las celdas por
    ENCIMA de `depth_floor_m`, en cada columna (x,z) de la malla.

    Devuelve un `DepthFloorPrior` con la matriz lista para el parámetro `boreholes`, o None
    si el horizonte no restringe nada (≤ 0). El caller pasa `.anchor` a la inversión con
    `anchor_mode="hard"` (constricción firme) o "soft" (guía).

    Args:
        x_c, z_c: coordenadas horizontales de los centros de celda (grilla aplanada del motor).
        base_density: densidad de fondo (t/m³) — el contraste anclado es 0.
        depth_floor_m: horizonte; se prohíbe contraste a profundidad y < depth_floor_m.
        source: procedencia del horizonte (p.ej. "sondaje", "usuario", "euler_somero") — reporte.
    """
    if depth_floor_m is None or not np.isfinite(depth_floor_m) or depth_floor_m <= 0:
        return None
    x_c = np.asarray(x_c, dtype=np.float64)
    z_c = np.asarray(z_c, dtype=np.float64)
    if x_c.shape != z_c.shape or x_c.ndim != 1:
        raise ValueError("x_c y z_c deben ser vectores 1-D de la misma longitud (grilla aplanada).")
    cols = np.unique(np.column_stack([x_c, z_c]), axis=0)
    anchor = np.array(
        [[float(x), float(z), 0.0, float(depth_floor_m), float(base_density)] for x, z in cols],
        dtype=np.float64,
    )
    note = (
        f"Prior de profundidad: se prohíbe contraste por encima de {depth_floor_m:.0f} m "
        f"({cols.shape[0]} columnas ancladas a densidad base). Fuente del horizonte: {source}. "
        "Mecanismo medido (docs/05): baja el error de profundidad de la gravedad-sola. "
        "La calidad del resultado depende de la calidad del horizonte."
    )
    return DepthFloorPrior(anchor=anchor, depth_floor_m=float(depth_floor_m),
                           n_columns=int(cols.shape[0]), source=source, note=note)


def estimate_depth_prior_from_grid(
    field_grid_values: np.ndarray,
    x0: float, y0: float, dx: float, dy: float,
    mesh_x_c: np.ndarray,
    mesh_z_c: np.ndarray,
    base_density: float,
    *,
    spectral_correction: float = 1.15,
    safety_fraction: float = 0.7,
) -> Optional[DepthFloorPrior]:
    """Cadena AUTOMÁTICA (fuente medida como la mejor, Punto 1/2 de docs/05):
    grilla del campo → **espectro radial de potencia** (F2B, `radial_power_spectrum`) →
    profundidad de ensamble profundo → piso conservador → prior listo para `boreholes`.

    El espectro es la fuente CONFIABLE de profundidad profunda (Euler satura ~250 m). En la
    validación medida estimó 99/98/92% de la verdad a 300/500/700 m y bajó el error de
    profundidad de la gravedad 7-18×. Subestima ~15% → se corrige ×`spectral_correction`
    antes del margen de seguridad.

    OJO de muestreo (medido): el espectro necesita una grilla DENSA (≥ ~20×20 con señal);
    esto NO obliga a invertir con esa densidad — grillá denso para el espectro (FFT barata)
    e invertí con el survey normal (ancla dura, rápida). Devuelve None si el espectro no da
    profundidad utilizable (grilla chica, sin anomalía).
    """
    from services.potential_field_grid_service import ScatteredGrid
    from services.euler_spectral_service import radial_power_spectrum

    vals = np.asarray(field_grid_values, dtype=np.float64)
    if vals.ndim != 2:
        raise ValueError("field_grid_values debe ser una grilla 2-D (ny, nx).")
    ny, nx = vals.shape
    sg = ScatteredGrid(values=vals, x0=float(x0), y0=float(y0), dx=float(dx), dy=float(dy),
                       nx=nx, ny=ny, inside_hull=np.ones((ny, nx), dtype=bool))
    try:
        z_deep = radial_power_spectrum(sg).get("ensemble_depth_deep_m")
    except Exception:
        return None
    if z_deep is None or not np.isfinite(z_deep) or z_deep <= 0:
        return None
    floor = recommend_depth_floor(float(spectral_correction) * float(z_deep),
                                  safety_fraction=safety_fraction)
    return build_depth_floor_prior(mesh_x_c, mesh_z_c, base_density, floor,
                                   source=f"espectro_radial z_deep={z_deep:.0f}m")


def estimate_depth_prior_from_stations(
    x_m: np.ndarray,
    z_m: np.ndarray,
    g_values: np.ndarray,
    mesh_x_c: np.ndarray,
    mesh_z_c: np.ndarray,
    base_density: float,
    *,
    target_nx: int = 128,
    spectral_correction: float = 1.15,
    safety_fraction: float = 0.7,
) -> Optional[DepthFloorPrior]:
    """Igual que `estimate_depth_prior_from_grid` pero desde estaciones DISPERSAS: primero
    grilla (`grid_scattered`, interpolación densa para el espectro) y luego estima el prior.
    Es el punto de entrada para el flujo de producción (survey de campo → prior).
    Devuelve None si el survey no permite grillar/estimar (nunca lanza)."""
    from services.potential_field_grid_service import grid_scattered

    try:
        sg = grid_scattered(np.asarray(x_m, dtype=np.float64), np.asarray(z_m, dtype=np.float64),
                            np.asarray(g_values, dtype=np.float64), target_nx=target_nx)
    except Exception:
        return None
    return estimate_depth_prior_from_grid(
        sg.values, sg.x0, sg.y0, sg.dx, sg.dy, mesh_x_c, mesh_z_c, base_density,
        spectral_correction=spectral_correction, safety_fraction=safety_fraction)
