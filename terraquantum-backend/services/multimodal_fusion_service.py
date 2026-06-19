"""FASE 21 — Multimodal Fusion Strategy.

Define CÓMO combinar gravimetría + magnetometría + sondajes SIN conflictos, y
adjunta a cada combinación una métrica honesta de confianza y error de profundidad.

Este módulo NO ejecuta física ni inversión: es la capa de DECISIÓN que precede a
los solvers (gravimetry / magnetometry / joint_inversion). Toma banderas de
disponibilidad de datos + señales de calidad ya calculadas (Fase 19) y devuelve
un plan (`MultimodalPlan`) con:
  • route          — qué solver corresponde
  • confidence     — confianza base del combo, ajustada por calidad de datos
  • error_depth_m  — error de profundidad esperado (heurística por combo)
  • weighting      — recetas de sigma por modalidad (robusto, R-04 / Fase 18)
  • conflict       — clasificador de desacuerdo densidad modelo↔sondaje

El ruteo aquí REPLICA la decisión real que toma `run_geophysics_inversion`
(magnetic_nt + g≠0 → joint; magnetic_nt + g=0 → magnético; sin magnetic_nt →
gravedad). El plan es metadato que acompaña al resultado; no cambia el flujo.

Referencias de los números base: calibración interna de combos del roadmap
industrial (Fases 19–29). Son heurísticas honestas, no garantías; se refinan con
la validación de campo (Fase 25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

# ── Nombres de ruta (estables; el frontend los consume) ────────────────────────
ROUTE_GRAVITY_ONLY = "gravity_only"
ROUTE_MAGNETIC_ONLY = "magnetic_only"
ROUTE_JOINT = "gravity_magnetic_joint"
ROUTE_GRAVITY_BOREHOLE = "gravity_with_constraints"
ROUTE_JOINT_BOREHOLE = "joint_with_constraints"

# Mínimo de sensores para que una inversión potencial tenga sentido (decisión de
# ruteo, NO un límite del solver — el solver exige ≥10 observaciones por schema).
MIN_SENSORS_FOR_INVERSION = 5

# Confianza BASE por combinación (fracción 0–1). Más modalidades independientes →
# menos ambigüedad → más confianza. Sondajes anclan densidad directa → el mayor
# salto. Magnética sola es la más ambigua (susceptibilidad ↔ geometría).
_BASE_CONFIDENCE = {
    ROUTE_GRAVITY_ONLY: 0.65,
    ROUTE_MAGNETIC_ONLY: 0.55,
    ROUTE_JOINT: 0.80,
    ROUTE_GRAVITY_BOREHOLE: 0.85,
    ROUTE_JOINT_BOREHOLE: 0.90,
}

# Prioridad de resolución de conflictos: el dato más directo gana. Un sondaje mide
# densidad in-situ; la gravimetría la infiere; la magnetometría ni siquiera mide
# densidad. Ante contradicción, se confía en este orden.
CONFLICT_RESOLUTION_PRIORITY = ("borehole", "gravity", "magnetic")

# Umbrales del clasificador de conflicto densidad (t/m³). Consistentes con
# borehole_service.detect_borehole_conflicts (Fase 20).
_CONFLICT_WARN_T_M3 = 0.2
_CONFLICT_FLAG_T_M3 = 0.5

# Incertidumbre intrínseca de muestreo de un sondaje (15% de la densidad medida)
# cuando NO hay réplicas para estimar dispersión empírica.
_BOREHOLE_REL_UNCERTAINTY = 0.15


# Fase 23: la jerarquía de errores vive en core.errors. Se re-exporta aquí para
# no romper imports existentes (`from services.multimodal_fusion_service import
# InsufficientDataError`). Sigue siendo ValueError + TerraquantumError y acepta
# tanto un código del catálogo como un mensaje literal (backward-compat).
from core.errors import InsufficientDataError  # noqa: E402,F401  (re-export)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


@dataclass
class MultimodalPlan:
    """Plan de fusión: ruta elegida + confianza + error esperado + avisos."""

    route: str
    has_gravity: bool
    has_magnetic: bool
    has_borehole: bool
    n_sensors: int
    base_confidence: float          # 0–1, sólo por combo
    confidence: float               # 0–1, ajustada por calidad de datos
    error_depth_m: float            # error de profundidad esperado (m)
    coverage_pct: float             # 0–1, fracción de área cubierta usada
    data_quality: Optional[float]   # 0–100 (Fase 19) o None si no disponible
    resolution_priority: tuple = CONFLICT_RESOLUTION_PRIORITY
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "route": self.route,
            "has_gravity": self.has_gravity,
            "has_magnetic": self.has_magnetic,
            "has_borehole": self.has_borehole,
            "n_sensors": self.n_sensors,
            "base_confidence": round(self.base_confidence, 3),
            "confidence": round(self.confidence, 3),
            "confidence_pct": round(self.confidence * 100.0, 1),
            "error_depth_m": round(self.error_depth_m, 1),
            "coverage_pct": round(self.coverage_pct, 3),
            "data_quality": self.data_quality,
            "resolution_priority": list(self.resolution_priority),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


def select_route(
    has_gravity: bool,
    has_magnetic: bool,
    has_borehole: bool,
    n_sensors: int,
) -> str:
    """Árbol de decisión: combinación de datos → ruta de solver.

    Reglas (roadmap Fase 21):
      - sin gravedad NI magnetismo               → InsufficientDataError
      - con potencial pero < MIN_SENSORS         → InsufficientDataError
      - g solo                                   → gravity_only
      - m solo                                   → magnetic_only
      - g + m                                    → joint
      - g + sondaje                              → gravity_with_constraints
      - g + m + sondaje                          → joint_with_constraints
      - m + sondaje (sin g): el sondaje de DENSIDAD no restringe una inversión
        magnética pura → se rutea a magnetic_only con aviso (no se descarta el dato).
    """
    if not (has_gravity or has_magnetic):
        raise InsufficientDataError(
            "Se necesita al menos un campo potencial: gravimetría O magnetometría. "
            "Un CSV de sólo sondajes no define una inversión por sí mismo; cárgalo "
            "junto con gravimetría para usarlo como restricción."
        )
    if n_sensors < MIN_SENSORS_FOR_INVERSION:
        raise InsufficientDataError(
            f"Se necesitan ≥{MIN_SENSORS_FOR_INVERSION} sensores para invertir; "
            f"recibí {n_sensors}. Con tan pocos puntos la geometría 3D es "
            "irresoluble (sistema fuertemente subdeterminado)."
        )

    if has_gravity and has_magnetic and has_borehole:
        return ROUTE_JOINT_BOREHOLE
    if has_gravity and has_magnetic:
        return ROUTE_JOINT
    if has_gravity and has_borehole:
        return ROUTE_GRAVITY_BOREHOLE
    if has_gravity:
        return ROUTE_GRAVITY_ONLY
    # Sólo magnetismo (con o sin sondaje de densidad).
    return ROUTE_MAGNETIC_ONLY


def compute_confidence(
    route: str,
    data_quality: Optional[float] = None,
) -> float:
    """Confianza ajustada = confianza_base(combo) · (data_quality / 100).

    data_quality es el score 0–100 de Fase 19. Si es None, se devuelve la
    confianza base sin penalizar (no inventamos calidad que no medimos).
    """
    base = _BASE_CONFIDENCE.get(route)
    if base is None:
        raise ValueError(f"Ruta desconocida para confianza: {route!r}")
    if data_quality is None:
        return base
    return _clamp01(base * (_clamp01(data_quality / 100.0)))


def estimate_error_depth(
    route: str,
    coverage_pct: float = 1.0,
    confidence: Optional[float] = None,
) -> float:
    """Error de profundidad esperado (m), heurística por combo (roadmap Fase 21).

    Combos sin sondaje escalan con la cobertura espacial (huecos → más error).
    Combos con sondaje escalan con la confianza (más confianza → menos error),
    porque el ancla in-situ ya fija la profundidad localmente.
    """
    cov = _clamp01(coverage_pct)
    conf = _clamp01(confidence if confidence is not None else 1.0)
    gap = 1.0 - cov
    cgap = 1.0 - conf

    if route == ROUTE_GRAVITY_ONLY:
        return 30.0 + 10.0 * gap
    if route == ROUTE_MAGNETIC_ONLY:
        return 40.0 + 15.0 * gap
    if route == ROUTE_JOINT:
        return 20.0 + 5.0 * gap
    if route == ROUTE_GRAVITY_BOREHOLE:
        return 15.0 + 3.0 * cgap
    if route == ROUTE_JOINT_BOREHOLE:
        return 10.0 + 2.0 * cgap
    raise ValueError(f"Ruta desconocida para error de profundidad: {route!r}")


def plan_multimodal(
    has_gravity: bool,
    has_magnetic: bool,
    has_borehole: bool,
    n_sensors: int,
    data_quality: Optional[float] = None,
    coverage_pct: float = 1.0,
) -> MultimodalPlan:
    """Combina ruteo + confianza + error de profundidad en un único plan."""
    route = select_route(has_gravity, has_magnetic, has_borehole, n_sensors)
    confidence = compute_confidence(route, data_quality=data_quality)
    error_depth = estimate_error_depth(route, coverage_pct=coverage_pct, confidence=confidence)

    warnings: list = []
    notes: list = []
    if has_borehole and not has_gravity:
        warnings.append(
            "Hay sondajes de densidad pero no gravimetría: la densidad medida no "
            "restringe una inversión magnética pura → se ignora como ancla. Carga "
            "gravimetría para aprovechar los sondajes."
        )
    if data_quality is None:
        notes.append("Confianza sin ajustar por calidad de datos (data_quality no provisto).")
    elif data_quality < 60.0:
        warnings.append(
            f"Calidad de datos baja ({data_quality:.0f}/100): el modelo será menos "
            "confiable. Revisa cobertura, ruido y outliers del CSV."
        )

    return MultimodalPlan(
        route=route,
        has_gravity=has_gravity,
        has_magnetic=has_magnetic,
        has_borehole=has_borehole,
        n_sensors=n_sensors,
        base_confidence=_BASE_CONFIDENCE[route],
        confidence=confidence,
        error_depth_m=error_depth,
        coverage_pct=_clamp01(coverage_pct),
        data_quality=data_quality,
        warnings=warnings,
        notes=notes,
    )


def classify_density_conflict(diff_t_m3: float) -> tuple:
    """Clasifica un desacuerdo de densidad (modelo − sondaje), en t/m³.

    |Δ| < 0.2        → ("OK", ...)        acuerdo
    0.2 ≤ |Δ| < 0.5  → ("WARNING", ...)   puede ser heterogeneidad local
    |Δ| ≥ 0.5        → ("FLAG", ...)      conflicto: revisar datos

    Devuelve (status, message). El llamador decide qué prioridad aplica
    (ver CONFLICT_RESOLUTION_PRIORITY: sondaje > gravimetría > magnetismo).
    """
    a = abs(float(diff_t_m3))
    if a < _CONFLICT_WARN_T_M3:
        return ("OK", f"Acuerdo: |Δρ|={a:.2f} t/m³ < {_CONFLICT_WARN_T_M3} t/m³.")
    if a < _CONFLICT_FLAG_T_M3:
        return (
            "WARNING",
            f"Desacuerdo menor: |Δρ|={a:.2f} t/m³. Puede ser heterogeneidad local; "
            "el ancla del sondaje es soft y el solver pudo apartarse.",
        )
    return (
        "FLAG",
        f"Conflicto: |Δρ|={a:.2f} t/m³ ≥ {_CONFLICT_FLAG_T_M3} t/m³. Revisa las "
        "muestras del sondaje o los datos gravimétricos (prioridad: sondaje > gravimetría).",
    )


def gravity_sigma(g_obs: Sequence[float], robust: bool = True) -> np.ndarray:
    """Sigma de pesado gravimétrico (R-04 / Fase 18), robusto a outliers MAD.

    Reutiliza el estimador validado del motor gravimétrico; no reimplementa física.
    """
    from exploration.gravimetry import _sigma_adaptive

    sigma, _is_out = _sigma_adaptive(np.asarray(g_obs, dtype=np.float64), detect_outliers=robust)
    return sigma


def magnetic_sigma(b_obs: Sequence[float], robust: bool = True) -> np.ndarray:
    """Sigma de pesado magnético. Usa la MISMA forma R-04 (sigma calibrado a la
    amplitud del dato), modalidad-agnóstica: sigma_i = max(0.02·|d_i|, 0.01·rango).
    """
    from exploration.gravimetry import _sigma_adaptive

    sigma, _is_out = _sigma_adaptive(np.asarray(b_obs, dtype=np.float64), detect_outliers=robust)
    return sigma


def borehole_sigma(
    rho_t_m3: float,
    samples: Optional[Sequence[float]] = None,
) -> float:
    """Sigma de un ancla de sondaje (t/m³).

    - Con réplicas (≥2 muestras en el intervalo): sigma = std(muestras)/√n
      (error estándar de la media). Si la dispersión es ~0, cae al piso relativo.
    - Sin réplicas: sigma = 15% · ρ (incertidumbre intrínseca de muestreo).
    """
    floor = _BOREHOLE_REL_UNCERTAINTY * abs(float(rho_t_m3))
    if samples is not None:
        arr = np.asarray(list(samples), dtype=np.float64)
        if arr.size >= 2:
            sem = float(np.std(arr)) / np.sqrt(arr.size)
            return max(sem, 1e-6)
    return max(floor, 1e-6)
