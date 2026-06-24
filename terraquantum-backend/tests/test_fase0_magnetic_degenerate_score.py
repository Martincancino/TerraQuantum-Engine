"""
FASE 0 Tarea 0.2 — Datos degenerados: score 1.0 → NaN (honestidad).

El motor magnético ponía relative_score = 1.0 cuando max_voxel_error <= 0 (datos
degenerados/planos), FINGIENDO calidad máxima. Gravimetría usa NaN. Este test
verifica que ahora magnetometría también devuelve NaN (no 1.0) en ese caso.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


def test_degenerate_data_score_is_nan_not_one():
    NX, NY, NZ, BS = 6, 4, 6, 20.0
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    sx, sz = np.meshgrid(np.linspace(BS, (NX - 1) * BS, 5), np.linspace(BS, (NZ - 1) * BS, 5))
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)

    # Dato PLANO (todo cero) → modelo cero → residual cero → max_voxel_error = 0
    # → rama degenerada.
    d_obs = np.zeros(sensors.shape[0])

    _susc, score, _misfit, _sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0,
    )
    score = np.asarray(score, dtype=np.float64)
    # NINGÚN vóxel debe reportar score 1.0 fabricado.
    assert not np.any(score == 1.0), "score=1.0 fabricado en datos degenerados (debe ser NaN)"
    # Las celdas degeneradas son NaN.
    assert np.any(np.isnan(score)), "se esperaba NaN en el score degenerado"
