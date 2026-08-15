# -*- coding: utf-8 -*-
"""FASE 4 — veredicto medido de la sonda de separacion Ws/W_z.

Lee los reportes de `wz_separation_probe.py --sweep` y produce lo que la Fase 4 pide
como criterio de aceptacion (a): **tabla de error de profundidad con y sin separacion,
por regimen**, mas el veredicto (b): **cablear o cerrar**.

REGLA DE DECISION, DECLARADA ANTES DE MIRAR LOS NUMEROS
-------------------------------------------------------
La separacion se CABLEA solo si existe UN unico beta fijo que, comparado con el brazo
`prod` (= produccion exacta), cumpla las cuatro condiciones a la vez:

  D1  Mejora el error de profundidad de PICO agregado sobre TODOS los regimenes
      (mediana de las medianas por profundidad), por un margen mayor que el ruido de
      semilla (se usa la mediana de los IQR por celda como vara).
  D2  No empeora en NINGUN regimen individual por mas de esa misma vara. Un peso que
      arregla 900 m y rompe 150 m es un regimen, no un arreglo.
  D3  No degrada el error HORIZONTAL agregado (el observable que el producto vende).
  D4  Gana con el MISMO beta en las tres configuraciones medidas (L2 sin padding,
      L2 con padding = punto de operacion de produccion, y compact con padding).
      Si el beta ganador cambia con la configuracion, no hay una constante que cablear:
      hay una perilla que el usuario no sabe poner.

Si no se cumplen, la decision es CERRAR: el depth-weighting no se cablea y `depth_beta`
se elimina de la firma (criterio de aceptacion (c)).

    python scripts/validation/wz_separation_verdict.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_REPORTS = [
    ("L2 sin padding", "wz_sep_sweep_L2_nopad.json"),
    ("L2 con padding (produccion)", "wz_sep_sweep_L2_pad.json"),
    ("compact con padding", "wz_sep_sweep_compact_pad.json"),
]
METRICS = [
    ("depth_peak_m", "prof. PICO"),
    ("depth_centroid_m", "prof. centroide"),
    ("top_depth_m", "techo"),
    ("horizontal_m", "horizontal"),
]


def _num(xs):
    return [float(x) for x in xs if x is not None and np.isfinite(float(x))]


def _med(xs):
    v = _num(xs)
    return float(median(v)) if v else float("nan")


def _iqr(xs):
    v = _num(xs)
    if len(v) < 2:
        return 0.0
    return float(np.percentile(v, 75) - np.percentile(v, 25))


def _cell(rows, arm, depth, key):
    return [r.get(key) for r in rows if r["arm"] == arm and r["depth_m"] == depth]


def summarize(report: dict) -> dict:
    rows = report["rows"]
    arms, depths = [], []
    for r in rows:                       # preserva orden de aparicion
        if r["arm"] not in arms:
            arms.append(r["arm"])
        if r["depth_m"] not in depths:
            depths.append(r["depth_m"])
    depths.sort()
    out = {"arms": arms, "depths": depths, "n_seeds": len(set(r["seed"] for r in rows)),
           "cells": {}, "agg": {}, "noise_bar": {}}
    for m, _lbl in METRICS:
        out["cells"][m] = {a: {d: {"median": _med(_cell(rows, a, d, m)),
                                   "iqr": _iqr(_cell(rows, a, d, m))}
                               for d in depths} for a in arms}
        # Vara de ruido: mediana de los IQR de todas las celdas (arm x profundidad).
        out["noise_bar"][m] = float(median(
            [out["cells"][m][a][d]["iqr"] for a in arms for d in depths]
        ))
        out["agg"][m] = {a: float(median([out["cells"][m][a][d]["median"] for d in depths]))
                         for a in arms}
    out["lambda"] = {a: {d: _med(_cell(rows, a, d, "lambda_selected")) for d in depths}
                     for a in arms}
    out["chi2"] = {a: {d: _med(_cell(rows, a, d, "chi2")) for d in depths} for a in arms}
    out["rho"] = {a: {d: _med(_cell(rows, a, d, "density_recovery_frac")) for d in depths}
                  for a in arms}
    warn = {}
    for a in arms:
        ws = [w for r in rows if r["arm"] == a for w in r.get("morozov_warnings", [])]
        warn[a] = {w: ws.count(w) for w in sorted(set(ws))}
    out["morozov_warnings"] = warn
    return out


def judge(s: dict) -> dict:
    """Aplica D1-D3 dentro de UNA configuracion. D4 se juzga entre configuraciones."""
    arms = [a for a in s["arms"] if a != "prod"]
    bar_d = s["noise_bar"]["depth_peak_m"]
    bar_h = s["noise_bar"]["horizontal_m"]
    prod_agg = s["agg"]["depth_peak_m"]["prod"]
    prod_h = s["agg"]["horizontal_m"]["prod"]
    verdicts = {}
    for a in arms:
        agg = s["agg"]["depth_peak_m"][a]
        d1 = agg < prod_agg - bar_d
        worst = max(
            s["cells"]["depth_peak_m"][a][d]["median"]
            - s["cells"]["depth_peak_m"]["prod"][d]["median"] for d in s["depths"]
        )
        d2 = worst <= bar_d
        d3 = s["agg"]["horizontal_m"][a] <= prod_h + bar_h
        verdicts[a] = {"agg_depth_peak_m": agg, "delta_vs_prod_m": agg - prod_agg,
                       "worst_regime_delta_m": worst, "agg_horizontal_m":
                       s["agg"]["horizontal_m"][a], "D1": bool(d1), "D2": bool(d2),
                       "D3": bool(d3), "wins": bool(d1 and d2 and d3)}
    return {"noise_bar_depth_m": bar_d, "noise_bar_horizontal_m": bar_h,
            "prod_agg_depth_peak_m": prod_agg, "prod_agg_horizontal_m": prod_h,
            "arms": verdicts,
            "winners": [a for a, v in verdicts.items() if v["wins"]]}


def _table(s: dict, metric: str, label: str) -> str:
    arms, depths = s["arms"], s["depths"]
    w = max(10, max(len(a) for a in arms) + 1)
    head = f"{'brazo':<{w}}" + "".join(f"{('%.0f m' % d):>16}" for d in depths) + f"{'AGREGADO':>16}"
    lines = [f"  {label} — mediana (IQR) sobre {s['n_seeds']} semillas, en metros", "  " + head,
             "  " + "-" * len(head)]
    for a in arms:
        cells = "".join(
            f"{('%.0f (%.0f)' % (s['cells'][metric][a][d]['median'], s['cells'][metric][a][d]['iqr'])):>16}"
            for d in depths
        )
        lines.append(f"  {a:<{w}}{cells}{('%.0f' % s['agg'][metric][a]):>16}")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    reports = []
    for label, name in DEFAULT_REPORTS:
        p = HERE / name
        if p.exists():
            reports.append((label, json.loads(p.read_text(encoding="utf-8"))))
        else:
            print(f"[aviso] falta {name} — esa configuracion NO entra en el veredicto")
    if not reports:
        print("No hay reportes. Corre wz_separation_probe.py --sweep primero.")
        return 2

    print("=" * 100)
    print("FASE 4 — VEREDICTO MEDIDO: ¿separar el precondicionador del peso de modelo")
    print("         recupera capacidad de resolver profundidad?")
    print("=" * 100)

    summaries, judgments = {}, {}
    for label, rep in reports:
        s = summarize(rep)
        j = judge(s)
        summaries[label], judgments[label] = s, j
        cfg = rep["config"]
        print(f"\n### {label}")
        print(f"  malla {cfg['mesh']}@{cfg['block_m']:.0f} m · norma={cfg['reg_norm']} · "
              f"padding={'si' if cfg.get('padding') else 'no'} · "
              f"{s['n_seeds']} semillas · Morozov re-elige lambda en cada brazo")
        print(f"  cuantizacion de la malla en profundidad: +-{cfg['block_m'] / 2:.1f} m "
              f"(piso irreducible de cualquier error de profundidad)")
        print()
        for m, lbl in METRICS:
            print(_table(s, m, lbl))
            print()
        print("  lambda que elige Morozov (mediana) y chi2 alcanzado:")
        for a in s["arms"]:
            lam = " ".join(f"{d:.0f}m:{s['lambda'][a][d]:.3g}" for d in s["depths"])
            ch = " ".join(f"{s['chi2'][a][d]:.2f}" for d in s["depths"])
            rho = " ".join(f"{s['rho'][a][d]:.3f}" for d in s["depths"])
            print(f"    {a:<10} lam[{lam}]  chi2[{ch}]  rho_rec[{rho}]")
        if any(s["morozov_warnings"].values()):
            print("  avisos de Morozov (sin bracket de chi2=1):")
            for a, ws in s["morozov_warnings"].items():
                if ws:
                    print(f"    {a:<10} {ws}")
        print(f"\n  vara de ruido (mediana de IQR): profundidad {j['noise_bar_depth_m']:.0f} m · "
              f"horizontal {j['noise_bar_horizontal_m']:.0f} m")
        print(f"  produccion agregado: profundidad {j['prod_agg_depth_peak_m']:.0f} m · "
              f"horizontal {j['prod_agg_horizontal_m']:.0f} m")
        for a, v in j["arms"].items():
            print(f"    {a:<10} agregado={v['agg_depth_peak_m']:>6.0f} m "
                  f"(delta {v['delta_vs_prod_m']:+.0f}) peor_regimen={v['worst_regime_delta_m']:+.0f} m "
                  f"horiz={v['agg_horizontal_m']:.0f} m  "
                  f"D1={'ok' if v['D1'] else 'no'} D2={'ok' if v['D2'] else 'no'} "
                  f"D3={'ok' if v['D3'] else 'no'} -> {'GANA' if v['wins'] else 'no gana'}")
        print(f"  ganadores en esta configuracion: {j['winners'] or 'ninguno'}")

    # ── D4: el mismo beta debe ganar en TODAS las configuraciones medidas ──────────
    sets = [set(j["winners"]) for j in judgments.values()]
    common = set.intersection(*sets) if sets else set()
    print("\n" + "=" * 100)
    print(f"D4 — brazos que ganan en las {len(reports)} configuraciones a la vez: "
          f"{sorted(common) or 'NINGUNO'}")
    decision = "CABLEAR" if common else "CERRAR"
    print(f"\nDECISION MEDIDA: **{decision}**")
    if common:
        print("  Existe un beta fijo que mejora la profundidad en todos los regimenes y")
        print("  configuraciones sin degradar el targeting horizontal. Cablearlo exige gate F9")
        print("  antes/despues y default byte-identico hasta que el numero lo justifique.")
    else:
        print("  Ningun beta fijo mejora la profundidad en todos los regimenes y configuraciones")
        print("  sin degradar el resto. La separacion RESUCITA la perilla (la sonda lo mide),")
        print("  pero la perilla no tiene un valor que sirva para todos los casos: el limite de")
        print("  profundidad no es un bug de implementacion, es el null-space del dato.")
        print("  => criterio (c): `depth_beta` se elimina de la firma y los comentarios se")
        print("     reescriben para describir el peso de modelo que el codigo aplica de verdad.")
    print("=" * 100)

    out = HERE / "wz_separation_verdict_report.json"
    out.write_text(json.dumps({
        "kind": "wz_separation_verdict",
        "configs": [lbl for lbl, _ in reports],
        "summaries": summaries, "judgments": judgments,
        "common_winners": sorted(common), "decision": decision,
    }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print(f"\nReporte -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
