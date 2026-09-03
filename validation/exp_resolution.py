"""FASE 26 — EL GATE: ¿informa la señal nueva, o sólo cambió de nombre?

El plan fija el criterio como **un número, no un parche**:

    Spearman entre el diagnóstico nuevo y PR-AUC sobre ≥75 corridas en ≥5 regímenes.
    Si no sube claramente por encima del 0,073 actual, la fase NO cierra.

Ese 0,073 es ρ(`chi2_red`, PR-AUC) medido en
`validation/HALLAZGO_2026-08-06_techo_medium.md`. Se reproduce aquí como control, y se
añade un segundo listón que el hallazgo no tenía: **el tablero de hoy ya da ρ = +0,275**
sobre las mismas 75 corridas, así que superar 0,073 es demasiado fácil. El diagnóstico
nuevo se compara contra los DOS.

DOS CONJUNTOS, y por qué
========================
El diseño del diagnóstico se eligió mirando datos. Reportar la ρ del ganador sobre esos
mismos datos sería contarse la victoria dos veces. Por eso:

    --set selection   las 5 semillas del barrido de 2026-08-06 → aquí se ELIGIÓ
    --set confirm     5 semillas frescas, sin solape           → aquí se MIDE el gate

Los dos escalares están PRE-REGISTRADOS antes de correr `confirm`:

    resolvability_index   media de r sobre TODO el examen (todas las bandas × todos los
                          peldaños). Se elige por no tener ningún parámetro ajustado al
                          resultado. Variantes con banda o peldaño escogidos daban ρ más
                          alta (+0,89–0,92 frente a +0,85); se descartan a propósito.

    floor_mass_excess     masa de la anomalía en la banda de piso dividida por la que
                          pondría ahí un modelo uniforme. Umbral geométrico (>1), no
                          ajustado. Es el ÚNICO que discrimina DENTRO de un régimen.

Uso
===
    python -m validation.exp_resolution --set confirm
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

import numpy as np

from .regimes import BLOCK_M, DIAGNOSTIC, REGIMES, SEEDS, _campaign
from .runner import run_case, tq_version
from .solver_configs import STRICT
from .store import results_home

# Semillas frescas para la CONFIRMACIÓN: sin solape con las del barrido
# (20260805, 11, 202, 3003, 40004) ni con las de `exp_bimodal` (700001+137i).
# Secuencia declarada, no cazada para producir un resultado.
CONFIRM_SEEDS = (900_011, 900_137, 900_263, 900_389, 900_515)

# Los listones. El primero es el del plan; el segundo, el que la propia medición
# de la Fase 26 descubrió que había que superar de verdad.
RHO_CHI2_BASELINE = 0.073
RHO_CHECKERBOARD_BASELINE = 0.275


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _find(d, key, depth: int = 5):
    if depth < 0 or not isinstance(d, dict):
        return None
    if key in d and d[key] is not None:
        return d[key]
    for v in d.values():
        if isinstance(v, dict):
            got = _find(v, key, depth - 1)
            if got is not None:
                return got
    return None


def _spearman(x, y):
    """Spearman por rangos, con corrección de empates. Sin dependencias nuevas."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if x.size < 3 or np.std(x) < 1e-15 or np.std(y) < 1e-15:
        return float("nan"), int(x.size)

    def rank(v):
        order = np.argsort(v, kind="mergesort")
        r = np.empty(v.size, dtype=float)
        r[order] = np.arange(1, v.size + 1, dtype=float)
        # promedio de rangos en los empates
        sv = v[order]
        i = 0
        while i < sv.size:
            j = i
            while j + 1 < sv.size and sv[j + 1] == sv[i]:
                j += 1
            if j > i:
                r[order[i:j + 1]] = np.mean(r[order[i:j + 1]])
            i = j + 1
        return r

    rx, ry = rank(x), rank(y)
    c = float(np.corrcoef(rx, ry)[0, 1])
    return (c if c == c else float("nan")), int(x.size)


def _run_one(name, world, kw, seed, capture):
    import services.geophysics_service as gs

    orig = gs.run_geophysics_inversion
    box = {}

    def wrapped(p):
        out = orig(p)
        box["out"] = out
        return out

    gs.run_geophysics_inversion = wrapped
    try:
        camp = _campaign(f"c_{name}_s{seed}", world, seed, **kw)
        res = run_case(world, camp, DIAGNOSTIC, block_m=BLOCK_M, tau_frac_of_peak=0.50,
                       error_is_large_above_m=200.0, solver=STRICT)
    finally:
        gs.run_geophysics_inversion = orig

    out = box.get("out")
    if res.verdict == "ERROR" or out is None:
        return None

    rq = _find(out, "resolution_qa") or {}
    cb = _find(out, "checkerboard_qa") or {}
    bt = out.get("best_target") or {}
    ov = _find(out, "overall_verdict") or {}
    return {
        "regime": name, "seed": seed,
        "pr_auc": res.metrics.pr_auc,
        "horizontal_error_m": res.metrics.horizontal_error_m,
        "chi2_red": res.metrics.chi2_red,
        "misfit_pct": res.metrics.misfit_pct,
        "lambda_selected": res.tq_config.get("lambda_selected"),
        # ── los dos escalares PRE-REGISTRADOS ──
        "resolvability_index": rq.get("resolvability_index"),
        "floor_mass_excess": bt.get("floor_mass_excess"),
        # ── controles ──
        "checkerboard_pearson_r": cb.get("pearson_r"),
        "shallowest_band_resolution_m": rq.get("shallowest_band_resolution_m"),
        "resolves_anywhere": rq.get("resolves_anywhere"),
        "is_floor_smear": bt.get("is_floor_smear"),
        "is_null_space_artifact": bt.get("is_null_space_artifact"),
        "verdict_level": ov.get("level"),
        "verdict_limiting": ov.get("limiting_factors"),
        "declared_confidence": res.calibration.declared_confidence,
        "quadrant": res.calibration.quadrant,
        "resolution_qa_elapsed_s": rq.get("elapsed_s"),
    }


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="which", default="confirm",
                    choices=("selection", "confirm"))
    ap.add_argument("--regimes", type=int, default=len(REGIMES))
    args = ap.parse_args()
    seeds = SEEDS if args.which == "selection" else CONFIRM_SEEDS
    regimes = REGIMES[:args.regimes]

    print("=" * 92)
    print(f"FASE 26 — GATE de la señal informativa   ({args.which})")
    print("=" * 92)
    print(f"Version de TQ : {tq_version()}")
    print(f"Corridas      : {len(regimes)} regimenes x {len(seeds)} semillas = "
          f"{len(regimes)*len(seeds)}")
    print(f"Semillas      : {list(seeds)}")
    print(f"Listones      : chi2_red = {RHO_CHI2_BASELINE:.3f} (el del plan)   "
          f"tablero de hoy = {RHO_CHECKERBOARD_BASELINE:.3f}")
    print()

    rows, t0 = [], time.perf_counter()
    n = 0
    for name, world, kw, axis in regimes:
        for s in seeds:
            n += 1
            r = _run_one(name, world, kw, s, None)
            if r is None:
                print(f"[{n:3d}] {name}__s{s}: ERROR", flush=True)
                continue
            rows.append(r)
            print(f"[{n:3d}] {name:16s} s{s:<8d} PR-AUC {r['pr_auc']:5.3f}  "
                  f"indice {r['resolvability_index']}  "
                  f"piso {r['floor_mass_excess']}  "
                  f"h {r['horizontal_error_m']:7.1f} m", flush=True)

    if not rows:
        print("Sin resultados.")
        return 1

    pr = [r["pr_auc"] for r in rows]
    print("\n" + "=" * 92)
    print(f"n = {len(rows)} corridas, {len({r['regime'] for r in rows})} regimenes")
    print("=" * 92)
    print(f"{'diagnostico':34s} {'rho vs PR-AUC':>14s} {'n':>5s}")
    print("-" * 60)
    resultados = {}
    for label, key, sign in (
        ("chi2_red  (control del plan)", "chi2_red", +1),
        ("checkerboard de hoy (control)", "checkerboard_pearson_r", +1),
        ("misfit_pct (negado)", "misfit_pct", -1),
        ("resolvability_index  [PRIMARIO]", "resolvability_index", +1),
        ("floor_mass_excess (negado)", "floor_mass_excess", -1),
    ):
        v = [(r.get(key) if isinstance(r.get(key), (int, float)) else float("nan"))
             for r in rows]
        rho, nn = _spearman([sign * x for x in v], pr)
        resultados[key] = rho
        print(f"{label:34s} {rho:+14.4f} {nn:5d}")

    # ── el discriminador DENTRO de régimen (la otra mitad del hallazgo) ──────
    print("\nDENTRO de cada régimen (mediana de rho) — el caso que el hallazgo llamaba")
    print("indistinguible: mismo mundo, mismo survey, sólo cambia la realización de ruido.")
    for label, key, sign in (("chi2_red", "chi2_red", +1),
                             ("resolvability_index", "resolvability_index", +1),
                             ("floor_mass_excess (neg)", "floor_mass_excess", -1)):
        inner = []
        for g in sorted({r["regime"] for r in rows}):
            sub = [r for r in rows if r["regime"] == g]
            v = [(r.get(key) if isinstance(r.get(key), (int, float)) else float("nan"))
                 for r in sub]
            rho, nn = _spearman([sign * x for x in v], [r["pr_auc"] for r in sub])
            if rho == rho:
                inner.append(rho)
        med = st.median(inner) if inner else float("nan")
        print(f"  {label:26s} mediana rho = {med:+.4f}   "
              f"({len(inner)} regimenes con varianza)")

    # ── veredicto del gate ──────────────────────────────────────────────────
    primario = resultados.get("resolvability_index", float("nan"))
    ok = (primario == primario
          and primario > RHO_CHECKERBOARD_BASELINE
          and primario > RHO_CHI2_BASELINE)
    print("\n" + "=" * 92)
    print(f"GATE: rho(resolvability_index, PR-AUC) = {primario:+.4f}")
    print(f"      contra chi2_red   {RHO_CHI2_BASELINE:+.4f}  -> "
          f"{'SUPERA' if primario > RHO_CHI2_BASELINE else 'NO SUPERA'}")
    print(f"      contra el tablero {RHO_CHECKERBOARD_BASELINE:+.4f}  -> "
          f"{'SUPERA' if primario > RHO_CHECKERBOARD_BASELINE else 'NO SUPERA'}")
    print(f"      => {'GATE PASADO' if ok else 'GATE NO PASADO'}")
    print("=" * 92)

    dest = results_home() / tq_version() / f"exp_resolution_{args.which}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({
        "tq_version": tq_version(), "set": args.which, "seeds": list(seeds),
        "n": len(rows), "rho": resultados,
        "baselines": {"chi2_red": RHO_CHI2_BASELINE,
                      "checkerboard": RHO_CHECKERBOARD_BASELINE},
        "gate_passed": bool(ok),
        "runtime_s": time.perf_counter() - t0, "runs": rows,
    }, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {dest}")
    print(f"Tiempo: {(time.perf_counter()-t0)/60:.1f} min")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
