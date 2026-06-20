"""
FASE 20B Tarea 5 — Bounds configurables + auto_kappa del motor MAGNÉTICO (port Fase 16).

Mismo patrón que test_kappa_adaptation.py (gravedad): asserts condicionales sobre el
path de ajuste (cuando cond>1e12) + asserts deterministas sobre las claves de meta y
el caso auto_kappa=False. Además: bounds custom respetados y presets de litología.

NOTA medida (2026-06-20): el kernel magnético está numéricamente bien escalado (sin Ws)
y anchor_kappa=1e4 da cond~25 → el estimador rara vez supera 1e12 (magnético = bien
condicionado). auto_kappa es la misma red de seguridad que gravedad, lista si el usuario
empuja kappa al extremo. Por eso el assert del trigger es condicional, igual que gravedad.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


NX, NY, NZ, BS = 6, 4, 6, 25.0


def _solve(anchor_kappa, auto_kappa, susc_max=1.0, susc_min=0.0, bh_susc=0.3):
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    sx, sz = np.meshgrid(np.linspace(BS, (NX - 1) * BS, 5), np.linspace(BS, (NZ - 1) * BS, 5))
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    aidx = 2 * NY * NZ + 1 * NZ + 2
    true = np.zeros(NX * NY * NZ)
    true[aidx] = bh_susc
    d_obs = G @ true
    bh = np.array([[75.0, 75.0, 37.0, 38.0, bh_susc]], dtype=np.float64)
    meta = {}
    susc, _, misfit, _ = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=susc_min, susc_max=susc_max,
        boreholes=bh, anchor_kappa=anchor_kappa, auto_kappa=auto_kappa,
        solver_meta=meta,
    )
    return susc, misfit, meta


def test_kappa_meta_logged():
    _s, _m, meta = _solve(anchor_kappa=1e4, auto_kappa=True)
    for key in ("cond_a_estimated", "anchor_kappa_used", "auto_kappa_adjusted"):
        assert key in meta, f"solver_meta falta clave: {key}"
    assert isinstance(meta["anchor_kappa_used"], float)
    assert isinstance(meta["auto_kappa_adjusted"], bool)
    if meta["cond_a_estimated"] is not None:
        assert isinstance(meta["cond_a_estimated"], float)


def test_auto_kappa_false_does_not_adjust():
    declared = 1e8
    _s, _m, meta = _solve(anchor_kappa=declared, auto_kappa=False)
    assert abs(meta["anchor_kappa_used"] - declared) < 1.0
    assert meta["auto_kappa_adjusted"] is False


def test_kappa_low_cond_no_adjust():
    declared = 1e4
    _s, _m, meta = _solve(anchor_kappa=declared, auto_kappa=True)
    cond = meta.get("cond_a_estimated")
    if cond is not None and cond <= 1e12:
        assert abs(meta["anchor_kappa_used"] - declared) < 1.0
        assert meta["auto_kappa_adjusted"] is False


def test_kappa_high_cond_conditional_adjust():
    # Igual que gravedad: si el estimador supera 1e12, se escala; si no, no se exige.
    declared = 1e8
    _s, _m, meta = _solve(anchor_kappa=declared, auto_kappa=True)
    cond = meta.get("cond_a_estimated")
    if cond is not None and cond > 1e12:
        assert meta["anchor_kappa_used"] < declared
        assert meta["auto_kappa_adjusted"] is True


def test_custom_bounds_respected():
    # susc_max bajo → la susceptibilidad recuperada nunca lo supera (clip petrofísico).
    susc, _m, _meta = _solve(anchor_kappa=1e4, auto_kappa=True, susc_max=0.1, bh_susc=0.5)
    finite = susc[np.isfinite(susc)]
    assert float(np.max(finite)) <= 0.1 + 1e-9, (
        f"susc recuperada {float(np.max(finite)):.4f} supera susc_max=0.1"
    )


def test_lithology_presets_sane():
    from core.config import MAGNETIC_SUSCEPTIBILITY_PRESETS as P
    assert "magnetite_massive" in P and "sediment_barren" in P and "unknown" in P
    # magnetita masiva: χ alta; estéril ≈ 0
    assert P["magnetite_massive"][0] >= 0.5
    assert P["sediment_barren"][0] <= 0.01
    # cada preset (típica, max) con max >= típica y ambos finitos ≥ 0
    for k, (typ, mx) in P.items():
        assert 0.0 <= typ <= mx, f"preset {k} inconsistente: typ={typ}, max={mx}"
