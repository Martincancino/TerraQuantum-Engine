"""
Experimento: ¿cuál es la tasa real de fallo en `baseline`, y qué la causa?

El barrido del 2026-08-06 midió, en el régimen donde el producto declara su fortaleza,
una distribución BIMODAL sobre 5 semillas: tres corridas con PR-AUC 1.000 y error de
5-18 m, dos con PR-AUC 0.58-0.70 y error de 208-285 m.

Con 5 semillas —y encima correlacionadas entre regímenes— no se puede afirmar una tasa.
Este experimento aísla la pregunta:

    MISMO mundo, MISMA geometría de survey, MISMA configuración de solver.
    Lo ÚNICO que cambia es la realización de ruido (0.02 mGal).

Si la distribución sigue siendo bimodal con N semillas frescas e independientes, entonces
**el resultado de TerraQuantum en este régimen lo elige el ruido, no el dato** — y eso es
un hallazgo del producto, no del harness.

    python -m validation.exp_bimodal --seeds 12
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .regimes import BLOCK_M, DIAGNOSTIC, W_BASE, _campaign
from .runner import run_case, tq_version
from .solver_configs import STRICT
from .store import results_home

# Semillas frescas, sin solape con las del barrido (20260805, 11, 202, 3003, 40004).
# Elegidas como una secuencia simple y declarada, no cazadas para producir un resultado.
FRESH_SEEDS = tuple(700_001 + 137 * i for i in range(24))

FAIL_PR_AUC = 0.90      # frontera declarada: por encima, el ranking es esencialmente perfecto


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    args = ap.parse_args()
    seeds = FRESH_SEEDS[:max(2, min(args.seeds, len(FRESH_SEEDS)))]

    print("=" * 88)
    print("EXPERIMENTO BIMODAL - baseline, solo cambia la realizacion de ruido")
    print("=" * 88)
    print(f"Version de TQ : {tq_version()}")
    print(f"Mundo         : {W_BASE.id} (esfera r=150 m a 400 m, contraste +0.6)")
    print(f"Survey        : 12x12 sobre 1500 m, ruido 0.02 mGal — geometria FIJA")
    print(f"Solver        : {STRICT.id}")
    print(f"Semillas      : {len(seeds)} frescas, sin solape con el barrido")
    print()

    out, t0 = [], time.perf_counter()
    for i, s in enumerate(seeds, 1):
        camp = _campaign(f"c_expbimodal_s{s}", W_BASE, s)
        res = run_case(W_BASE, camp, DIAGNOSTIC, block_m=BLOCK_M, tau_frac_of_peak=0.50,
                       error_is_large_above_m=200.0, solver=STRICT)
        if res.verdict == "ERROR":
            print(f"[{i:2d}/{len(seeds)}] semilla {s}: ERROR {res.error[:70]}")
            continue
        m, cal = res.metrics, res.calibration
        row = dict(seed=s, pr_auc=m.pr_auc, horizontal_m=m.horizontal_error_m,
                   depth_m=m.depth_error_centroid_m, chi2=m.chi2_red,
                   misfit_pct=m.misfit_pct, lam=res.tq_config.get("lambda_selected"),
                   confidence=cal.declared_confidence,
                   depth_confidence=cal.declared_depth_confidence,
                   null_space=cal.is_null_space_artifact)
        out.append(row)
        flag = "OK  " if m.pr_auc >= FAIL_PR_AUC else "CAE "
        print(f"[{i:2d}/{len(seeds)}] semilla {s}  {flag} PR-AUC {m.pr_auc:5.3f}  "
              f"horiz {m.horizontal_error_m:7.1f} m  prof {m.depth_error_centroid_m:7.1f} m  "
              f"chi2 {m.chi2_red:5.3f}  lambda {row['lam']}")

    if not out:
        print("Sin resultados.")
        return 1

    prs = [r["pr_auc"] for r in out]
    hors = [r["horizontal_m"] for r in out]
    chis = [r["chi2"] for r in out]
    fails = [r for r in out if r["pr_auc"] < FAIL_PR_AUC]

    print()
    print("=" * 88)
    print(f"n={len(out)}   tasa de caida (PR-AUC<{FAIL_PR_AUC}) = "
          f"{len(fails)}/{len(out)} = {100*len(fails)/len(out):.0f}%")
    print(f"PR-AUC     mediana {st.median(prs):.3f}   rango {min(prs):.3f} - {max(prs):.3f}")
    print(f"horizontal mediana {st.median(hors):.1f} m   rango {min(hors):.1f} - {max(hors):.1f} m "
          f"(factor {max(hors)/max(min(hors), 1e-9):.0f}x)")
    print(f"chi2       mediana {st.median(chis):.3f}   rango {min(chis):.3f} - {max(chis):.3f} "
          f"(dispersion {100*(max(chis)-min(chis))/st.fmean(chis):.1f}%)")
    print()
    print("Diagnosticos que TerraQuantum declara, por resultado:")
    for tag, sub in (("aciertos", [r for r in out if r["pr_auc"] >= FAIL_PR_AUC]),
                     ("caidas  ", fails)):
        if not sub:
            print(f"  {tag}: n=0")
            continue
        confs = {r["confidence"] for r in sub}
        dconfs = {r["depth_confidence"] for r in sub}
        nss = {r["null_space"] for r in sub}
        print(f"  {tag}: n={len(sub):2d}  confianza={sorted(confs)}  "
              f"conf_profundidad={sorted(dconfs)}  null_space={sorted(nss)}")

    dest = results_home() / tq_version() / "exp_bimodal.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(
        {"tq_version": tq_version(), "world": W_BASE.id, "solver": STRICT.id,
         "fail_threshold_pr_auc": FAIL_PR_AUC, "n": len(out),
         "fail_rate": len(fails) / len(out),
         "runtime_s": time.perf_counter() - t0, "runs": out},
        indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {dest}")
    print(f"Tiempo: {(time.perf_counter()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
