"""
Servicio de preprocesamiento gravimétrico — separación regional-residual.
================================================================================
Expone a la capa de servicio/API el paso de separación regional-residual que el
backend de producción NO tenía (gap industrial #2 de la auditoría). Delega la
física en ``exploration.preprocessing.remove_regional_trend`` (no duplica lógica).

La PROYECCIÓN de coordenadas ya la maneja ``coordinate_transform_service`` (UTM
vía pyproj). Este servicio asume que ``sensor_coords`` ya están en metros locales
(x = columna 0, z = columna 2) y opera sobre el campo de gravedad ``g_observed``.

Uso:
    g_residual, meta = separate_regional_residual(sensor_coords, g_observed, order=2)

El residual resultante tiene media ≈ 0 y se invierte DIRECTAMENTE (sin shift DC):
restar el mínimo introduce masa difusa profunda espuria (bug corregido en la
auditoría de Bushveld).
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np

from exploration.preprocessing import remove_regional_trend

logger = logging.getLogger(__name__)


def separate_regional_residual(
    sensor_coords: np.ndarray,
    g_observed: np.ndarray,
    order: int = 2,
) -> Tuple[np.ndarray, dict]:
    """
    Ajusta y resta una tendencia regional polinómica al campo observado.

    Parameters
    ----------
    sensor_coords : ndarray (N, 3)
        Coordenadas de sensores en metros locales [x, y, z]. Se usan x (col 0) y
        z (col 2) como ejes horizontales del ajuste.
    g_observed : ndarray (N,)
        Campo de gravedad observado (misma unidad que se invertirá).
    order : int
        Grado del polinomio regional (1=plano, 2=cuadrático estándar).

    Returns
    -------
    g_residual : ndarray (N,)
        Campo con el regional removido (media ≈ 0).
    meta : dict
        Estadísticos del residual y del regional para el reporte/QAQC.
    """
    sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
    g_observed = np.asarray(g_observed, dtype=np.float64)
    if sensor_coords.ndim != 2 or sensor_coords.shape[1] != 3:
        raise ValueError(f"sensor_coords debe ser (N,3); recibido {sensor_coords.shape}")
    if g_observed.shape[0] != sensor_coords.shape[0]:
        raise ValueError("sensor_coords y g_observed deben tener el mismo N.")

    x = sensor_coords[:, 0]
    z = sensor_coords[:, 2]
    residual, regional, coef = remove_regional_trend(x, z, g_observed, order=order)

    meta = {
        "applied": True,
        "regional_order": int(order),
        "n_coefficients": int(coef.size),
        "regional_min": float(regional.min()),
        "regional_max": float(regional.max()),
        "residual_min": float(residual.min()),
        "residual_max": float(residual.max()),
        "residual_std": float(residual.std()),
        "residual_mean": float(residual.mean()),
        "note": (
            "Separación regional-residual (poly grado {o}) aplicada antes de la "
            "inversión. El residual se invierte directamente, sin shift DC.".format(o=order)
        ),
    }
    logger.info(
        "[PREPROC-SVC] Regional poly-%d removido: residual std=%.4g (media=%.3g)",
        order, meta["residual_std"], meta["residual_mean"],
    )
    return residual, meta


def maybe_separate_regional_residual(
    sensor_coords: np.ndarray,
    g_observed: np.ndarray,
    enabled: bool,
    order: int = 2,
) -> Tuple[np.ndarray, Optional[dict]]:
    """
    Versión con interruptor: si ``enabled`` es False, devuelve el campo intacto y
    meta=None (cero cambio de comportamiento). Pensada para integrarse en el flujo
    de inversión sin alterar el camino por defecto.
    """
    if not enabled:
        return np.asarray(g_observed, dtype=np.float64), None
    return separate_regional_residual(sensor_coords, g_observed, order=order)
