# -*- coding: utf-8 -*-
"""PARTE C-C2 — ¿los campos de honestidad DISCRIMINAN recuperado vs fallido?

El probe mostró: a 900m el reporte da confidence=MEDIUM, is_null_space_artifact=False,
deep_mass_fraction=0.0 y "cuerpo resoluble a 62.5m" (para un cuerpo a 900m), y el
checkerboard_qa=FAIL NO propaga a la confianza. Test riguroso: correr por el PATH DE
PRODUCCIÓN casos que van de RECUPERADO (150/300m) a FALLIDO (600/900m) + el hundimiento
del cliente sin-σ, y tabular los campos de honestidad. Si NO degradan con la falla real
(medida en los sweeps) → gap de honestidad sistemático (C2).

    python scripts/validation/honesty_test.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.honesty_probe as HP

# (etiqueta, profundidad, semilla, morozov?)  — semillas elegidas de los sweeps
CASES = [
    ("150m MOROZOV (recuperado)",  150.0, 11,       True),
    ("300m MOROZOV (recuperado)",  300.0, 11,       True),
    ("600m MOROZOV (frágil)",      600.0, 101,      True),
    ("900m MOROZOV (falla)",       900.0, 11,       True),
    ("300m OPER sin-σ (se hunde)", 300.0, 20260725, False),
]


def _extract(by, res):
    rep = res.get("report", {}) if isinstance(res, dict) else {}
    bt = rep.get("best_target") or {}
    dr = rep.get("depthResolution") or {}
    cb = rep.get("checkerboard_qa") or {}
    ov = rep.get("overall_verdict") or {}
    return {
        "true_depth_m": by,
        "recovered_depth_m": bt.get("depth_m"),
        "depth_err_m": (None if bt.get("depth_m") is None else round(abs(bt.get("depth_m") - by), 1)),
        "confidence_level": rep.get("confidence_level"),
        "depth_confidence": bt.get("depth_confidence"),
        "model_reliability_level": rep.get("model_reliability_level"),
        "overall_verdict_level": ov.get("level"),
        "overall_limiting": ov.get("limiting_factors"),
        "risk_level": rep.get("risk_level"),
        "is_null_space_artifact": bt.get("is_null_space_artifact"),
        "deep_mass_fraction": dr.get("deep_mass_fraction"),
        "resolvable_body_depth_m": dr.get("resolvable_body_depth_m"),
        "checkerboard_status": cb.get("status"),
        "checkerboard_pearson": cb.get("pearson_r"),
        "chi2_final": rep.get("chi2_final"),
        "misfit_pct": res.get("misfit_error_percent"),
        "lambda_used": rep.get("lambda_used"),
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    rows = []
    for label, by, seed, moro in CASES:
        res = HP._run(by, seed, morozov=moro)
        r = _extract(by, res)
        r["label"] = label
        rows.append(r)
        print(f"\n### {label}  (verdad {by:.0f} m)", flush=True)
        print(f"  target recuperado @ {r['recovered_depth_m']} m  (err {r['depth_err_m']} m)")
        print(f"  confidence={r['confidence_level']} | model_reliab={r['model_reliability_level']} | "
              f"verdict={r['overall_verdict_level']} (limita: {r['overall_limiting']}) | risk={r['risk_level']}")
        print(f"  is_null_space_artifact={r['is_null_space_artifact']} | "
              f"deep_mass_fraction={r['deep_mass_fraction']} | checkerboard={r['checkerboard_status']} "
              f"(pearson {r['checkerboard_pearson']})")
        print(f"  χ²={r['chi2_final']} misfit={r['misfit_pct']}% λ={r['lambda_used']}")

    print("\n" + "=" * 100)
    print(f"{'CASO':<30}{'err prof':>9}{'conf(horiz)':>12}{'depth_conf':>11}{'verdict':>9}{'null_art':>10}")
    for r in rows:
        print(f"{r['label'][:29]:<30}{str(r['depth_err_m']):>9}{str(r['confidence_level']):>12}"
              f"{str(r['depth_confidence']):>11}{str(r['overall_verdict_level']):>9}"
              f"{str(r['is_null_space_artifact']):>10}")
    print("=" * 100)
    print("GAP si: err_prof grande (600/900m) pero confidence/verdict NO caen a LOW,")
    print("        is_null_space_artifact=False, y checkerboard=FAIL no propaga.")

    out = Path(__file__).resolve().parent / "honesty_test_report.json"
    out.write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReporte → {out}")


if __name__ == "__main__":
    main()
