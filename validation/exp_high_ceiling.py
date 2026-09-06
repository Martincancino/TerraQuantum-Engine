"""FASE 30 — EL GATE: ¿se puede soltar `HIGH` sin fabricar sobreconfianza?

El plan fija el criterio así:

    Sobre ≥150 corridas, el cuadrante SOBRECONFIADO (error grande + confianza alta)
    sigue en 0 — pero esta vez con `HIGH` alcanzable, así que ese 0 mide HONESTIDAD
    y no un techo.

Las dos mitades importan por igual, y la segunda es la que el proyecto ya falló cuatro
veces: un gate que se cumple sin que el cambio haga nada. Aquí eso es un riesgo LITERAL,
porque se midió antes de tocar código (`validation/PREREGISTRO_2026-09-06_fase30.md`) que
quitar la retención `high_hold_pending_fase30` —lo único que el plan pedía— **no cambiaba
ni uno de los 75 veredictos del barrido de la Fase 26**: `priority_class` capaba a MEDIUM
las 44 corridas MEDIUM. El gate habría dado 0 SOBRECONFIADAS con 0 corridas en HIGH.

Por eso G2 no es decoración: sin `HIGH` alcanzable, G1 no significa nada.

Los tres criterios, DECLARADOS ANTES de correr
==============================================

    G1  honestidad     cuadrante SOBRECONFIADO (error horizontal > 200 m Y veredicto
                       HIGH) = 0.
    G2  alcanzabilidad ≥ 20 % de las corridas en HIGH. Es lo que convierte el 0 de G1
                       en una medición y no en un techo.
    G3  no regresión   ninguna corrida con `resolves_anywhere = False` sale por encima
                       de LOW, y ninguna con `is_floor_smear = True` tampoco. Es lo que
                       la Fase 26 cerró; la Fase 30 no puede desandarlo.

Conjuntos
=========
La regla que se mide aquí se ELIGIÓ mirando las 75 corridas de confirmación de la Fase 26
(semillas 900011…900515). Ese conjunto queda quemado como conjunto de SELECCIÓN. Este
script corre semillas FRESCAS, sin solape con ninguna de las tres tandas anteriores
(20260805/11/202/3003/40004 del barrido, 900011… de la Fase 26, 700001+137i de
`exp_bimodal`).

Uso
===
    py -3.14 -m validation.exp_high_ceiling
    py -3.14 -m validation.exp_high_ceiling --seeds 3     (humo, NO es el gate)
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics as st
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .regimes import BLOCK_M, DIAGNOSTIC, REGIMES, _campaign
from .runner import run_case, tq_version
from .solver_configs import STRICT
from .store import results_home

# ── Semillas FRESCAS, secuencia declarada (no cazadas para producir un resultado) ──
# 10 semillas × 15 regímenes = 150 corridas, que es el mínimo que el plan exige.
GATE_SEEDS = tuple(310_007 + 1_009 * i for i in range(10))

# ── Los umbrales del gate, PRE-REGISTRADOS ────────────────────────────────────
# 200 m es el mismo `error_is_large_above_m` que usan el barrido de agosto y la Fase 26:
# no se re-elige aquí, se hereda, para que «error grande» signifique lo mismo que siempre.
ERROR_GRANDE_M = 200.0
MIN_FRACCION_HIGH = 0.20


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


def _run_one(name, world, kw, seed):
    import services.geophysics_service as gs

    orig = gs.run_geophysics_inversion
    box = {}

    def wrapped(p):
        out = orig(p)
        box["out"] = out
        return out

    gs.run_geophysics_inversion = wrapped
    try:
        camp = _campaign(f"g_{name}_s{seed}", world, seed, **kw)
        res = run_case(world, camp, DIAGNOSTIC, block_m=BLOCK_M, tau_frac_of_peak=0.50,
                       error_is_large_above_m=ERROR_GRANDE_M, solver=STRICT)
    finally:
        gs.run_geophysics_inversion = orig

    out = box.get("out")
    if res.verdict == "ERROR" or out is None:
        return None

    rq = _find(out, "resolution_qa") or {}
    bt = out.get("best_target") or {}
    ov = _find(out, "overall_verdict") or {}
    comp = ov.get("components") or {}
    seal = comp.get("high_seal") or {}
    ceiling = ov.get("ceiling") or {}

    nivel = ov.get("level")
    h = res.metrics.horizontal_error_m
    grande = (h == h) and h > ERROR_GRANDE_M

    return {
        "regime": name, "seed": seed,
        "pr_auc": res.metrics.pr_auc,
        "horizontal_error_m": h,
        "chi2_red": res.metrics.chi2_red,
        # ── el veredicto ──
        "verdict_level": nivel,
        "verdict_limiting": ov.get("limiting_factors"),
        "max_attainable_level": ceiling.get("max_attainable_level"),
        "capped_by": ceiling.get("capped_by"),
        # `declared_confidence` sale de best_target.confidence_level, que
        # `apply_reconciled_verdict` capa (downgrade-only) al nivel del veredicto: es el
        # número que el usuario ve, y por eso es el que se usa para el cuadrante.
        "declared_confidence": res.calibration.declared_confidence,
        "quadrant": res.calibration.quadrant,
        # El cuadrante recalculado sobre el VEREDICTO, explícito, para no depender de que
        # el capado downstream siga existiendo. Si los dos discrepan, es un hallazgo.
        "sobreconfiada": bool(grande and nivel == "HIGH"),
        "error_grande": bool(grande),
        # ── el sello ──
        "sealed": seal.get("sealed"),
        "seal_status": seal.get("status"),
        "seal_reason": seal.get("reason"),
        "shallowest_band_resolution_m": seal.get("shallowest_band_resolution_m"),
        "max_block_tested_m": seal.get("max_block_tested_m"),
        "floor_mass_excess": seal.get("floor_mass_excess"),
        # ── G3: lo que la Fase 26 cerró y no se puede desandar ──
        "resolves_anywhere": rq.get("resolves_anywhere"),
        "is_floor_smear": bt.get("is_floor_smear"),
        "is_null_space_artifact": bt.get("is_null_space_artifact"),
        "resolvability_index": rq.get("resolvability_index"),
        # ── la señal degradada, para poder auditar la decisión ──
        "priority_class": comp.get("priority_class"),
    }


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=len(GATE_SEEDS),
                    help="cuántas semillas de GATE_SEEDS usar (menos de 10 NO es el gate)")
    ap.add_argument("--regimes", type=int, default=len(REGIMES))
    args = ap.parse_args()
    seeds = GATE_SEEDS[:args.seeds]
    regimes = REGIMES[:args.regimes]
    total = len(seeds) * len(regimes)

    print("=" * 96)
    print("FASE 30 — GATE del techo a HIGH")
    print("=" * 96)
    print(f"Version de TQ : {tq_version()}")
    print(f"Corridas      : {len(regimes)} regimenes x {len(seeds)} semillas = {total}")
    print(f"Semillas      : {list(seeds)}")
    print(f"G1 honestidad : SOBRECONFIADAS (error > {ERROR_GRANDE_M:g} m Y veredicto HIGH) = 0")
    print(f"G2 alcanzable : fraccion en HIGH >= {MIN_FRACCION_HIGH:.0%}")
    print("G3 no regresion: 'no resuelve nada' y 'smear de piso' siguen sin superar LOW")
    if total < 150:
        print("\n*** AVISO: menos de 150 corridas. Esto NO es el gate del plan. ***")
    print()

    rows, t0 = [], time.perf_counter()
    n = 0
    for name, world, kw, axis in regimes:
        for s in seeds:
            n += 1
            r = _run_one(name, world, kw, s)
            if r is None:
                print(f"[{n:3d}/{total}] {name}__s{s}: ERROR", flush=True)
                continue
            rows.append(r)
            marca = "  <<< SOBRECONFIADA" if r["sobreconfiada"] else ""
            print(f"[{n:3d}/{total}] {name:16s} s{s:<8d} {str(r['verdict_level']):6s} "
                  f"sello={str(r['sealed']):5s} PR-AUC {r['pr_auc']:5.3f} "
                  f"h {r['horizontal_error_m']:7.1f} m{marca}", flush=True)

    if not rows:
        print("Sin resultados.")
        return 1

    niveles = collections.Counter(r["verdict_level"] for r in rows)
    n_high = niveles.get("HIGH", 0)
    frac_high = n_high / len(rows)
    sobre = [r for r in rows if r["sobreconfiada"]]

    # G3 — lo que la Fase 26 cerró
    fuga_resolucion = [r for r in rows
                       if r["resolves_anywhere"] is False and r["verdict_level"] != "LOW"]
    fuga_smear = [r for r in rows
                  if r["is_floor_smear"] is True and r["verdict_level"] != "LOW"]

    print("\n" + "=" * 96)
    print(f"n = {len(rows)} corridas, {len({r['regime'] for r in rows})} regimenes, "
          f"{(time.perf_counter()-t0)/60:.1f} min")
    print("=" * 96)
    print(f"Veredictos            : {dict(niveles)}")
    print(f"Sellaron HIGH         : {sum(1 for r in rows if r['sealed'])} de {len(rows)}")
    print()

    for etiqueta, sub in (("HIGH", [r for r in rows if r["verdict_level"] == "HIGH"]),
                          ("MEDIUM", [r for r in rows if r["verdict_level"] == "MEDIUM"]),
                          ("LOW", [r for r in rows if r["verdict_level"] == "LOW"])):
        if not sub:
            continue
        hs = sorted(r["horizontal_error_m"] for r in sub)
        prs = [r["pr_auc"] for r in sub]
        print(f"  {etiqueta:6s} n={len(sub):3d}  error horiz: mediana {st.median(hs):7.1f} m  "
              f"p90 {hs[min(int(0.9*len(hs)), len(hs)-1)]:7.1f} m  max {hs[-1]:7.1f} m   "
              f"PR-AUC mediana {st.median(prs):.3f}  min {min(prs):.3f}")

    print("\n" + "-" * 96)
    print("G1 — HONESTIDAD: cuadrante SOBRECONFIADO (error grande + veredicto HIGH)")
    print("-" * 96)
    print(f"  SOBRECONFIADAS: {len(sobre)}")
    for r in sorted(sobre, key=lambda r: -r["horizontal_error_m"]):
        print(f"    {r['regime']:16s} s{r['seed']:<8d} h={r['horizontal_error_m']:8.1f} m  "
              f"PR-AUC {r['pr_auc']:.3f}  res={r['shallowest_band_resolution_m']}/"
              f"{r['max_block_tested_m']}  piso={r['floor_mass_excess']}")
    g1 = len(sobre) == 0

    # Coherencia entre el cuadrante del framework y el veredicto: si divergen, el número
    # que el usuario ve no es el que este gate está midiendo.
    incoherentes = [r for r in rows
                    if (r["quadrant"] == "SOBRECONFIADO") != r["sobreconfiada"]]
    print(f"  Coherencia cuadrante-del-framework vs veredicto: "
          f"{'OK' if not incoherentes else f'{len(incoherentes)} DISCREPANCIAS'}")
    for r in incoherentes[:5]:
        print(f"    {r['regime']} s{r['seed']}: quadrant={r['quadrant']} "
              f"conf={r['declared_confidence']} veredicto={r['verdict_level']}")

    print("\n" + "-" * 96)
    print("G2 — ALCANZABILIDAD: el 0 de G1 tiene que medir honestidad, no un techo")
    print("-" * 96)
    print(f"  corridas en HIGH: {n_high} de {len(rows)} = {frac_high:.1%}  "
          f"(minimo {MIN_FRACCION_HIGH:.0%})")
    if n_high:
        alto = [r for r in rows if r["verdict_level"] == "HIGH"]
        print(f"  regimenes que llegan a HIGH: "
              f"{dict(collections.Counter(r['regime'] for r in alto))}")
    g2 = frac_high >= MIN_FRACCION_HIGH

    print("\n" + "-" * 96)
    print("G3 — NO REGRESION de lo que cerro la Fase 26")
    print("-" * 96)
    print(f"  'no resuelve nada' por encima de LOW : {len(fuga_resolucion)}")
    print(f"  'smear de piso'    por encima de LOW : {len(fuga_smear)}")
    g3 = not fuga_resolucion and not fuga_smear

    # ── material para el registro: quien topea, y con que numeros ────────────
    print("\n" + "-" * 96)
    print("Quien topeo, sobre las corridas que NO llegaron a HIGH")
    print("-" * 96)
    tope = collections.Counter()
    for r in rows:
        if r["verdict_level"] != "HIGH":
            for f in (r["verdict_limiting"] or []):
                tope[f] += 1
    for k, v in tope.most_common():
        print(f"  {k:28s} {v:4d}")

    print("\n" + "=" * 96)
    print(f"G1 honestidad   : {'PASA' if g1 else 'FALLA'}  ({len(sobre)} sobreconfiadas)")
    print(f"G2 alcanzable   : {'PASA' if g2 else 'FALLA'}  ({frac_high:.1%} en HIGH)")
    print(f"G3 no regresion : {'PASA' if g3 else 'FALLA'}")
    ok = g1 and g2 and g3 and len(rows) >= 150
    if len(rows) < 150:
        print(f"n = {len(rows)} < 150: el gate del plan NO se cumple por tamano de muestra")
    print(f"=> {'GATE PASADO' if ok else 'GATE NO PASADO'}")
    print("=" * 96)

    dest = results_home() / tq_version() / "exp_high_ceiling.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({
        "tq_version": tq_version(),
        "seeds": list(seeds),
        "n": len(rows),
        "thresholds": {"error_grande_m": ERROR_GRANDE_M,
                       "min_fraccion_high": MIN_FRACCION_HIGH},
        "levels": dict(niveles),
        "n_sobreconfiadas": len(sobre),
        "fraccion_high": frac_high,
        "g1_honestidad": bool(g1),
        "g2_alcanzable": bool(g2),
        "g3_no_regresion": bool(g3),
        "gate_passed": bool(ok),
        "capped_by_counts": dict(tope),
        "runtime_s": time.perf_counter() - t0,
        "runs": rows,
    }, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {dest}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
