"""
FASE 0 Tarea 0.5 — Validar β magnético (depth_beta 1.5 vs 3.0) con cuerpo PROFUNDO.

El default depth_beta=1.5 es < el clásico 3.0 para un kernel 1/r³. El __main__ del
motor solo probaba un blob somero. Riesgo: cuerpos profundos recuperados demasiado
someros. Este test MIDE |y_pico_recuperado − y_verdadero| barriendo β ∈
{1.5, 2.0, 2.5, 3.0} sobre un cuerpo a y≈120 m. NO se tunea a ciegas: la decisión
del default se toma a partir de la tabla medida.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion

BETAS = [1.5, 2.0, 2.5, 3.0]
Y_TRUE = 120.0


def _run_sweep():
    NX, NY, NZ, BS = 10, 10, 10, 20.0
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    x_c = (ix.ravel() + 0.5) * BS
    y_c = (iy.ravel() + 0.5) * BS
    z_c = (iz.ravel() + 0.5) * BS

    # Sensores en superficie (y=0) cubriendo el área del cuerpo.
    sx, sz = np.meshgrid(
        np.linspace(BS, (NX - 1) * BS, 8), np.linspace(BS, (NZ - 1) * BS, 8)
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])

    fwd = MagnetometryForward(BS, BS, BS, cutoff_radius=BS * 25)
    G = fwd._build_sparse_kernel(x_c, y_c, z_c, sensors)

    # Cuerpo profundo centrado en x,z, a y≈120 (celdas iy=5,6 → centros 110,130).
    true = np.zeros(NX * NY * NZ)
    cx, cz = NX // 2, NZ // 2
    for iyy in (5, 6):
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                idx = (cx + dx) * NY * NZ + iyy * NZ + (cz + dz)
                true[idx] = 0.1
    d_clean = G @ true
    rng = np.random.default_rng(0)
    d_obs = d_clean + 0.01 * np.abs(d_clean).max() * rng.standard_normal(d_clean.size)

    inv = MagnetometryInversion(NX, NY, NZ, BS)
    results = {}
    for beta in BETAS:
        susc, _score, misfit, _sens = inv.solve_magnetic_inversion_lsqr(
            d_observed=d_obs, y_c=y_c, lambda_mag=1e-3, alpha_spatial=1.0,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            susc_min=0.0, susc_max=1.0, depth_beta=beta,
        )
        susc = np.nan_to_num(np.asarray(susc), nan=0.0)
        w = np.clip(susc, 0.0, None)
        if w.sum() <= 0:
            y_centroid = float("nan")
        else:
            # Centroide en y ponderado por susc, restringido a celdas relevantes
            # (>20% del pico) para no sesgar con el fondo difuso.
            thr = 0.2 * w.max()
            mask = w >= thr
            y_centroid = float(np.sum(y_c[mask] * w[mask]) / np.sum(w[mask]))
        results[beta] = {
            "y_centroid": y_centroid,
            "y_err": abs(y_centroid - Y_TRUE),
            "misfit": float(misfit),
        }
    return results


def test_beta_sweep_recovers_deep_body():
    results = _run_sweep()
    # Reporte legible (visible con pytest -s o en fallo).
    lines = ["\n[FASE 0.5] Barrido depth_beta — cuerpo a y≈120 m:"]
    for b in BETAS:
        r = results[b]
        lines.append(
            f"  β={b:>3} | y_centroide={r['y_centroid']:7.1f} m | "
            f"|Δy|={r['y_err']:6.1f} m | misfit={r['misfit']:.2f}%"
        )
    report = "\n".join(lines)
    print(report)

    errs = {b: results[b]["y_err"] for b in BETAS}
    best_beta = min(errs, key=errs.get)
    # El mejor β debe localizar la profundidad razonablemente (< 60 m ≈ 3 celdas).
    assert errs[best_beta] < 60.0, f"Ningún β localiza el cuerpo profundo.\n{report}"
    # Todos los β producen una medición finita (no NaN/no diverge).
    assert all(np.isfinite(errs[b]) for b in BETAS), report


if __name__ == "__main__":
    res = _run_sweep()
    for b in BETAS:
        r = res[b]
        print(f"beta={b}: y_centroid={r['y_centroid']:.1f} y_err={r['y_err']:.1f} misfit={r['misfit']:.2f}%")
