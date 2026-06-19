"""
Fase 16 — Tests de bounds configurables (density_min/max/base_density).

Verifica que la inversión respeta los bounds petrofísicos declarados y que
la validación del schema rechaza configuraciones inválidas.

Casos:
  - test_granite_bounds_ok: bounds granito (2.6–3.0) → densidades en rango
  - test_magnetite_bounds_ok: bounds magnetita (4.5–5.5) → densidades en rango
  - test_custom_bounds_respected: bounds personalizados (3.0–4.5) → m ∈ rango
  - test_bounds_validation: density_max < density_min → ValidationError
  - test_kappa_scaling: inversión con kappas custom completa sin error
"""
import numpy as np
import pytest

from exploration.gravimetry import GravimetryInversion, GravimetryForward


# ── Problema sintético mínimo ─────────────────────────────────────────────────

NX, NY, NZ = 4, 4, 4
BS = 30.0  # metros por vóxel


def _build_problem(density_min=0.0, density_max=5.5, base_density=2.6,
                   padding_kappa=1e5, anchor_kappa=1e4, auto_kappa=True,
                   seed=7):
    """Construye inversor + forward + datos sintéticos para NX×NY×NZ=64 vóxeles."""
    rng = np.random.default_rng(seed)

    inv = GravimetryInversion(NX, NY, NZ, BS)
    fwd = GravimetryForward(dx=BS, dy=BS, dz=BS, cutoff_radius=BS * 8)

    ix, iy, iz = np.meshgrid(
        np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij"
    )
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS

    # 12 sensores superficiales en y=0
    xs_s = np.linspace(BS, (NX - 1) * BS, 4)
    zs_s = np.linspace(BS, (NZ - 1) * BS, 3)
    xg, zg = np.meshgrid(xs_s, zs_s)
    sensor_coords = np.column_stack([xg.ravel(), np.zeros(12), zg.ravel()])

    # Densidad sintética: anomalía central
    mid = NX * NY * NZ // 2
    true_contrast = np.zeros(NX * NY * NZ)
    true_contrast[mid] = 0.3
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    g_obs = G @ true_contrast + 1e-8 * rng.standard_normal(12)

    return inv, fwd, x_c, y_c, z_c, sensor_coords, g_obs


def _run(density_min, density_max, base_density=2.6,
         padding_kappa=1e5, anchor_kappa=1e4, auto_kappa=True):
    inv, fwd, x_c, y_c, z_c, sc, g_obs = _build_problem(
        density_min=density_min, density_max=density_max, base_density=base_density,
    )
    meta: dict = {}
    est_density, _, _, _ = inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=1.0, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sc,
        x_c=x_c, z_c=z_c,
        density_min=density_min, density_max=density_max,
        padding_kappa=padding_kappa, anchor_kappa=anchor_kappa,
        auto_kappa=auto_kappa,
        solver_meta=meta,
    )
    active = est_density[np.isfinite(est_density)]
    return active, meta


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_granite_bounds_ok():
    """Bounds granito (2.6–3.0): todas las densidades activas en [2.6, 3.0]."""
    densities, _ = _run(density_min=2.6, density_max=3.0, base_density=2.6)
    assert len(densities) > 0
    assert float(np.min(densities)) >= 2.6 - 1e-6, \
        f"Min densidad {np.min(densities):.4f} < 2.6 (granito)"
    assert float(np.max(densities)) <= 3.0 + 1e-6, \
        f"Max densidad {np.max(densities):.4f} > 3.0 (granito)"


def test_magnetite_bounds_ok():
    """Bounds magnetita (4.5–5.5): todas las densidades activas en [4.5, 5.5]."""
    densities, _ = _run(density_min=4.5, density_max=5.5, base_density=4.5)
    assert len(densities) > 0
    assert float(np.min(densities)) >= 4.5 - 1e-6, \
        f"Min densidad {np.min(densities):.4f} < 4.5 (magnetita)"
    assert float(np.max(densities)) <= 5.5 + 1e-6, \
        f"Max densidad {np.max(densities):.4f} > 5.5 (magnetita)"


def test_custom_bounds_respected():
    """Bounds personalizados (3.0–4.5): todas las densidades activas en rango."""
    densities, _ = _run(density_min=3.0, density_max=4.5, base_density=3.0)
    assert len(densities) > 0
    assert float(np.min(densities)) >= 3.0 - 1e-6, \
        f"Min densidad {np.min(densities):.4f} < 3.0 (custom)"
    assert float(np.max(densities)) <= 4.5 + 1e-6, \
        f"Max densidad {np.max(densities):.4f} > 4.5 (custom)"


def test_bounds_validation():
    """density_max <= density_min debe lanzar ValidationError."""
    from pydantic import ValidationError
    from schemas.geophysics_schema import GeophysicsInvertInput

    rng = np.random.default_rng(0)
    g_vals = (1e-6 * rng.standard_normal(12)).tolist()
    xs = np.tile([5.0, 15.0, 25.0], 4).tolist()
    zs = np.repeat([5.0, 15.0, 25.0, 35.0], 3).tolist()
    observations = [
        {"x_m": float(x), "y_m": 0.0, "z_m": float(z), "g": float(g)}
        for x, z, g in zip(xs, zs, g_vals)
    ]

    with pytest.raises(ValidationError, match="density_min"):
        GeophysicsInvertInput(
            project_id="test", run_id="test",
            depth=20, nir=80, fe=75,
            region="norte_chile", lat="-22.0", lon="-68.0",
            nx=6, ny=4, nz=6,
            block_size=10, cutoff_radius=500,
            lambda_mag=1.0, alpha_spatial=1.0,
            observations=observations,
            density_min=5.0,   # density_min > density_max → inválido
            density_max=2.0,
        )


def test_kappa_scaling():
    """Kappas custom (1e4/1e3) con auto_kappa=False → padding_kappa_used = 1e4."""
    densities, meta = _run(
        density_min=0.0, density_max=5.5,
        padding_kappa=1e4, anchor_kappa=1e3, auto_kappa=False,
    )
    assert len(densities) > 0, "La inversión no produjo vóxeles activos"
    assert "padding_kappa_used" in meta, "solver_meta falta clave padding_kappa_used"
    # Sin auto_kappa, el valor usado debe ser exactamente el declarado
    assert abs(meta["padding_kappa_used"] - 1e4) < 1.0, \
        f"padding_kappa_used ({meta['padding_kappa_used']:.2e}) ≠ 1e4 declarado"
