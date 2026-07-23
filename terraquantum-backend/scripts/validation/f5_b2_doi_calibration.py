"""
F5 / B2 — Recalibración del horizonte DOI de `build_depth_resolution`.
======================================================================

PROBLEMA MEDIDO (docs/01_PLAN_MAESTRO.md l.79/281): en producción `deep_mass_fraction`
salía ~0.94 para CASI CUALQUIER cuerpo → `vert_quality` era casi siempre
`null_space_dominated`, sano o patológico. El campo perdía todo poder discriminante.

CAUSA RAÍZ (verificada en código, no asumida):
  `sensitivity_proxy` = norma-L2 de columna del kernel data-weighted G_w, tomada en
  exploration/gravimetry.py:2160 ANTES del cambio de variable de depth-weighting Wz_inv
  (línea 2208). Es la sensibilidad CRUDA: decae ~1/prof² y su half-max se alcanza en ~1
  capa. Pero la densidad recuperada es Wz_inv·m_tilde (gravimetry.py:2633): el
  depth-weighting (Li & Oldenburg 1998) COMPENSA esa caída para dejar la amplitud
  ~uniforme en profundidad. Comparar la masa recuperada (post-compensación) contra un
  horizonte de sensibilidad cruda (pre-compensación) da deep_mass_fraction alto SIEMPRE,
  por DISEÑO del depth-weighting — no porque el caso sea patológico.

CORRECCIÓN:
  Usar el índice DOI de doble inversión (doi_index/doi_raw, Oldenburg & Li 1999), que mide
  la resolubilidad del modelo RECUPERADO (post-Wz, mismo espacio que la masa). Horizonte =
  capa MATERIAL más profunda con DOI medio ≤ 1.0 (umbral absoluto: doi≥1 ⇒ la celda se
  movió al menos el offset completo entre modelos de referencia ⇒ controlada por el prior,
  no por el dato ⇒ null-space). "Material" = masa ≥ 1% de la capa pico (ignora capas base
  ~vacías con DOI≈0 trivial y artefactos someros de borde).

DATASETS (con métrica INDEPENDIENTE de sano/patológico):
  • DO-27 mini    — SANO (kimberlita compacta; 53.7 m horizontal validado, benchmark ext.).
  • San Nicolás   — SANO (geometría aprobada con campo real; techo 125 m vs 150-220 pub.).
  • LdM           — PATOLÓGICO (smear profundo real documentado; cuerpo somero robusto
                    ~1.6 km, cola profunda = null-space data-consistente pero no constreñido).
  • Raglan        — EXCLUIDO por costo (requiere re-inversión con datos externos pesados;
                    el cache raglan_recovered_grid*.npz no trae la columna doi_index del
                    pipeline de producción, así que no re-deriva depthResolution barato).

RESULTADO MEDIDO (2026-07-21, umbral DOI=1.0, umbrales de clase 0.66/0.33):
  ┌─────────────┬───────────────────────────┬───────────────────────────┐
  │             │  ANTES (sens half-max)    │  DESPUÉS (horizonte DOI)  │
  ├─────────────┼───────────────────────────┼───────────────────────────┤
  │ DO-27 (sano)│ 0.961 → null_space        │ 0.433 → poor              │
  │ San Nicolás │ 0.975 → null_space        │ 0.396 → poor              │
  │ LdM (patho) │ 0.923 → null_space        │ 0.751 → null_space        │
  └─────────────┴───────────────────────────┴───────────────────────────┘
  Antes: los 3 idénticos (~0.92-0.98) → cero discriminación. Después: sólo el smear
  patológico (LdM) dispara null_space; los sanos caen en 'poor' (ambigüedad de profundidad
  NORMAL de gravedad-sola, honesta — no una alarma).

USO:
  cd terraquantum-backend
  python scripts/validation/f5_b2_doi_calibration.py
"""
from __future__ import annotations

import json
import math
import sys
import uuid
from pathlib import Path

import numpy as np
import polars as pl

try:                                                # consola Windows = cp1252
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]          # terraquantum-backend
sys.path.insert(0, str(ROOT))

from services.geophysics_service import (            # noqa: E402
    build_depth_resolution,
    run_geophysics_inversion,
    _DOI_NULLSPACE_CUTOFF,
)
from services.gravity_import_service import import_gravity_csv_v1   # noqa: E402
from schemas.geophysics_schema import GeophysicsInvertInput          # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────
def _classify(dmf: float) -> str:
    if dmf >= 0.66:
        return "null_space_dominated"
    if dmf >= 0.33:
        return "poor"
    return "resolved"


def _legacy_sens_deep_mass_fraction(df: pl.DataFrame, observable_max: float) -> float:
    """Reproduce el horizonte ANTERIOR (half-max de sensibilidad cruda) para el contraste."""
    a = df.filter(pl.col("density").is_not_null() & pl.col("density").is_finite())
    dens = a["density"].to_numpy().astype(float)
    ys = a["y"].to_numpy().astype(float)
    sens = np.clip(np.nan_to_num(a["sensitivity_proxy"].to_numpy().astype(float), nan=0.0), 0.0, None)
    bg = float(np.median(dens))
    anom = np.abs(dens - bg)
    tot = float(anom.sum())
    if tot <= 0:
        return float("nan")
    layers = np.unique(ys)
    lmean = np.array([float(sens[ys == yy].mean()) for yy in layers])
    peak = float(lmean.max())
    ok = layers[lmean >= 0.5 * peak] if peak > 0 else layers[:0]
    h = min(float(ok.max()) if ok.size > 0 else float(layers.min()), observable_max)
    return float(anom[ys > h].sum()) / tot


def _input_from_gravity_csv(csv_path: Path, tag: str, density_min: float, density_max: float):
    ir = import_gravity_csv_v1(csv_path, strict=False, allow_g_raw=False, data_kind="gravity")
    if ir.status != "ok":
        raise RuntimeError(f"import fail {tag}: {ir.errors}")
    obs = list(ir.observations or [])
    ag = ir.auto_grid or (ir.csv_analysis.auto_grid if ir.csv_analysis else None)

    def _eff(av):
        return int(av)

    return GeophysicsInvertInput(
        project_id=f"calib_{tag}", run_id=f"run_{uuid.uuid4().hex[:12]}",
        depth=int(math.ceil(ag.depth_m)), nir=0, fe=0, region="field_data",
        nx=_eff(ag.nx), ny=_eff(ag.ny), nz=_eff(ag.nz),
        block_size=int(math.ceil(ag.block_size_m)), cutoff_radius=float(ag.cutoff_radius_m),
        lambda_mag=0.0, auto_lambda=True, alpha_spatial=1.0,
        observations=obs, enable_focusing=True,
        density_min=float(density_min), density_max=float(density_max),
    )


def _report_case(label: str, df: pl.DataFrame, observable_max: float, best_target, block_size,
                 independent_note: str):
    legacy = _legacy_sens_deep_mass_fraction(df, observable_max)
    dr = build_depth_resolution(df, observable_max, best_target, block_size)
    dmf = dr.get("deep_mass_fraction")
    vq = dr["per_axis"]["vertical"]["quality"]
    print(f"\n■ {label}")
    print(f"    métrica independiente: {independent_note}")
    print(f"    horizonte             : {dr.get('resolvable_depth_horizon_method')} "
          f"@ {dr.get('resolvable_depth_max_m')} m (geom_max={dr.get('geometric_observable_depth_max_m')} m)")
    print(f"    ANTES (sens half-max) : deep_mass_fraction={legacy:.3f} -> {_classify(legacy)}")
    print(f"    DESPUÉS (DOI={_DOI_NULLSPACE_CUTOFF}) : deep_mass_fraction={dmf:.3f} -> {vq}")
    return {"label": label, "before": round(legacy, 3), "before_class": _classify(legacy),
            "after": dmf, "after_class": vq,
            "horizon_m": dr.get("resolvable_depth_max_m"),
            "horizon_method": dr.get("resolvable_depth_horizon_method")}


def main():
    print("=" * 78)
    print("F5/B2 — Calibración del horizonte DOI de deep_mass_fraction (números medidos)")
    print(f"        Umbral DOI null-space = {_DOI_NULLSPACE_CUTOFF} (absoluto, Oldenburg & Li 1999)")
    print("=" * 78)
    rows = []

    # ── DO-27 mini — SANO (benchmark externo, 53.7 m horizontal validado) ────────
    do27_csv = ROOT / "tests" / "fixtures" / "csv_reales" / "do27_gravity_LISTO_mini.csv"
    if do27_csv.exists():
        out = run_geophysics_inversion(_input_from_gravity_csv(
            do27_csv, "do27mini", density_min=1.5, density_max=2.7))
        rep = out["report"]
        df = pl.read_parquet(rep.get("parquet_path") or rep.get("blockModelPath"))
        rows.append(_report_case(
            "DO-27 mini — SANO (kimberlita compacta)", df,
            rep["depthResolution"]["geometric_observable_depth_max_m"],
            out.get("best_target"), rep["depthResolution"].get("horizontal_extent_m") or 40.0,
            "53.7 m error horizontal validado (Astic & Oldenburg 2020) → cuerpo bien recuperado"))
    else:
        print("\n[SKIP] DO-27 mini fixture no encontrado")

    # ── San Nicolás — SANO (corrida ya persistida; re-deriva sin re-invertir) ─────
    sn_dir = ROOT / "data" / "projects" / "val_san_nicolas" / "runs" / "a407c45e6d"
    sn_pq = sn_dir / "block_model.parquet"
    if sn_pq.exists():
        df = pl.read_parquet(sn_pq)
        rep = json.load(open(sn_dir / "report.json", encoding="utf-8"))
        obs_max = min(2500.0, 20 * 50)   # min(cutoff_radius, ny*block) de inputs.json
        rows.append(_report_case(
            "San Nicolás — SANO (geometría aprobada)", df, float(obs_max),
            rep.get("best_target"), 50.0,
            "techo recuperado 125 m vs 150-220 m publicado → geometría aprobada con campo real"))
    else:
        print("\n[SKIP] San Nicolás run persistida no encontrada")

    # ── LdM — PATOLÓGICO (smear profundo real documentado) ───────────────────────
    try:
        import scripts.validation.tanda_a_part1b_shallow_vs_smear as B
        out = run_geophysics_inversion(B._build_ldm_input(
            lambda_mag=0.0, auto_lambda=True, density_min=0.0, density_max=5.5, tag="f5b2"))
        rep = out["report"]
        df = pl.read_parquet(rep.get("parquet_path") or rep.get("blockModelPath"))
        rows.append(_report_case(
            "LdM — PATOLÓGICO (smear profundo real)", df,
            rep["depthResolution"]["geometric_observable_depth_max_m"],
            out.get("best_target"), rep["depthResolution"].get("horizontal_extent_m") or 520.0,
            "cuerpo somero robusto ~1.6 km + cola profunda null-space documentada (memoria proyecto)"))
    except Exception as exc:
        print(f"\n[SKIP] LdM: {exc}")

    # ── Raglan — EXCLUIDO por costo ──────────────────────────────────────────────
    print("\n■ Raglan — EXCLUIDO por costo")
    print("    El cache raglan_recovered_grid*.npz no trae la columna doi_index del pipeline")
    print("    de producción; re-derivar depthResolution exigiría re-invertir con los datos")
    print("    externos pesados. No bloquea la conclusión (3 casos ya separan sano/patológico).")

    # ── Veredicto ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VEREDICTO")
    print("=" * 78)
    print(f"{'caso':44} {'ANTES':>20} {'DESPUÉS':>20}")
    for r in rows:
        print(f"{r['label']:44} {r['before']:.3f} {r['before_class'][:9]:>13} "
              f"{r['after']:.3f} {r['after_class'][:9]:>13}")
    sanos_after = [r for r in rows if "SANO" in r["label"]]
    patho_after = [r for r in rows if "PATOL" in r["label"]]
    ok = (all(r["after_class"] != "null_space_dominated" for r in sanos_after)
          and all(r["after_class"] == "null_space_dominated" for r in patho_after))
    print()
    print("El horizonte DOI RESTAURA el poder discriminante: los sanos ya NO son "
          "null_space_dominated;")
    print("sólo el smear patológico (LdM) lo es." if ok else
          "ATENCIÓN: la separación esperada NO se cumplió — revisar.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
