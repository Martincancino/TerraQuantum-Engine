"""
Fase 15 — Test de compatibilidad de poda R-05 con inversión conjunta.

Verifica que joint inversion con joint_observable_pruning=True (Joint v1.1) produce
resultados comparables a joint_observable_pruning=False (v1.0) y que en ambos casos
los vóxeles muertos no divergen.

Casos:
  - test_joint_prune_vs_no_prune: misfit comparable (±15%), n_dead=0 en ambos
  - test_joint_no_prune_dead_voxels_finite: sanity check — dead voxels sin poda ≤ density_max
"""
import numpy as np
import pytest


# Tolerancia de misfit relativo entre versiones (15% = holgado; diferencias numéricas
# son esperadas porque prune cambia el espacio del problema).
MISFIT_REL_TOL = 0.15

# ── Fixture de datos sintéticos (depósito simple, 12 sensores) ────────────────

def _make_synthetic_params(project_id, run_id, prune: bool, nx=6, ny=4, nz=6):
    from schemas.geophysics_schema import GeophysicsInvertInput

    rng = np.random.default_rng(7)
    # Señal gravimétrica: anomalía positiva pequeña (depósito denso)
    g_vals = 1e-6 * (1.0 + 0.2 * rng.standard_normal(12))
    # Señal magnética: anomalía positiva (depósito susceptible)
    nt_vals = 5.0 + 1.5 * rng.standard_normal(12)

    xs = np.tile([5.0, 15.0, 25.0, 35.0], 3).tolist()
    zs = np.repeat([5.0, 15.0, 25.0], 4).tolist()

    observations = [
        {"x_m": float(x), "y_m": 0.0, "z_m": float(z), "g": float(g)}
        for x, z, g in zip(xs, zs, g_vals)
    ]

    return GeophysicsInvertInput(
        project_id=project_id,
        run_id=run_id,
        depth=20, nir=83, fe=79,
        region="norte_chile", lat="-22.28", lon="-68.89",
        nx=nx, ny=ny, nz=nz,
        block_size=8, cutoff_radius=400,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=observations,
        magnetic_nt=list(nt_vals),
        inclination=60.0, declination=-5.0,
        joint_max_iter=2,
        cross_lambda_beta=0.01,
        joint_observable_pruning=prune,
    )


# ── TAREA 3: Test poda ON vs OFF — misfit comparable, n_dead=0 ────────────────

def test_joint_prune_vs_no_prune(test_project_id, test_run_id):
    """Joint v1.1 con poda=True produce misfit comparable a v1.0 (±15%) y n_dead=0."""
    from services.geophysics_service import run_geophysics_inversion

    params_prune = _make_synthetic_params(test_project_id, test_run_id + "_prune", prune=True)
    params_no_prune = _make_synthetic_params(test_project_id, test_run_id + "_noprune", prune=False)

    res_prune = run_geophysics_inversion(params_prune)
    res_no_prune = run_geophysics_inversion(params_no_prune)

    report_p = res_prune.get("report", {})
    report_np = res_no_prune.get("report", {})

    # Ambas inversiones deben producir un resultado (no error)
    assert "voxels" in res_prune or "block_model" in res_prune or report_p, \
        "Joint con poda no devolvió resultado"
    assert "voxels" in res_no_prune or "block_model" in res_no_prune or report_np, \
        "Joint sin poda no devolvió resultado"

    # Misfit gravimétrico comparable
    hist_p = report_p.get("joint_history", [])
    hist_np = report_np.get("joint_history", [])
    if hist_p and hist_np:
        mf_p = hist_p[-1].get("misfit_gravity_percent", None)
        mf_np = hist_np[-1].get("misfit_gravity_percent", None)
        if mf_p is not None and mf_np is not None and mf_np > 0:
            rel_diff = abs(mf_p - mf_np) / (abs(mf_np) + 1e-9)
            assert rel_diff <= MISFIT_REL_TOL, (
                f"Misfit gravimétrico difiere demasiado entre prune={True} ({mf_p:.3f}%) "
                f"y prune={False} ({mf_np:.3f}%): diff relativa = {rel_diff:.2%} > {MISFIT_REL_TOL:.0%}"
            )

    # solver_meta: n_dead debe ser 0 con poda activada (o no reportarse)
    solver_meta_p = report_p.get("solver_meta", {})
    n_dead_prune = solver_meta_p.get("n_dead_voxels", 0)
    assert n_dead_prune == 0, (
        f"Con joint_observable_pruning=True se esperan 0 vóxeles muertos en el solver, "
        f"pero se encontraron {n_dead_prune}"
    )


# ── Sanity check: dead voxels no divergen sin poda ────────────────────────────

def test_joint_no_prune_dead_voxels_finite(test_project_id, test_run_id):
    """Sin poda (v1.0), los vóxeles muertos no divergen: densidad dentro de bounds."""
    from services.geophysics_service import run_geophysics_inversion

    params = _make_synthetic_params(
        test_project_id, test_run_id + "_sanity", prune=False
    )
    result = run_geophysics_inversion(params)

    # Extraer densidades del resultado
    voxels = result.get("voxels") or result.get("block_model", {}).get("voxels", [])
    if not voxels:
        # Alternativa: leer desde report si voxels no está en response
        pytest.skip("Voxels no en response; skip sanity (structure OK si no raise)")

    densities = [v.get("density_t_m3", v.get("density", None)) for v in voxels]
    densities = [d for d in densities if d is not None]
    if not densities:
        pytest.skip("No hay densidades en voxels para verificar")

    arr = np.array(densities, dtype=np.float64)
    assert np.isfinite(arr).all(), "Densidades no finitas en joint sin poda (vóxeles divergentes)"
    assert float(np.max(arr)) <= params.density_max + 1e-6, (
        f"Densidad máxima {float(np.max(arr)):.4f} supera density_max={params.density_max}"
    )
    assert float(np.min(arr)) >= params.density_min - 1e-6, (
        f"Densidad mínima {float(np.min(arr)):.4f} bajo density_min={params.density_min}"
    )
