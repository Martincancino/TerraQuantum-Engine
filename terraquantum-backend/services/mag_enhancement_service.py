"""F2B — Suite de REALCE magnético de gabinete (FFT sobre grilla, numpy puro).

Los 4+2 productos estándar con los que el consultor ve estructura:
  - Corrección DIURNA desde estación base magnética (serie temporal).
  - RTP (reducción al polo) con inc/dec del survey; en latitudes magnéticas
    bajas es INESTABLE → se estabiliza acotando el filtro y se ADVIERTE
    ofreciendo el tilt como alternativa estable (regla del plan: decirlo).
  - Derivadas: 1VD (primera vertical), THD (horizontal total), TILT,
    SEÑAL ANALÍTICA |AS| — todas en el dominio del número de onda.
  - Continuación ascendente (separar fuentes someras/profundas) — reusa
    potential_field_grid_service.

Convenciones (x=este, y=norte, z hacia ABAJO — la del dominio):
  - D (declinación) medida desde el NORTE hacia el ESTE.
  - El vector unitario del campo: f = (cosI·sinD, cosI·cosD, sinI).

Oráculos en tests (independientes del motor): dipolo puntual TMI de forma
CERRADA implementado en el test (μ0/4π…), armónicos exactos para 1VD/THD, y
la propiedad física del |AS| (pico sobre la fuente).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.logging import get_logger
from services.potential_field_grid_service import (
    ScatteredGrid,
    apply_fft_filter,
    grid_scattered,
    upward_continue_grid,
)

_log = get_logger(__name__)

VALID_PRODUCTS = ("rtp", "vd1", "thd", "tilt", "analytic_signal", "upward_continuation")

# |I| bajo este umbral el operador RTP amplifica sin control ciertas
# direcciones → advertir y ofrecer tilt (estable por construcción).
RTP_LOW_LAT_DEG = 15.0
# Cota de amplitud del filtro RTP (estabilización estándar, documentada).
RTP_MAX_GAIN = 20.0


class MagEnhancementError(ValueError):
    """Input inválido para el realce magnético (mensaje ES accionable)."""


# ─────────────────────────────────────────────────────────────────────────────
# Corrección diurna desde estación base
# ─────────────────────────────────────────────────────────────────────────────
def correct_diurnal(
    survey_times: Sequence[datetime],
    survey_nt: np.ndarray,
    base_times: Sequence[datetime],
    base_nt: np.ndarray,
) -> "Tuple[np.ndarray, dict]":
    """Resta la variación temporal medida en la base magnética.

    corrected = survey − (base(t_survey) − mediana(base)). Interpolación
    lineal en el tiempo; fuera de la ventana de la base se sostiene el
    extremo CON AVISO. <2 lecturas de base → error claro.
    """
    if len(base_times) < 2:
        raise MagEnhancementError(
            f"La corrección diurna necesita ≥2 lecturas de la base magnética "
            f"(hay {len(base_times)}); suba el archivo de la estación base."
        )
    bt = np.array([t.timestamp() for t in base_times], dtype=float)
    order = np.argsort(bt, kind="stable")
    bt = bt[order]
    bv = np.asarray(base_nt, dtype=float)[order]
    st = np.array([t.timestamp() for t in survey_times], dtype=float)

    ref = float(np.median(bv))
    variation = np.interp(st, bt, bv) - ref
    corrected = np.asarray(survey_nt, dtype=float) - variation

    meta = {
        "base_reference_nt": ref,
        "variation_min_nt": float(variation.min()),
        "variation_max_nt": float(variation.max()),
        "n_base_readings": int(len(bv)),
        "warnings": [],
    }
    n_out = int(((st < bt[0]) | (st > bt[-1])).sum())
    if n_out:
        meta["warnings"].append(
            f"{n_out} lectura(s) del survey fuera de la ventana temporal de la "
            "base magnética: se sostuvo la variación del extremo más cercano."
        )
    return corrected, meta


# ─────────────────────────────────────────────────────────────────────────────
# Operadores en número de onda
# ─────────────────────────────────────────────────────────────────────────────
def _direction_factor(KX, KY, K, inc_deg: float, dec_deg: float):
    """Θ(k) del vector (I,D): sinI + i·(kx·cosI·sinD + ky·cosI·cosD)/|k|."""
    inc = np.radians(inc_deg)
    dec = np.radians(dec_deg)
    with np.errstate(divide="ignore", invalid="ignore"):
        proj = np.where(K > 0, (KX * np.sin(dec) + KY * np.cos(dec)) / K, 0.0)
    return np.sin(inc) + 1j * np.cos(inc) * proj


def reduce_to_pole(
    grid: np.ndarray, dx: float, dy: float, inc_deg: float, dec_deg: float
) -> "Tuple[np.ndarray, List[str]]":
    """RTP clásico (magnetización paralela al campo): filtro 1/Θ².

    Estabilizado acotando |filtro| ≤ RTP_MAX_GAIN (evita la explosión de
    azimutes cercanos al ecuador magnético). En |I| < RTP_LOW_LAT_DEG se
    ADVIERTE que el resultado es poco confiable y que el TILT es la
    alternativa estable — nunca se falla en silencio.
    """
    warnings: List[str] = []
    if abs(inc_deg) < RTP_LOW_LAT_DEG:
        warnings.append(
            f"RTP en latitud magnética baja (|I|={abs(inc_deg):.1f}° < "
            f"{RTP_LOW_LAT_DEG:.0f}°): el operador es inestable y el mapa RTP "
            "puede tener rayas direccionales. Use el TILT (estable por "
            "construcción) como mapa primario de estructura."
        )

    def _factor(KX, KY, K):
        theta = _direction_factor(KX, KY, K, inc_deg, dec_deg)
        theta2 = theta * theta
        f = np.where(np.abs(theta2) > 0, 1.0 / theta2, 0.0)
        mag = np.abs(f)
        f = np.where(mag > RTP_MAX_GAIN, f * (RTP_MAX_GAIN / mag), f)
        return np.where(K > 0, f, 1.0)   # DC intacto

    return apply_fft_filter(grid, dx, dy, _factor), warnings


def first_vertical_derivative(grid: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """1VD: factor |k| exacto de teoría de potencial (nT/m)."""
    return apply_fft_filter(grid, dx, dy, lambda KX, KY, K: K)


def horizontal_derivatives(
    grid: np.ndarray, dx: float, dy: float
) -> "Tuple[np.ndarray, np.ndarray]":
    gx = apply_fft_filter(grid, dx, dy, lambda KX, KY, K: 1j * KX)
    gy = apply_fft_filter(grid, dx, dy, lambda KX, KY, K: 1j * KY)
    return gx, gy


def total_horizontal_derivative(grid: np.ndarray, dx: float, dy: float) -> np.ndarray:
    gx, gy = horizontal_derivatives(grid, dx, dy)
    return np.hypot(gx, gy)


def tilt_derivative(grid: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """TILT = atan(1VD / THD) ∈ [−π/2, π/2]: autonormalizado y estable a
    cualquier latitud (por eso es la alternativa al RTP ecuatorial)."""
    vd = first_vertical_derivative(grid, dx, dy)
    thd = total_horizontal_derivative(grid, dx, dy)
    return np.arctan2(vd, thd + 1e-30)

def analytic_signal(grid: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """|AS| = √(∂x² + ∂y² + ∂z²): su máximo se centra sobre la fuente."""
    gx, gy = horizontal_derivatives(grid, dx, dy)
    gz = first_vertical_derivative(grid, dx, dy)
    return np.sqrt(gx * gx + gy * gy + gz * gz)


# ─────────────────────────────────────────────────────────────────────────────
# Suite completa sobre estaciones dispersas
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MagSuiteResult:
    grid: ScatteredGrid                      # TMI grillada (post-diurna si hubo)
    products: Dict[str, np.ndarray] = field(default_factory=dict)
    report: dict = field(default_factory=dict)


def run_mag_enhancement(
    x_m: np.ndarray,
    y_m: np.ndarray,
    tmi_nt: np.ndarray,
    products: Sequence[str],
    inc_deg: float = -30.0,
    dec_deg: float = 0.0,
    uc_height_m: float = 500.0,
    survey_times: "Optional[Sequence[datetime]]" = None,
    base_times: "Optional[Sequence[datetime]]" = None,
    base_nt: "Optional[np.ndarray]" = None,
) -> MagSuiteResult:
    """Corre los productos pedidos sobre la TMI dispersa (grilla adentro)."""
    unknown = [p for p in products if p not in VALID_PRODUCTS]
    if unknown:
        raise MagEnhancementError(
            f"Producto(s) desconocido(s): {unknown}. Válidos: {list(VALID_PRODUCTS)}."
        )

    tmi = np.asarray(tmi_nt, dtype=float)
    report: dict = {"products": list(products), "warnings": []}

    if base_times is not None and base_nt is not None and survey_times is not None:
        tmi, dmeta = correct_diurnal(survey_times, tmi, base_times, base_nt)
        report["diurnal"] = {k: v for k, v in dmeta.items() if k != "warnings"}
        report["warnings"].extend(dmeta["warnings"])
        report["diurnal_applied"] = True

    sg = grid_scattered(x_m, y_m, tmi)
    report["grid"] = sg.meta()
    report["warnings"].extend(sg.warnings)

    out: Dict[str, np.ndarray] = {}
    for p in products:
        if p == "rtp":
            out[p], w = reduce_to_pole(sg.values, sg.dx, sg.dy, inc_deg, dec_deg)
            report["warnings"].extend(w)
        elif p == "vd1":
            out[p] = first_vertical_derivative(sg.values, sg.dx, sg.dy)
        elif p == "thd":
            out[p] = total_horizontal_derivative(sg.values, sg.dx, sg.dy)
        elif p == "tilt":
            out[p] = tilt_derivative(sg.values, sg.dx, sg.dy)
        elif p == "analytic_signal":
            out[p] = analytic_signal(sg.values, sg.dx, sg.dy)
        elif p == "upward_continuation":
            out[p] = upward_continue_grid(sg.values, sg.dx, sg.dy, uc_height_m)
            report["uc_height_m"] = float(uc_height_m)

    _log.info("mag_enhancement", products=list(products), nx=sg.nx, ny=sg.ny)
    return MagSuiteResult(grid=sg, products=out, report=report)
