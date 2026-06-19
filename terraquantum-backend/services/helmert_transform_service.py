"""
Fase 19 Tarea 7 (Caso B) — Georreferenciación de precisión por transformada de
similitud (Helmert) 2D.

Principio geomático: un único punto de anclaje fija la POSICIÓN pero no la
ROTACIÓN ni la ESCALA de un sistema de coordenadas local. Con ≥2 puntos de
control con coordenadas reales conocidas se resuelve la transformada completa:

    [E]       [cosθ  -sinθ] [x]   [tE]
    [N] = s · [sinθ   cosθ] [z] + [tN]

que en forma lineal (a = s·cosθ, b = s·sinθ) es:

    E = a·x − b·z + tE
    N = b·x + a·z + tN

con 4 incógnitas (a, b, tE, tN). Con 2 puntos el sistema es exacto; con ≥3 se
resuelve por mínimos cuadrados y el residual valida el anclaje (escala/rotación
consistentes ⇒ residual bajo).

Servicio matemático puro (sin estado, sin I/O). No reproyecta CRS: asume que las
coordenadas reales de los puntos de control están en un sistema proyectado
coherente (p.ej. Easting/Northing de una misma zona UTM, en metros).
"""
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from schemas.gravity_import_schema import HelmertTransformResult

# Umbral por defecto de residual aceptable (m). Sobre esto se marca confidence LOW.
DEFAULT_RESIDUAL_WARN_M = 10.0
# Distancia mínima entre puntos de control locales para que el ajuste sea estable.
_MIN_CONTROL_SEPARATION_M = 1e-6

Point = Tuple[float, float]


def _validate_points(local_points: Sequence[Point], real_points: Sequence[Point]) -> int:
    n = len(local_points)
    if n != len(real_points):
        raise ValueError(
            "local_points y real_points deben tener la misma cantidad de puntos."
        )
    if n < 2:
        raise ValueError(
            "Se requieren al menos 2 puntos de control para resolver posición, "
            "rotación y escala (un solo punto no define la rotación)."
        )
    # Los puntos locales no pueden ser todos coincidentes (sistema indeterminado).
    xs = [p[0] for p in local_points]
    zs = [p[1] for p in local_points]
    span = math.hypot(max(xs) - min(xs), max(zs) - min(zs))
    if span < _MIN_CONTROL_SEPARATION_M:
        raise ValueError(
            "Los puntos de control locales son coincidentes; no definen una "
            "transformada. Use puntos separados espacialmente."
        )
    return n


def solve_similarity_transform(
    local_points: Sequence[Point],
    real_points: Sequence[Point],
    *,
    residual_warn_m: float = DEFAULT_RESIDUAL_WARN_M,
) -> HelmertTransformResult:
    """Resuelve la transformada de similitud 2D local→real.

    local_points: [(x_local, z_local), ...]
    real_points:  [(easting, northing), ...] en el MISMO orden y CRS proyectado.
    """
    n = _validate_points(local_points, real_points)

    # Sistema lineal A·[a, b, tE, tN]ᵀ = rhs, dos filas (E, N) por punto.
    rows: List[List[float]] = []
    rhs: List[float] = []
    for (x, z), (e, north) in zip(local_points, real_points):
        rows.append([x, -z, 1.0, 0.0])
        rhs.append(e)
        rows.append([z, x, 0.0, 1.0])
        rhs.append(north)

    A = np.asarray(rows, dtype=float)
    b_vec = np.asarray(rhs, dtype=float)
    sol, _residuals, _rank, _sv = np.linalg.lstsq(A, b_vec, rcond=None)
    a, b, t_e, t_n = (float(v) for v in sol)

    scale = math.hypot(a, b)
    rotation_deg = math.degrees(math.atan2(b, a))

    # Residual por punto: distancia euclidiana entre real dado y real predicho.
    pred = A @ np.array([a, b, t_e, t_n], dtype=float)
    resid = (b_vec - pred).reshape(n, 2)
    point_err = np.sqrt(np.sum(resid ** 2, axis=1))
    residual_rms_m = float(np.sqrt(np.mean(point_err ** 2))) if n else 0.0
    max_residual_m = float(np.max(point_err)) if n else 0.0

    warnings: List[str] = []

    if scale <= 0.0 or not math.isfinite(scale):
        warnings.append(
            "Escala degenerada o no finita; los puntos de control podrían ser "
            "colineales o estar mal definidos."
        )
        confidence = "LOW"
    elif n == 2:
        confidence = "MEDIUM"
        warnings.append(
            "Ajuste con exactamente 2 puntos de control: la transformada es exacta "
            "pero NO hay redundancia para validar el anclaje. Se recomiendan ≥3 puntos."
        )
    elif residual_rms_m > residual_warn_m:
        confidence = "LOW"
        warnings.append(
            f"Residual RMS de la transformada = {residual_rms_m:.2f} m "
            f"(> {residual_warn_m:.1f} m): el anclaje es inconsistente. Revise las "
            "coordenadas de los puntos de control o el sistema local del CSV."
        )
    else:
        confidence = "HIGH"

    # Escala muy alejada de 1.0 suele indicar mezcla de unidades (p.ej. pies vs m).
    if math.isfinite(scale) and scale > 0 and (scale < 0.5 or scale > 2.0):
        warnings.append(
            f"Factor de escala = {scale:.4g} (lejos de 1.0): posible mezcla de "
            "unidades entre coordenadas locales y reales (¿pies vs metros?)."
        )

    return HelmertTransformResult(
        n_control_points=n,
        scale=scale,
        rotation_deg=rotation_deg,
        translation_e=t_e,
        translation_n=t_n,
        residual_rms_m=residual_rms_m,
        max_residual_m=max_residual_m,
        confidence=confidence,
        warnings=warnings,
        a=a,
        b=b,
    )


def apply_similarity_transform(
    transform: HelmertTransformResult,
    local_points: Sequence[Point],
) -> List[Point]:
    """Aplica una transformada resuelta a coordenadas locales → (E, N) reales."""
    a, b = transform.a, transform.b
    t_e, t_n = transform.translation_e, transform.translation_n
    return [
        (a * x - b * z + t_e, b * x + a * z + t_n)
        for (x, z) in local_points
    ]
