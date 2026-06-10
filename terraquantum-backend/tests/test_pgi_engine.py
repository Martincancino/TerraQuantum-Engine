"""
Tests Fase 11 — PGI Engine (Criterios de aceptación §11.7)

CA-1: compute_m_pgi para m=[2.65, 2.90, 3.50] asigna cada valor al centroide correcto.
CA-2: inversión PGI sintética (3 litologías): asignación de clase correcta en > 70% de celdas.
CA-3: histograma post-PGI muestra picos en centroides GMM (más bimodal que sin PGI).
CA-4: convergencia en ≤ 10 iteraciones de actualización m_PGI.
"""
import sys
import os

# Agrega el directorio raíz del backend al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import scipy.sparse as sp
import pytest

from exploration.pgi_engine import PGIEngine, DEPOSIT_GMM_DEFAULTS


# ── Fixtures ───────────────────────────────────────────────────────────────

BASE_DENSITY = 2.67  # t/m³

def _make_engine_3class():
    """GMM de 3 litologías estándar para tests (pórfido Cu)."""
    defaults = DEPOSIT_GMM_DEFAULTS["porfido_cu"]
    return PGIEngine(
        means=[c["mean"] for c in defaults],
        stds=[c["std"] for c in defaults],
        weights=[c["weight"] for c in defaults],
        alpha_pgi=0.1,
        base_density=BASE_DENSITY,
    )


def _synthetic_3class_model(n_per_class: int = 100, noise_std: float = 0.03):
    """Modelo sintético de 3 clases con ruido Gaussiano leve."""
    np.random.seed(42)
    defaults = DEPOSIT_GMM_DEFAULTS["porfido_cu"]
    samples = []
    labels  = []
    for k, c in enumerate(defaults):
        s = np.random.normal(loc=c["mean"], scale=noise_std, size=n_per_class)
        samples.append(s)
        labels.extend([k] * n_per_class)
    m_abs = np.concatenate(samples)
    return m_abs, np.array(labels)


# ── CA-1: asignación MAP correcta para valores exactos de los centroides ──

class TestComputeMPgi:
    def test_exact_means_assigned_to_own_class(self):
        """CA-1 §11.7: compute_m_pgi para m=[2.65, 2.90, 3.50] asigna al centroide correcto."""
        engine = _make_engine_3class()
        # Valores exactamente en los centroides (contraste = mean - base_density)
        means_abs = np.array([2.65, 2.90, 3.50])
        contrast = means_abs - BASE_DENSITY
        m_pgi = engine.compute_m_pgi(contrast)
        # Cada valor debe asignarse a su centroide exacto (± 1e-10 por float)
        expected_abs = means_abs  # cada valor está más cerca de su propio centroide
        np.testing.assert_allclose(
            m_pgi + BASE_DENSITY, expected_abs, atol=1e-8,
            err_msg="compute_m_pgi no asignó los centroides GMM correctamente."
        )

    def test_between_class_value_goes_to_nearest_centroid(self):
        """Valor entre dos clases se asigna a la más cercana."""
        engine = _make_engine_3class()
        # 2.77 está entre 2.65 y 2.90 — más cerca de 2.65 (diff=0.12 vs diff=0.13) ... ambas stds 0.08/0.15
        # Con el GMM, la probabilidad depende también de std y weight.
        # 2.77: z1=(2.77-2.65)/0.08=1.5, z2=(2.77-2.90)/0.15=0.87
        # log-prob2 = log(0.10) - log(0.15) - 0.5*0.87^2 = -2.30 - (-1.90) - 0.38 = -0.78
        # log-prob1 = log(0.85) - log(0.08) - 0.5*1.5^2 = -0.16 - (-2.53) - 1.125 = 1.245
        # Clase 1 (μ=2.65) gana. Check esto:
        contrast = np.array([2.77 - BASE_DENSITY])
        m_pgi = engine.compute_m_pgi(contrast)
        assert abs(m_pgi[0] + BASE_DENSITY - 2.65) < 1e-6, (
            f"Esperaba clase μ=2.65, obtuvo {m_pgi[0]+BASE_DENSITY:.4f}"
        )

    def test_high_density_assigned_to_mineralisation(self):
        """Valor 3.50 se asigna a la clase de mineralización alta."""
        engine = _make_engine_3class()
        contrast = np.array([3.50 - BASE_DENSITY])
        m_pgi = engine.compute_m_pgi(contrast)
        assert abs(m_pgi[0] + BASE_DENSITY - 3.50) < 1e-6, (
            f"Esperaba clase μ=3.50, obtuvo {m_pgi[0]+BASE_DENSITY:.4f}"
        )

    def test_output_shape_matches_input(self):
        """compute_m_pgi devuelve array de la misma longitud que la entrada."""
        engine = _make_engine_3class()
        n = 500
        contrast = np.random.normal(0.0, 0.3, size=n)
        m_pgi = engine.compute_m_pgi(contrast)
        assert m_pgi.shape == (n,), f"Shape esperado ({n},), obtuvo {m_pgi.shape}"


# ── CA-2: asignación de clase correcta > 70% en datos sintéticos ──────────

class TestClassificationAccuracy:
    def test_accuracy_3class_synthetic(self):
        """CA-2 §11.7: asignación de clase correcta en > 70% de celdas sintéticas."""
        engine = _make_engine_3class()
        m_abs, true_labels = _synthetic_3class_model(n_per_class=200, noise_std=0.04)
        contrast = m_abs - BASE_DENSITY
        predicted_labels = engine.predict_class(m_abs)
        accuracy = np.mean(predicted_labels == true_labels)
        assert accuracy >= 0.70, (
            f"Accuracy de clasificación GMM = {accuracy:.2%} < 70% mínimo requerido."
        )

    def test_m_pgi_values_in_gmm_means(self):
        """compute_m_pgi retorna solo valores de los centroides GMM."""
        engine = _make_engine_3class()
        n = 300
        m_abs = np.concatenate([
            np.random.normal(2.65, 0.05, 100),
            np.random.normal(2.90, 0.10, 100),
            np.random.normal(3.50, 0.10, 100),
        ])
        contrast = m_abs - BASE_DENSITY
        m_pgi = engine.compute_m_pgi(contrast)
        m_pgi_abs = m_pgi + BASE_DENSITY
        allowed = set(engine.means.round(10).tolist())
        unique_vals = set(np.unique(m_pgi_abs).round(10).tolist())
        assert unique_vals.issubset(allowed), (
            f"m_pgi contiene valores fuera de los centroides GMM: {unique_vals - allowed}"
        )


# ── CA-3: histograma post-PGI más bimodal que sin PGI ─────────────────────

class TestHistogramBimodality:
    def _bimodality_score(self, data: np.ndarray, centers: list, width: float = 0.10) -> float:
        """Fracción de valores en ventanas alrededor de los centroides GMM."""
        in_peak = np.zeros(len(data), dtype=bool)
        for c in centers:
            in_peak |= (np.abs(data - c) <= width)
        return in_peak.mean()

    def test_pgi_concentrates_near_gmm_means(self):
        """CA-3 §11.7: m_pgi muestra más masa cerca de los centroides que el input difuso."""
        engine = _make_engine_3class()
        # Input difuso (distribución uniforme amplia)
        np.random.seed(0)
        m_diffuse_abs = np.random.uniform(2.5, 3.8, 1000)
        contrast_diffuse = m_diffuse_abs - BASE_DENSITY

        m_pgi_abs = engine.compute_m_pgi(contrast_diffuse) + BASE_DENSITY
        centers = engine.means.tolist()

        bimod_pgi = self._bimodality_score(m_pgi_abs, centers, width=0.01)
        bimod_input = self._bimodality_score(m_diffuse_abs, centers, width=0.01)

        # m_pgi SIEMPRE tiene 100% en los centroides (MAP assignment)
        assert bimod_pgi >= bimod_input, (
            f"m_pgi bimodality={bimod_pgi:.3f} no supera input bimodality={bimod_input:.3f}"
        )
        # La asignación MAP produce exactamente los centroides → todo está "en los picos"
        assert bimod_pgi >= 0.99, f"bimodality_pgi={bimod_pgi:.3f} < 0.99 esperado para asignación MAP exacta."


# ── CA-4: convergencia en ≤ 10 iteraciones ────────────────────────────────

class TestConvergence:
    def test_convergence_within_10_iters_pure_pgi(self):
        """CA-4 §11.7: el bucle m_PGI converge en ≤ 10 iteraciones."""
        engine = _make_engine_3class()
        tol = 1e-3
        max_iter = 10

        # Simular el bucle: empezar con contraste aleatorio, iterar
        np.random.seed(7)
        m_contrast = np.random.normal(0.0, 0.5, size=500)

        converged = False
        m_pgi_prev = engine.compute_m_pgi(m_contrast)
        for i in range(max_iter):
            # En una inversión real, el modelo cambiaría entre iteraciones.
            # Aquí simulamos con pequeños cambios decrecientes (worst-case suave).
            noise = np.random.normal(0.0, 0.05 * (0.5 ** i), size=len(m_contrast))
            m_contrast = m_pgi_prev + noise
            m_pgi_new = engine.compute_m_pgi(m_contrast)
            conv = engine.convergence_norm(m_pgi_prev, m_pgi_new)
            m_pgi_prev = m_pgi_new
            if conv < tol:
                converged = True
                break

        assert converged, (
            f"El bucle PGI no convergió en {max_iter} iteraciones "
            f"(última conv={engine.convergence_norm(m_pgi_prev, m_pgi_new):.4e})."
        )

    def test_convergence_norm_zero_for_same_model(self):
        """Convergencia es 0 cuando el modelo no cambia."""
        engine = _make_engine_3class()
        m_pgi = engine.compute_m_pgi(np.zeros(100))
        conv = engine.convergence_norm(m_pgi, m_pgi)
        assert conv == 0.0

    def test_convergence_norm_finite(self):
        """Norma de convergencia es finita y no-negativa."""
        engine = _make_engine_3class()
        old = engine.compute_m_pgi(np.zeros(100))
        new = engine.compute_m_pgi(np.ones(100) * 0.1)
        conv = engine.convergence_norm(old, new)
        assert np.isfinite(conv) and conv >= 0.0


# ── Tests adicionales: construcción del bloque y validación de inputs ──────

class TestBuildPgiBlock:
    def test_block_shape(self):
        """build_pgi_block retorna A (n,n) y b (n,)."""
        engine = _make_engine_3class()
        n = 64
        m_c = np.random.normal(0.0, 0.2, n)
        A, b = engine.build_pgi_block(m_c, n)
        assert A.shape == (n, n), f"A shape esperado ({n},{n}), obtuvo {A.shape}"
        assert b.shape == (n,),   f"b shape esperado ({n},), obtuvo {b.shape}"

    def test_block_sparse(self):
        """A_pgi es una matriz sparse."""
        engine = _make_engine_3class()
        n = 50
        A, b = engine.build_pgi_block(np.zeros(n), n)
        assert sp.issparse(A), "A_pgi debe ser sparse."

    def test_block_diagonal_value(self):
        """Diagonal de A_pgi = sqrt(alpha_pgi)."""
        engine = _make_engine_3class()
        n = 10
        A, _ = engine.build_pgi_block(np.zeros(n), n)
        A_dense = A.toarray()
        expected_diag = np.sqrt(engine.alpha_pgi)
        np.testing.assert_allclose(
            np.diag(A_dense), expected_diag * np.ones(n), rtol=1e-10
        )

    def test_block_rhs_matches_m_pgi(self):
        """b_pgi = sqrt(alpha_pgi) * compute_m_pgi(m_contrast)."""
        engine = _make_engine_3class()
        n = 30
        m_c = np.random.normal(0.0, 0.3, n)
        A, b = engine.build_pgi_block(m_c, n)
        expected_b = np.sqrt(engine.alpha_pgi) * engine.compute_m_pgi(m_c)
        np.testing.assert_allclose(b, expected_b, rtol=1e-10)

    def test_shape_mismatch_raises(self):
        """ValueError si m_contrast y n_active no coinciden."""
        engine = _make_engine_3class()
        with pytest.raises(ValueError, match="n_active"):
            engine.build_pgi_block(np.zeros(10), 20)


# ── Tests de validación del constructor ───────────────────────────────────

class TestPGIEngineValidation:
    def test_single_component_raises(self):
        """Menos de 2 componentes GMM levanta ValueError."""
        with pytest.raises(ValueError, match="mínimo 2"):
            PGIEngine(means=[2.65], stds=[0.08], weights=[1.0])

    def test_zero_std_raises(self):
        """std = 0 levanta ValueError."""
        with pytest.raises(ValueError, match="estrictamente positivo"):
            PGIEngine(means=[2.65, 2.90], stds=[0.08, 0.0], weights=[0.5, 0.5])

    def test_mismatched_lengths_raises(self):
        """Longitudes distintas de means/stds/weights levanta ValueError."""
        with pytest.raises(ValueError):
            PGIEngine(means=[2.65, 2.90], stds=[0.08], weights=[0.5, 0.5])

    def test_weights_normalized(self):
        """Los pesos se normalizan automáticamente para sumar 1."""
        engine = PGIEngine(means=[2.65, 3.50], stds=[0.08, 0.20], weights=[2.0, 1.0])
        assert abs(engine.weights.sum() - 1.0) < 1e-12

    def test_deposit_defaults_load(self):
        """Todos los tipos de depósito en DEPOSIT_GMM_DEFAULTS son válidos."""
        for deposit_type, components in DEPOSIT_GMM_DEFAULTS.items():
            engine = PGIEngine(
                means=[c["mean"] for c in components],
                stds=[c["std"] for c in components],
                weights=[c["weight"] for c in components],
            )
            assert engine.K >= 2, f"{deposit_type}: K < 2"


# ── Test de integración: fit_from_model ───────────────────────────────────

class TestFitFromModel:
    def test_fit_from_model_produces_valid_engine(self):
        """fit_from_model crea un PGIEngine válido desde datos de inversión."""
        pytest.importorskip("sklearn", reason="sklearn requerido para fit_from_model")
        np.random.seed(99)
        # Simular un modelo invertido con 3 distribuciones
        m_abs = np.concatenate([
            np.random.normal(2.65, 0.07, 200),
            np.random.normal(2.90, 0.12, 50),
            np.random.normal(3.40, 0.15, 20),
        ])
        m_contrast = m_abs - BASE_DENSITY
        engine = PGIEngine.fit_from_model(
            m_contrast=m_contrast, n_components=3, alpha_pgi=0.2, base_density=BASE_DENSITY
        )
        assert engine.K == 3
        assert abs(engine.weights.sum() - 1.0) < 1e-9
        # Los medios deben estar ordenados (fit_from_model ordena por media)
        assert engine.means[0] < engine.means[1] < engine.means[2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
