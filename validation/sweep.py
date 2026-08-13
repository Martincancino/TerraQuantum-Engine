"""
Barrido de regímenes con MÚLTIPLES SEMILLAS y agregación media ± σ.

    python -m validation.sweep --probe          # 1 régimen x 1 semilla (mide tiempo)
    python -m validation.sweep --seeds 2        # todos los regímenes, 2 semillas
    python -m validation.sweep                  # completo: 15 regímenes x 5 semillas

P7 — la varianza ES el hallazgo: `docs/05` §A′ midió 288 ± 550 m en un régimen
donde una sola semilla habría reportado un número tranquilizador y falso. Por eso
la unidad de reporte es media ± σ sobre N semillas, nunca un valor suelto.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .regimes import (BLOCK_M, DIAGNOSTIC, REGIMES, SEEDS, campaigns_for)
from .solver_configs import ARMS
from .runner import run_case, tq_version
from .store import results_home, save

TAU = 0.50
ERROR_LARGE_ABOVE_M = 200.0
METRIC_KEYS = ("horizontal_error_m", "depth_error_centroid_m",
               "pr_auc", "iou_auc", "chi2_red", "misfit_pct")


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def agg(values):
    """media ± σ ignorando NaN. Devuelve (media, sigma, n_validos)."""
    v = [x for x in values if x == x]
    if not v:
        return float("nan"), float("nan"), 0
    return (statistics.fmean(v),
            statistics.stdev(v) if len(v) > 1 else 0.0,
            len(v))


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    ap.add_argument("--probe", action="store_true",
                    help="1 regimen x 1 semilla: mide el coste antes de comprometerse")
    args = ap.parse_args()

    regimes = REGIMES[:1] if args.probe else REGIMES
    seeds = SEEDS[:1] if args.probe else SEEDS[:max(1, args.seeds)]

    print("=" * 92)
    print("VALIDATION FRAMEWORK - BARRIDO DE REGIMENES (Sprint 2)")
    print("=" * 92)
    print(f"Version de TQ  : {tq_version()}")
    print(f"Regimenes      : {len(regimes)}   Semillas: {len(seeds)}   "
          f"Brazos: {len(ARMS)}   Inversiones: {len(regimes)*len(seeds)*len(ARMS)}")
    print(f"Brazos         : {', '.join(s.id for s in ARMS)}")
    print(f"Config         : PRODUCCION (Morozov, sigma declarado). density_min es "
          f"VARIABLE declarada, no default (Sprint 2)")
    print(f"Malla          : 18x14x18 @ {BLOCK_M:.0f} m (identica a error_budget.py)")

    rows, t_start = [], time.perf_counter()
    for solver in ARMS:
      print("\n" + "#" * 92)
      print(f"# BRAZO: {solver.id}  (density_min = base {solver.density_min_rel_base:+.2f}, "
            f"{solver.regularization_norm}, lambda={solver.lambda_mode})")
      print("#" * 92)
      for i, (name, world, kw, axis) in enumerate(regimes, 1):
          per_metric = {k: [] for k in METRIC_KEYS}
          quadrants, lambdas = [], []
          t_reg = time.perf_counter()

          for campaign in campaigns_for(name, world, kw, seeds):
              res = run_case(world, campaign, DIAGNOSTIC, block_m=BLOCK_M,
                             tau_frac_of_peak=TAU,
                             error_is_large_above_m=ERROR_LARGE_ABOVE_M,
                             solver=solver)
              save(res)
              if res.verdict == "ERROR":
                  print(f"  [{name}] ERROR: {res.error[:90]}")
                  continue
              for k in METRIC_KEYS:
                  per_metric[k].append(getattr(res.metrics, k))
              quadrants.append(res.calibration.quadrant)
              lam = res.tq_config.get("lambda_selected")
              if isinstance(lam, (int, float)) and lam == lam:
                  lambdas.append(float(lam))

          row = {"regime": name, "axis": axis, "world": world.id,
                 "solver_config": solver.id,
                 "n_seeds": len(seeds),
                 "quadrants": quadrants,
                 "lambda_median": (statistics.median(lambdas) if lambdas else None)}
          for k in METRIC_KEYS:
              m, s, n = agg(per_metric[k])
              row[k] = {"mean": m, "sigma": s, "n": n}
          rows.append(row)

          h = row["horizontal_error_m"]
          d = row["depth_error_centroid_m"]
          print(f"\n[{i}/{len(regimes)}] {name:16s} ({axis:12s}) "
                f"{time.perf_counter()-t_reg:6.0f}s")
          print(f"     horizontal {h['mean']:8.1f} +/- {h['sigma']:6.1f} m   |   "
                f"profundidad {d['mean']:8.1f} +/- {d['sigma']:6.1f} m   |   "
                f"lambda~{row['lambda_median']}")

    total_s = time.perf_counter() - t_start
    _table(rows)

    out = results_home() / tq_version() / "sweep_regimes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"tq_version": tq_version(), "config": "production_morozov",
         "mesh": [18, 14, 18, BLOCK_M], "seeds": list(seeds), "arms": [s.id for s in ARMS],
         "runtime_s": total_s, "rows": rows},
        indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {out}")
    print(f"Tiempo total: {total_s/60:.1f} min "
          f"({total_s/max(len(regimes)*len(seeds)*len(ARMS),1):.0f} s por inversion)")
    return 0


def _table(rows):
    print("\n" + "=" * 92)
    print("TABLA  error x regimen   (media +/- sigma sobre semillas, config de PRODUCCION)")
    print("=" * 92)
    print(f"{'regimen':16s} {'eje':9s} {'config':12s} {'horizontal (m)':>19s} "
          f"{'profundidad (m)':>19s} {'PR-AUC':>13s}")
    print("-" * 92)
    for r in rows:
        h, d, p = r["horizontal_error_m"], r["depth_error_centroid_m"], r["pr_auc"]
        print(f"{r['regime']:16s} {r['axis'][:9]:9s} {r['solver_config'][2:14]:12s} "
              f"{h['mean']:11.1f} +/- {h['sigma']:5.1f} "
              f"{d['mean']:12.1f} +/- {d['sigma']:5.1f} "
              f"{p['mean']:8.3f} +/- {p['sigma']:4.3f}")

    over = [r["regime"] for r in rows if "SOBRECONFIADO" in r["quadrants"]]
    print("-" * 92)
    print(f"Cuadrante SOBRECONFIADO (error grande + confianza alta): "
          f"{len(over)} regimenes {over if over else ''}")


if __name__ == "__main__":
    raise SystemExit(main())