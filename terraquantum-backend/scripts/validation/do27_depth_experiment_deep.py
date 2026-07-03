"""
DO-27 — Experimento de profundidad EN RÉGIMEN AMBIGUO (malla profunda tipo LdM)
==============================================================================

El experimento somero (do27_depth_experiment.py) mostró que en DO-27 la profundidad
YA está bien resuelta (~33 m) con la malla de 500 m: ni el default ni 1 ancla la
mueven. Razón: la malla somera + cobertura densa no le dan al cuerpo espacio para
hundirse. DO-27-somero NO tiene la enfermedad de z, así que no puede mostrar la cura.

Este script recrea el RÉGIMEN de Laguna del Maule (donde el cuerpo se hundió a ~4.8 km)
PERO con el ground truth de DO-27: misma física, mismos datos, misma cobertura, pero
una malla PROFUNDA (le damos al solver espacio vertical para que la no-unicidad de z
se manifieste). Ahí medimos:

  A. Default (L2), malla profunda      → ¿se hunde el cuerpo? (régimen LdM con verdad)
  B. Compacto (sano), malla profunda   → ¿cuánto arregla la norma?
  C. Compacto + 1 sondaje, malla prof. → cuánto colapsa z UN pozo cuando z SÍ está mal

Es la prueba honesta del argumento de venta del ancla: sólo aporta cuando hay algo
que arreglar. Backend-only, sin tuneo.

USO:
  cd terraquantum-backend
  python scripts/validation/do27_depth_experiment_deep.py
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
    NZ,
    _grid_centers_fortran,
    _prepare,
    measure_geometry,
)
from scripts.validation.do27_depth_experiment import build_truth_anchor
from scripts.validation.ingest_do27 import (
    build_local_frame,
    load_gravity,
    load_ground_truth,
    load_magnetic,
)

# Malla PROFUNDA: en vez de 10 celdas (500 m) bajamos 40 celdas (2000 m) → 4× el
# espacio vertical. El cuerpo verdadero está a ~200 m; el resto de la malla es
# "espacio libre" donde la no-unicidad puede empujar la masa hacia abajo (como LdM).
NY_DEEP = 40
COMPACT_IRLS = 2


def _deep_geo(grav, mag, fr):
    """Reusa la preparación del harness (sensores/datos/sigma) pero con malla profunda."""
    geo = _prepare(grav, mag, fr)
    geo.x_c, geo.y_c, geo.z_c = _grid_centers_fortran(NX, NY_DEEP, NZ, BLOCK_SIZE)
    return geo


def invert_deep(geo, *, regularization_norm, boreholes=None, anchor_mode="soft"):
    inv = GravimetryInversion(NX, NY_DEEP, NZ, BLOCK_SIZE, base_density=BASE_DENSITY)
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
        depth_beta=2.0,
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
    geo = _deep_geo(grav, mag, fr)

    borehole, anchor_info = build_truth_anchor(gt_g, fr, raw)

    configs = [
        ("A_default_L2", "Default (L2) · malla profunda", {"regularization_norm": "L2"}),
        ("B_compact_sane", "Compacto (sano) · malla profunda", {"regularization_norm": "compact"}),
        ("C_compact_anchor", "Compacto + 1 sondaje · malla profunda",
         {"regularization_norm": "compact", "boreholes": borehole, "anchor_mode": "hard"}),
    ]

    results = {}
    for key, label, kw in configs:
        print(f"\n[{key}] {label} ...")
        rho, misfit, meta = invert_deep(geo, **kw)
        geom = measure_geometry(rho, geo.x_c, geo.y_c, geo.z_c, gt_g, fr, BASE_DENSITY)
        geom["misfit_percent"] = round(misfit, 3)
        geom["label"] = label
        results[key] = geom
        print(f"   err prof centroide = {geom['centroid_depth_error_m']}m | "
              f"prof recuperada = {geom['recovered_centroid_depth_m']}m "
              f"(verdadera {geom['true_centroid_depth_m']}m) | "
              f"err horiz = {geom['horizontal_error_m']}m | misfit = {geom['misfit_percent']}%")

    report = {
        "dataset": "DO-27 — experimento de profundidad EN MALLA PROFUNDA (régimen LdM con ground truth)",
        "mesh": {"nx": NX, "ny": NY_DEEP, "nz": NZ, "block_size_m": BLOCK_SIZE,
                 "depth_extent_m": NY_DEEP * BLOCK_SIZE, "n_sensors_used": int(geo.sensors_g.shape[0])},
        "true_centroid_depth_m": results["A_default_L2"]["true_centroid_depth_m"],
        "synthetic_anchor": anchor_info,
        "results": results,
        "deltas": {
            "fixable_default_A_to_B_m": _delta(results, "A_default_L2", "B_compact_sane"),
            "anchor_gain_B_to_C_m": _delta(results, "B_compact_sane", "C_compact_anchor"),
            "anchor_gain_A_to_C_m": _delta(results, "A_default_L2", "C_compact_anchor"),
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    report["table_markdown"] = render_table(results)
    return report


def _delta(results, k_from, k_to):
    a = results[k_from].get("centroid_depth_error_m")
    b = results[k_to].get("centroid_depth_error_m")
    if a is None or b is None:
        return None
    return round(a - b, 1)


def render_table(results: dict) -> str:
    order = ["A_default_L2", "B_compact_sane", "C_compact_anchor"]
    h = ("| Configuración | err prof centroide | prof recuperada | err horiz | misfit |\n"
         "|---------------|--------------------|-----------------|-----------|--------|")
    lines = [h]
    for k in order:
        d = results[k]

        def _m(v, suf="m"):
            return "—" if v is None else f"{v:.1f}{suf}"
        lines.append(
            f"| {d['label']} | {_m(d.get('centroid_depth_error_m'))} | "
            f"{_m(d.get('recovered_centroid_depth_m'))} | {_m(d.get('horizontal_error_m'))} | "
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
    print("DO-27 — EXPERIMENTO DE PROFUNDIDAD EN MALLA PROFUNDA (régimen LdM con verdad)")
    print("=" * 80)
    print(f"\nProfundidad verdadera del centroide: {report['true_centroid_depth_m']}m bajo datum")
    print(f"Malla: baja {report['mesh']['depth_extent_m']}m (espacio para que z se hunda)")
    print("\n" + report["table_markdown"])
    d = report["deltas"]
    print(f"\nArreglable por default (A→B): {d['fixable_default_A_to_B_m']}m")
    print(f"Ganancia con 1 sondaje (B→C): {d['anchor_gain_B_to_C_m']}m")
    print(f"Ganancia total default→ancla (A→C): {d['anchor_gain_A_to_C_m']}m")
    print(f"\nTiempo: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "do27_depth_experiment_deep_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
