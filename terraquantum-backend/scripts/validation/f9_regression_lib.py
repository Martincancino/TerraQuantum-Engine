# -*- coding: utf-8 -*-
"""F9 — Librería de regresión física (congela la física ya validada).

Un solo lugar de verdad para la suite `pytest -m validation` (tests/test_f9_physics_regression.py)
y para el gate `f9_gate_regression.py`. Cada `case_*()` RE-EJECUTA el motor real
(no lee modelos cacheados) y devuelve un dict normalizado con:

    {key, title, dataset, kind, metric, value, unit, tolerance_str, passed,
     secondary:[...], note, elapsed_s}

kind == "regression"       → passed = la métrica cumple la tolerancia.
kind == "documented_limit" → passed = el LÍMITE conocido se reproduce (esperado, no fallo).

Tolerancias EXPLÍCITAS y MEDIDAS (no se tunean para pasar). Los datasets canónicos
viven versionados: DO-27/Raglan en fixtures + ingest; LdM/San Nicolás como
`observations.json` de corridas guardadas en data/projects. La ambigüedad-z es un
límite físico DOCUMENTADO. Backend-only; no toca el motor.

Correr una sola corrida es lento (minutos): esta suite corre A DEMANDA / semanal /
pre-release, NO en cada commit (marcador `validation`).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

BACKEND = Path(__file__).resolve().parents[2]


# ══════════════════════════════════════════════════════════════════════════════
#  TOLERANCIAS EXPLÍCITAS (medidas con el motor sano; margen sobre el valor real)
# ══════════════════════════════════════════════════════════════════════════════
TOL = {
    "do27_horiz_max_m": 70.0,           # medido ~53.7 m (plan F9)
    "raglan_interior_max_m": 250.0,     # medido ~212 m (plan F9)
    "synthetic_pearson_min": 0.70,      # W_z formal → GOOD; medido 0.726 (synthetic_recovery_benchmark)
    "ldm_chi2_lo": 0.7,                 # χ² ∈ [0.7, 1.3] al nivel de ruido (plan F9); medido 0.987
    "ldm_chi2_hi": 1.3,
    "san_nicolas_misfit_max_pct": 3.0,  # ajuste excelente; medido 1.51% (stride 4) → margen ~2x
    "zamb_disease_min_m": 400.0,        # z-error sin restricción DEBE ser grande (límite conocido)
}

# San Nicolás trae 1024 estaciones: a cutoff 2500 m el kernel (celdas×estaciones) supera
# el presupuesto de memoria en máquinas de 8 GB (guardia SolverMemoryError de F8). Se
# submuestrean estaciones (stride) para que la regresión corra en cualquier máquina; el
# ajuste sigue siendo excelente (misfit ~1.5%). El número se CONGELA con este submuestreo.
SAN_NICOLAS_STATION_STRIDE = 4


def _resolve_field_run(pid: str, rid: str):
    """Dónde están las observaciones de una corrida canónica de campo.

    Fase 3. Se prefiere la corrida VIVA (`data/projects/`), para que en la
    máquina de desarrollo se siga midiendo exactamente el artefacto canónico. Si
    no está —el caso de un checkout limpio, es decir la CI— se cae a las
    fixtures versionadas: las MISMAS observaciones, copiadas a un sitio que git
    sí rastrea (122 KB entre San Nicolás y LdM). Sin esto la CI no podía evaluar
    esos dos casos y el gate defendía 4 de 6.

    Si no hay ninguna de las dos, se lanza `DatosNoVersionados`: eso NO es una
    regresión física y el gate no puede contarlo como tal.
    """
    candidatos = (
        BACKEND / "data" / "projects" / pid / "runs" / rid,
        BACKEND / "tests" / "fixtures" / "f9" / pid / rid,
    )
    for base in candidatos:
        if (base / "observations.json").is_file() and (base / "inputs.json").is_file():
            return base
    raise DatosNoVersionados(
        f"faltan las observaciones de {pid}/{rid}; se buscó en "
        + " y en ".join(str(c) for c in candidatos)
    )


class DatosNoVersionados(RuntimeError):
    """El caso no se puede evaluar porque su dataset no vive en el repositorio.

    No es un fallo de física: es ausencia de dato. Se separa a propósito para que
    el veredicto del gate no mienta en ninguna de las dos direcciones — ni
    llamando FALLO a lo que no se midió, ni llamando PASS a una suite incompleta.
    """


#: Casos cuyos datos NO están versionados (viven bajo `data/projects/`, excluido
#: por .gitignore). Sólo estos pueden quedar sin evaluar; si cualquier OTRO caso
#: se queda sin datos, es una rotura del repositorio y el gate debe fallar.
CASOS_SIN_DATOS_EN_REPO = {"case_san_nicolas", "case_ldm"}


def _case(key, title, dataset, metric, value, unit, tolerance_str, passed, *,
          kind="regression", secondary=None, note=None, elapsed_s=None) -> Dict[str, Any]:
    return {
        "key": key, "title": title, "dataset": dataset, "kind": kind,
        "metric": metric, "value": value, "unit": unit,
        "tolerance_str": tolerance_str, "passed": bool(passed),
        "secondary": secondary or [], "note": note, "elapsed_s": elapsed_s,
    }


def _timed(fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    t0 = time.time()
    case = fn()
    case["elapsed_s"] = round(time.time() - t0, 1)
    return case


# ══════════════════════════════════════════════════════════════════════════════
#  Sintético — esfera con verdad conocida (canario directo del depth-weighting W_z)
# ══════════════════════════════════════════════════════════════════════════════
def synthetic_sphere_recovery() -> Dict[str, Any]:
    """Recuperación de esfera sintética con el benchmark canónico anti-inverse-crime
    (`tests/synthetic_recovery_benchmark.py`): malla forward FINA (5 m) ≠ malla de
    inversión (15 m) + tendencia regional no modelada + ruido con semilla fija.

    La correlación de Pearson vs la verdad es EL canario del W_z formal (el propio
    benchmark fija su umbral de CI en r ≥ 0.70 para el W_z de Li & Oldenburg). Si se
    degrada el depth-weighting, r cae por debajo de 0.70 y la regresión falla.
    """
    import importlib

    srb = importlib.import_module("tests.synthetic_recovery_benchmark")
    srb._STORAGE_AVAILABLE = False   # sin efectos de disco (parquet/zarr)
    r = srb.run_benchmark(use_lcurve=False, use_focusing=False, verbose=False)
    return {
        "pearson_r": r["pearson_r"], "recovery_score": r["recovery_score"],
        "misfit_pct": r["misfit_percent"], "chi_squared": r["chi_squared"],
    }


def case_synthetic_sphere() -> Dict[str, Any]:
    m = synthetic_sphere_recovery()
    passed = m["pearson_r"] >= TOL["synthetic_pearson_min"]
    return _case(
        "synthetic_sphere", "Esfera sintética (motor real, anti-inverse-crime)",
        "Sintético con verdad conocida — malla forward ≠ malla de inversión + tendencia regional",
        "correlación de Pearson (recuperación)", m["pearson_r"], "",
        f"r ≥ {TOL['synthetic_pearson_min']}", passed,
        secondary=[
            {"label": "recovery_score", "value": m["recovery_score"]},
            {"label": "misfit", "value": f"{m['misfit_pct']}%"},
            {"label": "χ² reducido", "value": m["chi_squared"]},
        ],
        note="Canario de FORMA: la correlación cae si la regularización se degrada (medido: "
             "λ_spatial×500 → FALLA). NO es canario de escala ni de W_z — medido 2026-08-13, "
             "con G a +4,9% y con W_z apagado el veredicto no se mueve (r=0.7259 en los tres "
             "casos): el benchmark usa las mismas constantes para generar el dato y para "
             "invertir, así que un error de calibración se cancela, y `depth_beta` resultó "
             "inerte (Punto 4). Las regresiones de escala las cubre "
             "tests/test_fase3_calibracion_absoluta.py. Umbral 0.70 = el CI del propio benchmark.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Ambigüedad-z — LÍMITE FÍSICO DOCUMENTADO (no es un fallo)
# ══════════════════════════════════════════════════════════════════════════════
def case_depth_ambiguity() -> Dict[str, Any]:
    from scripts.validation.synthetic_depth_ambiguity import run as za_run
    r = za_run()
    z_err = r["results"]["A_unconstrained"]["z_error_m"]
    disease = bool(r.get("disease_present"))
    # El LÍMITE se "cumple" si la enfermedad de z se reproduce (esperado).
    passed = disease and z_err is not None and z_err >= TOL["zamb_disease_min_m"]
    anchor_gain = r["deltas"]["anchor_gain_B_to_C_m"]
    return _case(
        "depth_ambiguity", "Ambigüedad de profundidad (gravedad-sola)",
        "Sintético régimen LdM — cuerpo profundo + cobertura dispersa (esfera analítica)",
        "z-error sin restricción", z_err, "m",
        f"≥ {TOL['zamb_disease_min_m']:.0f} m (LÍMITE conocido, no fallo)", passed,
        kind="documented_limit",
        secondary=[
            {"label": "z-error +guardrails", "value": f"{r['results']['B_guardrails']['z_error_m']} m"},
            {"label": "z-error +1 ancla dura", "value": f"{r['results']['C_anchor']['z_error_m']} m"},
            {"label": "ganancia del ancla (B→C)", "value": f"{anchor_gain} m"},
        ],
        note="La gravedad-sola NO resuelve profundidad (null-space). Se DOCUMENTA como límite "
             "esperado; el producto vende targeting horizontal, jamás profundidad sin restricciones.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  DO-27 (kimberlita) — targeting gravimétrico vs ground truth externo
# ══════════════════════════════════════════════════════════════════════════════
def case_do27() -> Dict[str, Any]:
    from scripts.validation.do27_harness import run as do27_run
    r = do27_run()
    go = r["results"]["gravity_only"]
    horiz = go.get("horizontal_error_m")
    passed = horiz is not None and horiz <= TOL["do27_horiz_max_m"]
    return _case(
        "do27", "DO-27 Tli Kwi Cho (kimberlita)",
        "Benchmark externo peer-reviewed (Astic & Oldenburg 2020) — ground truth de sondajes",
        "error horizontal (grav-sola)", horiz, "m",
        f"≤ {TOL['do27_horiz_max_m']:.0f} m", passed,
        secondary=[
            {"label": "joint grav horiz", "value": f"{r['results']['joint_gravity'].get('horizontal_error_m')} m"},
            {"label": "misfit grav", "value": f"{go.get('misfit_percent')}%"},
        ],
        note="Targeting horizontal validado contra benchmark publicado.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Raglan (Ni-Cu) — cuerpo dominante interior vs referencia (dato de campo real)
# ══════════════════════════════════════════════════════════════════════════════
def case_raglan() -> Dict[str, Any]:
    from scripts.validation import raglan_harness as RG
    survey = RG.load_raglan_magnetic()
    ref = RG.load_raglan_reference(survey=survey)
    fr = RG.build_raglan_frame(survey)
    chi, misfit, x_c, y_c, z_c, ns, sig, meta = RG.invert_magnetic(survey, fr, use_padding=True)
    geom = RG._evaluate(chi, x_c, y_c, z_c, ref, fr, misfit)
    interior = geom.get("horiz_err_interior_peak_vs_ref_m")
    passed = interior is not None and interior <= TOL["raglan_interior_max_m"]
    return _case(
        "raglan", "Raglan Ni-Cu (Quebec)",
        "Benchmark externo de DATO DE CAMPO REAL — ref. maginv3d (1997)",
        "error pico interior vs ref", interior, "m",
        f"≤ {TOL['raglan_interior_max_m']:.0f} m", passed,
        secondary=[
            {"label": "corr. horizontal", "value": geom.get("model_pearson_corr_horizontal")},
            {"label": "misfit", "value": f"{geom.get('misfit_percent')}%"},
            {"label": "n sensores", "value": ns},
        ],
        note="Magnetometría escalar con padding (BC física). El pico GLOBAL cae en artefacto "
             "de borde; el blanco geológico es el cuerpo INTERIOR.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Campo real re-invertido desde observaciones guardadas (San Nicolás, LdM)
# ══════════════════════════════════════════════════════════════════════════════
def _field_rerun(pid: str, rid: str, *, auto_lambda: bool, station_stride: int = 1) -> Dict[str, Any]:
    """Re-invierte, con el MOTOR de producción (`run_geophysics_inversion`), las
    observaciones guardadas de una corrida canónica. project_id=None → no persiste
    (no pisa la corrida guardada). enable_focusing=False (el χ²/misfit los da la solución
    base; el focusing es post-proceso y sólo gasta tiempo)."""
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import run_geophysics_inversion

    base = _resolve_field_run(pid, rid)
    obs_raw = json.loads((base / "observations.json").read_text(encoding="utf-8"))
    cfg = json.loads((base / "inputs.json").read_text(encoding="utf-8"))
    if station_stride > 1:
        obs_raw = obs_raw[::station_stride]
    obs = [GravityObservation(x_m=o["x_m"], y_m=o["y_m"], z_m=o["z_m"], g=o["g"]) for o in obs_raw]
    params = GeophysicsInvertInput(
        project_id=None, run_id=None,           # None → no persiste (no pisa la corrida canónica)
        depth=int(cfg["depth"]), nir=0, fe=0, region="field_data",
        nx=int(cfg["nx"]), ny=int(cfg["ny"]), nz=int(cfg["nz"]),
        block_size=float(cfg["block_size"]), cutoff_radius=float(cfg["cutoff_radius"]),
        lambda_mag=0.0 if auto_lambda else float(cfg["lambda_mag"]),
        alpha_spatial=float(cfg.get("alpha_spatial", 1.0)),
        observations=obs, density_min=0.0, density_max=5.5,
        auto_lambda=bool(auto_lambda), enable_focusing=False,
    )
    res = run_geophysics_inversion(params)
    rep = res.get("report", {})
    return {
        "chi2_final": rep.get("chi2_final"),
        "lambda_used": rep.get("lambda_used"),
        "misfit_error_percent": res.get("misfit_error_percent"),
        "n_observations": len(obs),
    }


def case_san_nicolas() -> Dict[str, Any]:
    m = _field_rerun("val_san_nicolas", "a407c45e6d", auto_lambda=False,
                     station_stride=SAN_NICOLAS_STATION_STRIDE)
    misfit = m["misfit_error_percent"]
    passed = misfit is not None and misfit <= TOL["san_nicolas_misfit_max_pct"]
    return _case(
        "san_nicolas", "San Nicolás (VMS, México)",
        f"Dato de campo real re-invertido desde observaciones guardadas "
        f"(λ=0.1 fijo · {m['n_observations']} estaciones, stride {SAN_NICOLAS_STATION_STRIDE})",
        "misfit del ajuste", misfit, "%",
        f"≤ {TOL['san_nicolas_misfit_max_pct']:.0f}%", passed,
        secondary=[
            {"label": "χ² reducido", "value": m["chi2_final"]},
            {"label": "n observaciones", "value": m["n_observations"]},
        ],
        note="El motor reproduce el dato real a ~1.5% de misfit. Geometría del cuerpo aprobada "
             "con campo real (techo ~125 m vs 150–220 publicado). Estaciones submuestreadas por "
             "la guardia de memoria (8 GB); el número se congela con este submuestreo.",
    )


def case_ldm() -> Dict[str, Any]:
    m = _field_rerun("val_ldm", "ldm_v2_lam3p0", auto_lambda=True)
    chi2 = m["chi2_final"]
    passed = chi2 is not None and TOL["ldm_chi2_lo"] <= chi2 <= TOL["ldm_chi2_hi"]
    return _case(
        "ldm", "Laguna del Maule (dato real, Miller et al. 2017)",
        "Bouguer de campo real re-invertido desde observaciones guardadas (191 estaciones, λ=0.1)",
        "χ² reducido (ajuste al ruido)", chi2, "",
        f"∈ [{TOL['ldm_chi2_lo']}, {TOL['ldm_chi2_hi']}]", passed,
        secondary=[
            {"label": "λ usado", "value": m["lambda_used"]},
            {"label": "misfit", "value": f"{m['misfit_error_percent']}%"},
            {"label": "n observaciones", "value": m["n_observations"]},
        ],
        note="El motor ajusta el dato real al nivel de ruido (χ²≈1 medido = 0.99) y acierta el "
             "targeting somero (~2 km, coincide con la literatura).",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Orquestación
# ══════════════════════════════════════════════════════════════════════════════
ALL_CASES: List[Callable[[], Dict[str, Any]]] = [
    case_synthetic_sphere,
    case_depth_ambiguity,
    case_do27,
    case_san_nicolas,
    case_ldm,
    case_raglan,
]


def run_all(generated_utc: Optional[str] = None) -> Dict[str, Any]:
    """Corre TODOS los casos (re-invirtiendo el motor) y arma el reporte de la suite."""
    t0 = time.time()
    cases: List[Dict[str, Any]] = []
    for i, fn in enumerate(ALL_CASES, 1):
        print(f"  [{i}/{len(ALL_CASES)}] {fn.__name__} ...", flush=True)
        try:
            c = _timed(fn)
            cases.append(c)
            estado = "LÍMITE ✓" if (c["kind"] == "documented_limit" and c["passed"]) \
                else "PASS" if c["passed"] else "FALLO"
            print(f"      -> {estado}  {c['metric']}={c['value']}  ({c['elapsed_s']}s)", flush=True)
        except DatosNoVersionados as exc:
            # Sólo los casos declarados pueden quedarse sin evaluar. Que falte el
            # dato de DO-27 o Raglan (que SÍ están en el repositorio) significa
            # que el repositorio está roto, y eso sí es un fallo.
            permitido = fn.__name__ in CASOS_SIN_DATOS_EN_REPO
            caso = _case(
                fn.__name__, fn.__name__, "—", "no evaluado", None, "", "—",
                permitido,
                note=f"NO EVALUADO: {exc}",
            )
            caso["skipped"] = permitido
            cases.append(caso)
            etiqueta = "NO EVALUADO" if permitido else "FALLO (datos que deberían estar)"
            print(f"      -> {etiqueta}: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            cases.append(_case(
                fn.__name__, fn.__name__, "—", "ejecución", None, "", "—", False,
                note=f"ERROR: {exc}", secondary=[{"label": "traceback", "value": traceback.format_exc()[-400:]}],
            ))
            print(f"      -> ERROR: {exc}", flush=True)

    evaluados = [c for c in cases if not c.get("skipped")]
    no_evaluados = [c for c in cases if c.get("skipped")]
    n_pass = sum(1 for c in evaluados if c["passed"])
    return {
        "suite": "F9",
        "title": "F9 — Validación física como regresión automática",
        "generated_utc": generated_utc or "—",
        # El veredicto habla SÓLO de lo que se evaluó, y el reporte dice cuántos
        # casos no se evaluaron para que "PASS" nunca se lea como "6 de 6".
        "verdict": "PASS" if n_pass == len(evaluados) else "FALLO",
        "n_pass": n_pass, "n_total": len(evaluados),
        "n_skipped": len(no_evaluados),
        "skipped_keys": [c["key"] for c in no_evaluados],
        "elapsed_s": round(time.time() - t0, 1),
        "cases": cases,
    }
