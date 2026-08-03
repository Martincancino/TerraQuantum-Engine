# -*- coding: utf-8 -*-
"""PARTE C-C1 — Caza de corrupción silenciosa (red-team de ingesta física).

Invariante DURO (F0): ante el dato más feo posible, o sale un MODELO VÁLIDO, o un ERROR
CLARO EN ESPAÑOL — JAMÁS un número silenciosamente equivocado con sello de calidad.

F8 ya fuzzeó la API (106/106 cero 5xx pelados) y C2 ya cazó el target-confiado-en-null-space.
Este harness ataca los vectores de CORRUPCIÓN FÍSICA que producen un número plausible-pero-
falso (no un crash): unidades confundidas (mGal↔m/s², factor 1e5), señal nula/constante,
outlier gigante, signo invertido, SNR<1, coma decimal ya parseada como basura. Para cada uno
se corre el motor real y se clasifica el desenlace en el invariante.

    python scripts/validation/c1_silent_corruption.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.validation.honesty_probe as HP
from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import run_geophysics_inversion

NX = HP.NX; NY = HP.NY; NZ = HP.NZ; BLOCK = HP.BLOCK; CUTOFF = HP.CUTOFF
MC = HP.MESH_CENTER


def _base_obs(seed=11, by=300.0):
    """Survey sano de referencia (esfera a 300 m, señal clara)."""
    rng = np.random.default_rng(seed)
    half = HP.SPAN_M / 2.0
    a = np.linspace(MC - half, MC + half, HP.N_SIDE)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    g = HP._sphere_gy_ms2(sensors, MC, by, MC, HP.RADIUS_M, HP.DELTA_RHO)
    g = g + HP.NOISE_MGAL * 1e-5 * rng.standard_normal(g.size)
    return sensors, g


def _to_obs(sensors, g):
    return [GravityObservation(x_m=float(s[0]), y_m=float(s[1]), z_m=float(s[2]), g=float(gi))
            for s, gi in zip(sensors, g)]


def _invert(obs, noise_floor_mgal=HP.NOISE_MGAL):
    params = GeophysicsInvertInput(
        project_id=None, run_id=None, depth=int(NY * BLOCK), nir=0, fe=0, region="field_data",
        nx=NX, ny=NY, nz=NZ, block_size=BLOCK, cutoff_radius=CUTOFF,
        alpha_spatial=1.0, observations=obs, density_min=0.0, density_max=5.5,
        enable_focusing=False, regularization_norm="compact", compact_max_irls=8,
        lambda_mag=0.0, auto_lambda=True, noise_floor_mgal=noise_floor_mgal,
    )
    return run_geophysics_inversion(params)


def _classify(res):
    """Clasifica el desenlace: OK_MODEL / CLEAR_ERROR / SILENT_CORRUPTION (el enemigo)."""
    rep = res.get("report", {}) if isinstance(res, dict) else {}
    conf = rep.get("confidence_level")
    verdict = (rep.get("overall_verdict") or {}).get("level")
    misfit = res.get("misfit_error_percent")
    bt = rep.get("best_target") or {}
    return {
        "confidence": conf, "verdict": verdict, "misfit_pct": misfit,
        "risk": rep.get("risk_level"),
        "target_depth_confidence": bt.get("depth_confidence"),
        "null_space_flag": bt.get("is_null_space_artifact"),
        "saturation": (rep.get("r03_saturation") or {}).get("sat_pct_total"),
    }


# ── Vectores adversariales: (label, corruptor(sensors,g)->(sensors,g), noise_floor) ──
def _identity_signal(s, g):   # señal constante (sin anomalía) → no debe fingir un blanco
    return s, np.full_like(g, float(np.mean(g)))
def _units_mgal(s, g):        # g en mGal en vez de m/s² → 1e5 veces más grande
    return s, g / 1e-5
def _giant_outlier(s, g):     # un outlier 100× el pico
    g2 = g.copy(); g2[len(g2) // 2] = 100.0 * float(np.max(np.abs(g))); return s, g2
def _sign_flip(s, g):         # anomalía invertida (déficit de masa) → densidad baja, no crash
    return s, -g
def _tiny_snr(s, g):          # ruido 5× la señal (SNR<1)
    rng = np.random.default_rng(7)
    return s, g + 5.0 * float(np.max(np.abs(g))) * rng.standard_normal(g.size)

CASES = [
    ("señal_constante (sin anomalía)", _identity_signal, HP.NOISE_MGAL),
    ("unidades mGal↔m/s² (×1e5)",      _units_mgal,      HP.NOISE_MGAL),
    ("outlier gigante (100×pico)",     _giant_outlier,   HP.NOISE_MGAL),
    ("signo invertido (déficit masa)", _sign_flip,       HP.NOISE_MGAL),
    ("SNR<1 (ruido 5× señal)",         _tiny_snr,        HP.NOISE_MGAL),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sensors, g0 = _base_obs()
    rows = []
    print("PARTE C-C1 — corrupción silenciosa. Invariante: MODELO VÁLIDO o ERROR CLARO ES, "
          "jamás basura silenciosa.\n", flush=True)
    for label, corrupt, nf in CASES:
        s, g = corrupt(sensors, g0.copy())
        outcome, detail = "?", {}
        try:
            res = _invert(_to_obs(s, g), noise_floor_mgal=nf)
            detail = _classify(res)
            # Heurística del invariante: un desenlace es SANO si el reporte NO vende
            # confianza alta sobre dato corrupto (confidence/verdict no-HIGH, o degradado).
            hi = str(detail.get("confidence")).upper() == "HIGH" or str(detail.get("verdict")).upper() == "HIGH"
            outcome = "OK_MODEL(degradado)" if not hi else "⚠ REVISAR (HIGH sobre dato corrupto)"
        except Exception as exc:
            # Un error es SANO sólo si es un TerraquantumError con mensaje claro (ES).
            etype = type(exc).__name__
            msg = str(exc)
            clear = ("Terraquantum" in etype) or any(w in msg.lower() for w in
                     ("no ", "inválid", "cero", "señal", "sensor", "gravim", "insuficiente"))
            outcome = f"CLEAR_ERROR({etype})" if clear else f"⚠ ERROR_OPACO({etype})"
            detail = {"error": msg[:160]}
        rows.append({"case": label, "outcome": outcome, **detail})
        print(f"  {label:36s} → {outcome}")
        for k, v in detail.items():
            if k != "error":
                print(f"      {k}={v}")
        if "error" in detail:
            print(f"      msg: {detail['error']}")

    bad = [r for r in rows if "⚠" in r["outcome"]]
    print("\n" + "=" * 78)
    print(f"INVARIANTE C1: {'PASS — sin corrupción silenciosa' if not bad else f'REVISAR — {len(bad)} caso(s)'}")
    for r in bad:
        print(f"  ⚠ {r['case']}: {r['outcome']}")
    print("=" * 78)

    out = Path(__file__).resolve().parent / "c1_silent_corruption_report.json"
    out.write_text(json.dumps({"rows": rows, "n_flagged": len(bad)}, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    print(f"\nReporte → {out}")


if __name__ == "__main__":
    main()
