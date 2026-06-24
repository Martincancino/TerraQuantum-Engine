"""
FASE 0 Tarea 0.6 — print() → logger en los motores.

Los motores (gravimetry / magnetometry / joint) emitían diagnósticos vía print(),
contaminando stdout en producción. Ahora usan el logger del módulo. Este test
ejecuta una inversión magnética real y verifica que NO escribe nada en stdout
(los diagnósticos van por logging, no por print).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion


def test_magnetic_inversion_emits_no_stdout(capsys):
    NX, NY, NZ, BS = 6, 4, 6, 20.0
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS
    sx, sz = np.meshgrid(np.linspace(BS, (NX - 1) * BS, 5), np.linspace(BS, (NZ - 1) * BS, 5))
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 12)
    inv = MagnetometryInversion(NX, NY, NZ, BS)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)
    true = np.zeros(NX * NY * NZ)
    true[2 * NY * NZ + 1 * NZ + 2] = 0.1
    d_obs = G @ true

    # Limpia lo capturado durante el setup (kernel build) y mide solo la inversión.
    capsys.readouterr()
    inv.solve_magnetic_inversion_lsqr(
        d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0,
    )
    captured = capsys.readouterr()
    assert captured.out == "", f"el motor escribió en stdout (debe usar logger):\n{captured.out}"
