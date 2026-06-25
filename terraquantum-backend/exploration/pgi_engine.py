"""
PGI Engine — Inversión Guiada Petrológica (Astic & Oldenburg 2019)

Implementa la formulación GMM-PGI: ancla el modelo invertido a K clases
petrológicas con distribuciones Gaussianas conocidas (de sondaje o bibliografía).
El término PGI se inyecta como un bloque extra en el sistema aumentado del solver
LSQR vía el hook extra_reg_blocks de solve_inversion_lsqr().

Referencia: Astic, T. & Oldenburg, D.W. (2019). A framework for petrophysically
and geologically guided geophysical inversion using a dynamic Gaussian mixture model
prior. GJI, 219(3), 1989–2012.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

# ── Tabla de GMM por tipo de depósito (Fase 11 §11.5) ──────────────────────
# Formato: lista de {"mean": float, "std": float, "weight": float}
# Unidades: t/m³ (densidad absoluta).
DEPOSIT_GMM_DEFAULTS: dict[str, list[dict]] = {
    "porfido_cu": [
        {"mean": 2.65, "std": 0.08, "weight": 0.85},
        {"mean": 2.90, "std": 0.15, "weight": 0.10},
        {"mean": 3.50, "std": 0.20, "weight": 0.05},
    ],
    "vms_cu_zn": [
        {"mean": 2.70, "std": 0.10, "weight": 0.80},
        {"mean": 3.20, "std": 0.20, "weight": 0.12},
        {"mean": 4.60, "std": 0.20, "weight": 0.08},
    ],
    "skarn_fe": [
        {"mean": 2.65, "std": 0.08, "weight": 0.80},
        {"mean": 3.50, "std": 0.20, "weight": 0.10},
        {"mean": 5.10, "std": 0.15, "weight": 0.10},
    ],
    "iocg": [
        {"mean": 2.70, "std": 0.10, "weight": 0.80},
        {"mean": 3.20, "std": 0.20, "weight": 0.10},
        {"mean": 4.60, "std": 0.20, "weight": 0.10},
    ],
}


# ── FASE 2.3: tabla de bounds petrofísicos por UNIDAD litológica ────────────
# Box [min, max] por litología para la restricción de membership dura (bounds KKT
# por unidad). density en t/m³, susc en SI. Rangos de referencia (Telford et al.
# 1990; Clark 1997; Hunt et al. 1995). El servicio empareja la litología del
# sondaje (case-insensitive) contra esta tabla; el usuario puede sobreescribir vía
# `lithology_bounds` en el input. None en un eje = sin restricción en esa física.
LITHOLOGY_BOUNDS_DEFAULTS: dict[str, dict] = {
    "granite":   {"density": (2.52, 2.75), "susc": (0.0, 0.02)},
    "granodiorite": {"density": (2.65, 2.80), "susc": (0.0, 0.03)},
    "diorite":   {"density": (2.72, 2.99), "susc": (0.0, 0.10)},
    "gabbro":    {"density": (2.85, 3.12), "susc": (0.001, 0.10)},
    "basalt":    {"density": (2.70, 3.20), "susc": (0.001, 0.10)},
    "andesite":  {"density": (2.40, 2.80), "susc": (0.0, 0.05)},
    "sandstone": {"density": (2.20, 2.70), "susc": (0.0, 0.005)},
    "limestone": {"density": (2.30, 2.80), "susc": (0.0, 0.001)},
    "shale":     {"density": (2.06, 2.67), "susc": (0.0, 0.005)},
    "schist":    {"density": (2.39, 2.90), "susc": (0.0, 0.03)},
    "magnetite": {"density": (4.90, 5.20), "susc": (0.5, 5.0)},
    "hematite":  {"density": (4.90, 5.30), "susc": (0.0, 0.05)},
    "pyrite":    {"density": (4.90, 5.20), "susc": (0.0, 0.005)},
    "chromite":  {"density": (4.30, 4.80), "susc": (0.0, 0.10)},
    "kimberlite": {"density": (2.30, 2.90), "susc": (0.0, 0.05)},
}


class PGIEngine:
    """Motor PGI con prior de Mixtura Gaussiana.

    Args:
        means:     densidades medias por clase [t/m³], longitud K.
        stds:      desviaciones estándar por clase [t/m³], longitud K.
        weights:   pesos de mezcla (proporciones volumétricas), longitud K, suman 1.
        alpha_pgi: peso del término PGI en la función objetivo (positivo).
        base_density: densidad de roca caja del solver (t/m³), para convertir
                      entre densidad absoluta y contraste.
    """

    def __init__(
        self,
        means: list[float],
        stds: list[float],
        weights: list[float],
        alpha_pgi: float = 0.1,
        base_density: float = 2.67,
    ):
        means_arr   = np.asarray(means,   dtype=np.float64)
        stds_arr    = np.asarray(stds,    dtype=np.float64)
        weights_arr = np.asarray(weights, dtype=np.float64)

        if means_arr.shape != stds_arr.shape or means_arr.shape != weights_arr.shape:
            raise ValueError("means, stds y weights deben tener la misma longitud K.")
        if means_arr.ndim != 1 or len(means_arr) < 2:
            raise ValueError("Se requieren mínimo 2 componentes GMM.")
        if np.any(stds_arr <= 0):
            raise ValueError("stds debe ser estrictamente positivo.")
        if np.any(weights_arr <= 0):
            raise ValueError("weights debe ser estrictamente positivo.")

        # Normalizar pesos para que sumen 1
        weights_arr = weights_arr / weights_arr.sum()

        self.means    = means_arr
        self.stds     = stds_arr
        self.weights  = weights_arr
        self.alpha_pgi  = float(alpha_pgi)
        self.base_density = float(base_density)
        self.K = len(means_arr)

        # ── FASE 2.2: prior petrofísico INMUTABLE para el GMM dinámico (NIW) ──
        # El refit() dinámico (Astic & Oldenburg 2019) re-estima means/stds/weights
        # del modelo invertido en cada iteración, pero REGULARIZADO hacia este prior
        # (Normal-Inverse-Wishart + Dirichlet). means/stds/weights de arriba mutan;
        # estos NO — son el centro del prior (conocimiento de sondaje/bibliografía).
        self._prior_means   = means_arr.copy()
        self._prior_vars    = (stds_arr ** 2).copy()
        self._prior_weights = weights_arr.copy()

    # ── Núcleo del GMM ──────────────────────────────────────────────────────

    def _log_gaussian(self, m_abs: np.ndarray, k: int) -> np.ndarray:
        """Log-probabilidad de la componente k para cada celda (sin constante)."""
        z = (m_abs - self.means[k]) / self.stds[k]
        return np.log(self.weights[k]) - np.log(self.stds[k]) - 0.5 * z * z

    def _log_proba_all(self, m_abs: np.ndarray) -> np.ndarray:
        """Matriz (K, n) de log-probabilidades sin normalizar."""
        return np.stack([self._log_gaussian(m_abs, k) for k in range(self.K)], axis=0)

    def predict_proba(self, m_abs: np.ndarray) -> np.ndarray:
        """Probabilidades de pertenencia (soft assignment), shape (K, n).

        Estabilizado numéricamente (log-sum-exp por fila).
        """
        log_p = self._log_proba_all(m_abs)            # (K, n)
        log_p -= log_p.max(axis=0, keepdims=True)      # resta máximo por celda
        p = np.exp(log_p)
        p /= p.sum(axis=0, keepdims=True)
        return p                                        # (K, n)

    def predict_class(self, m_abs: np.ndarray) -> np.ndarray:
        """Asignación MAP: argmax_k P(k | m_j) para cada celda. Shape (n,)."""
        return np.argmax(self._log_proba_all(m_abs), axis=0)

    # ── Interface principal ────────────────────────────────────────────────

    def compute_m_pgi(self, m_contrast: np.ndarray) -> np.ndarray:
        """Modelo de referencia PGI = centroide GMM de la clase MAP.

        Devuelve m_pgi en espacio de CONTRASTE (t/m³), longitud n_active.
        El contraste se convierte a densidad absoluta para la asignación y
        luego se vuelve a contraste para el RHS del sistema.
        """
        m_abs = np.asarray(m_contrast, dtype=np.float64) + self.base_density
        class_map = self.predict_class(m_abs)                   # (n,)
        m_pgi_abs = self.means[class_map]                       # centroide por celda
        return m_pgi_abs - self.base_density                    # contraste

    # ── FASE 2.2: GMM DINÁMICO (EM con prior NIW) ──────────────────────────
    def refit(
        self,
        m_contrast: np.ndarray,
        prior_kappa: float = 50.0,
        prior_nu: float = 50.0,
        weight_concentration: float = 1.0,
        min_std: float = 0.01,
    ) -> dict:
        """Re-estima means/stds/weights del modelo actual con UNA pasada EM MAP.

        Reemplaza el GMM estático (means/stds/weights fijos) por uno DINÁMICO
        (Astic & Oldenburg 2019, §3.2): cada iteración del bucle PGI re-ajusta la
        mixtura al modelo invertido, pero REGULARIZADA hacia el prior petrofísico
        (`_prior_*`) mediante un prior conjugado Normal-Inverse-Wishart (medias +
        varianzas) y Dirichlet (pesos). Esto permite que las componentes se adapten
        al dato sin colapsar ni alejarse del conocimiento de sondaje/bibliografía.

        E-step: responsabilidades r_kj con el GMM ACTUAL (predict_proba).
        M-step MAP (cerrado, conjugado), por componente k:
            π_k = (N_k + ζ) / (N + Kζ)
            μ_k = (κ0·μ0_k + N_k·x̄_k) / (κ0 + N_k)
            v_k = [ν0·v0_k + S_k + (κ0·N_k/(κ0+N_k))·(x̄_k − μ0_k)²] / (ν0 + N_k + 2)
        donde N_k=Σr_kj, x̄_k=Σr_kj·x_j/N_k, S_k=Σr_kj·(x_j−x̄_k)², y (μ0,v0,ζ) son
        el prior. κ0/ν0 = confianza del prior (↑ = más rígido ≈ estático); ζ evita
        componentes vacías. Modifica self.means/stds/weights IN-PLACE.

        Returns: dict con el cambio relativo de medias (diagnóstico de convergencia).
        """
        x = np.asarray(m_contrast, dtype=np.float64).ravel() + self.base_density
        if x.size == 0:
            return {"n_cells": 0, "mean_shift_rel": 0.0}

        r = self.predict_proba(x)                      # (K, n), GMM ACTUAL
        Nk = r.sum(axis=1)                              # (K,)
        Nk_safe = np.where(Nk > 1e-12, Nk, 1.0)
        sum_rx  = r @ x                                 # (K,)
        sum_rx2 = r @ (x * x)                           # (K,)
        xbar = sum_rx / Nk_safe                         # (K,)
        # Scatter ponderado S_k = Σ r·(x−x̄)² = Σ r·x² − N·x̄² (≥0, clip numérico).
        Sk = np.maximum(sum_rx2 - Nk * xbar * xbar, 0.0)

        k0, nu0, zeta = float(prior_kappa), float(prior_nu), float(weight_concentration)
        mu0, v0, w0 = self._prior_means, self._prior_vars, self._prior_weights

        # MAP de las medias (Normal prior) — componentes vacías → quedan en μ0.
        means_new = (k0 * mu0 + Nk * xbar) / (k0 + Nk)
        # MAP de las varianzas (Inverse-Gamma/IW prior).
        shrink = (k0 * Nk) / (k0 + Nk)                  # 0 si N_k=0
        vars_new = (nu0 * v0 + Sk + shrink * (xbar - mu0) ** 2) / (nu0 + Nk + 2.0)
        stds_new = np.sqrt(np.maximum(vars_new, float(min_std) ** 2))
        # MAP de los pesos (Dirichlet con pseudoconteo ζ sobre el prior).
        w_unnorm = Nk + zeta * w0 * self.K
        weights_new = w_unnorm / w_unnorm.sum()

        _shift = float(
            np.linalg.norm(means_new - self.means) / max(np.linalg.norm(self.means), 1e-12)
        )
        self.means   = means_new
        self.stds    = stds_new
        self.weights = weights_new
        return {"n_cells": int(x.size), "mean_shift_rel": _shift}

    def build_pgi_block(
        self,
        m_contrast: np.ndarray,
        n_active: int,
    ) -> tuple[sp.csr_matrix, np.ndarray]:
        """Bloque PGI para inyectar en extra_reg_blocks del solver.

        El sistema aumentado queda:
            min  ||G_aug @ m_tilde - d_aug||²
            donde G_aug incluye:
                sqrt(alpha_pgi) * I @ Wz_inv  (escalado internamente por el solver)
            y d_aug incluye:
                sqrt(alpha_pgi) * m_pgi_contrast

        Args:
            m_contrast: contraste de densidad actual (t/m³), shape (n_active,).
            n_active:   número de celdas activas (debe coincidir con shape de m_contrast).

        Returns:
            A_pgi: sparse (n_active, n_active).
            b_pgi: array (n_active,), RHS del bloque PGI.
        """
        if len(m_contrast) != n_active:
            raise ValueError(
                f"m_contrast tiene {len(m_contrast)} elementos; n_active={n_active}."
            )
        sqrt_a = np.sqrt(self.alpha_pgi)
        m_pgi  = self.compute_m_pgi(m_contrast)
        A_pgi  = sqrt_a * sp.eye(n_active, format="csr", dtype=np.float64)
        b_pgi  = sqrt_a * m_pgi
        return A_pgi, b_pgi

    def convergence_norm(
        self,
        m_pgi_old: np.ndarray,
        m_pgi_new: np.ndarray,
    ) -> float:
        """Norma relativa de cambio en la referencia PGI entre dos iteraciones."""
        denom = np.linalg.norm(m_pgi_old)
        if denom < 1e-12:
            return 0.0
        return float(np.linalg.norm(m_pgi_new - m_pgi_old) / denom)

    # ── Construcción desde modelo inicial (fuente de baja confiabilidad) ───

    @classmethod
    def fit_from_model(
        cls,
        m_contrast: np.ndarray,
        n_components: int = 3,
        alpha_pgi: float = 0.1,
        base_density: float = 2.67,
    ) -> "PGIEngine":
        """Estima GMM desde el modelo invertido inicial (sin sondajes).

        Usa sklearn GaussianMixture con inicialización k-means. Solo se
        recomienda como primer punto de partida; la confiabilidad es baja
        comparada con parámetros de sondaje o bibliografía.
        """
        try:
            from sklearn.mixture import GaussianMixture
        except ImportError as exc:
            raise ImportError("scikit-learn requerido para fit_from_model.") from exc

        m_abs = np.asarray(m_contrast, dtype=np.float64) + base_density
        gm = GaussianMixture(
            n_components=n_components,
            covariance_type="spherical",
            init_params="k-means++",
            n_init=5,
            random_state=42,
        )
        gm.fit(m_abs.reshape(-1, 1))
        order = np.argsort(gm.means_.ravel())
        means   = gm.means_.ravel()[order].tolist()
        stds    = np.sqrt(gm.covariances_.ravel()[order]).tolist()
        weights = gm.weights_[order].tolist()
        return cls(means=means, stds=stds, weights=weights,
                   alpha_pgi=alpha_pgi, base_density=base_density)


# ── FASE 2.2: GMM 2D en el plano ρ-χ (kernel NIW para joint) ────────────────
# Foundation para el PGI conjunto dinámico (Fase 3): la mixtura vive en el plano
# (densidad, susceptibilidad) con covarianza 2×2 plena, de modo que captura la
# CORRELACIÓN petrofísica ρ↔χ (p.ej. magnetita: alta densidad Y alta susc). Aquí
# se entrega el actualizador MAP conjugado (E-step responsabilidades + M-step NIW
# de medias/covarianzas + Dirichlet de pesos), validado en aislamiento. El cableado
# al solver joint co-localizado se hace en Fase 3 (NO en 2.2).
def gmm_responsibilities_2d(
    X: np.ndarray, means: np.ndarray, covs: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    """Responsabilidades (soft assignment) de un GMM 2D pleno. Shape (K, n).

    X: (n, 2) puntos (ρ, χ). means: (K, 2). covs: (K, 2, 2) SPD. weights: (K,).
    Estabilizado por log-sum-exp.
    """
    X = np.asarray(X, dtype=np.float64)
    means = np.asarray(means, dtype=np.float64)
    covs = np.asarray(covs, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    K = means.shape[0]
    n = X.shape[0]
    log_p = np.empty((K, n), dtype=np.float64)
    for k in range(K):
        cov = covs[k]
        det = np.linalg.det(cov)
        inv = np.linalg.inv(cov)
        d = X - means[k]                                   # (n, 2)
        maha = np.einsum("ni,ij,nj->n", d, inv, d)         # (n,)
        log_p[k] = np.log(max(weights[k], 1e-300)) - 0.5 * (np.log(max(det, 1e-300)) + maha)
    log_p -= log_p.max(axis=0, keepdims=True)
    p = np.exp(log_p)
    p /= p.sum(axis=0, keepdims=True)
    return p


def niw_map_update_2d(
    X: np.ndarray,
    resp: np.ndarray,
    prior_means: np.ndarray,
    prior_covs: np.ndarray,
    prior_weights: np.ndarray,
    prior_kappa: float = 50.0,
    prior_nu: float = 50.0,
    weight_concentration: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """M-step MAP conjugado (Normal-Inverse-Wishart + Dirichlet) en 2D.

    Análogo 2×2 de PGIEngine.refit: re-estima (medias, covarianzas, pesos) de la
    mixtura ρ-χ regularizada hacia (prior_means, prior_covs, prior_weights). El
    prior NIW usa Ψ0 = ν0·prior_cov de modo que la moda IW ≈ prior_cov (consistente
    con el caso 1D: denom ν0+N+d+1, d=2).

    Returns: (means (K,2), covs (K,2,2), weights (K,)).
    """
    X = np.asarray(X, dtype=np.float64)
    resp = np.asarray(resp, dtype=np.float64)              # (K, n)
    mu0 = np.asarray(prior_means, dtype=np.float64)        # (K, 2)
    cov0 = np.asarray(prior_covs, dtype=np.float64)        # (K, 2, 2)
    w0 = np.asarray(prior_weights, dtype=np.float64)       # (K,)
    K, d = mu0.shape[0], 2
    k0, nu0, zeta = float(prior_kappa), float(prior_nu), float(weight_concentration)

    Nk = resp.sum(axis=1)                                  # (K,)
    Nk_safe = np.where(Nk > 1e-12, Nk, 1.0)
    means = np.empty((K, d), dtype=np.float64)
    covs = np.empty((K, d, d), dtype=np.float64)
    for k in range(K):
        rk = resp[k]                                       # (n,)
        xbar = (rk[:, None] * X).sum(axis=0) / Nk_safe[k]  # (2,)
        mean_k = (k0 * mu0[k] + Nk[k] * xbar) / (k0 + Nk[k])
        dxc = X - xbar                                     # (n, 2)
        Sk = (rk[:, None, None] * np.einsum("ni,nj->nij", dxc, dxc)).sum(axis=0)
        dm = (xbar - mu0[k]).reshape(2, 1)
        Psi_N = nu0 * cov0[k] + Sk + (k0 * Nk[k] / (k0 + Nk[k])) * (dm @ dm.T)
        cov_k = Psi_N / (nu0 + Nk[k] + d + 1.0)            # moda IW
        # Blindaje SPD: simetriza y añade piso diagonal mínimo.
        cov_k = 0.5 * (cov_k + cov_k.T) + 1e-9 * np.eye(d)
        means[k] = mean_k
        covs[k] = cov_k
    w_unnorm = Nk + zeta * w0 * K
    weights = w_unnorm / w_unnorm.sum()
    return means, covs, weights
