"""
DO-27 — Experimento de profundidad CON COBERTURA DISPERSA (régimen LdM con verdad)
==================================================================================

Los dos experimentos previos mostraron que en DO-27 la profundidad YA está bien
resuelta (~33 m) y que NI una malla 4× más profunda hace hundir el cuerpo. Conclusión
parcial: en DO-27 z no está mal → ni default ni ancla la mueven. Pero eso deja sin
responder la pregunta de venta: cuando z SÍ está mal, ¿1 pozo la colapsa?

El sospechoso que queda es la COBERTURA DE DATOS. LdM (donde z se hundió) tenía 191
estaciones dispersas sobre ~14 km; DO-27 tiene cobertura DENSA (256 estaciones sobre
600 m) de una anomalía compacta → la longitud de onda de la anomalía pinea la
profundidad. Aquí submuestreamos DO-27 a cobertura DISPERSA para inducir la ambigüedad
de z, manteniendo el ground truth, y medimos:

  B. Compacto (sano), cobertura dispersa   → ¿se degrada z al quitar estaciones?
  C. Compacto + 1 sondaje, dispersa        → cuánto colapsa z UN pozo cuando z está mal

Barremos varios niveles de dispersión (stride 2/4/6/8). Es la prueba honesta del
argumento de venta del ancla. Backend-only, sin tuneo.

USO:
  cd terraquantum-backend
  python scripts/validation/do27_depth_experiment_sparse.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from scripts.validation.do27_harness import (
    BASE_DENSITY,
    BLOCK_SIZE,
    CUTOFF,
    DENSITY_MAX,
    DENSITY_MIN,
    LAMBDA_GRAV,
    NX,
    NY,
    NZ,
    _Geometry,
    _grid_centers_fortran,
    _subsample,
    measure_geometry,
)
from scripts.validation.do27_depth_experiment import build_truth_anchor
from scripts.validation.ingest_do27 import (
    build_local_frame,
    load_gravity,
    load_ground_truth,
    load_magnetic,
)

COMPACT_IRLS = 2
STRIDES = [2, 4, 6, 8]   # 2 = denso (baseline); 8 = muy disperso (régimen LdM)


def _prepare_stride(grav, mag, fr, stride) -> _Geometry:
    """Igual que do27_harness._prepare pero con stride de sensores parametrizable."""
    ge, gn, gz, gv = _subsample(
        [grav.easting, grav.northing, grav.elevation, grav.bouguer_mgal], stride
    )
    gv = np.asarray(gv, dtype=np.float64) * 1e-5      # mGal → m/s² (igual que producción)
    sensors_g = fr.sensors(ge, gn, gz)
    x_c, y_c, z_c = _grid_centers_fortran(NX, NY, NZ, BLOCK_SIZE)
    sigma_g = max(0.02 * float(np.std(gv)), 1e-9)
    return _Geometry(
        sensors_g=sensors_g, g_obs=np.asarray(gv, dtype=np.float64), sigma_g=sigma_g,
        sensors_m=sensors_g, d_obs=gv, sigma_m=sigma_g,   # mag no se usa aquí
        x_c=x_c, y_c=y_c, z_c=z_c, igrf={},
    )


def invert(geo, *, regularization_norm, boreholes=None, anchor_mode="soft"):
    inv = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF)
    meta: dict = {}
    rho_full, _score, misfit, _sens = inv.solve_inversion_lsqr(
        geo.g_obs, None, geo.y_c,
        lambda_mag=LAMBDA_GRAV, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=geo.sensors_g,
        x_c=geo.x_c, z_c=geo.z_c,
        density_min=DENSITY_MIN, density_max=DENSITY_MAX,
        noise_floor=geo.sigma_g, noise_pct=0.02,
        auto_kappa=True, prune_observable_domain=True,
        regularization_norm=regularization_norm, compact_max_irls=COMPACT_IRLS,
        # Fase 4: `depth_beta` se elimino de solve_inversion_lsqr (era inerte: Ws lo cancelaba).
        boreholes=boreholes, anchor_mode=anchor_mode,
        solver_meta=meta,
    )
    return np.asarray(rho_full, dtype=np.float64), float(misfit), meta


def run() -> dict:
    t0 = time.time()
    grav = load_gravity()
    mag = load_magnetic()
    gt_g, _gt_m, raw = load_ground_truth()
    fr = build_local_frame(grav, mag)
    borehole, anchor_info = build_truth_anchor(gt_g, fr, raw)

    rows = []
    for stride in STRIDES:
        geo = _prepare_stride(grav, mag, fr, stride)
        n_sensors = int(geo.sensors_g.shape[0])
        print(f"\n=== stride={stride} ({n_sensors} estaciones) ===")

        rho_b, mf_b, _ = invert(geo, regularization_norm="compact")
        gb = measure_geometry(rho_b, geo.x_c, geo.y_c, geo.z_c, gt_g, fr, BASE_DENSITY)

        rho_c, mf_c, meta_c = invert(
            geo, regularization_norm="compact", boreholes=borehole, anchor_mode="hard")
        gc = measure_geometry(rho_c, geo.x_c, geo.y_c, geo.z_c, gt_g, fr, BASE_DENSITY)

        dz_b = gb.get("centroid_depth_error_m")
        dz_c = gc.get("centroid_depth_error_m")
        gain = None if (dz_b is None or dz_c is None) else round(dz_b - dz_c, 1)
        row = {
            "stride": stride, "n_sensors": n_sensors,
            "depth_err_no_anchor_m": dz_b, "depth_err_anchor_m": dz_c,
            "anchor_gain_m": gain,
            "horiz_no_anchor_m": gb.get("horizontal_error_m"),
            "horiz_anchor_m": gc.get("horizontal_error_m"),
            "recovered_depth_no_anchor_m": gb.get("recovered_centroid_depth_m"),
            "recovered_depth_anchor_m": gc.get("recovered_centroid_depth_m"),
            "misfit_no_anchor_pct": round(mf_b, 3), "misfit_anchor_pct": round(mf_c, 3),
            "n_anchored_voxels": meta_c.get("n_anchored_voxels"),
        }
        rows.append(row)
        print(f"   z err: sin ancla = {dz_b}m → con ancla = {dz_c}m (ganancia {gain}m) | "
              f"horiz {gb.get('horizontal_error_m')}→{gc.get('horizontal_error_m')}m")

    report = {
        "dataset": "DO-27 — profundidad vs COBERTURA (denso→disperso), B=compacto sin ancla, C=+1 ancla dura",
        "true_centroid_depth_m": 199.7,
        "mesh": {"nx": NX, "ny": NY, "nz": NZ, "block_size_m": BLOCK_SIZE,
                 "depth_extent_m": NY * BLOCK_SIZE},
        "synthetic_anchor": anchor_info,
        "rows": rows,
        "elapsed_s": round(time.time() - t0, 1),
    }
    report["table_markdown"] = render_table(rows)
    return report


def render_table(rows) -> str:
    h = ("| Estaciones (stride) | z err SIN ancla | z err CON ancla | ganancia ancla | horiz sin→con |\n"
         "|---------------------|-----------------|-----------------|----------------|---------------|")
    out = [h]

    def _m(v):
        return "—" if v is None else f"{v:.1f}m"
    for r in rows:
        out.append(
            f"| {r['n_sensors']} (s{r['stride']}) | {_m(r['depth_err_no_anchor_m'])} | "
            f"{_m(r['depth_err_anchor_m'])} | {_m(r['anchor_gain_m'])} | "
            f"{_m(r['horiz_no_anchor_m'])}→{_m(r['horiz_anchor_m'])} |"
        )
    return "\n".join(out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = run()
    print("\n" + "=" * 80)
    print("DO-27 — PROFUNDIDAD vs COBERTURA DE DATOS (denso → disperso)")
    print("=" * 80)
    print(f"\nProfundidad verdadera del centroide: {report['true_centroid_depth_m']}m")
    print("\n" + report["table_markdown"])
    print(f"\nTiempo: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "do27_depth_experiment_sparse_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
