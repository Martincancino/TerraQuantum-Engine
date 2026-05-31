"""
TerraQuantum — Módulo experimental de focusing MS-x.

Implementa Minimum Support IRLS en espacio x = m/W (formulación MS-x).
Referencia: Portniaguine & Zhdanov (1999), Geophysics 64(3), 829-843.

EXPERIMENTAL: activar solo mediante enable_focusing=True en el request.
La inversión LSQR base nunca se modifica por este módulo.

Diferencia con el script de validación sintética (1.7C.3L.8):
  - Sin ground truth en producción → best_iter se selecciona por mínimo RMS
    (proxy de ajuste a datos) en lugar de PR-AUC máximo.
  - m_best y m_base son contrastes de densidad (t/m³), no densidad absoluta.
  - La densidad absoluta la reconstruye geophysics_service.py (base + contraste).

Configuración validada en Fase 1.7C.3L.3–1.7C.3L.8. No modificar sin nueva fase.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import LinearOperator, lsqr

# Configuración fija validada (no exponer como parámetros públicos todavía)
_BETA_MS     = 1e-2
_EPS_0       = 0.80
_EPS_MIN     = 0.12
_COOLING     = 0.90
_MAX_IRLS    = 10
_IRLS_TOL    = 1e-3
_M_MAX       = 1.60
_DEPTH_BETA  = 1.00

_THR_SUPPRESS = 0.15   # max_density < umbral → ESCALA_SUPRIMIDA
_SPIKE_FACTOR = 1.50   # max_density > factor * base → ESCALA_INESTABLE


@dataclass
class MSXResult:
    """
    Resultado del focusing MS-x.

    m_best es contraste de densidad en t/m³ (no densidad absoluta).
    Para densidad absoluta: base_density + m_best (geophysics_service lo maneja).

    config_summary contiene los hiperparámetros efectivos usados, incluyendo
    lambda_mag_used_in_msx=0 (ver nota en run_focusing sobre por qué no se usa).
    """
    m_best:           np.ndarray
    scale_status:     str          # "OK" | "SUPRIMIDA" | "INESTABLE"
    use_mode:         str          # "physical_mask_candidate" | "relative_targeting_score"
    safety_labels:    list[str]
    best_iter:        int
    total_iters:      int
    converged:        bool
    rms_best:         float
    rms_base:         float
    max_density_msx:  float
    max_density_base: float
    elapsed_seconds:  float
    config_summary:   dict = field(default_factory=dict)
    history:          list[dict] = field(default_factory=list)


def _depth_weights(y_c: np.ndarray) -> np.ndarray:
    """W = y_c^(beta/2) normalizado por la media."""
    W = np.power(np.maximum(y_c, 1e-3), _DEPTH_BETA / 2.0)
    W /= np.mean(W)
    return W


def _residual_rms(Gn, m: np.ndarray, sG: float, g_obs: np.ndarray) -> float:
    return float(np.sqrt(np.mean((g_obs - Gn.dot(m) * sG) ** 2)))


def _classify_scale(max_density_msx: float, max_density_base: float) -> str:
    if max_density_base > 1e-9 and max_density_msx > _SPIKE_FACTOR * max_density_base:
        return "INESTABLE"
    if max_density_msx < _THR_SUPPRESS:
        return "SUPRIMIDA"
    return "OK"


def _safety_labels(scale_status: str) -> list[str]:
    labels = ["targeting_score", "not_resource_estimate", "relative_model"]
    if scale_status in ("SUPRIMIDA", "INESTABLE"):
        labels += ["scale_suppressed", "do_not_use_for_physical_masking"]
    if scale_status == "INESTABLE":
        labels.append("scale_unstable")
    return labels


def run_focusing(
    kernel_sparse,
    g_obs: np.ndarray,
    y_c: np.ndarray,
    inversor,
    est_density: np.ndarray,
    alpha_spatial: float = 2.0,
    lambda_mag: float = 5e-5,
) -> MSXResult:
    """
    Aplica MS-IRLS x-space sobre el resultado de una inversión LSQR existente.

    Parameters
    ----------
    kernel_sparse : scipy sparse (n_sensors × n_voxels) — kernel gravitacional
    g_obs         : observaciones gravimétricas (n_sensors,) en unidades físicas
    y_c           : coordenada Y (profundidad) de cada vóxel (n_voxels,) en metros
    inversor      : instancia de GravimetryInversion — se usa _build_spatial_regularizer
    est_density   : densidad absoluta estimada por LSQR (n_voxels,) en t/m³
    alpha_spatial : mismo alpha_spatial usado en la inversión base
    lambda_mag    : mismo lambda_mag usado en la inversión base

    Returns
    -------
    MSXResult — m_best es contraste de densidad en t/m³ al iter de mínimo RMS.
    """
    t0 = time.perf_counter()

    # Contraste de densidad desde la inversión base (warm start para MS-IRLS)
    base_density     = float(inversor.base_density)
    m_base           = np.clip(est_density - base_density, 0.0, _M_MAX)
    max_density_base = float(np.max(m_base))

    # Validación del kernel
    if kernel_sparse.nnz == 0:
        raise ValueError("[FOCUSING] Kernel vacío: no se puede aplicar MS-x.")

    sG = float(np.max(np.abs(kernel_sparse.data)))
    if sG <= 0 or not np.isfinite(sG):
        raise ValueError("[FOCUSING] sG inválido: no se puede normalizar kernel.")

    Gn = kernel_sparse / sG
    gn = g_obs / sG

    n_s, n_v = kernel_sparse.shape

    # Operador de depth weighting
    W  = _depth_weights(y_c)
    Wm = sp.diags(W, 0, format="csr")

    # Sistema aumentado para MS-IRLS:
    #   Ga_base = vstack([Gn @ Wm, ls * Ws @ Wm])
    #
    # Nota sobre lambda_mag:
    #   En la inversión LSQR base (gravimetry.py), lambda_mag actúa como damp en lsqr().
    #   En MS-IRLS no se incluye: el prior de soporte mínimo (focus_diag) reemplaza
    #   el rol del damping escalar por iteración. Incluir ambos doble-regularizaría.
    #   lambda_mag se recibe como parámetro solo para mantener la firma del API
    #   consistente, pero su valor efectivo en MS-x es 0.
    #   Ver config_summary["lambda_mag_used_in_msx"] = 0.
    Gt  = Gn.dot(Wm)
    Ws  = inversor._build_spatial_regularizer() / 6.0
    Wst = Ws.dot(Wm)
    ls  = float(alpha_spatial) * (n_s / n_v)

    Ga_base = sp.vstack([Gt, ls * Wst], format="csr")
    da_base = np.concatenate([gn, np.zeros(n_v)])
    n_base  = Ga_base.shape[0]

    rms_base = _residual_rms(Gn, m_base, sG, g_obs)

    # Estado inicial del IRLS
    m_prev   = np.clip(m_base, 0.0, _M_MAX)
    x_prev   = m_prev / np.maximum(W, 1e-12)
    eps      = _EPS_0
    sqrt_bms = float(np.sqrt(_BETA_MS))

    history       = []
    converged     = False
    best_rms      = float("inf")
    best_iter_idx = 0
    m_best        = m_prev.copy()

    for k in range(_MAX_IRLS):
        # Pesos de foco IRLS en espacio x (formulación MS-x)
        x_safe     = m_prev / np.maximum(W, 1e-12)
        denom_sq_x = np.maximum(
            x_safe ** 2 + eps ** 2,
            (_EPS_MIN / np.maximum(W, 1e-12)) ** 2,
        )
        focus_diag = np.clip(1.0 / np.sqrt(denom_sq_x), 0.0, 1.0 / _EPS_MIN)

        # Operador lineal: evita vstack en cada iteración
        def _mv(x, fd=focus_diag, sb=sqrt_bms):
            return np.concatenate([Ga_base @ x, sb * fd * x])

        def _rmv(y, fd=focus_diag, sb=sqrt_bms):
            return Ga_base.T @ y[:n_base] + sb * fd * y[n_base:]

        op   = LinearOperator(
            (n_base + n_v, n_v), matvec=_mv, rmatvec=_rmv, dtype=np.float64,
        )
        da_k = np.concatenate([da_base, np.zeros(n_v)])
        sol  = lsqr(
            op, da_k, damp=0.0, atol=1e-6, btol=1e-6,
            iter_lim=200, show=False, x0=x_prev,
        )

        x_new = sol[0]
        m_new = np.clip(x_new * W, 0.0, _M_MAX)
        delta = float(np.linalg.norm(m_new - m_prev) / max(np.linalg.norm(m_new), 1e-9))
        rms_k = _residual_rms(Gn, m_new, sG, g_obs)

        # Early stopping: best_iter = iteración de mínimo RMS
        # (en producción no hay ground truth → RMS como proxy de data fit)
        if rms_k < best_rms:
            best_rms      = rms_k
            best_iter_idx = k
            m_best        = m_new.copy()

        history.append({
            "iter":        k,
            "eps":         eps,
            "delta":       delta,
            "rms":         rms_k,
            "max_density": float(np.max(m_new)),
        })

        x_prev = x_new
        m_prev = m_new
        eps    = max(eps * _COOLING, _EPS_MIN)

        if delta < _IRLS_TOL:
            converged = True
            break

    elapsed         = time.perf_counter() - t0
    rms_best_final  = best_rms if best_rms < float("inf") else rms_base
    max_density_msx = float(np.max(m_best))

    status = _classify_scale(max_density_msx, max_density_base)
    mode   = "physical_mask_candidate" if status == "OK" else "relative_targeting_score"
    labels = _safety_labels(status)

    config_summary = {
        "method":                        "ms_x",
        "beta_ms":                       _BETA_MS,
        "eps_0":                         _EPS_0,
        "eps_min":                       _EPS_MIN,
        "cooling":                       _COOLING,
        "max_irls":                      _MAX_IRLS,
        "depth_beta":                    _DEPTH_BETA,
        "alpha_spatial":                 float(alpha_spatial),
        "lambda_mag_received":           float(lambda_mag),
        "lambda_mag_used_in_msx":        0,
        "best_iter_selection":           "min_rms_proxy_without_ground_truth",
    }

    print(
        f"[FOCUSING] MS-x: best_iter={best_iter_idx} | iters={len(history)} | "
        f"conv={converged} | rms_base={rms_base:.5f} -> rms_best={rms_best_final:.5f} | "
        f"maxd: base={max_density_base:.3f} msx={max_density_msx:.3f} | "
        f"escala={status} | t={elapsed:.1f}s"
    )

    return MSXResult(
        m_best=m_best,
        scale_status=status,
        use_mode=mode,
        safety_labels=labels,
        best_iter=best_iter_idx,
        total_iters=len(history),
        converged=converged,
        rms_best=rms_best_final,
        rms_base=rms_base,
        max_density_msx=max_density_msx,
        max_density_base=max_density_base,
        elapsed_seconds=elapsed,
        config_summary=config_summary,
        history=history,
    )
