# -*- coding: utf-8 -*-
"""PARTE B — ¿Cuánto GANAMOS combinando gravimetría + magnetometría + sondajes?

Un cuerpo sintético con contraste de DENSIDAD (Δρ) y de SUSCEPTIBILIDAD (Δκ) a
profundidad conocida, con un sondaje que lo intersecta. Se genera el dato con el motor
en malla FINA (anti-inverse-crime) e se invierte en malla gruesa con 5 configuraciones:

  1. grav-sola          2. mag-sola          3. joint grav+mag (cross-gradient)
  4. grav + sondaje (ancla dura)             5. grav + mag + sondaje

Mide error HORIZONTAL y de PROFUNDIDAD de cada una vs la verdad → muestra la fortaleza
de cada física y cuánto recorta la combinación el error (sobre todo la PROFUNDIDAD, que
la gravedad-sola no resuelve). NO se ajusta nada. Regla de oro: si una combinación NO
mejora, se reporta igual (recordatorio: el cross-gradient NO mejoró DO-27).

    python scripts/validation/multiphysics_gain.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
from exploration.geophysics_math import build_gradient_operators
from services.joint_inversion import _build_cross_gradient_block, _normalized_gradient
from services.field_validation_service import estimate_location_error

# ── Malla (igual que el presupuesto de error, para comparabilidad) ──────────────
BLOCK = 125.0
NX = NZ = 18
NY = 14
CUTOFF = 2600.0
CENTER = NX * BLOCK / 2.0

# ── Cuerpo sintético: denso Y magnético, a profundidad MEDIA (donde grav-sola falla) ──
BASE_DENSITY = 2.67
DELTA_RHO = 0.6          # t/m³
DELTA_KAPPA = 0.05       # SI
BODY_DEPTH = 500.0       # m (grav-sola da ~440 m de error de profundidad aquí)
BODY_RADIUS = 150.0

# ── Survey + IGRF (campo de latitud media, hemisferio sur) ──────────────────────
SPAN = 1500.0
N_SIDE = 12
INCL, DECL, B0 = -55.0, 3.0, 24000.0
NOISE_MGAL = 0.02
NOISE_NT = 5.0

DENSITY_MAX = BASE_DENSITY + 2.0
SUSC_MAX = 0.2
LAMBDA_G = 1e-3
LAMBDA_M = 1e-3
IRLS = 2
JOINT_ITERS = 2          # warm-up + 1 iteración acoplada
SEED = 20260724


def _centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _sensors():
    half = SPAN / 2.0
    a = np.linspace(CENTER - half, CENTER + half, N_SIDE)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    return np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)


def _make_data():
    """Genera g_obs (m/s²) y tmi_obs (nT) con el motor en malla FINA (anti-inverse-crime)."""
    rng = np.random.default_rng(SEED)
    bf = BLOCK / 2.0
    nxf, nyf, nzf = NX * 2, NY * 2, NZ * 2
    xf, yf, zf = _centers(nxf, nyf, nzf, bf)
    inside = (xf - CENTER) ** 2 + (yf - BODY_DEPTH) ** 2 + (zf - CENTER) ** 2 <= BODY_RADIUS ** 2
    rho_f = np.where(inside, DELTA_RHO, 0.0)
    kap_f = np.where(inside, DELTA_KAPPA, 0.0)
    sensors = _sensors()

    gfwd = GravimetryForward(bf, bf, bf, cutoff_radius=CUTOFF)
    g_clean = gfwd.build_sparse_kernel(xf, yf, zf, sensors) @ rho_f
    g_obs = g_clean + (NOISE_MGAL * 1e-5) * rng.standard_normal(sensors.shape[0])

    mfwd = MagnetometryForward(bf, bf, bf, cutoff_radius=CUTOFF,
                               inclination_deg=INCL, declination_deg=DECL, field_intensity_nt=B0)
    t_clean = mfwd.build_sparse_kernel(xf, yf, zf, sensors) @ kap_f
    tmi_obs = t_clean + NOISE_NT * rng.standard_normal(sensors.shape[0])

    return (sensors, g_obs, tmi_obs, max(NOISE_MGAL * 1e-5, 1e-12), max(NOISE_NT, 1e-6),
            float(np.max(np.abs(g_clean))) / 1e-5, float(np.max(np.abs(t_clean))))


def _anchor():
    """Sondaje vertical en el centro que intersecta el cuerpo, anclado a la densidad verdadera."""
    return np.array([[CENTER, CENTER, BODY_DEPTH - BODY_RADIUS, BODY_DEPTH + BODY_RADIUS,
                      BASE_DENSITY + DELTA_RHO]], dtype=np.float64)


def _solve_grav(g_obs, sensors, sigma, extra=None, mref=None, boreholes=None, prune=True):
    x_c, y_c, z_c = _centers(NX, NY, NZ, BLOCK)
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    meta: dict = {}
    rho, _s, mf, _n = inv.solve_inversion_lsqr(
        g_obs, None, y_c, lambda_mag=LAMBDA_G, alpha_spatial=1.0, forward_model=fwd,
        sensor_coords=sensors, x_c=x_c, z_c=z_c, density_min=BASE_DENSITY, density_max=DENSITY_MAX,
        noise_floor=sigma, noise_pct=0.02, auto_kappa=True, prune_observable_domain=prune,
        regularization_norm="compact", compact_max_irls=IRLS,
        boreholes=boreholes, anchor_mode=("hard" if boreholes is not None else "soft"),
        extra_reg_blocks=extra, m_ref=mref, solver_meta=meta)
    return np.nan_to_num(np.asarray(rho), nan=BASE_DENSITY), float(mf), (x_c, y_c, z_c)


def _solve_mag(tmi, sensors, sigma, extra=None, mref=None, prune=True):
    x_c, y_c, z_c = _centers(NX, NY, NZ, BLOCK)
    inv = MagnetometryInversion(NX, NY, NZ, BLOCK)
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF,
                              inclination_deg=INCL, declination_deg=DECL, field_intensity_nt=B0)
    meta: dict = {}
    chi, _s, mf, _n = inv.solve_magnetic_inversion_lsqr(
        d_observed=tmi, override_kernel=None, y_c=y_c, lambda_mag=LAMBDA_M, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c, susc_min=0.0, susc_max=SUSC_MAX,
        noise_floor=sigma, noise_pct=0.0, detect_outliers=False, auto_kappa=True,
        prune_observable_domain=prune, regularization_norm="compact", compact_max_irls=IRLS,
        extra_reg_blocks=extra, m_ref=mref, solver_meta=meta)
    return np.nan_to_num(np.asarray(chi), nan=0.0), float(mf), (x_c, y_c, z_c)


def _joint(g_obs, tmi, sensors, sig_g, sig_m, boreholes=None):
    """Cross-gradient alternado (mismas primitivas que producción). Sin poda (bloques conforman nC)."""
    nC = NX * NY * NZ
    Dx, Dy, Dz = build_gradient_operators(NX, NY, NZ, BLOCK, BLOCK, BLOCK)
    Gn = float(np.sqrt(nC))
    rho, mf_g, grid = _solve_grav(g_obs, sensors, sig_g, boreholes=boreholes, prune=False)
    chi, mf_m, _ = _solve_mag(tmi, sensors, sig_m, prune=False)
    for k in range(1, JOINT_ITERS + 1):
        if k >= 2:
            hx, hy, hz = _normalized_gradient(chi, Dx, Dy, Dz)
            B = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            bn = float(np.sqrt(B.power(2).sum()))
            gblk = [(Gn / max(bn, 1e-12)) * B]
        else:
            gblk = None
        rho, mf_g, grid = _solve_grav(g_obs, sensors, sig_g, extra=gblk,
                                      mref=(rho - BASE_DENSITY), boreholes=boreholes, prune=False)
        if k >= 2:
            hx, hy, hz = _normalized_gradient(rho, Dx, Dy, Dz)
            B = _build_cross_gradient_block(hx, hy, hz, Dx, Dy, Dz)
            bn = float(np.sqrt(B.power(2).sum()))
            mblk = [(Gn / max(bn, 1e-12)) * B]
        else:
            mblk = None
        chi, mf_m, _ = _solve_mag(tmi, sensors, sig_m, extra=mblk, mref=chi, prune=False)
    return rho, chi, mf_g, mf_m, grid


def _measure(model, grid, base_val):
    x_c, y_c, z_c = grid
    loc = estimate_location_error(model, x_c, y_c, z_c, (CENTER, BODY_DEPTH, CENTER),
                                  base_density=base_val)
    contrast = np.abs(model - base_val)
    finite = np.isfinite(contrast)
    peak = None
    if np.any(finite) and np.nanmax(contrast[finite]) > 0:
        peak = float(y_c[int(np.nanargmax(np.where(finite, contrast, -np.inf)))])
    return {
        "horizontal_m": loc.get("horizontal_error_m"),
        "depth_centroid_m": loc.get("depth_error_m"),
        "depth_peak_m": None if peak is None else round(abs(peak - BODY_DEPTH), 1),
        "recovered_depth_m": loc.get("recovered_y_m"),
    }


def run():
    sensors, g_obs, tmi, sig_g, sig_m, peak_mgal, peak_nt = _make_data()
    anchor = _anchor()
    print(f"Cuerpo: prof {BODY_DEPTH:.0f} m, R {BODY_RADIUS:.0f} m, Δρ {DELTA_RHO}, Δκ {DELTA_KAPPA} | "
          f"anomalía grav {peak_mgal:.2f} mGal, mag {peak_nt:.0f} nT | {sensors.shape[0]} estaciones", flush=True)
    res = {}

    t = time.time(); rho, mf, grid = _solve_grav(g_obs, sensors, sig_g)
    res["1_grav_sola"] = {**_measure(rho, grid, BASE_DENSITY), "misfit_pct": round(mf, 2), "s": round(time.time()-t,1)}
    print(f"[1] grav-sola        {res['1_grav_sola']}", flush=True)

    t = time.time(); chi, mfm, gridm = _solve_mag(tmi, sensors, sig_m)
    res["2_mag_sola"] = {**_measure(chi, gridm, 0.0), "misfit_pct": round(mfm, 2), "s": round(time.time()-t,1)}
    print(f"[2] mag-sola         {res['2_mag_sola']}", flush=True)

    t = time.time(); jr, jc, jmg, jmm, jgrid = _joint(g_obs, tmi, sensors, sig_g, sig_m)
    res["3_joint_gm"] = {**_measure(jr, jgrid, BASE_DENSITY), "misfit_pct": round(jmg, 2), "s": round(time.time()-t,1)}
    print(f"[3] joint grav+mag   {res['3_joint_gm']} (densidad)", flush=True)

    t = time.time(); rho_a, mfa, grid_a = _solve_grav(g_obs, sensors, sig_g, boreholes=anchor)
    res["4_grav_anchor"] = {**_measure(rho_a, grid_a, BASE_DENSITY), "misfit_pct": round(mfa, 2), "s": round(time.time()-t,1)}
    print(f"[4] grav+sondaje     {res['4_grav_anchor']}", flush=True)

    t = time.time(); jr2, jc2, jmg2, jmm2, jgrid2 = _joint(g_obs, tmi, sensors, sig_g, sig_m, boreholes=anchor)
    res["5_grav_mag_anchor"] = {**_measure(jr2, jgrid2, BASE_DENSITY), "misfit_pct": round(jmg2, 2), "s": round(time.time()-t,1)}
    print(f"[5] grav+mag+sondaje {res['5_grav_mag_anchor']}", flush=True)

    report = {
        "kind": "multiphysics_gain_partB",
        "body": {"depth_m": BODY_DEPTH, "radius_m": BODY_RADIUS, "delta_rho": DELTA_RHO,
                 "delta_kappa": DELTA_KAPPA},
        "mesh": {"nx": NX, "ny": NY, "nz": NZ, "block_m": BLOCK},
        "results": res,
    }
    out = Path(__file__).resolve().parent / "multiphysics_gain_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte → {out}", flush=True)
    return report


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    run()


if __name__ == "__main__":
    main()
