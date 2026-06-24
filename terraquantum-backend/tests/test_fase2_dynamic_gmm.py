"""
FASE 2.2 (God-Tier) — GMM DINÁMICO (PGIEngine.refit) con prior NIW.

El PGI de Fase 11 usa un GMM ESTÁTICO: means/stds/weights fijos; el bucle solo
reasigna la clase MAP. La Fase 2.2 añade `refit()` (Astic & Oldenburg 2019, §3.2):
un paso EM MAP que re-estima la mixtura del modelo invertido, REGULARIZADO hacia
el prior petrofísico vía Normal-Inverse-Wishart (medias/varianzas) + Dirichlet (pesos).

Estos tests verifican:
  1) refit ADAPTA las medias hacia el dato cuando el prior es débil (κ0,ν0 bajos);
  2) el prior FUERTE (κ0,ν0 altos) mantiene las medias ≈ prior (≈ estático);
  3) una componente sin celdas NO colapsa (NIW la deja en el prior, sin NaN);
  4) los pesos siguen las proporciones del dato (Dirichlet);
  5) refit NO toca el prior inmutable (_prior_*);
  6) el kernel 2D ρ-χ recupera dos clústeres y mantiene SPD (fundación Fase 3).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from exploration.pgi_engine import (
    PGIEngine,
    gmm_responsibilities_2d,
    niw_map_update_2d,
)


BASE = 2.67


def _engine(means, stds, weights):
    return PGIEngine(means=means, stds=stds, weights=weights,
                     alpha_pgi=0.1, base_density=BASE)


def _data_contrast(means_abs, n_each=400, noise=0.02, seed=7):
    """Modelo sintético (contraste) con clústeres en means_abs."""
    rng = np.random.default_rng(seed)
    blocks = [rng.normal(m, noise, n_each) for m in means_abs]
    return np.concatenate(blocks) - BASE


# ── 1) Prior DÉBIL: las medias se adaptan al dato ───────────────────────────
def test_refit_adapts_means_with_weak_prior():
    # Prior en 2.70/3.00/3.60; dato realmente en 2.80/3.00/3.40.
    eng = _engine([2.70, 3.00, 3.60], [0.10, 0.10, 0.10], [0.34, 0.33, 0.33])
    data = _data_contrast([2.80, 3.00, 3.40])
    means0 = eng.means.copy()
    info = eng.refit(data, prior_kappa=1.0, prior_nu=1.0, weight_concentration=1.0)

    assert info["n_cells"] == data.size
    # La 1ª media sube hacia 2.80, la 3ª baja hacia 3.40 (se acercan al dato).
    assert eng.means[0] > means0[0] + 0.02
    assert eng.means[2] < means0[2] - 0.05
    assert abs(eng.means[0] - 2.80) < abs(means0[0] - 2.80)
    assert abs(eng.means[2] - 3.40) < abs(means0[2] - 3.40)


# ── 2) Prior FUERTE: las medias se quedan ≈ prior (≈ estático) ──────────────
def test_refit_strong_prior_stays_near_prior():
    eng = _engine([2.70, 3.00, 3.60], [0.10, 0.10, 0.10], [0.34, 0.33, 0.33])
    data = _data_contrast([2.80, 3.00, 3.40])
    means0 = eng.means.copy()
    eng.refit(data, prior_kappa=1e5, prior_nu=1e5)
    # Con κ0,ν0 enormes el dato casi no mueve las medias.
    assert np.allclose(eng.means, means0, atol=1e-2)


# ── 3) Componente vacía NO colapsa (NIW la deja en el prior) ────────────────
def test_refit_empty_component_no_collapse():
    # Prior con una clase muy lejos del dato (4.50) → no recibe celdas.
    eng = _engine([2.70, 3.00, 4.50], [0.10, 0.10, 0.15], [0.4, 0.4, 0.2])
    data = _data_contrast([2.70, 3.00, 3.00])   # nada cerca de 4.50
    eng.refit(data, prior_kappa=10.0, prior_nu=10.0)
    assert np.all(np.isfinite(eng.means))
    assert np.all(np.isfinite(eng.stds))
    assert np.all(eng.stds > 0.0)
    # La componente huérfana se mantiene cerca del prior (no se va a NaN/0).
    assert abs(eng.means[2] - 4.50) < 0.20
    assert np.isclose(eng.weights.sum(), 1.0)


# ── 4) Los pesos siguen las proporciones del dato ───────────────────────────
def test_refit_weights_track_data_proportions():
    eng = _engine([2.70, 3.40], [0.10, 0.10], [0.5, 0.5])
    rng = np.random.default_rng(3)
    # 80% en 2.70, 20% en 3.40.
    data = np.concatenate([
        rng.normal(2.70, 0.02, 800),
        rng.normal(3.40, 0.02, 200),
    ]) - BASE
    eng.refit(data, prior_kappa=5.0, prior_nu=5.0, weight_concentration=1.0)
    assert eng.weights[0] > eng.weights[1]
    assert eng.weights[0] > 0.6   # claramente mayoritaria


# ── 5) refit NO muta el prior inmutable ─────────────────────────────────────
def test_refit_preserves_immutable_prior():
    eng = _engine([2.70, 3.00, 3.60], [0.10, 0.10, 0.10], [0.34, 0.33, 0.33])
    p_means = eng._prior_means.copy()
    p_vars = eng._prior_vars.copy()
    p_w = eng._prior_weights.copy()
    eng.refit(_data_contrast([2.90, 3.10, 3.30]), prior_kappa=1.0, prior_nu=1.0)
    assert np.array_equal(eng._prior_means, p_means)
    assert np.array_equal(eng._prior_vars, p_vars)
    assert np.array_equal(eng._prior_weights, p_w)


# ── 6) Kernel 2D ρ-χ: recupera 2 clústeres y mantiene SPD (fundación F3) ─────
def test_niw_2d_recovers_two_clusters():
    rng = np.random.default_rng(11)
    # Clúster A: ρ≈2.7, χ≈0.0 (estéril). Clúster B: ρ≈3.4, χ≈0.4 (magnetita).
    A = rng.multivariate_normal([2.70, 0.00], np.diag([0.02**2, 0.01**2]), 500)
    B = rng.multivariate_normal([3.40, 0.40], np.diag([0.03**2, 0.03**2]), 500)
    X = np.vstack([A, B])

    prior_means = np.array([[2.80, 0.05], [3.20, 0.30]])   # prior desplazado
    prior_covs = np.array([np.diag([0.1**2, 0.1**2])] * 2)
    prior_w = np.array([0.5, 0.5])

    # E-step con el prior, M-step MAP (prior débil para que se adapte).
    resp = gmm_responsibilities_2d(X, prior_means, prior_covs, prior_w)
    means, covs, weights = niw_map_update_2d(
        X, resp, prior_means, prior_covs, prior_w,
        prior_kappa=1.0, prior_nu=2.0, weight_concentration=1.0,
    )
    # Las medias se mueven hacia los clústeres reales.
    assert abs(means[0, 0] - 2.70) < 0.10 and abs(means[0, 1] - 0.00) < 0.10
    assert abs(means[1, 0] - 3.40) < 0.10 and abs(means[1, 1] - 0.40) < 0.10
    # Covarianzas SPD (autovalores > 0) y pesos normalizados.
    for k in range(2):
        assert np.all(np.linalg.eigvalsh(covs[k]) > 0)
    assert np.isclose(weights.sum(), 1.0)


def test_refit_empty_input_is_noop():
    eng = _engine([2.70, 3.40], [0.10, 0.10], [0.5, 0.5])
    means0 = eng.means.copy()
    info = eng.refit(np.array([]), prior_kappa=1.0, prior_nu=1.0)
    assert info["n_cells"] == 0
    assert np.array_equal(eng.means, means0)
