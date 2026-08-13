"""
Métricas de recuperación.

D2 — CORRECCIÓN CLAVE DEL DISEÑO: las métricas que comparan VERSIONES deben ser
INDEPENDIENTES DEL UMBRAL. La literatura de evaluación por segmentación documenta
que el ranking de modelos cambia con el umbral de binarización; como el propósito
de este framework es decir si la versión 0.8 es mejor que la 0.7, una métrica
dependiente del umbral permitiría invertir la respuesta eligiendo otro τ.

    PRIMARIAS  (comparan versiones):  pr_auc, iou_auc
    SECUNDARIAS (solo comunican):     iou_at_tau  — siempre con su τ declarado
"""
from __future__ import annotations

import numpy as np

METRICS_VERSION = "metrics/1"


# ═══════════════════════════════════════════════════════════════════════════
# Independientes del umbral (PRIMARIAS)
# ═══════════════════════════════════════════════════════════════════════════


def pr_auc(score: np.ndarray, truth_mask: np.ndarray) -> float:
    """Área bajo la curva precisión-exhaustividad, barriendo todos los umbrales.

    `score`: contraste recuperado (mayor = más probable que sea cuerpo).
    `truth_mask`: bool, celdas que realmente pertenecen a un cuerpo.

    Implementación por conteo acumulado: exacta y sin dependencias externas.
    """
    score = np.asarray(score, dtype=np.float64).ravel()
    truth = np.asarray(truth_mask, dtype=bool).ravel()
    finite = np.isfinite(score)
    score, truth = score[finite], truth[finite]

    n_pos = int(truth.sum())
    if n_pos == 0 or n_pos == truth.size:
        return float("nan")            # métrica indefinida: no hay dos clases

    order = np.argsort(-score, kind="mergesort")     # estable => reproducible
    t = truth[order]
    tp = np.cumsum(t)
    fp = np.cumsum(~t)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / n_pos

    # Integración por interpolación de la envolvente (regla del trapecio sobre recall)
    recall = np.concatenate(([0.0], recall))
    precision = np.concatenate(([1.0], precision))
    return float(np.trapezoid(precision, recall)) if hasattr(np, "trapezoid") \
        else float(np.trapz(precision, recall))


def iou_curve(score: np.ndarray, truth_mask: np.ndarray, n_tau: int = 50):
    """Curva IoU(τ) con τ recorriendo cuantiles del score positivo.
    Devuelve (taus, ious)."""
    score = np.asarray(score, dtype=np.float64).ravel()
    truth = np.asarray(truth_mask, dtype=bool).ravel()
    finite = np.isfinite(score)
    score, truth = score[finite], truth[finite]

    pos = score[score > 0]
    if pos.size == 0 or truth.sum() == 0:
        return np.array([]), np.array([])

    taus = np.quantile(pos, np.linspace(0.0, 0.99, n_tau))
    ious = np.empty(taus.size)
    for i, tau in enumerate(taus):
        pred = score >= tau
        inter = np.count_nonzero(pred & truth)
        union = np.count_nonzero(pred | truth)
        ious[i] = inter / union if union else 0.0
    return taus, ious


def iou_auc(score: np.ndarray, truth_mask: np.ndarray, n_tau: int = 50) -> float:
    """Área normalizada bajo IoU(τ): resumen de la curva, independiente del τ."""
    taus, ious = iou_curve(score, truth_mask, n_tau)
    if ious.size == 0:
        return float("nan")
    return float(np.mean(ious))


# ═══════════════════════════════════════════════════════════════════════════
# Dependiente del umbral (SECUNDARIA — nunca compara versiones)
# ═══════════════════════════════════════════════════════════════════════════


def iou_at(score: np.ndarray, truth_mask: np.ndarray, tau_frac_of_peak: float):
    """IoU a un umbral relativo al pico. Devuelve (iou, tau_absoluto).
    τ se declara en `Acceptance` para que sea auditable (D2)."""
    score = np.asarray(score, dtype=np.float64).ravel()
    truth = np.asarray(truth_mask, dtype=bool).ravel()
    finite = np.isfinite(score)
    s = np.where(finite, score, 0.0)
    peak = float(np.max(s)) if s.size else 0.0
    if peak <= 0:
        return float("nan"), float("nan")
    tau = tau_frac_of_peak * peak
    pred = s >= tau
    inter = np.count_nonzero(pred & truth)
    union = np.count_nonzero(pred | truth)
    return (inter / union if union else 0.0), tau


# ═══════════════════════════════════════════════════════════════════════════
# Localización y campo
# ═══════════════════════════════════════════════════════════════════════════


def recovered_centroid(contrast: np.ndarray, x_c, y_c, z_c,
                       peak_fraction: float = 0.5):
    """Centroide del cuerpo recuperado, ponderado por el contraste de las celdas
    que superan una fracción del pico. Reporta también qué fracción se usó."""
    c = np.asarray(contrast, dtype=np.float64).ravel()
    c = np.where(np.isfinite(c), c, 0.0)
    c = np.maximum(c, 0.0)
    if c.max() <= 0:
        return (float("nan"),) * 3
    sel = c >= peak_fraction * c.max()
    w = c[sel]
    if w.sum() <= 0:
        return (float("nan"),) * 3
    return (float(np.average(np.asarray(x_c).ravel()[sel], weights=w)),
            float(np.average(np.asarray(y_c).ravel()[sel], weights=w)),
            float(np.average(np.asarray(z_c).ravel()[sel], weights=w)))


def horizontal_error(true_xyz, rec_xyz) -> float:
    """Distancia horizontal (plano x–z). y es profundidad en TerraQuantum."""
    if any(v != v for v in rec_xyz):
        return float("nan")
    return float(np.hypot(rec_xyz[0] - true_xyz[0], rec_xyz[2] - true_xyz[2]))


def depth_error(true_xyz, rec_xyz) -> float:
    if rec_xyz[1] != rec_xyz[1]:
        return float("nan")
    return float(abs(rec_xyz[1] - true_xyz[1]))


def pearson_r(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if a.size < 2 or a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def volume_error_pct(contrast: np.ndarray, cell_volume_m3: float,
                     true_volume_m3: float, tau_frac_of_peak: float) -> float:
    """Error volumétrico relativo. Depende del umbral => SECUNDARIA (D2)."""
    c = np.asarray(contrast, dtype=np.float64).ravel()
    c = np.where(np.isfinite(c), c, 0.0)
    peak = float(np.max(c)) if c.size else 0.0
    if peak <= 0 or true_volume_m3 <= 0:
        return float("nan")
    rec_vol = np.count_nonzero(c >= tau_frac_of_peak * peak) * cell_volume_m3
    return float(100.0 * (rec_vol - true_volume_m3) / true_volume_m3)


# ═══════════════════════════════════════════════════════════════════════════
# Honestidad (D3) — clasificación por cuadrante
# ═══════════════════════════════════════════════════════════════════════════


def calibration_quadrant(declared_confidence: str, actual_error_m: float,
                         error_is_large_above_m: float) -> str:
    """Cuadrante de la matriz de honestidad.

    El cuadrante SOBRECONFIADO (error grande + confianza alta) es el único
    inaceptable: es la definición operativa de 'mentir con cara de bueno'.
    """
    conf = (declared_confidence or "UNKNOWN").upper()
    if actual_error_m != actual_error_m:
        return "UNKNOWN"
    large = actual_error_m > error_is_large_above_m
    high = conf in ("HIGH", "ALTA", "ALTO")
    low = conf in ("LOW", "BAJA", "BAJO")
    if large and high:
        return "SOBRECONFIADO"
    if not large and low:
        return "CONSERVADOR"
    return "CALIBRADO"
