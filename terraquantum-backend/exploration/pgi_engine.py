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
