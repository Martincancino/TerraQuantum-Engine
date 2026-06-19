"""
FASE 24B — Tarea 1: Test de mejora de localización con normas compactas.

Criterio (roadmap GO/NO-GO):
  - La norma "compact" (minimum support IRLS) mejora el ERROR DE PROFUNDIDAD de
    localización de un cuerpo compacto en ≥30% respecto a L2 (Tikhonov suave).
  - La norma compacta NO degrada el misfit (≤20% peor que L2).
  - La norma compacta NO genera cuerpos falsos: su anomalía es MÁS compacta
    (menos vóxeles anómalos que L2) y centrada horizontalmente sobre el cuerpo.

Métrica de "error de profundidad":
  loc_err = sqrt( Σ_i w_i (y_i − y_true)² / Σ_i w_i ),  w_i = contraste_i ≥ 0.
  Es el error RMS de profundidad ponderado por masa: cuán concentrada en
  profundidad queda la masa recuperada alrededor del cuerpo real. L2 produce un
  halo difuso (gran loc_err); compact produce un cuerpo nítido (loc_err menor).
  Esto operacionaliza la afirmación del roadmap: "cuerpos NÍTIDOS y bien
  delimitados → mejor error de profundidad" (Last & Kubik 1983,
  Portniaguine & Zhdanov 1999, Fournier & Oldenburg 2019).

El cuerpo se sitúa a profundidad RESOLUBLE para el survey (≈0.35× ancho). A
profundidades no resolubles la inversión gravimétrica es intrínsecamente
depth-ambigua y NINGUNA norma mejora la profundidad — límite físico documentado.

Anti inverse-crime: forward en malla FINA (10 m), inversión en malla GRUESA (20 m).
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.checkerboard_test import build_voxel_grid, build_sensor_grid

# ── Geometría sintética ───────────────────────────────────────────────────────
NX, NY, NZ = 10, 10, 10
BLOCK = 20.0                 # m — celda de inversión (dominio 200×200×200 m)
FINE_BLOCK = 10.0            # m — celda del forward (anti inverse-crime, 2:1)
CONTRAST = 1.2              # t/m³ — cuerpo denso compacto
TRUE_DEPTH_M = 70.0         # m — centro de la esfera (profundidad resoluble)
SPHERE_RADIUS_M = 24.0      # m — radio (cuerpo compacto)
LAMBDA_MAG = 0.1            # operating point validado (Morozov chi²~1 en LdM)
ALPHA_SPATIAL = 1.0
NOISE_PCT = 0.02
RNG_SEED = 7


def _build_sphere_contrast(x_c, y_c, z_c, center, radius, contrast):
    r2 = (x_c - center[0]) ** 2 + (y_c - center[1]) ** 2 + (z_c - center[2]) ** 2
    m = np.zeros_like(x_c, dtype=np.float64)
    m[r2 <= radius ** 2] = contrast
    return m


def _make_observations():
    """Forward en malla fina → g_obs con ruido. Devuelve (g_obs, geom coarse)."""
    nxf = int(NX * BLOCK / FINE_BLOCK)
    nyf = int(NY * BLOCK / FINE_BLOCK)
    nzf = int(NZ * BLOCK / FINE_BLOCK)
    _, _, _, xf, yf, zf = build_voxel_grid(nxf, nyf, nzf, FINE_BLOCK)

    cx = (NX * BLOCK) / 2.0
    cz = (NZ * BLOCK) / 2.0
    center = (cx, TRUE_DEPTH_M, cz)
    true_contrast_fine = _build_sphere_contrast(
        xf, yf, zf, center, SPHERE_RADIUS_M, CONTRAST
    )
    assert np.sum(true_contrast_fine > 0) > 0, "esfera vacía: ajustar radio/profundidad"

    cutoff_fine = min(3.0 * FINE_BLOCK * max(nxf, nyf, nzf), 5000.0)
    forward_fine = GravimetryForward(
        dx=FINE_BLOCK, dy=FINE_BLOCK, dz=FINE_BLOCK, cutoff_radius=cutoff_fine
    )
    sensors = build_sensor_grid(NX, NZ, BLOCK, sensor_elevation=0.0)
    kernel_fine = forward_fine.build_sparse_kernel(xf, yf, zf, sensors)
    g_clean = np.asarray(kernel_fine @ true_contrast_fine, dtype=np.float64)

    signal_rms = float(np.sqrt(np.mean(g_clean ** 2)))
    rng = np.random.default_rng(RNG_SEED)
    g_obs = g_clean + rng.normal(0.0, NOISE_PCT * signal_rms, size=g_clean.shape)

    _, _, _, xc, yc, zc = build_voxel_grid(NX, NY, NZ, BLOCK)
    cutoff_coarse = min(3.0 * BLOCK * max(NX, NY, NZ), 5000.0)
    forward_coarse = GravimetryForward(
        dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=cutoff_coarse
    )
    geom = dict(xc=xc, yc=yc, zc=zc, forward=forward_coarse, sensors=sensors)
    return g_obs, geom


def _invert(g_obs, geom, norm):
    """Inversión con la norma dada. Devuelve métricas de localización."""
    inversor = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK)
    meta: dict = {}
    with contextlib.redirect_stdout(io.StringIO()):
        est_density, _, misfit_pct, _ = inversor.solve_inversion_lsqr(
            g_observed=g_obs,
            kernel_sparse=None,
            y_c=geom["yc"],
            lambda_mag=LAMBDA_MAG,
            alpha_spatial=ALPHA_SPATIAL,
            forward_model=geom["forward"],
            sensor_coords=geom["sensors"],
            x_c=geom["xc"],
            z_c=geom["zc"],
            density_min=2.6,
            density_max=5.5,
            regularization_norm=norm,
            solver_meta=meta,
        )
    contrast = np.clip(np.nan_to_num(est_density - inversor.base_density, nan=0.0), 0.0, None)
    cmax = float(np.max(contrast))
    pos = contrast > 0.0
    if cmax <= 0 or not pos.any():
        return dict(loc_err=float("nan"), misfit=float(misfit_pct), n_anom=0,
                    cx=float("nan"), cz=float("nan"), cmax=0.0, irls=meta.get("compact_irls_iters"))

    w = contrast[pos]
    # Error RMS de profundidad ponderado por masa (cuán localizada está la masa)
    loc_err = float(np.sqrt(np.sum(w * (geom["yc"][pos] - TRUE_DEPTH_M) ** 2) / np.sum(w)))
    # Centroide horizontal de la anomalía principal (>50% del pico)
    main = contrast > 0.5 * cmax
    wm = contrast[main]
    cx_rec = float(np.sum(wm * geom["xc"][main]) / np.sum(wm))
    cz_rec = float(np.sum(wm * geom["zc"][main]) / np.sum(wm))
    return dict(
        loc_err=loc_err, misfit=float(misfit_pct), n_anom=int(np.sum(main)),
        cx=cx_rec, cz=cz_rec, cmax=cmax, irls=meta.get("compact_irls_iters"),
    )


def _run_comparison():
    g_obs, geom = _make_observations()
    l2 = _invert(g_obs, geom, "L2")
    cp = _invert(g_obs, geom, "compact")
    improvement = (l2["loc_err"] - cp["loc_err"]) / l2["loc_err"] if l2["loc_err"] > 1e-9 else 0.0
    return l2, cp, improvement, geom


def test_compact_improves_depth_localization():
    l2, cp, improvement, _ = _run_comparison()

    print(
        f"\n[FASE 24B] L2:      loc_err={l2['loc_err']:.1f}m misfit={l2['misfit']:.2f}% n_anom={l2['n_anom']}"
    )
    print(
        f"[FASE 24B] compact: loc_err={cp['loc_err']:.1f}m misfit={cp['misfit']:.2f}% "
        f"n_anom={cp['n_anom']} irls={cp['irls']}"
    )
    print(f"[FASE 24B] mejora error profundidad = {improvement*100:.1f}% (criterio >=30%)")

    # 1) Mejora de localización en profundidad ≥30%
    assert improvement >= 0.30, (
        f"compact debe mejorar el error de profundidad ≥30% vs L2 "
        f"(L2={l2['loc_err']:.1f}m, compact={cp['loc_err']:.1f}m, mejora={improvement*100:.1f}%)"
    )

    # 2) NO degrada el misfit materialmente (≤20% peor)
    assert cp["misfit"] <= l2["misfit"] * 1.20 + 0.5, (
        f"compact degradó el misfit: L2={l2['misfit']:.2f}% compact={cp['misfit']:.2f}%"
    )

    # 3) NO crea cuerpos falsos: anomalía más compacta y centrada horizontalmente
    assert cp["n_anom"] < l2["n_anom"], (
        f"compact no es más compacto que L2 (n_anom L2={l2['n_anom']} compact={cp['n_anom']})"
    )
    true_cx = (NX * BLOCK) / 2.0
    true_cz = (NZ * BLOCK) / 2.0
    assert abs(cp["cx"] - true_cx) <= 1.5 * BLOCK and abs(cp["cz"] - true_cz) <= 1.5 * BLOCK, (
        f"compact descentró el cuerpo (cx={cp['cx']:.1f} cz={cp['cz']:.1f}; verdad {true_cx},{true_cz})"
    )


def test_l2_is_backward_compatible():
    """L2 debe seguir produciendo un resultado físico válido (no NaN, misfit finito)."""
    g_obs, geom = _make_observations()
    l2 = _invert(g_obs, geom, "L2")
    assert np.isfinite(l2["loc_err"]), "L2 produjo localización no finita"
    assert np.isfinite(l2["misfit"]) and l2["misfit"] < 100.0, "L2 misfit inválido"
    assert l2["cmax"] > 0.0, "L2 no recuperó contraste positivo"
    assert l2["irls"] == 0, "L2 no debe ejecutar iteraciones IRLS (compact_irls_iters=0)"


if __name__ == "__main__":
    l2, cp, improvement, _ = _run_comparison()
    print("=" * 60)
    print(f"VERDAD profundidad : {TRUE_DEPTH_M:.1f} m")
    print(f"L2      : loc_err={l2['loc_err']:.1f}m misfit={l2['misfit']:.2f}% n_anom={l2['n_anom']}")
    print(f"compact : loc_err={cp['loc_err']:.1f}m misfit={cp['misfit']:.2f}% n_anom={cp['n_anom']} irls={cp['irls']}")
    print(f"MEJORA error profundidad : {improvement*100:.1f}%")
    print("=" * 60)
