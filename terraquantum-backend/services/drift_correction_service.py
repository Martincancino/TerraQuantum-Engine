"""F2B — Corrección de DERIVA instrumental por cierres a estación base.

El gravímetro de resorte deriva (mGal/día). El procedimiento de campo
estándar: abrir y cerrar el loop re-ocupando la estación BASE; la diferencia
entre lecturas de base sucesivas (ya corregidas por marea) ES la deriva, y se
interpola al tiempo de cada estación.

Dos modelos (elección del usuario, documentada en el reporte):
  - "linear":    ajuste por mínimos cuadrados sobre TODAS las ocupaciones de
                 base → tasa única k [mGal/día]. Robusto con pocas bases.
  - "piecewise": interpolación lineal entre ocupaciones consecutivas de base
                 (deriva por tramos). Exacta en cada cierre; requiere que las
                 estaciones estén dentro de la ventana de bases (fuera de
                 ella se sostiene el valor extremo CON AVISO).

Convención: corrected = reading − drift(t), con drift anclada en 0 en la
PRIMERA ocupación de base (la base define el datum relativo del loop).
ORDEN de reducción de campo: marea PRIMERO (earth_tide_service), deriva
después — la deriva se estima sobre lecturas ya libres de marea.

Guardarraíles (nunca adivinar): <2 ocupaciones de base → no se corrige
(pregunta needs_context aguas arriba); tiempos no crecientes → error claro;
todo-base o ninguna-estación → error claro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence

import numpy as np

from core.logging import get_logger

_log = get_logger(__name__)

VALID_METHODS = ("linear", "piecewise")


class DriftInputError(ValueError):
    """Input insuficiente/inconsistente para corregir deriva (mensaje ES claro)."""


@dataclass
class DriftResult:
    corrected_mgal: np.ndarray
    drift_at_station_mgal: np.ndarray
    method: str = "linear"
    n_base_occupations: int = 0
    drift_rate_mgal_per_day: Optional[float] = None
    closure_mgal: Optional[float] = None          # deriva total primer→último cierre
    base_residuals_mgal: List[float] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "method": self.method,
            "n_base_occupations": self.n_base_occupations,
            "drift_rate_mgal_per_day": self.drift_rate_mgal_per_day,
            "closure_mgal": self.closure_mgal,
            "base_residuals_mgal": [round(float(r), 5) for r in self.base_residuals_mgal],
            "warnings": list(self.warnings),
        }


def suggest_base_station(station_ids: Sequence[str]) -> "tuple[str, int] | None":
    """Candidata a estación BASE: el id repetido con más ocupaciones.

    Para el patrón needs_context: se SUGIERE con evidencia (n ocupaciones) y
    el usuario confirma — jamás se asume en silencio. None si ningún id se
    repite (no hay cierres → no hay corrección de deriva posible).
    """
    counts: dict = {}
    for sid in station_ids:
        key = str(sid).strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    repeated = {k: n for k, n in counts.items() if n >= 2}
    if not repeated:
        return None
    best = max(repeated.items(), key=lambda kv: kv[1])
    return best[0], best[1]


def correct_drift(
    times_utc: Sequence[datetime],
    readings_mgal: Sequence[float],
    is_base: Sequence[bool],
    method: str = "linear",
) -> DriftResult:
    """Corrige deriva instrumental usando las ocupaciones de base.

    `times_utc`, `readings_mgal`, `is_base` son paralelos (una fila por
    lectura, INCLUIDAS las ocupaciones de base). Devuelve las lecturas
    corregidas (las bases quedan ~constantes) + reporte auditable.
    """
    if method not in VALID_METHODS:
        raise DriftInputError(
            f"Método de deriva desconocido: '{method}'. Use 'linear' (tasa única "
            "por mínimos cuadrados) o 'piecewise' (interpolación entre cierres)."
        )
    t = list(times_utc)
    g = np.asarray(readings_mgal, dtype=float)
    base_mask = np.asarray(is_base, dtype=bool)
    if not (len(t) == len(g) == len(base_mask)):
        raise DriftInputError(
            "times/readings/is_base deben tener el mismo largo (una fila por lectura)."
        )
    if len(t) == 0:
        raise DriftInputError("No hay lecturas para corregir.")

    t0 = t[0]
    hours = np.array([(ti - t0).total_seconds() / 3600.0 for ti in t], dtype=float)
    if np.any(np.diff(hours) < 0):
        raise DriftInputError(
            "Los tiempos del survey no son crecientes: ordene el archivo por "
            "hora de lectura antes de corregir deriva (la deriva es función del tiempo)."
        )

    n_base = int(base_mask.sum())
    if n_base < 2:
        raise DriftInputError(
            f"Se necesitan ≥2 ocupaciones de la estación base para medir la deriva "
            f"(hay {n_base}). Marque qué filas son re-ocupaciones de base, o "
            "agregue los cierres de loop al archivo."
        )
    if n_base == len(g):
        raise DriftInputError(
            "Todas las filas son ocupaciones de base: no hay estaciones que corregir."
        )

    warnings: List[str] = []
    tb = hours[base_mask]
    gb = g[base_mask]
    # Deviación de la base respecto de su PRIMERA ocupación = deriva observada.
    dev = gb - gb[0]
    closure = float(dev[-1])

    if method == "linear":
        # Mínimos cuadrados por el origen anclado en la primera base:
        # drift(t) = k · (t − t_base0). k en mGal/h → reporte en mGal/día.
        tt = tb - tb[0]
        denom = float(np.dot(tt, tt))
        k = float(np.dot(tt, dev) / denom) if denom > 0 else 0.0
        drift = k * (hours - tb[0])
        rate_per_day = k * 24.0
        residuals = dev - k * tt
    else:  # piecewise
        drift = np.interp(hours, tb, dev)
        rate_per_day = (closure / (tb[-1] - tb[0]) * 24.0) if tb[-1] > tb[0] else 0.0
        residuals = np.zeros_like(dev)   # exacta en cada cierre por construcción
        out_lo = hours < tb[0]
        out_hi = hours > tb[-1]
        n_out = int(out_lo.sum() + out_hi.sum())
        if n_out:
            warnings.append(
                f"{n_out} lectura(s) fuera de la ventana de cierres de base "
                f"[{tb[0]:.2f} h, {tb[-1]:.2f} h]: se sostuvo la deriva del cierre "
                "más cercano (extrapolación plana). Ideal: abrir y cerrar el loop "
                "en base."
            )

    if abs(rate_per_day) > 5.0:
        warnings.append(
            f"Tasa de deriva inusualmente alta ({rate_per_day:+.2f} mGal/día; lo "
            "típico es <1 mGal/día en gravímetros modernos): verifique que la "
            "columna de gravedad esté en mGal y que las filas de base sean "
            "realmente re-ocupaciones del mismo punto."
        )

    corrected = g - drift
    _log.info(
        "drift_corrected", method=method, n_base=n_base,
        rate_mgal_day=round(rate_per_day, 4), closure_mgal=round(closure, 4),
    )
    return DriftResult(
        corrected_mgal=corrected,
        drift_at_station_mgal=drift,
        method=method,
        n_base_occupations=n_base,
        drift_rate_mgal_per_day=float(rate_per_day),
        closure_mgal=closure,
        base_residuals_mgal=[float(r) for r in residuals],
        warnings=warnings,
    )
