# -*- coding: utf-8 -*-
"""PARTE C-C2 (probe) — ¿el REPORTE de producción avisa cuando la profundidad es basura?

Los sweeps midieron: a 600-900m Morozov reporta χ²≈1 (ajuste "sano") pero profundidad/horiz
basura; el cliente sin-σ a 300m se hunde a 1387m. La pregunta de honestidad (escudo JORC):
¿la trilogía B1/B2/B3 + horizonte DOI DEGRADA la confianza (null_space/LOW), o reporta un
target confiado y equivocado?

Este probe corre UN caso profundo por el PATH DE PRODUCCIÓN (run_geophysics_inversion, que
es donde vive la trilogía) y vuelca los campos de honestidad, para confirmar el contrato
antes del test completo. Verdad conocida (esfera analítica).

    python scripts/validation/honesty_probe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
from services.geophysics_service import run_geophysics_inversion

NX = NZ = 18
NY = 14
BLOCK = 125.0
CUTOFF = 2600.0
MESH_CENTER = NX * BLOCK / 2.0
RADIUS_M = 150.0
DELTA_RHO = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02


def _sphere_gy_ms2(sensors, x0, y0, z0, radius, delta_rho):
    G = 6.67430e-11
    mass = (delta_rho * 1000.0) * (4.0 / 3.0) * np.pi * radius ** 3
    dy = sensors[:, 1] - y0
    r3 = ((sensors[:, 0] - x0) ** 2 + dy ** 2 + (sensors[:, 2] - z0) ** 2) ** 1.5
    return -G * mass * dy / r3


def _make_obs(by, seed):
    rng = np.random.default_rng(seed)
    cx = cz = MESH_CENTER
    half = SPAN_M / 2.0
    a = np.linspace(cx - half, cx + half, N_SIDE)
    gx, gz = np.meshgrid(a, a, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)
    g = _sphere_gy_ms2(sensors, cx, by, cz, RADIUS_M, DELTA_RHO)
    g = g + NOISE_MGAL * 1e-5 * rng.standard_normal(g.size)
    return [GravityObservation(x_m=float(s[0]), y_m=float(s[1]), z_m=float(s[2]), g=float(gi))
            for s, gi in zip(sensors, g)]


def _run(by, seed, morozov):
    obs = _make_obs(by, seed)
    kw = dict(
        project_id=None, run_id=None, depth=int(NY * BLOCK), nir=0, fe=0, region="field_data",
        nx=NX, ny=NY, nz=NZ, block_size=BLOCK, cutoff_radius=CUTOFF,
        alpha_spatial=1.0, observations=obs, density_min=0.0, density_max=5.5,
        enable_focusing=False, regularization_norm="compact", compact_max_irls=8,
    )
    if morozov:
        kw["lambda_mag"] = 0.0
        kw["auto_lambda"] = True
        kw["noise_floor_mgal"] = NOISE_MGAL   # σ explícito → Morozov
    else:
        kw["lambda_mag"] = 0.0
        kw["auto_lambda"] = True              # sin σ → operating-point 0.1
    params = GeophysicsInvertInput(**kw)
    res = run_geophysics_inversion(params)
    return res


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    by, seed = 900.0, 11
    print(f"Caso PROFUNDO: esfera a {by:.0f} m, Morozov (σ declarado). Verdad = {by:.0f} m.\n")
    res = _run(by, seed, morozov=True)
    rep = res.get("report", {}) if isinstance(res, dict) else {}

    print("=== CLAVES del res ===")
    print(sorted(res.keys()) if isinstance(res, dict) else type(res))
    print("\n=== CLAVES del report ===")
    print(sorted(rep.keys()))

    print("\n=== CAMPOS DE HONESTIDAD (claves camelCase reales) ===")
    print(f"  confidence_level          = {rep.get('confidence_level')}")
    print(f"  model_reliability_level   = {rep.get('model_reliability_level')}")
    print(f"  overall_verdict           = {rep.get('overall_verdict')}")
    print(f"  risk_level                = {rep.get('risk_level')}")
    print(f"  preliminary_signal        = {rep.get('preliminary_signal')}")
    print(f"  drill_recommendation      = {rep.get('drill_recommendation')}")
    print(f"  chi2_final / misfit%      = {rep.get('chi2_final')} / {res.get('misfit_error_percent')}")
    print(f"  lambda_used               = {rep.get('lambda_used')}")
    bt = rep.get("best_target") or {}
    print(f"\n  best_target.depth_m       = {bt.get('depth_m')}   (VERDAD = {by:.0f} m)")
    print(f"  best_target.confidence    = {bt.get('confidence_level')}")
    print(f"  best_target.is_null_space_artifact = {bt.get('is_null_space_artifact')}")
    dr = rep.get("depthResolution") or {}
    print(f"\n  depthResolution.keys      = {sorted(dr.keys())}")
    for k in ("vert_quality", "doi_horizon_m", "deep_mass_fraction", "recommended_depth_max_m",
              "compactness", "status", "reason", "observable_depth_max_m"):
        if k in dr:
            print(f"    depthResolution.{k} = {dr.get(k)}")
    doi = rep.get("doiDiagnostics") or {}
    print(f"\n  doiDiagnostics.keys       = {sorted(doi.keys())}")
    uq = rep.get("uncertaintyDiagnostics") or {}
    print(f"  uncertaintyDiagnostics.keys = {sorted(uq.keys())}")
    for k in ("status", "reason"):
        if k in uq:
            print(f"    uncertaintyDiagnostics.{k} = {uq.get(k)}")
    print(f"\n  checkerboard_qa           = {rep.get('checkerboard_qa')}")
    print(f"  observationQuality        = {rep.get('observationQuality')}")
    print(f"  disclaimer                = {str(rep.get('disclaimer'))[:200]}")
    print(f"  semantic_note             = {str(rep.get('semantic_note'))[:200]}")

    out = Path(__file__).resolve().parent / "honesty_probe_dump.json"
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReporte COMPLETO → {out}")


if __name__ == "__main__":
    main()
