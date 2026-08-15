"""
DO-27 — Experimento de PROFUNDIDAD: ¿cuánto de la borrosidad en z es física
irreducible vs cuánto es un default malo?
============================================================================

Toma el MISMO dato DO-27 (ground truth de profundidad conocido, Astic & Oldenburg
2020) y corre la inversión GRAVIMÉTRICA SOLA bajo 3 configuraciones, midiendo en
cada una el error de profundidad del centroide recuperado contra el ground truth:

  A. "Default (L2)"        — Tikhonov L2 (la norma histórica antes de Fase 24B).
                             Aísla cuánto sesgo de profundidad arrastra el default.
  B. "Compacto (sano)"     — norma minimum-support (Fase 24B), depth_beta=2 estándar,
                             bounds petrofísicos correctos. = config embarcada hoy.
                             Aísla cuánto del mal número era arreglable (A→B).
  C. "Compacto + 1 sondaje"— B + UN sondaje sintético de ancla DURA (Fase 2.1) en la
                             posición verdadera del cuerpo, con su densidad verdadera.
                             Mide cuánto colapsa la incertidumbre de z con 1 pozo (B→C).

NO se tunea nada para pasar. Mismo dato, misma malla, mismos sensores en las 3.
Lo único que cambia es la columna que se está testeando. Backend-only.

CONTEXTO HONESTO: el hundimiento a ~4.8 km que se vio en Laguna del Maule (LdM) NO
se reproduce en DO-27 — la malla DO-27 baja solo ~500 m y la cobertura es densa, así
que el cuerpo no tiene a dónde hundirse. Este experimento mide lo que SÍ es medible
en DO-27 con ground truth: el sesgo de profundidad del default y el colapso con 1
ancla. La interpretación del límite irreducible se discute en el reporte.

USO:
  cd terraquantum-backend
  python scripts/validation/do27_depth_experiment.py
  # → imprime la tabla y escribe scripts/validation/do27_depth_experiment_report.json
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
    _prepare,
    _truth_to_local,
    measure_geometry,
)
from scripts.validation.ingest_do27 import (
    build_local_frame,
    load_gravity,
    load_ground_truth,
    load_magnetic,
)

COMPACT_IRLS = 2


# ══════════════════════════════════════════════════════════════════════════════
#  Inversión gravimétrica parametrizable (la ÚNICA variable es la config)
# ══════════════════════════════════════════════════════════════════════════════
def invert_gravity_cfg(geo, *, regularization_norm: str, boreholes=None,
                       anchor_mode: str = "soft") -> tuple[np.ndarray, float, dict]:
    """Corre gravimetría sola con la norma/anclaje pedidos. Todo lo demás constante."""
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


# ══════════════════════════════════════════════════════════════════════════════
#  Sondaje sintético de ancla en la posición VERDADERA del cuerpo
# ══════════════════════════════════════════════════════════════════════════════
def build_truth_anchor(gt, fr, raw) -> tuple[np.ndarray, dict]:
    """1 sondaje vertical en el centroide verdadero (x,z), intersectando el cuerpo de
    su techo a su base verdaderos, anclado a la densidad VERDADERA del cuerpo.

    Densidad verdadera = base_density + contraste medio del cuerpo en el modelo .den
    (el .den almacena el contraste Δρ; 0 = roca caja). Es el valor que un sondaje real
    leería: no se inventa, se toma del ground truth peer-reviewed.
    """
    tx, ty, tz = _truth_to_local(gt, fr)          # x=Norte, y=prof, z=Este (local)
    den = raw["den"]
    body = (den != 0.0) & (den != -100.0)
    mean_contrast = float(np.mean(den[body]))     # Δρ medio (negativo: kimberlita)
    anchor_density = BASE_DENSITY + mean_contrast

    # Intervalo vertical del sondaje = techo→base verdaderos bajo datum.
    y_top = float(fr.datum_elev - gt.top_elevation)
    y_bot = float(fr.datum_elev - gt.bottom_elevation)

    borehole = np.array([[tx, tz, y_top, y_bot, anchor_density]], dtype=np.float64)
    info = {
        "local_xz_m": [round(tx, 1), round(tz, 1)],
        "interval_depth_m": [round(y_top, 1), round(y_bot, 1)],
        "anchored_density_t_m3": round(anchor_density, 3),
        "mean_density_contrast_t_m3": round(mean_contrast, 3),
        "true_centroid_depth_m": round(ty, 1),
    }
    return borehole, info


# ══════════════════════════════════════════════════════════════════════════════
#  Orquestación
# ══════════════════════════════════════════════════════════════════════════════
def run() -> dict:
    t0 = time.time()
    grav = load_gravity()
    mag = load_magnetic()
    gt_g, _gt_m, raw = load_ground_truth()
    fr = build_local_frame(grav, mag)
    geo = _prepare(grav, mag, fr)

    borehole, anchor_info = build_truth_anchor(gt_g, fr, raw)

    configs = [
        ("A_default_L2", "Default (L2)", {"regularization_norm": "L2"}),
        ("B_compact_sane", "Compacto (sano)", {"regularization_norm": "compact"}),
        ("C_compact_anchor", "Compacto + 1 sondaje",
         {"regularization_norm": "compact", "boreholes": borehole, "anchor_mode": "hard"}),
    ]

    results = {}
    for key, label, kw in configs:
        print(f"\n[{key}] {label} ...")
        rho, misfit, meta = invert_gravity_cfg(geo, **kw)
        geom = measure_geometry(rho, geo.x_c, geo.y_c, geo.z_c, gt_g, fr, BASE_DENSITY)
        geom["misfit_percent"] = round(misfit, 3)
        geom["label"] = label
        geom["acond"] = meta.get("acond")
        geom["n_anchored_voxels"] = meta.get("n_anchored_voxels")
        results[key] = geom
        print(f"   err prof centroide = {geom['centroid_depth_error_m']}m | "
              f"err horiz = {geom['horizontal_error_m']}m | misfit = {geom['misfit_percent']}%")

    report = {
        "dataset": "DO-27 Tli Kwi Cho (Astic & Oldenburg 2020) — experimento de profundidad",
        "question": ("¿Cuánto de la borrosidad en z es física irreducible vs default malo? "
                     "A=default L2, B=compacto sano, C=compacto+1 ancla."),
        "mesh": {"nx": NX, "ny": NY, "nz": NZ, "block_size_m": BLOCK_SIZE,
                 "depth_extent_m": NY * BLOCK_SIZE, "n_sensors_used": int(geo.sensors_g.shape[0])},
        "true_centroid_depth_m": results["A_default_L2"]["true_centroid_depth_m"],
        "true_top_depth_m": results["A_default_L2"]["true_top_depth_m"],
        "synthetic_anchor": anchor_info,
        "results": results,
        "deltas": {
            "fixable_default_A_to_B_m": _delta(results, "A_default_L2", "B_compact_sane"),
            "anchor_gain_B_to_C_m": _delta(results, "B_compact_sane", "C_compact_anchor"),
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    report["table_markdown"] = render_table(results)
    return report


def _delta(results, k_from, k_to) -> float | None:
    a = results[k_from].get("centroid_depth_error_m")
    b = results[k_to].get("centroid_depth_error_m")
    if a is None or b is None:
        return None
    return round(a - b, 1)


def render_table(results: dict) -> str:
    order = ["A_default_L2", "B_compact_sane", "C_compact_anchor"]
    h = ("| Configuración | err prof centroide | err prof techo | err horiz | misfit |\n"
         "|---------------|--------------------|----------------|-----------|--------|")
    lines = [h]
    for k in order:
        d = results[k]

        def _m(v):
            return "—" if v is None else f"{v:.1f}m"
        lines.append(
            f"| {d['label']} | {_m(d.get('centroid_depth_error_m'))} | "
            f"{_m(d.get('top_depth_error_m'))} | {_m(d.get('horizontal_error_m'))} | "
            f"{d.get('misfit_percent')}% |"
        )
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = run()
    print("\n" + "=" * 80)
    print("DO-27 — EXPERIMENTO DE PROFUNDIDAD (física irreducible vs default malo)")
    print("=" * 80)
    print(f"\nProfundidad verdadera del centroide: {report['true_centroid_depth_m']}m bajo datum")
    print(f"Malla: baja {report['mesh']['depth_extent_m']}m ({report['mesh']['nz']}×"
          f"{report['mesh']['nx']}×{report['mesh']['ny']} celdas de {report['mesh']['block_size_m']}m)")
    print("\n" + report["table_markdown"])
    d = report["deltas"]
    print(f"\nArreglable por default (A→B): {d['fixable_default_A_to_B_m']}m de mejora")
    print(f"Ganancia con 1 sondaje (B→C): {d['anchor_gain_B_to_C_m']}m de mejora")
    print(f"\nTiempo: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "do27_depth_experiment_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
