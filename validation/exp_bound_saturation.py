"""
Experimento: ¿es el BOUND INFERIOR el mecanismo de la bimodalidad?

Los logs de producción muestran, en el brazo estricto, `sat_pct_core ≈ 91 %`: casi todas
las celdas del núcleo quedan pegadas al límite inferior de densidad. Cuando el 91 % de las
incógnitas está en el bound, la solución la determina **qué celdas escapan** — un conjunto
activo, es decir una elección combinatoria. Y un conjunto activo puede cambiar de golpe con
una perturbación pequeña del dato, mientras el ajuste (χ²) apenas se mueve.

Esa es la hipótesis que explicaría lo medido en `exp_bimodal.py`: 33 % de caídas, χ²
solapado, mismo λ, y dos poblaciones en vez de una nube.

PREDICCIONES CONTRASTABLES:
  (a) Si el bound es el mecanismo, aflojarlo debería reducir la saturación y, con ella, la
      bimodalidad — aunque empeore otras cosas.
  (b) El brazo permisivo (base − 0.5) ya se midió: PR-AUC 0.037 ± 0.003, es decir
      **consistentemente malo, NO bimodal**. Dos modos de fallo distintos.
  (c) Si el bound NO es el mecanismo, la tasa de caída debería ser parecida en los 4 brazos.

    python -m validation.exp_bound_saturation --seeds 8
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

import polars as pl

from .contract import Provenance, SolverConfig
from .regimes import BLOCK_M, DIAGNOSTIC, W_BASE, _campaign
from .runner import run_case, tq_version
from .store import results_home

REPO = Path(__file__).resolve().parents[1]
FAIL_PR_AUC = 0.90
SEEDS = tuple(810_001 + 211 * i for i in range(16))

# El sondeo mostró que la transición es ABRUPTA: con base −0.05 el modelo ya se hunde
# (PR-AUC 0.03-0.04, idéntico al brazo permisivo de −0.50). Así que el barrido fino va
# entre 0.00 y −0.05, no hasta −0.50.
ARMS_REL = (0.0, -0.01, -0.02, -0.05)


def _arm(rel: float) -> SolverConfig:
    # OJO: el backend valida `run_id` y RECHAZA '+' y '.'. El id del brazo entra en el
    # run_id, así que sólo puede llevar letras, números, guion y guion bajo.
    tag = ("p" if rel >= 0 else "m") + f"{abs(rel):.2f}".replace(".", "")
    return SolverConfig(
        schema_version="solver_config/1",
        id=f"s_bound_{tag}",
        lambda_mode="morozov", lambda_fixed=None,
        density_min_rel_base=rel, density_max_rel_base=2.0,
        regularization_norm="L2",
        rationale=("Brazo del experimento de saturacion de bound. Barre el limite inferior "
                   "entre el estricto (0.00, que satura ~91% del nucleo) y el permisivo "
                   "(-0.50, medido como consistentemente malo pero NO bimodal). El objetivo "
                   "es localizar donde aparece la bimodalidad, no elegir un valor."),
        provenance=Provenance(seed=0, generator_version="exp_bound_saturation/1"),
    )


def _saturation(run_id: str, base_density: float, floor_rel: float):
    """Fracción de celdas del núcleo pegadas al bound inferior, leída del parquet."""
    hits = list((REPO / "terraquantum-backend" / "data" / "projects").glob(
        f"*/runs/{run_id}/block_model.parquet"))
    if not hits:
        return None, None
    df = pl.read_parquet(hits[0])
    if "density_contrast_t_m3" in df.columns:
        c = df["density_contrast_t_m3"].to_numpy().astype(np.float64)
    elif "density" in df.columns:
        c = df["density"].to_numpy().astype(np.float64) - base_density
    else:
        return None, None
    at_floor = float(np.mean(c <= floor_rel + 1e-6))
    free = int(np.sum(c > floor_rel + 0.01))
    return at_floor, free


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--arms", type=str, default=None,
                    help="lista separada por comas de density_min RELATIVO al fondo, "
                         "p.ej. '0,-2.6' para comparar el estricto contra el DEFAULT "
                         "de la API (density_min=0.0 absoluto, base 2.6 -> contraste -2.6)")
    args = ap.parse_args()
    seeds = SEEDS[:max(2, min(args.seeds, len(SEEDS)))]
    global ARMS_REL
    if args.arms:
        ARMS_REL = tuple(float(x) for x in args.arms.split(","))
    base = float(W_BASE.properties.background.density_t_m3)

    print("=" * 96)
    print("EXPERIMENTO — ¿el bound inferior explica la bimodalidad?")
    print("=" * 96)
    print(f"Version TQ : {tq_version()}   mundo {W_BASE.id}   {len(ARMS_REL)} brazos x "
          f"{len(seeds)} semillas = {len(ARMS_REL)*len(seeds)} inversiones")
    print()

    rows, summary, errors = [], [], []
    for rel in ARMS_REL:
        solver = _arm(rel)
        per = []
        print(f"# density_min = base {rel:+.2f}  ({solver.id})")
        for s in seeds:
            camp = _campaign(f"c_bound{solver.id}_s{s}", W_BASE, s)
            res = run_case(W_BASE, camp, DIAGNOSTIC, block_m=BLOCK_M, tau_frac_of_peak=0.50,
                           error_is_large_above_m=200.0, solver=solver)
            if res.verdict == "ERROR":
                errors.append((solver.id, s, res.error))
                print(f"   semilla {s}: ERROR {res.error[:60]}")
                continue
            sat, free = _saturation(res.run_id, base, rel)
            row = dict(arm=solver.id, rel=rel, seed=s, pr_auc=res.metrics.pr_auc,
                       horizontal_m=res.metrics.horizontal_error_m,
                       depth_m=res.metrics.depth_error_centroid_m,
                       chi2=res.metrics.chi2_red, sat_frac=sat, n_free=free,
                       lam=res.tq_config.get("lambda_selected"))
            per.append(row)
            rows.append(row)
            tag = "OK " if row["pr_auc"] >= FAIL_PR_AUC else "CAE"
            sat_s = f"{100*sat:5.1f}%" if sat is not None else "  n/d"
            print(f"   semilla {s}  {tag}  PR-AUC {row['pr_auc']:5.3f}  "
                  f"horiz {row['horizontal_m']:7.1f} m  bound {sat_s}  libres {free}")

        if not per:
            continue
        prs = [r["pr_auc"] for r in per]
        hs = [r["horizontal_m"] for r in per]
        sats = [r["sat_frac"] for r in per if r["sat_frac"] is not None]
        nf = len([r for r in per if r["pr_auc"] < FAIL_PR_AUC])
        summary.append(dict(
            arm=solver.id, rel=rel, n=len(per), fails=nf, fail_rate=nf / len(per),
            pr_med=st.median(prs), pr_min=min(prs), pr_max=max(prs),
            hor_med=st.median(hs), hor_min=min(hs), hor_max=max(hs),
            sat_med=(st.median(sats) if sats else None),
        ))
        print()

    print("=" * 96)
    print(f"{'density_min':>12s} {'caidas':>8s} {'PR-AUC med':>11s} {'PR-AUC rango':>16s} "
          f"{'horiz med':>10s} {'horiz rango':>16s} {'bound%':>8s}")
    print("-" * 96)
    for s in summary:
        sat = f"{100*s['sat_med']:6.1f}%" if s["sat_med"] is not None else "   n/d"
        print(f"  base {s['rel']:+.2f} {s['fails']:3d}/{s['n']:<4d} {s['pr_med']:11.3f} "
              f"{s['pr_min']:7.3f}-{s['pr_max']:<7.3f} {s['hor_med']:10.1f} "
              f"{s['hor_min']:7.1f}-{s['hor_max']:<7.1f} {sat:>8s}")

    print()
    print("Saturacion en el bound: ¿difiere entre aciertos y caidas DENTRO de cada brazo?")
    for rel in ARMS_REL:
        sub = [r for r in rows if r["rel"] == rel and r["sat_frac"] is not None]
        ok = [r["sat_frac"] for r in sub if r["pr_auc"] >= FAIL_PR_AUC]
        bad = [r["sat_frac"] for r in sub if r["pr_auc"] < FAIL_PR_AUC]
        f_ok = [r["n_free"] for r in sub if r["pr_auc"] >= FAIL_PR_AUC]
        f_bad = [r["n_free"] for r in sub if r["pr_auc"] < FAIL_PR_AUC]
        def m(v):
            return f"{100*st.median(v):.1f}%" if v else "-"
        def mi(v):
            return f"{st.median(v):.0f}" if v else "-"
        print(f"  base {rel:+.2f}: aciertos bound={m(ok):>7s} libres={mi(f_ok):>5s} (n={len(ok)})   "
              f"caidas bound={m(bad):>7s} libres={mi(f_bad):>5s} (n={len(bad)})")

    # Nunca fallar en silencio: un brazo entero puede desaparecer del resumen por errores
    # y la tabla se vería igual de sana. (Pasó en el sondeo: el '+' del id rompía el run_id.)
    print()
    if errors:
        print(f"!! {len(errors)} CORRIDAS CON ERROR — el resumen de arriba está INCOMPLETO")
        for arm, s, e in errors[:8]:
            print(f"   {arm} semilla {s}: {str(e)[:80]}")
        faltan = {a for a, _, _ in errors}
        print(f"   brazos afectados: {sorted(faltan)}")
    else:
        print(f"Sin errores: {len(rows)}/{len(ARMS_REL)*len(seeds)} corridas válidas.")

    dest = results_home() / tq_version() / "exp_bound_saturation.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"tq_version": tq_version(), "world": W_BASE.id,
                                "seeds": list(seeds), "summary": summary, "runs": rows},
                               indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
