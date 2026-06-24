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


# ── FASE 1.2 — Auto-desmagnetización (self-demagnetization) ───────────────────
# Para cuerpos de alta susceptibilidad (κ ≳ 0.1 SI: magnetita masiva, IOCG, BIF)
# la magnetización inducida perturba el campo local de forma NO despreciable, así
# que M ≠ κ·H0. El campo interno es H_int = H0 − N·M (N = factor desmagnetizante
# de la forma del cuerpo), de donde M = κ·H_int = κ·H0/(1 + N·κ). El motor lineal
# "ve" entonces una susceptibilidad APARENTE κ_eff = κ/(1 + N·κ) < κ.
#
# Aproximación LOCAL (celda aislada): se asigna a cada celda el factor escalar N
# de su propia forma (N≈1/3 para una celda equidimensional/esfera). Esto IGNORA el
# acoplamiento entre celdas vecinas (el tensor desmagnetizante completo N_ij del
# solve finite-volume de Krahenbuhl & Li 2007 / Lelièvre & Oldenburg 2006). Es el
# régimen dominante para κ moderada; para κ≫1 (saturación) el acoplamiento importa
# y el solve acoplado completo queda DIFERIDO. Referencia: Blakely 1995 §5.

def apparent_susceptibility(kappa, demag_factor: float):
    """κ_eff = κ / (1 + N·κ): susceptibilidad APARENTE que ve el kernel lineal.

    Monótona creciente y acotada: κ→∞ ⇒ κ_eff→1/N (saturación). N=0 ⇒ κ_eff=κ
    (sin desmagnetización, comportamiento histórico).
    """
    kappa = np.asarray(kappa, dtype=np.float64)
    N = float(demag_factor)
    return kappa / (1.0 + N * kappa)


def true_susceptibility(kappa_eff, demag_factor: float):
    """Inversa de apparent_susceptibility: κ = κ_eff / (1 − N·κ_eff).

    Definida para N·κ_eff < 1 (garantizado si κ_eff proviene de bounds aparentes
    derivados de un κ_max finito). Se acota el denominador por seguridad numérica.
    """
    kappa_eff = np.asarray(kappa_eff, dtype=np.float64)
    N = float(demag_factor)
    denom = np.maximum(1.0 - N * kappa_eff, 1e-9)
    return kappa_eff / denom
