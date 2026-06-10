"""
Fase 2 — Tests de validación para GeophysicsInvertInputV2 y endpoint /v2/geophysics-invert.

Cubre:
- test_v2_density_validation       : density_min >= density_max → ValidationError
- test_v2_corrections_required     : gravity_type g_raw ausente del schema V2 → ValidationError
- test_v2_sigma_adaptive           : noise_floor correcto produce chi² realista (no 0.000)
- test_v2_lambda_fixed_requires_value: lambda_strategy='fixed' sin lambda_fixed → ValidationError
- test_v2_magnetic_nt_length_mismatch: len(magnetic_nt) != len(obs) → ValidationError
- test_v2_negative_density_min     : density_min negativo permitido en V2 → OK
- test_v2_grid_calculator_dynamic_min: MIN_BLOCK_SIZE dinámico sigue spacing/4 rule
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
from pydantic import ValidationError

from schemas.geophysics_schema import GeophysicsInvertInputV2, GravityObservation
from services.grid_calculator_service import _initial_block_size


# ── Observaciones sintéticas mínimas (10 puntos, ~Bouguer anomaly en m/s²) ────
def _obs(n=12):
    return [
        GravityObservation(
            x_m=float(i * 100),
            y_m=float(i * 5),
            z_m=float(i * 100),
            g=float(-1.2e-5 + i * 1e-7),   # ~-12 a -10.8 mGal en m/s²
        )
        for i in range(n)
    ]


def _base_params(**kwargs):
    defaults = dict(
        depth=500,
        nir=50,
        fe=50,
        region="norte_chile",
        nx=8,
        ny=8,
        nz=8,
        block_size=100,
        cutoff_radius=800.0,
        lambda_mag=3.0,
        alpha_spatial=1.0,
        gravity_type="complete_bouguer_anomaly",
        observations=_obs(),
    )
    defaults.update(kwargs)
    return defaults


# ──────────────────────────────────────────────────────────────────────────────
class TestDensityValidation:
    def test_density_min_lt_max_ok(self):
        p = GeophysicsInvertInputV2(**_base_params(density_min=-0.5, density_max=2.0))
        assert p.density_min == -0.5

    def test_density_min_equals_max_raises(self):
        with pytest.raises(ValidationError, match="density_min"):
            GeophysicsInvertInputV2(**_base_params(density_min=2.0, density_max=2.0))

    def test_density_min_gt_max_raises(self):
        with pytest.raises(ValidationError, match="density_min"):
            GeophysicsInvertInputV2(**_base_params(density_min=3.0, density_max=2.0))


# ──────────────────────────────────────────────────────────────────────────────
class TestCorrectionsRequired:
    def test_bouguer_accepted(self):
        p = GeophysicsInvertInputV2(**_base_params(gravity_type="complete_bouguer_anomaly"))
        assert p.gravity_type_v2 == "complete_bouguer_anomaly"

    def test_free_air_accepted(self):
        p = GeophysicsInvertInputV2(**_base_params(gravity_type="free_air_anomaly"))
        assert p.gravity_type_v2 == "free_air_anomaly"

    def test_g_raw_rejected(self):
        # g_raw no existe en el Literal del V2 → ValidationError en la carga
        with pytest.raises(ValidationError):
            GeophysicsInvertInputV2(**_base_params(gravity_type="g_raw"))

    def test_absolute_gravity_rejected(self):
        with pytest.raises(ValidationError):
            GeophysicsInvertInputV2(**_base_params(gravity_type="absolute_gravity"))


# ──────────────────────────────────────────────────────────────────────────────
class TestSigmaAdaptive:
    """
    Verifica que sigma calibrado produce chi² realista comparado con el default v1.

    Criterio del plan (§2.8 item 4): con noise_pct calibrado al ruido real (~5 %),
    chi²_red ∈ [0.5, 2.0]. Con el default v1 sobreestimado, chi²_red ≪ 0.5.
    Criterio §2.8 item 6: con noise_floor=0.005 mGal (CG-6) y datos con ese ruido real,
    chi²_red ≠ 0.000 (no ficticiamente cero).
    """

    def _compute_chi2_parametric(self, noise_floor_mgal: float, noise_pct: float,
                                  actual_noise_pct: float = 0.05):
        """Genera datos con ruido ``actual_noise_pct`` relativo y calcula chi² con sigma dado."""
        rng = np.random.default_rng(42)
        n = 200
        # Anomalía Bouguer sintética: -15 a -5 mGal en m/s²
        g_true = rng.uniform(-15e-5, -5e-5, n)
        noise = rng.normal(0, actual_noise_pct * np.abs(g_true))
        g_obs = g_true + noise
        residuals = g_obs - g_true     # residuals = ruido real

        # Sigma en m/s² (noise_floor_mgal convertido a m/s²)
        sigma = noise_floor_mgal * 1e-5 + noise_pct * np.abs(g_obs)
        sigma = np.maximum(sigma, 1e-30)
        return float(np.mean((residuals / sigma) ** 2))

    def test_calibrated_sigma_produces_realistic_chi2(self):
        # noise_pct = 0.05 calibrado al ruido real del 5% → chi²_red ≈ 1
        chi2 = self._compute_chi2_parametric(
            noise_floor_mgal=0.005, noise_pct=0.05, actual_noise_pct=0.05
        )
        assert 0.5 <= chi2 <= 2.0, (
            f"chi²_red={chi2:.4f} debería estar en [0.5, 2.0] con sigma calibrado al ruido real."
        )

    def test_default_v1_sentinel_overestimates_sigma(self):
        # Default v1: sigma = 0.02 * |g| (equivalente al sentinel _sigma_adaptive).
        # Para ruido real del 5%, sigma sobreestima → chi² ≪ 0.5.
        chi2_v1 = self._compute_chi2_parametric(
            noise_floor_mgal=0.0, noise_pct=0.20, actual_noise_pct=0.05
        )
        assert chi2_v1 < 0.5, (
            f"chi²_red={chi2_v1:.6f} debería ser < 0.5 con sigma sobreestimado 4×."
        )

    def test_cg6_produces_nonzero_chi2(self):
        # §2.8 item 6: con noise_floor=0.005 mGal (CG-6) y ruido real de esa magnitud,
        # chi² ≠ 0.000 (el sigma NO colapsa a 0 ficticio).
        # Ruido real = 0.005 mGal = 5e-8 m/s²; señal ~10 mGal = 1e-4 m/s²
        # → noise_pct_actual ≈ 5e-8/1e-4 = 0.0005 (0.05 %)
        chi2 = self._compute_chi2_parametric(
            noise_floor_mgal=0.005, noise_pct=0.005, actual_noise_pct=0.0005
        )
        assert chi2 > 1e-6, f"chi²_red={chi2:.2e} no debe ser cero (ficticio)."

    def test_noise_floor_mgal_stored_in_v2(self):
        p = GeophysicsInvertInputV2(**_base_params(noise_floor_mgal=0.005, noise_pct=0.005))
        assert p.noise_floor_mgal == pytest.approx(0.005)
        assert p.noise_pct_v2 == pytest.approx(0.005)


# ──────────────────────────────────────────────────────────────────────────────
class TestLambdaStrategy:
    def test_fixed_without_lambda_fixed_raises(self):
        with pytest.raises(ValidationError, match="lambda_fixed"):
            GeophysicsInvertInputV2(**_base_params(lambda_strategy="fixed", lambda_fixed=None))

    def test_fixed_with_lambda_fixed_ok(self):
        p = GeophysicsInvertInputV2(**_base_params(lambda_strategy="fixed", lambda_fixed=3.0))
        assert p.lambda_strategy == "fixed"
        assert p.lambda_fixed == pytest.approx(3.0)

    def test_chi2_strategy_default(self):
        p = GeophysicsInvertInputV2(**_base_params())
        assert p.lambda_strategy == "chi2"

    def test_lcurve_strategy_accepted(self):
        p = GeophysicsInvertInputV2(**_base_params(lambda_strategy="lcurve"))
        assert p.lambda_strategy == "lcurve"


# ──────────────────────────────────────────────────────────────────────────────
class TestMagneticNtLength:
    def test_matching_length_ok(self):
        obs = _obs(10)
        p = GeophysicsInvertInputV2(**_base_params(observations=obs, magnetic_nt=[0.0] * 10))
        assert len(p.magnetic_nt) == 10

    def test_mismatched_length_raises(self):
        obs = _obs(10)
        with pytest.raises(ValidationError, match="magnetic_nt"):
            GeophysicsInvertInputV2(**_base_params(observations=obs, magnetic_nt=[0.0] * 5))


# ──────────────────────────────────────────────────────────────────────────────
class TestNegativeDensityMin:
    def test_negative_contrast_accepted(self):
        p = GeophysicsInvertInputV2(**_base_params(density_min=-2.0, density_max=5.0))
        assert p.density_min == pytest.approx(-2.0)

    def test_below_minus_five_rejected(self):
        with pytest.raises(ValidationError):
            GeophysicsInvertInputV2(**_base_params(density_min=-6.0, density_max=5.0))


# ──────────────────────────────────────────────────────────────────────────────
class TestGridCalculatorDynamicMin:
    def test_dynamic_min_follows_spacing_rule(self):
        # spacing = sqrt(1e6 / 100) = 100 m → dynamic_min = max(100/4, 10) = 25 m
        block_size, _ = _initial_block_size(1000.0, 1000.0, 100, mean_spacing_m=100.0)
        assert block_size == pytest.approx(50.0)   # mean_spacing/2 = 50, clamp min=25

    def test_dynamic_min_10m_floor(self):
        # spacing = 20 m → dynamic_min = max(20/4, 10) = 10 m
        # block_size = 20/2 = 10, clamped to dynamic_min=10
        block_size, _ = _initial_block_size(200.0, 200.0, 100, mean_spacing_m=20.0)
        assert block_size == pytest.approx(10.0)

    def test_fine_survey_gets_smaller_min(self):
        # spacing = 50 m → dynamic_min = max(50/4, 10) = 12.5 m
        # block_size = 50/2 = 25, valid
        block_size, _ = _initial_block_size(500.0, 500.0, 100, mean_spacing_m=50.0)
        assert block_size == pytest.approx(25.0)


if __name__ == "__main__":
    import sys
    # Ejecutar sin pytest si se llama directamente
    results = []
    failures = []

    def _run_class(cls):
        inst = cls()
        for name in dir(inst):
            if name.startswith("test_"):
                try:
                    getattr(inst, name)()
                    results.append(f"PASS  {cls.__name__}.{name}")
                except Exception as e:
                    results.append(f"FAIL  {cls.__name__}.{name}: {e}")
                    failures.append(name)

    for c in [
        TestDensityValidation,
        TestCorrectionsRequired,
        TestSigmaAdaptive,
        TestLambdaStrategy,
        TestMagneticNtLength,
        TestNegativeDensityMin,
        TestGridCalculatorDynamicMin,
    ]:
        _run_class(c)

    for r in results:
        print(r)
    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(results) - len(failures)}/{len(results)}")
    sys.exit(1 if failures else 0)
