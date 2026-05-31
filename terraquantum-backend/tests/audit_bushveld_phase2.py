"""
AUDIT FASE 2 — Diagnóstico de inversión real Bushveld con lambda_mag CONECTADO.
================================================================================
Objetivo: determinar si, con el bug de lambda_mag arreglado + buena parametrización
(ventana compacta, malla más fina/menos profunda, regularización barrida), el motor
produce un cuerpo FÍSICAMENTE PLAUSIBLE sobre datos reales — o si falta arreglar más.

Usa EXCLUSIVAMENTE el motor real. Preprocesamiento (proyección, regional) hecho a
mano (gap conocido del motor). Cuerpo recuperado = celdas con Δρ > 0.5·Δρmax.
"""
from __future__ import annotations
import os, sys, lzma, logging, contextlib, io, json
import numpy as np

try:
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid
    from exploration.preprocessing import project_geographic_to_local, remove_regional_trend
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exploration.gravimetry import GravimetryForward, GravimetryInversion
    from exploration.checkerboard_test import build_voxel_grid
    from exploration.preprocessing import project_geographic_to_local, remove_regional_trend

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("audit.phase2")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_data", "bushveld-gravity.csv.xz")
WIN_LON = (28.4, 29.6)
WIN_LAT = (-24.6, -23.4)
BLOCK = 4000.0          # 4 km — malla más fina
NZ_DEPTH = 5            # 5 capas × 4 km = 20 km (vs 40 km de Fase 1)
REG_ORDER = 2


def load_window():
    rows = [l.split(",") for l in lzma.open(DATA, "rt", encoding="utf-8").read().splitlines()[1:]]
    a = np.array(rows, dtype=float)
    lon, lat, bg = a[:, 0], a[:, 1], a[:, 6]
    m = (lon >= WIN_LON[0]) & (lon <= WIN_LON[1]) & (lat >= WIN_LAT[0]) & (lat <= WIN_LAT[1])
    return lon[m], lat[m], bg[m]


def project(lon, lat):
    x, z, _meta = project_geographic_to_local(lon, lat)
    return x, z


def remove_regional(x, z, g, order):
    residual, _regional, _coef = remove_regional_trend(x, z, g, order=order)
    return residual


def body_metrics(contrast, x_c, y_c, z_c, x_pk, z_pk):
    """Cuerpo = celdas con Δρ > 0.5·max. CoM, profundidad, offset al pico, frac@clip."""
    dmax = float(np.nanmax(contrast))
    if dmax <= 0:
        return dict(dmax=0, depth_km=np.nan, off_km=np.nan, frac_clip=0, nbody=0)
    body = contrast > 0.5 * dmax
    w = contrast[body]; tot = w.sum()
    cmx = (w * x_c[body]).sum() / tot; cmy = (w * y_c[body]).sum() / tot; cmz = (w * z_c[body]).sum() / tot
    off = np.hypot(cmx - x_pk, cmz - z_pk) / 1000.0
    frac_clip = float(np.mean(contrast[np.isfinite(contrast)] >= 1.599))
    return dict(dmax=dmax, depth_km=cmy / 1000.0, off_km=off, frac_clip=frac_clip, nbody=int(body.sum()))


def main():
    lon, lat, bg = load_window()
    x, z = project(lon, lat)
    residual = remove_regional(x, z, bg, REG_ORDER)
    # Invertimos el residual de media-cero DIRECTAMENTE (sin shift DC). Restar el
    # mínimo introducía un offset uniforme (~37 mGal) que el motor explicaba con
    # masa difusa profunda → profundidades y desfases irreales. El residual ya
    # representa el contraste de densidad respecto al regional.
    g_target = residual
    pk = int(np.argmax(g_target)); x_pk, z_pk = x[pk], z[pk]
    g_si = g_target * 1e-5
    log.info(f"Ventana compacta: {len(lon)} estaciones | x 0..{x.max()/1000:.0f}km z 0..{z.max()/1000:.0f}km")
    log.info(f"Residual poly-{REG_ORDER}: min={residual.min():.1f} max={residual.max():.1f} std={residual.std():.1f} mGal")
    log.info(f"Pico anomalía densa en x={x_pk/1000:.0f}km z={z_pk/1000:.0f}km")

    nx = int(np.ceil(x.max() / BLOCK)) + 1
    nz = int(np.ceil(z.max() / BLOCK)) + 1
    ny = NZ_DEPTH
    log.info(f"Malla: {nx}x{ny}x{nz}={nx*ny*nz} celdas | {BLOCK/1000:.0f}km | prof {ny*BLOCK/1000:.0f}km")
    _, _, _, x_c, y_c, z_c = build_voxel_grid(nx, ny, nz, BLOCK)
    sensors = np.column_stack([x, np.zeros_like(x), z]).astype(np.float64)
    fwd = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=2e6)
    inv = GravimetryInversion(nx=nx, ny=ny, nz=nz, block_size=BLOCK)
    noise = 0.02 * float(np.sqrt(np.mean(g_si ** 2)))

    log.info("-" * 78)
    log.info("Barrido (lambda_mag CONECTADO × alpha_spatial). Plausible: prof 5-18km, off<25km, Δρ 0.15-0.9")
    log.info("-" * 78)
    results = []
    for lm in (0.01, 0.3, 1.0, 3.0):
        for asp in (1.0, 10.0, 50.0):
            with contextlib.redirect_stdout(io.StringIO()):
                ed, _, mis, _ = inv.solve_inversion_lsqr(
                    g_observed=g_si, kernel_sparse=None, y_c=y_c, lambda_mag=lm, alpha_spatial=asp,
                    forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
                    noise_floor=noise, noise_pct=0.0)
            c = np.nan_to_num(ed - inv.base_density, nan=0.0)
            mt = body_metrics(c, x_c, y_c, z_c, x_pk, z_pk)
            plausible = (5 <= mt["depth_km"] <= 18) and (mt["off_km"] < 25) and (0.15 <= mt["dmax"] <= 0.9)
            flag = " <== PLAUSIBLE" if plausible else ""
            log.info(f"λ={lm:5.2f} α={asp:5.1f} | misfit={mis:5.1f}% | Δρmax={mt['dmax']:.2f} "
                     f"clip%={mt['frac_clip']*100:4.1f} | prof={mt['depth_km']:4.1f}km off={mt['off_km']:4.0f}km{flag}")
            results.append({"lambda_mag": lm, "alpha_spatial": asp, "misfit": mis, **mt, "plausible": bool(plausible)})

    plaus = [r for r in results if r["plausible"]]
    log.info("-" * 78)
    log.info(f"Configs plausibles: {len(plaus)}/{len(results)}")
    json.dump(results, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
              "audit_bushveld_phase2_results.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
