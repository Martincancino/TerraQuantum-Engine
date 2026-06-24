"""
FASE 0 Tarea 0.3 — Continuation joint: escalón → log-homotopía.

El bucle conjunto usaba  lambda_cross = 1.0 if k>=2 else 0.0  (escalón binario),
pero el docstring promete "continuation exponencial". Ahora, en modo 'log'
(default), el peso cross-gradient sube log-homotópicamente 0.01→1.0 para k≥2.
El modo 'step' conserva el comportamiento histórico (rollback).

Verifica vía joint_history["lambda_cross_raw"]:
  - modo 'log': k=1 → 0; k≥2 estrictamente creciente hasta ~1.0;
  - modo 'step': k≥2 constante = 1.0.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from schemas.geophysics_schema import GeophysicsInvertInput


def _joint_params(project_id, run_id, mode, nx=6, ny=4, nz=6):
    rng = np.random.default_rng(7)
    g_vals = 1e-6 * (1.0 + 0.2 * rng.standard_normal(12))
    nt_vals = 5.0 + 1.5 * rng.standard_normal(12)
    xs = np.tile([5.0, 15.0, 25.0, 35.0], 3).tolist()
    zs = np.repeat([5.0, 15.0, 25.0], 4).tolist()
    observations = [
        {"x_m": float(x), "y_m": 0.0, "z_m": float(z), "g": float(g)}
        for x, z, g in zip(xs, zs, g_vals)
    ]
    return GeophysicsInvertInput(
        project_id=project_id, run_id=run_id,
        depth=20, nir=83, fe=79,
        region="norte_chile", lat="-22.28", lon="-68.89",
        nx=nx, ny=ny, nz=nz, block_size=8, cutoff_radius=400,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=observations, magnetic_nt=list(nt_vals),
        inclination=60.0, declination=-5.0,
        joint_max_iter=4, cross_lambda_beta=0.05,
        joint_continuation_mode=mode,
    )


def _raw_sequence(report):
    hist = report.get("convergence_history", [])
    # Entradas del bucle (iter>=1), en orden.
    loop = [h for h in hist if h.get("iter", 0) >= 1]
    return [(h["iter"], h["lambda_cross_raw"]) for h in loop]


def test_schema_default_is_log():
    assert GeophysicsInvertInput.model_fields["joint_continuation_mode"].default == "log"


def test_log_continuation_monotonic(test_project_id, test_run_id):
    from services.geophysics_service import run_geophysics_inversion

    res = run_geophysics_inversion(_joint_params(test_project_id, test_run_id + "_log", "log"))
    seq = _raw_sequence(res.get("report", {}))
    assert seq, "joint_history vacío (¿no ruteó a joint?)"
    by_iter = dict(seq)
    assert by_iter.get(1, 0.0) == 0.0, "k=1 debe ir sin coupling (warm-up)"
    ramp = [v for k, v in sorted(by_iter.items()) if k >= 2]
    assert len(ramp) >= 2
    # Estrictamente creciente y acotado 0.01→1.0.
    assert all(b > a for a, b in zip(ramp, ramp[1:])), f"lambda_cross_raw no monótono: {ramp}"
    assert ramp[-1] == 1.0, f"el último lambda_cross_raw debe ser 1.0, fue {ramp[-1]}"
    assert ramp[0] < 1.0


def test_step_continuation_constant(test_project_id, test_run_id):
    from services.geophysics_service import run_geophysics_inversion

    res = run_geophysics_inversion(_joint_params(test_project_id, test_run_id + "_step", "step"))
    seq = _raw_sequence(res.get("report", {}))
    assert seq, "joint_history vacío (¿no ruteó a joint?)"
    by_iter = dict(seq)
    assert by_iter.get(1, 0.0) == 0.0
    ramp = [v for k, v in sorted(by_iter.items()) if k >= 2]
    assert ramp and all(v == 1.0 for v in ramp), f"modo step no es escalón 1.0: {ramp}"
