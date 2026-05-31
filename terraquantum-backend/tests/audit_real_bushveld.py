"""
AUDIT — INVERSIÓN DE DATOS GRAVIMÉTRICOS REALES (Complejo de Bushveld, Sudáfrica)
================================================================================
Artefacto de AUDITORÍA. Usa EXCLUSIVAMENTE el motor real (exploration/gravimetry.py).

Dataset REAL (CC-BY 4.0, Zenodo 10.5281/zenodo.6511942):
    bushveld-gravity.csv.xz — 3877 mediciones de gravedad terrestre sobre el
    Complejo Ígneo de Bushveld (mayor intrusión máfica del mundo; Pt/Cr/V).
    Columna usada: gravity_bouguer_mgal (anomalía de Bouguer, corregida por terreno).

HONESTIDAD METODOLÓGICA — preprocesamiento que el MOTOR NO PROVEE y que hago aquí
a mano (esto ES el gap industrial #2 documentado en la auditoría):
    1. Proyección lon/lat (grados) → metros locales (equirectangular).
    2. Separación regional-residual (resto una tendencia polinómica 2º orden).
    3. Topografía: se desprecia (sensores en datum plano y=0). El motor sí soporta
       topography_elevations, pero la corrección Bouguer ya removió parte del efecto.

Resultado esperado: NO es un pass/fail cuantitativo (la "verdad" 3D de Bushveld es
un modelo publicado, no puntos). Es una prueba de FACTIBILIDAD + cordura física:
¿el motor ingiere datos reales dispersos y localiza masa densa bajo la anomalía
positiva a profundidad plausible?

Uso:  python tests/audit_real_bushveld.py
"""
from __future__ import annotations
import os, sys, json, lzma, logging
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
log = logging.getLogger("audit.bushveld")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_data", "bushveld-gravity.csv.xz")

# Ventana de trabajo COMPACTA alrededor de una sola anomalía dominante.
# (La ventana de ~200 km original NO se corrobora: a esa escala un regional
#  polinómico de 2º orden no separa múltiples fuentes y la masa se dispersa
#  >80 km del pico. La separación regional-residual de bajo orden solo es
#  válida sobre una anomalía local aislada — limitación metodológica real,
#  no un bug del motor. Ver tests/audit_bushveld_phase2.py para el barrido.)
WIN_LON = (28.4, 29.6)     # ~120 km E-W
WIN_LAT = (-24.6, -23.4)   # ~130 km N-S
BLOCK   = 4000.0           # m por celda (4 km) — malla más fina, menos profunda
NZ_DEPTH = 5               # capas en profundidad → 20 km
REG_ORDER = 2              # orden del polinomio regional
ALPHA_SPATIAL = 10.0       # regularización espacial moderada (validada en Fase 2)


def load_window():
    rows = [l.split(",") for l in lzma.open(DATA, "rt", encoding="utf-8").read().splitlines()[1:]]
    a = np.array(rows, dtype=float)
    lon, lat, bg = a[:, 0], a[:, 1], a[:, 6]
    m = (lon >= WIN_LON[0]) & (lon <= WIN_LON[1]) & (lat >= WIN_LAT[0]) & (lat <= WIN_LAT[1])
    return lon[m], lat[m], bg[m]


def project(lon, lat):
    """Equirectangular → metros locales (delega en el motor: exploration.preprocessing)."""
    x, z, _meta = project_geographic_to_local(lon, lat)
    return x, z


def remove_regional(x, z, g, order=2):
    """Separación regional-residual (delega en el motor: exploration.preprocessing)."""
    residual, regional, _coef = remove_regional_trend(x, z, g, order=order)
    return residual, regional


def main():
    log.info("=" * 72)
    log.info("AUDITORÍA — Inversión de DATOS REALES: Complejo de Bushveld")
    log.info("=" * 72)
    lon, lat, bg = load_window()
    log.info(f"Ventana {WIN_LON}°E x {WIN_LAT}°S → {len(lon)} estaciones reales")
    log.info(f"Bouguer crudo: min={bg.min():.1f} max={bg.max():.1f} mean={bg.mean():.1f} mGal")

    x, z = project(lon, lat)
    log.info(f"Proyección local: x 0..{x.max()/1000:.0f} km | z 0..{z.max()/1000:.0f} km")

    residual, regional = remove_regional(x, z, bg, REG_ORDER)
    log.info(f"[PREPROC manual] Regional poly-{REG_ORDER} removido. "
             f"Residual mGal: min={residual.min():.1f} max={residual.max():.1f} std={residual.std():.1f}")

    # Invertimos el residual de media-cero DIRECTAMENTE. (Antes se restaba el mínimo,
    # introduciendo un offset uniforme ~37 mGal que el motor explicaba con masa difusa
    # profunda → profundidad/desfase irreales. El residual YA es el contraste sobre el
    # regional; su máximo marca la anomalía densa máfica.)
    g_target = residual
    peak_i = int(np.argmax(g_target))
    log.info(f"Pico de anomalía densa en (x={x[peak_i]/1000:.0f}km, z={z[peak_i]/1000:.0f}km), "
             f"residual = {g_target[peak_i]:.1f} mGal")

    g_si = g_target * 1e-5                          # mGal → m/s² (convención del motor)

    # ── Malla que cubre la ventana ──────────────────────────────────────────
    nx = int(np.ceil(x.max() / BLOCK)) + 1
    nz = int(np.ceil(z.max() / BLOCK)) + 1
    ny = NZ_DEPTH
    log.info(f"Malla: {nx}x{ny}x{nz} = {nx*ny*nz} vóxeles | celda {BLOCK/1000:.0f} km | "
             f"profundidad {ny*BLOCK/1000:.0f} km")

    _, _, _, x_c, y_c, z_c = build_voxel_grid(nx, ny, nz, BLOCK)
    sensors = np.column_stack([x, np.zeros_like(x), z]).astype(np.float64)   # y=0 datum plano

    # cutoff GRANDE: con celdas de 8 km, el default 800 m anularía todo
    forward = GravimetryForward(dx=BLOCK, dy=BLOCK, dz=BLOCK, cutoff_radius=2.0e6)
    inversor = GravimetryInversion(nx=nx, ny=ny, nz=nz, block_size=BLOCK)

    # lambda_mag CONECTADO al solver (fix de la auditoría) + α espacial moderado.
    # Barrido corto de λ; el centro de masa se mide sobre el CUERPO recuperado
    # (celdas con Δρ > 0.5·máx), no sobre todas las celdas positivas (que diluyen
    # el CoM hacia el fondo de la malla).
    noise = 0.02 * float(np.sqrt(np.mean(g_si ** 2)))
    best = None
    for lam in (0.3, 1.0, 3.0):
        est_density, prob, misfit, sens = inversor.solve_inversion_lsqr(
            g_observed=g_si, kernel_sparse=None, y_c=y_c, lambda_mag=lam,
            alpha_spatial=ALPHA_SPATIAL,
            forward_model=forward, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            noise_floor=noise, noise_pct=0.0,
        )
        contrast = np.nan_to_num(est_density - inversor.base_density, nan=0.0)
        dmax = float(contrast.max())
        body = contrast > 0.5 * dmax           # cuerpo recuperado (umbral estándar)
        w = contrast[body]; tot = w.sum()
        cmx = (w * x_c[body]).sum() / tot
        cmy = (w * y_c[body]).sum() / tot
        cmz = (w * z_c[body]).sum() / tot
        log.info(f"λ={lam:.2f} α={ALPHA_SPATIAL:.0f} | misfit={misfit:.1f}% | Δρmax={dmax:.2f} t/m³ | "
                 f"cuerpo@ x={cmx/1000:.0f}km z={cmz/1000:.0f}km prof={cmy/1000:.1f}km")
        if best is None or misfit < best["misfit"]:
            best = {"lam": lam, "misfit": misfit, "cmx": cmx, "cmy": cmy, "cmz": cmz,
                    "dmax": dmax}

    # ── Cordura física: ¿la masa densa cae bajo el pico de anomalía? ─────────
    dx_peak = abs(best["cmx"] - x[peak_i]); dz_peak = abs(best["cmz"] - z[peak_i])
    horiz_km = np.hypot(dx_peak, dz_peak) / 1000.0
    log.info("-" * 72)
    log.info(f"[CORDURA] Masa densa recuperada vs pico de anomalía: "
             f"desfase horizontal = {horiz_km:.0f} km")
    log.info(f"[CORDURA] Profundidad de la masa densa = {best['cmy']/1000:.1f} km "
             f"(intrusión Bushveld documentada: superficie → ~7-9 km)")
    log.info(f"[CORDURA] Δρ máx recuperado = {best['dmax']:.2f} t/m³ "
             f"(máfico Bushveld real ~ +0.3 a +0.5 t/m³ sobre corteza)")

    cert = {
        "audit": "real_data_bushveld",
        "dataset": "Zenodo 10.5281/zenodo.6511942 (CC-BY 4.0)",
        "n_stations_real": len(lon),
        "manual_preprocessing_NOT_in_engine": ["lonlat->meters projection",
                                               f"regional-residual (poly{REG_ORDER})",
                                               "topography neglected (flat datum)"],
        "residual_mgal": {"min": float(residual.min()), "max": float(residual.max()),
                          "std": float(residual.std())},
        "mesh": {"nx": nx, "ny": ny, "nz": nz, "block_m": BLOCK},
        "best_fit": best,
        "sanity_horiz_offset_km": horiz_km,
        "sanity_depth_km": best["cmy"]/1000.0,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_bushveld_results.json")
    json.dump(cert, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    log.info("=" * 72)
    log.info(f"Certificado: {out}")
    log.info("=" * 72)


if __name__ == "__main__":
    main()
