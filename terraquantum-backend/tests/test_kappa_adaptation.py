"""
Fase 16 — Tests de dynamic kappa adaptation.

Verifica que el solver escala kappas automáticamente cuando cond(A) > 1e12,
y que los valores usados quedan registrados en solver_meta.

Casos:
  - test_kappa_adaptation_high_cond: kappas muy altos (1e8) → si cond > 1e12
    → padding_kappa_used < padding_kappa (auto-scale activado)
  - test_kappa_adaptation_low_cond: kappas default → cond normal → sin cambio
  - test_solver_meta_kappas_logged: solver_meta contiene las 4 claves de diagnóstico
  - test_auto_kappa_false_does_not_adjust: auto_kappa=False → kappas exactos
"""
import numpy as np

from exploration.gravimetry import GravimetryInversion, GravimetryForward


# ── Problema sintético ────────────────────────────────────────────────────────

NX, NY, NZ = 4, 4, 4
BS = 30.0


def _build_and_solve(padding_kappa: float, anchor_kappa: float, auto_kappa: bool):
    """Construye un problema 4×4×4 y llama a solve_inversion_lsqr. Retorna solver_meta."""
    rng = np.random.default_rng(99)

    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 8)

    ix, iy, iz = np.meshgrid(
        np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij"
    )
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS

    xs_s = np.linspace(BS, (NX - 1) * BS, 4)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 3)
    xg, zg = np.meshgrid(xs_s, zs_s)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(12), zg.ravel()])

    mid = NX * NY * NZ // 2
    true_contrast = np.zeros(NX * NY * NZ)
    true_contrast[mid] = 0.3
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ true_contrast + 1e-8 * rng.standard_normal(12)

    meta: dict = {}
    inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensor_coords,
        x_c=x_c, z_c=z_c,
        density_min=0.0, density_max=5.5,
        padding_kappa=padding_kappa,
        anchor_kappa=anchor_kappa,
        auto_kappa=auto_kappa,
        solver_meta=meta,
    )
    return meta


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_kappa_adaptation_high_cond():
    """Kappas extremos (1e8): si cond > 1e12, padding_kappa_used < 1e8."""
    meta = _build_and_solve(padding_kappa=1e8, anchor_kappa=1e7, auto_kappa=True)

    assert "cond_a_estimated" in meta
    assert "padding_kappa_used" in meta
    assert "anchor_kappa_used" in meta
    assert "auto_kappa_adjusted" in meta

    cond = meta["cond_a_estimated"]
    kappa_used = meta["padding_kappa_used"]
    adjusted = meta["auto_kappa_adjusted"]

    if cond is not None and cond > 1e12:
        assert kappa_used < 1e8, (
            f"Con cond={cond:.2e} > 1e12, padding_kappa_used ({kappa_used:.2e}) "
            "debería ser < 1e8 (scale_factor aplicado)."
        )
        assert adjusted is True, "auto_kappa_adjusted debe ser True cuando se escala"


def test_kappa_adaptation_low_cond():
    """Kappas default (1e5): si cond <= 1e12, padding_kappa_used = 1e5 sin cambio."""
    meta = _build_and_solve(padding_kappa=1e5, anchor_kappa=1e4, auto_kappa=True)

    assert "padding_kappa_used" in meta

    cond = meta.get("cond_a_estimated")
    kappa_used = meta["padding_kappa_used"]
    adjusted = meta.get("auto_kappa_adjusted", False)

    if cond is not None and cond <= 1e12:
        assert abs(kappa_used - 1e5) < 1.0, (
            f"Con cond={cond:.2e} <= 1e12, padding_kappa_used ({kappa_used:.2e}) "
            "debe ser igual al declarado (1e5)."
        )
        assert adjusted is False, "auto_kappa_adjusted debe ser False cuando no se ajusta"


def test_solver_meta_kappas_logged():
    """solver_meta siempre contiene las 4 claves de diagnóstico de kappa."""
    meta = _build_and_solve(padding_kappa=1e5, anchor_kappa=1e4, auto_kappa=True)

    required_keys = [
        "cond_a_estimated",
        "padding_kappa_used",
        "anchor_kappa_used",
        "auto_kappa_adjusted",
    ]
    for key in required_keys:
        assert key in meta, f"solver_meta falta clave requerida: '{key}'"

    assert isinstance(meta["padding_kappa_used"], float), "padding_kappa_used debe ser float"
    assert isinstance(meta["anchor_kappa_used"], float), "anchor_kappa_used debe ser float"
    assert isinstance(meta["auto_kappa_adjusted"], bool), "auto_kappa_adjusted debe ser bool"
    if meta["cond_a_estimated"] is not None:
        assert isinstance(meta["cond_a_estimated"], float), "cond_a_estimated debe ser float"


def test_auto_kappa_false_does_not_adjust():
    """Con auto_kappa=False, kappas se usan exactamente como declarados."""
    declared = 1e8
    meta = _build_and_solve(padding_kappa=declared, anchor_kappa=1e7, auto_kappa=False)

    kappa_used = meta.get("padding_kappa_used")
    adjusted = meta.get("auto_kappa_adjusted", True)

    assert kappa_used is not None
    assert abs(kappa_used - declared) < 1.0, (
        f"Con auto_kappa=False, padding_kappa_used ({kappa_used:.2e}) "
        f"debe ser igual al declarado ({declared:.0e})."
    )
    assert adjusted is False, "auto_kappa_adjusted debe ser False cuando auto_kappa=False"
