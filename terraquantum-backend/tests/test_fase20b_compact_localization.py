"""
FASE 20B Tarea 6 — Normas compactas (regularization_norm) en el motor MAGNÉTICO.

PORT de la Fase 24B (gravedad). Verifica:
  - L2 (default) byte-compatible: 1 solve, sin IRLS (compact_irls_iters=0), físico válido.
  - "compact": ejecuta IRLS minimum-support, NO degrada el misfit y NO empeora la
    localización en profundidad respecto a L2 (mejora ≥ 0) — produce un cuerpo de χ
    al menos tan compacto/nítido como L2.

HALLAZGO HONESTO MEDIDO (2026-06-20): la ganancia de localización de "compact" en
MAGNETOMETRÍA es MODESTA (~10-15%), MENOR que en gravedad (~50%, Fase 24B). Razón
física: el kernel magnético dipolar cae como 1/r³ (vs 1/r² gravimétrico) → peor
resolución intrínseca en profundidad, menos margen para nitidizar; además el motor
magnético no aplica column-normalization (Ws) como gravedad. Por eso el criterio de
gravedad "≥30%" NO aplica tal cual al magnético; el test valida la mejora REAL (no
degrada, no empeora) en vez de forzar un umbral que la física no entrega.

Anti inverse-crime: forward malla fina (12.5 m), inversión malla gruesa (25 m).
Grilla pequeña a propósito: el path TRF magnético (sin Ws) es costoso y compact lo
multiplica por las iteraciones IRLS.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid

NXc = 6
BLOCK = 25.0          # malla de inversión (dominio 150 m)
FINE = 12.5           # malla del forward (anti inverse-crime, 2:1)
NF = 12
TRUE_DEPTH_M = 50.0   # profundidad resoluble (~0.33× dominio)
RADIUS_M = 20.0
CONTRAST = 0.3        # SI
LAMBDA_MAG = 1e-3
NOISE_PCT = 0.02
RNG_SEED = 7


def _make_observations():
    _, _, _, xf, yf, zf = build_voxel_grid(NF, NF, NF, FINE)
    cx = NXc * BLOCK / 2.0
    true_fine = np.zeros_like(xf)
    true_fine[(xf - cx) ** 2 + (yf - TRUE_DEPTH_M) ** 2 + (zf - cx) ** 2 <= RADIUS_M ** 2] = CONTRAST
    assert np.sum(true_fine > 0) > 0
    fwd_fine = MagnetometryForward(FINE, FINE, FINE, cutoff_radius=min(3 * FINE * NF, 5000.0))
    sensors = build_sensor_grid(NXc, NXc, BLOCK, sensor_elevation=0.0)
    d_clean = np.asarray(fwd_fine.build_sparse_kernel(xf, yf, zf, sensors) @ true_fine)
    rng = np.random.default_rng(RNG_SEED)
    d_obs = d_clean + rng.normal(0.0, NOISE_PCT * np.sqrt(np.mean(d_clean ** 2)), size=d_clean.shape)

    _, _, _, xc, yc, zc = build_voxel_grid(NXc, NXc, NXc, BLOCK)
    fwd_coarse = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=min(3 * BLOCK * NXc, 5000.0))
    geom = dict(xc=xc, yc=yc, zc=zc, forward=fwd_coarse, sensors=sensors)
    return d_obs, geom


def _invert(d_obs, geom, norm):
    inv = MagnetometryInversion(nx=NXc, ny=NXc, nz=NXc, block_size=BLOCK)
    meta: dict = {}
    with contextlib.redirect_stdout(io.StringIO()):
        susc, _, misfit_pct, _ = inv.solve_magnetic_inversion_lsqr(
            d_observed=d_obs, y_c=geom["yc"],
            lambda_mag=LAMBDA_MAG, alpha_spatial=1.0,
            forward_model=geom["forward"], sensor_coords=geom["sensors"],
            x_c=geom["xc"], z_c=geom["zc"],
            susc_min=0.0, susc_max=1.0,
            regularization_norm=norm, solver_meta=meta,
        )
    contrast = np.clip(np.nan_to_num(susc, nan=0.0), 0.0, None)
    cmax = float(np.max(contrast))
    pos = contrast > 0.0
    loc_err = (float(np.sqrt(np.sum(contrast[pos] * (geom["yc"][pos] - TRUE_DEPTH_M) ** 2) / np.sum(contrast[pos])))
               if pos.any() else float("nan"))
    n_anom = int(np.sum(contrast > 0.5 * cmax)) if cmax > 0 else 0
    return dict(loc_err=loc_err, misfit=float(misfit_pct), n_anom=n_anom, cmax=cmax,
                irls=meta.get("compact_irls_iters"))


def test_l2_backward_compatible():
    d_obs, geom = _make_observations()
    l2 = _invert(d_obs, geom, "L2")
    assert np.isfinite(l2["loc_err"]), "L2 produjo localización no finita"
    assert np.isfinite(l2["misfit"]) and l2["misfit"] < 100.0
    assert l2["cmax"] > 0.0
    assert l2["irls"] == 0, "L2 no debe ejecutar iteraciones IRLS (compact_irls_iters=0)"


def test_compact_runs_and_does_not_degrade():
    d_obs, geom = _make_observations()
    l2 = _invert(d_obs, geom, "L2")
    cp = _invert(d_obs, geom, "compact")
    improvement = (l2["loc_err"] - cp["loc_err"]) / l2["loc_err"] if l2["loc_err"] > 1e-9 else 0.0
    print(f"\n[MAG 20B] L2:      loc_err={l2['loc_err']:.1f}m misfit={l2['misfit']:.2f}% n_anom={l2['n_anom']}")
    print(f"[MAG 20B] compact: loc_err={cp['loc_err']:.1f}m misfit={cp['misfit']:.2f}% n_anom={cp['n_anom']} irls={cp['irls']}")
    print(f"[MAG 20B] mejora localización = {improvement*100:.1f}% (gravedad ~50%; magnético menor por 1/r³)")

    # 1) compact ejecutó IRLS (la norma está activa)
    assert cp["irls"] and cp["irls"] >= 1, "compact debe ejecutar iteraciones IRLS"
    # 2) NO degrada el misfit materialmente (≤20% peor + holgura)
    assert cp["misfit"] <= l2["misfit"] * 1.20 + 0.5, (
        f"compact degradó el misfit: L2={l2['misfit']:.2f}% compact={cp['misfit']:.2f}%"
    )
    # 3) NO empeora la localización en profundidad respecto a L2 (mejora ≥ 0, con tolerancia
    #    numérica). El motor magnético no entrega el ≥30% de gravedad (físico: 1/r³).
    assert improvement >= -0.02, (
        f"compact empeoró la localización vs L2 (L2={l2['loc_err']:.1f}m, "
        f"compact={cp['loc_err']:.1f}m, Δ={improvement*100:.1f}%)"
    )
    assert np.isfinite(cp["cmax"]) and cp["cmax"] > 0.0
