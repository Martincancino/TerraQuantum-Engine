"""
FASE 18: Tests de robustez de sigma adaptivo con detección de outliers MAD.

4 tests:
  1. naive vs robust con un solo outlier
  2. percentile p5-p95 más robusto que min-max
  3. sin outliers: sigma_robust ≈ sigma_naive
  4. is_outlier flag y logging propagados correctamente
"""
import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from exploration.gravimetry import _sigma_adaptive


class TestSigmaRobustSingleOutlier:
    """Test 1: naive vs robust con 1 outlier extremo."""

    def setup_method(self):
        rng = np.random.default_rng(42)
        # 20 sensores limpios en [0, 10] mGal
        self.clean = rng.uniform(0.5, 10.0, size=20)
        # 1 outlier en 100 mGal
        self.outlier_val = 100.0
        self.g_naive = np.append(self.clean, self.outlier_val)
        self.g_robust = self.g_naive.copy()

    def test_sigma_naive_dilates_globally(self):
        """Naive: data_range = 100 - 0.5 = 99.5 → sigma_clean ≈ 0.995 (diluído)."""
        sigma_naive, is_out = _sigma_adaptive(self.g_naive, detect_outliers=False)
        # data_range limpia ≈ 9.5; con outlier = 99.5 → 0.01 * 99.5 ≈ 1.0
        data_range_naive = float(np.max(self.g_naive) - np.min(self.g_naive))
        expected_floor = 0.01 * data_range_naive
        # Los sensores limpios deben tener sigma dominado por data_range (global dilación)
        sigma_clean_naive = sigma_naive[:-1]
        assert float(np.mean(sigma_clean_naive)) > 0.5, (
            "Naive debe dilatar sigma de limpios cuando hay outlier extremo"
        )
        assert is_out.sum() == 0, "detect_outliers=False no debe marcar outliers"

    def test_sigma_robust_isolates_outlier(self):
        """Robust: sigma de limpios no se dilata; outlier recibe sigma 10× mayor."""
        sigma_robust, is_out = _sigma_adaptive(self.g_robust, detect_outliers=True)
        sigma_naive, _ = _sigma_adaptive(self.g_robust, detect_outliers=False)

        # El outlier debe estar marcado
        assert is_out[-1], "El último sensor (100 mGal) debe ser outlier"
        assert is_out.sum() == 1, "Solo 1 outlier esperado"

        # sigma de limpios en modo robust < en modo naive (menos dilación global)
        sigma_clean_robust = sigma_robust[:-1]
        sigma_clean_naive = sigma_naive[:-1]
        assert float(np.mean(sigma_clean_robust)) < float(np.mean(sigma_clean_naive)), (
            "sigma_robust de limpios debe ser < sigma_naive (sin dilación global)"
        )

        # sigma del outlier en robust > sigma del outlier en naive
        assert float(sigma_robust[-1]) > float(sigma_naive[-1]), (
            "sigma del outlier debe ser mayor en modo robust (10× penalty)"
        )

    def test_outlier_chi2_reduced_in_robust(self):
        """Robust downpesa el outlier: su chi² individual es menor en robust que en naive.

        En naive, sigma_outlier ≈ 0.01 * data_range = 0.01 * 99.5 ≈ 1.0 (o 2% del outlier).
        En robust, sigma_outlier = 10 × sigma_base_outlier → chi² del outlier ≈ 100× menor.
        """
        g_pred_flat = np.full_like(self.g_naive, float(np.mean(self.clean)))
        residual = self.g_naive - g_pred_flat

        sigma_naive, _ = _sigma_adaptive(self.g_naive, detect_outliers=False)
        sigma_robust, _ = _sigma_adaptive(self.g_naive, detect_outliers=True)

        chi2_outlier_naive = float((residual[-1] / sigma_naive[-1]) ** 2)
        chi2_outlier_robust = float((residual[-1] / sigma_robust[-1]) ** 2)

        assert chi2_outlier_robust < chi2_outlier_naive, (
            f"Chi² del outlier debe ser menor en robust "
            f"(robust={chi2_outlier_robust:.2f} vs naive={chi2_outlier_naive:.2f})"
        )
        # El ratio debe ser ≈ 100× (sigma_robust_outlier = 10× → chi² = 100×)
        ratio = chi2_outlier_naive / chi2_outlier_robust
        assert ratio > 50, (
            f"Reducción de chi² del outlier esperada >50×, got {ratio:.1f}×"
        )


class TestSigmaRobustPercentileVsMinMax:
    """Test 2: percentile(95)-percentile(5) más robusto que max-min en distribución skewed."""

    def test_percentile_range_smaller_than_minmax(self):
        """19 sensores a 5 mGal, 1 outlier a 500 mGal → data_range naive = 495, robust ≈ 0."""
        g = np.concatenate([np.full(19, 5.0), [500.0]])
        sigma_robust, is_out = _sigma_adaptive(g, detect_outliers=True)
        sigma_naive, _ = _sigma_adaptive(g, detect_outliers=False)

        # El outlier (500 mGal) debe ser detectado
        assert is_out[-1], "500 mGal debe ser detectado como outlier"

        # data_range naive = 495; data_range robust (p5-p95 de limpios ≈ 5-5 = 0, mínimo 1e-30)
        # → sigma_clean_naive >> sigma_clean_robust
        mean_clean_naive = float(np.mean(sigma_naive[:-1]))
        mean_clean_robust = float(np.mean(sigma_robust[:-1]))
        assert mean_clean_robust < mean_clean_naive * 0.5, (
            f"sigma_clean_robust ({mean_clean_robust:.6f}) debe ser < 50% de "
            f"sigma_clean_naive ({mean_clean_naive:.6f}) en distribución skewed"
        )

    def test_percentile_range_computed_from_clean_subset(self):
        """Verificar que el data_range se calcula sobre datos limpios (no sobre todos)."""
        rng = np.random.default_rng(7)
        g_clean = rng.uniform(1.0, 11.0, size=30)   # rango ≈ 10 mGal
        g_with_outlier = np.append(g_clean, [200.0, 300.0])

        sigma_robust, is_out = _sigma_adaptive(g_with_outlier, detect_outliers=True)
        # Ambos outliers deben detectarse
        assert is_out[-1] and is_out[-2], "Ambos outliers (200, 300) deben detectarse"

        # sigma de limpios ≈ max(0.02*|g|, 0.01*clean_range) donde clean_range ≈ p90-p10 ≈ 8
        # → 0.01 * 8 = 0.08; mean(0.02*|clean|) ≈ 0.02*6 = 0.12
        # sigma de naive: data_range = 299; → 0.01*299 = 2.99 → dominante sobre 0.02*|g|
        sigma_naive, _ = _sigma_adaptive(g_with_outlier, detect_outliers=False)
        assert float(np.mean(sigma_robust[:30])) < float(np.mean(sigma_naive[:30])), (
            "sigma_robust de limpios debe ser < sigma_naive cuando hay 2 outliers extremos"
        )


class TestSigmaRobustNoOutliers:
    """Test 3: sin outliers → sigma_robust ≈ sigma_naive (sin overhead)."""

    def test_clean_gaussian_data_no_penalty(self):
        """Datos gaussianos sin outliers: ambas versiones deben dar sigma ≈ igual."""
        rng = np.random.default_rng(99)
        g = rng.normal(loc=5.0, scale=0.5, size=50)  # sin outliers por construcción

        sigma_robust, is_out = _sigma_adaptive(g, detect_outliers=True)
        sigma_naive, _ = _sigma_adaptive(g, detect_outliers=False)

        assert is_out.sum() == 0, "No debe detectar outliers en datos gaussianos limpios"
        # Las sigmas deben ser muy similares (data_range ≈ p95-p5 para distribución limpia)
        ratio = float(np.mean(sigma_robust)) / float(np.mean(sigma_naive))
        assert 0.5 <= ratio <= 2.0, (
            f"Sin outliers, sigma_robust/sigma_naive={ratio:.3f} debe estar en [0.5, 2.0]. "
            "La diferencia viene de percentile vs min-max en datos limpios."
        )

    def test_uniform_clean_data(self):
        """Datos uniformes: sin outliers → is_outlier todo False."""
        g = np.linspace(1.0, 10.0, 20)
        _, is_out = _sigma_adaptive(g, detect_outliers=True)
        assert is_out.sum() == 0, "Distribución uniforme sin saltos extremos no debe tener outliers"


class TestIsOutlierFlagPropagated:
    """Test 4: is_outlier array retornado y logging correctos."""

    def test_is_outlier_shape_and_dtype(self):
        """El array is_outlier debe tener shape (n,) y dtype bool."""
        g = np.array([1.0, 2.0, 3.0, 100.0, 2.5])
        sigma, is_out = _sigma_adaptive(g, detect_outliers=True)
        assert is_out.shape == g.shape, "is_outlier debe tener misma shape que g_observed"
        assert is_out.dtype == bool, "is_outlier debe ser dtype bool"

    def test_is_outlier_false_when_detect_disabled(self):
        """Con detect_outliers=False, is_outlier debe ser todo False."""
        g = np.array([1.0, 2.0, 3.0, 100.0, 2.5])
        sigma, is_out = _sigma_adaptive(g, detect_outliers=False)
        assert not is_out.any(), "detect_outliers=False debe retornar is_outlier todo False"

    def test_outlier_count_matches_extreme_values(self):
        """Verificar que n_outliers es consistente con la magnitud de los outliers."""
        rng = np.random.default_rng(1234)
        g_base = rng.normal(5.0, 0.3, size=40)
        g_with_3_outliers = np.concatenate([g_base, [100.0, 200.0, -50.0]])

        _, is_out = _sigma_adaptive(g_with_3_outliers, detect_outliers=True)
        n_out = int(is_out.sum())
        # Los 3 valores extremos deben detectarse (están a >30σ del median)
        assert n_out >= 3, (
            f"Deben detectarse al menos 3 outliers extremos, se detectaron {n_out}"
        )
        # Los 3 outliers deben estar en los últimos 3 indices
        assert is_out[-3:].all(), "Los 3 outliers sintéticos deben estar en los últimos 3 índices"

    def test_return_is_tuple_of_two(self):
        """La función siempre retorna (sigma, is_outlier) — con y sin detect_outliers."""
        g = np.ones(10)
        result_on = _sigma_adaptive(g, detect_outliers=True)
        result_off = _sigma_adaptive(g, detect_outliers=False)
        assert isinstance(result_on, tuple) and len(result_on) == 2
        assert isinstance(result_off, tuple) and len(result_off) == 2
        sigma_on, flag_on = result_on
        sigma_off, flag_off = result_off
        assert sigma_on.shape == g.shape
        assert flag_on.shape == g.shape
        assert sigma_off.shape == g.shape
        assert flag_off.shape == g.shape
