"""
Pesos de datos compartidos por los motores geofísicos (gravimetría / magnetometría).

Centraliza la forma de PISO instrumental del sigma paramétrico para que ambos
motores usen exactamente la misma definición. Históricamente magnetometría usaba
una forma ADITIVA (``noise_floor + noise_pct·|d|``) que sobreestimaba sigma
~|d|/floor veces para datos de campo, colapsando chi²_red a ~0 — el mismo bug que
gravimetría ya había corregido en su ``_sigma_parametric`` local.
"""

import numpy as np


def sigma_parametric(d: np.ndarray, noise_floor: float, noise_pct: float) -> np.ndarray:
    """
    Sigma con piso instrumental explícito (flujo de datos de campo).

        sigma_i = max(noise_floor, noise_pct · |d_i|)

    ``noise_floor`` es un PISO (no se suma): el ruido restante de una anomalía
    bien corregida es instrumental y el término relativo solo domina cuando |d|
    es grande. La forma aditiva anterior (floor + pct·|d|) sobreestimaba sigma
    para datos de campo, colapsando chi²_red a ~0.

    Unidades: las mismas de ``d`` (el caller convierte mGal/nT → SI si aplica).
    """
    sigma = np.maximum(float(noise_floor), float(noise_pct) * np.abs(d))
    return np.maximum(sigma, 1e-30)
