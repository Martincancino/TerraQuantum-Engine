"""
scripts/validation/validate_output.py
=======================================
Framework de validación textual para la respuesta JSON de la API de inversión.

Funciones exportadas:
  validate_output_sanity(result)             → bool
  validate_forward_fit(result, observations) → bool
  validate_geometry_3d(result)               → bool
  validate_joint_coupling(result)            → bool
  full_validation_report(result, observations_original) → bool

Sin matplotlib — salida 100% texto (✅/❌).

Uso desde línea de comandos:
  cd terraquantum-backend
  python scripts/validation/validate_output.py --input result.json

Uso como módulo:
  from scripts.validation.validate_output import full_validation_report
  is_good = full_validation_report(result, observations_original)
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Constantes de umbrales (ajustables si el proyecto lo requiere)
# ---------------------------------------------------------------------------
MIN_VOXELS = 10
DENSITY_MIN = 2.6
DENSITY_MAX = 4.2
MAX_MISFIT_PCT = 20.0
MAX_NRMSE = 0.20
MAX_CHI2 = 5.0
MAX_HIGH_RESIDUAL_RATIO = 0.25
CENTROID_DEPTH_RATIO = 0.90    # centroide no puede ser > 90% de y_max
MIN_EXTENT_M = 1.0             # al menos 1 m de extensión (grilla muy pequeña OK)
MAX_E_NORM_WARN = 0.50         # E_norm_final > 0.50 = acoplamiento débil


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_voxels(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = result.get("voxels", [])
    if raw and hasattr(raw[0], "__dict__"):
        return [v.__dict__ for v in raw]
    return [dict(v) if not isinstance(v, dict) else v for v in raw]


def _safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _check(label: str, passed: bool, detail: str = "") -> bool:
    icon = "  ✅" if passed else "  ❌"
    line = f"{icon} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


# ---------------------------------------------------------------------------
# Nivel 1: Cordura básica
# ---------------------------------------------------------------------------

def validate_output_sanity(result: Dict[str, Any]) -> bool:
    """Chequeos que TODO modelo debe cumplir independientemente del dataset."""
    print("\n[SANITY] Validaciones de cordura básica")
    print("─" * 50)

    checks: List[bool] = []
    voxels = _get_voxels(result)

    # 1. ¿Existen vóxeles?
    ok = len(voxels) >= MIN_VOXELS
    checks.append(_check(
        "Vóxeles suficientes",
        ok,
        f"{len(voxels)} (mínimo {MIN_VOXELS})",
    ))
    if not ok:
        print("  ⛔ Sin vóxeles suficientes — resto de checks omitidos")
        return False

    # 2. ¿Densidades dentro de bounds físicos?
    densities = [_safe_float(v.get("density")) for v in voxels
                 if v.get("density") is not None]
    if densities:
        d_min, d_max = min(densities), max(densities)
        ok = (d_min >= DENSITY_MIN) and (d_max <= DENSITY_MAX)
        checks.append(_check(
            "Densidades en bounds físicos",
            ok,
            f"[{d_min:.3f}, {d_max:.3f}] t/m³ (esperado [{DENSITY_MIN}, {DENSITY_MAX}])",
        ))
    else:
        checks.append(_check("Densidades presentes", False, "sin campo 'density'"))

    # 3. ¿Susceptibilidades no-negativas?
    suscs = [_safe_float(v.get("susceptibility_si")) for v in voxels
             if v.get("susceptibility_si") is not None]
    if suscs:
        neg_count = sum(1 for s in suscs if s < 0)
        ok = neg_count == 0
        checks.append(_check(
            "Susceptibilidades ≥ 0 (no-negatividad física)",
            ok,
            f"{neg_count} negativas de {len(suscs)}",
        ))

    # 4. ¿Coordenadas finitas?
    try:
        xs = np.array([_safe_float(v.get("x_m"), 0.0) for v in voxels])
        ys = np.array([_safe_float(v.get("y_m"), 0.0) for v in voxels])
        zs = np.array([_safe_float(v.get("z_m"), 0.0) for v in voxels])
        ok = bool(np.all(np.isfinite(xs)) and np.all(np.isfinite(ys)) and np.all(np.isfinite(zs)))
    except Exception:
        ok = False
    checks.append(_check("Coordenadas finitas (sin NaN/Inf)", ok))

    # 5. ¿Misfit razonable?
    misfit = _safe_float(result.get("misfit_error_percent"))
    if misfit is not None:
        ok = misfit <= MAX_MISFIT_PCT
        checks.append(_check(
            "Misfit razonable",
            ok,
            f"{misfit:.2f}% (máximo {MAX_MISFIT_PCT}%)",
        ))

    # 6. ¿Scores de probabilidad normalizados?
    probs = [_safe_float(v.get("probability")) for v in voxels
             if v.get("probability") is not None]
    if probs:
        out_of_range = sum(1 for p in probs if p < 0 or p > 1)
        ok = out_of_range == 0
        checks.append(_check(
            "Scores de probabilidad en [0,1]",
            ok,
            f"{out_of_range} fuera de rango de {len(probs)}",
        ))

    # 7. ¿Centro de masa no en el borde inferior?
    if len(ys) > 0:
        y_centroid = float(ys.mean())
        y_max = float(ys.max())
        ok = y_max == 0.0 or (y_centroid <= CENTROID_DEPTH_RATIO * y_max)
        checks.append(_check(
            "Centro de masa no en borde inferior",
            ok,
            f"centroide y={y_centroid:.1f} m, y_max={y_max:.1f} m",
        ))

    # 8. ¿Report existe?
    report = result.get("report")
    ok = isinstance(report, dict) and len(report) > 0
    checks.append(_check("Report presente", ok))

    # 9. ¿best_target existe?
    bt = result.get("best_target")
    ok = bt is not None and isinstance(bt, dict)
    checks.append(_check("best_target presente", ok))

    passed = sum(1 for c in checks if c)
    total = len(checks)
    threshold = max(6, total - 2)   # admite hasta 2 fallos opcionales
    overall = passed >= threshold
    print(f"\n  SANITY: {passed}/{total} — {'✅ OK' if overall else '❌ REVISAR'}")
    return overall


# ---------------------------------------------------------------------------
# Nivel 2: Ajuste forward
# ---------------------------------------------------------------------------

def validate_forward_fit(
    result: Dict[str, Any],
    observations: Optional[Any] = None,
) -> bool:
    """¿El modelo reconstruye los datos observados al nivel del ruido?"""
    print("\n[FIT] Validación de ajuste forward")
    print("─" * 50)

    report = result.get("report", {})
    fit = report.get("fitDiagnostics") or report.get("fit_diagnostics") or {}
    checks: List[bool] = []

    # Misfit directo desde la raíz
    misfit = _safe_float(result.get("misfit_error_percent"))
    if misfit is not None:
        ok = misfit <= MAX_MISFIT_PCT
        checks.append(_check("misfit_error_percent", ok, f"{misfit:.2f}% (max {MAX_MISFIT_PCT}%)"))

    # NRMSE
    nrmse = _safe_float(fit.get("normalized_rmse") or fit.get("nrmse"))
    if nrmse is not None:
        ok = nrmse <= MAX_NRMSE
        label = "EXCELENTE" if nrmse < 0.05 else ("BUENO" if nrmse < MAX_NRMSE else "MALO")
        checks.append(_check("Normalized RMSE", ok, f"{nrmse:.4f} [{label}]"))

    # Chi²
    chi2 = _safe_float(fit.get("chi_squared") or fit.get("chi2"))
    if chi2 is not None:
        ok = chi2 <= MAX_CHI2
        label = "al nivel de ruido" if chi2 < 2.0 else ("aceptable" if chi2 < MAX_CHI2 else "pobre ajuste")
        checks.append(_check("Chi² final", ok, f"{chi2:.3f} [{label}] (objetivo ~1.0)"))

    # Sesgo residual
    bias = _safe_float(fit.get("residual_bias"))
    rmse = _safe_float(fit.get("residual_rmse") or fit.get("rmse"))
    if bias is not None and rmse is not None and rmse > 0:
        ok = abs(bias) <= 0.10 * rmse
        checks.append(_check("Sin sesgo sistemático", ok, f"bias/rmse={abs(bias)/rmse:.3f} (max 0.10)"))

    # Distribución residuales
    res_map = fit.get("residualMap") or fit.get("residual_map") or []
    if res_map:
        n_high = sum(1 for r in res_map if r.get("residual_level") == "HIGH")
        ratio = n_high / len(res_map)
        ok = ratio <= MAX_HIGH_RESIDUAL_RATIO
        checks.append(_check(
            "Residuales HIGH",
            ok,
            f"{n_high}/{len(res_map)} = {ratio:.1%} (max {MAX_HIGH_RESIDUAL_RATIO:.0%})",
        ))

    if not checks:
        print("  ⚠️  Sin métricas de ajuste en el report — check omitido")
        return True   # no penalizar si el endpoint no emite fitDiagnostics

    passed = sum(1 for c in checks if c)
    total = len(checks)
    overall = passed >= max(1, total - 1)
    print(f"\n  FIT: {passed}/{total} — {'✅ OK' if overall else '❌ REVISAR'}")
    return overall


# ---------------------------------------------------------------------------
# Nivel 3: Geometría 3D
# ---------------------------------------------------------------------------

def validate_geometry_3d(result: Dict[str, Any]) -> bool:
    """¿La anomalía tiene forma geológica realista?"""
    print("\n[GEOM] Validación geométrica 3D")
    print("─" * 50)

    voxels = _get_voxels(result)
    if not voxels:
        _check("Vóxeles para geometría", False, "lista vacía")
        return False

    checks: List[bool] = []

    xs = np.array([_safe_float(v.get("x_m"), 0.0) for v in voxels])
    ys = np.array([_safe_float(v.get("y_m"), 0.0) for v in voxels])
    zs = np.array([_safe_float(v.get("z_m"), 0.0) for v in voxels])

    ex = float(xs.max() - xs.min())
    ey = float(ys.max() - ys.min())
    ez = float(zs.max() - zs.min())
    print(f"  Extensión 3D: {ex:.0f} m (X) × {ey:.0f} m (Y) × {ez:.0f} m (Z)")

    # Extensión mínima en al menos dos ejes
    ok = sum(e > MIN_EXTENT_M for e in [ex, ey, ez]) >= 2
    checks.append(_check("Extensión mínima en ≥2 ejes", ok, f"X={ex:.0f} Y={ey:.0f} Z={ez:.0f} m"))

    # Profundidad razonable
    y_mean = float(ys.mean())
    y_max = float(ys.max())
    if y_max > 0:
        ok = y_mean <= CENTROID_DEPTH_RATIO * y_max
        checks.append(_check(
            "Anomalía no concentrada en borde inferior",
            ok,
            f"y_mean={y_mean:.0f} m / y_max={y_max:.0f} m = {y_mean/y_max:.0%}",
        ))

    # Número de vóxeles activos (is_active)
    active = [v for v in voxels if v.get("is_active") is True]
    if active:
        ok = len(active) >= MIN_VOXELS
        checks.append(_check(
            "Vóxeles activos suficientes",
            ok,
            f"{len(active)} activos de {len(voxels)} totales",
        ))

    # Separación no-trivial entre vóxeles (evita colapso a un punto)
    if len(voxels) >= 4:
        sample_size = min(200, len(voxels))
        idx = np.round(np.linspace(0, len(voxels) - 1, sample_size)).astype(int)
        coords = np.column_stack([xs[idx], ys[idx], zs[idx]])
        pairwise = np.std(coords, axis=0)
        ok = bool(np.any(pairwise > 0.1))
        checks.append(_check(
            "Dispersión espacial no-trivial",
            ok,
            f"std(x,y,z)=({pairwise[0]:.1f},{pairwise[1]:.1f},{pairwise[2]:.1f}) m",
        ))

    if not checks:
        print("  ⚠️  Sin datos suficientes para geometría")
        return True

    passed = sum(1 for c in checks if c)
    total = len(checks)
    overall = passed >= max(1, total - 1)
    print(f"\n  GEOM: {passed}/{total} — {'✅ OK' if overall else '❌ REVISAR'}")
    return overall


# ---------------------------------------------------------------------------
# Nivel 4: Acoplamiento joint
# ---------------------------------------------------------------------------

def validate_joint_coupling(result: Dict[str, Any]) -> bool:
    """Valida el acoplamiento cross-gradient si el run fue joint."""
    print("\n[JOINT] Validación acoplamiento joint")
    print("─" * 50)

    report = result.get("report", {})
    jm = report.get("joint_metrics") or {}

    if not jm:
        print("  (No hay joint_metrics — run no fue joint o no se calcularon)")
        return True

    checks: List[bool] = []

    e_norm = _safe_float(jm.get("E_norm_final"))
    if e_norm is not None:
        ok = True   # E_norm siempre pasa — solo categoriza
        label = (
            "EXCELENTE" if e_norm < 0.1 else
            "BUENO" if e_norm < 0.3 else
            "MODERADO" if e_norm < MAX_E_NORM_WARN else
            "DÉBIL (puede ser realista)"
        )
        checks.append(_check("E_norm acoplamiento", ok, f"{e_norm:.4f} [{label}]"))

    centroid_sep = _safe_float(jm.get("centroid_separation_m"))
    if centroid_sep is not None:
        ok = True   # solo informativo
        label = "coinciden" if centroid_sep < 50 else ("próximos" if centroid_sep < 200 else "separados")
        checks.append(_check(
            "Separación centroides ρ vs χ",
            ok,
            f"{centroid_sep:.0f} m [{label}]",
        ))

    # ¿Contiene vóxeles con susceptibilidad y densidad?
    voxels = _get_voxels(result)
    has_density = any(v.get("density") is not None for v in voxels)
    has_susc = any(v.get("susceptibility_si") is not None for v in voxels)
    ok = has_density and has_susc
    checks.append(_check(
        "Vóxeles con ambas propiedades (density + susceptibility_si)",
        ok,
        f"density={has_density}, susc={has_susc}",
    ))

    if not checks:
        return True

    passed = sum(1 for c in checks if c)
    total = len(checks)
    overall = passed >= max(1, total - 1)
    print(f"\n  JOINT: {passed}/{total} — {'✅ OK' if overall else '❌ REVISAR'}")
    return overall


# ---------------------------------------------------------------------------
# Reporte consolidado
# ---------------------------------------------------------------------------

def full_validation_report(
    result: Dict[str, Any],
    observations_original: Optional[Any] = None,
) -> bool:
    """Ejecuta todos los niveles y devuelve True si el modelo es confiable."""
    print("=" * 60)
    print("REPORTE DE VALIDACIÓN COMPLETO — TerraQuantum")
    print("=" * 60)

    sanity_ok = validate_output_sanity(result)
    fit_ok = validate_forward_fit(result, observations_original)
    geom_ok = validate_geometry_3d(result)
    joint_ok = validate_joint_coupling(result)

    # Métricas rápidas de resumen
    voxels = _get_voxels(result)
    misfit = _safe_float(result.get("misfit_error_percent"))
    densities = [_safe_float(v.get("density")) for v in voxels if v.get("density") is not None]
    ys = [_safe_float(v.get("y_m")) for v in voxels if v.get("y_m") is not None]

    print("\n" + "=" * 60)
    print("RESUMEN EJECUTIVO")
    print("=" * 60)
    print(f"  Sanity:  {'✅ PASS' if sanity_ok else '❌ FAIL'}")
    print(f"  Fit:     {'✅ PASS' if fit_ok else '❌ FAIL'}")
    print(f"  Geometría: {'✅ PASS' if geom_ok else '❌ FAIL'}")
    print(f"  Joint:   {'✅ PASS' if joint_ok else '❌ FAIL'}")
    print()
    print(f"  Vóxeles totales: {len(voxels)}")
    if misfit is not None:
        print(f"  Misfit:  {misfit:.2f}%")
    if densities:
        print(f"  Densidad: [{min(densities):.3f}, {max(densities):.3f}] t/m³")
    if ys:
        print(f"  Profundidad máx: {max(ys):.0f} m")

    all_ok = sanity_ok and fit_ok and geom_ok and joint_ok
    verdict = "✅ APROBADO — Modelo confiable" if all_ok else "⚠️  REVISAR — Ver detalles arriba"
    print(f"\n  {verdict}")

    if not all_ok:
        print("\n  SUGERENCIAS:")
        if not sanity_ok:
            print("    • Verificar que el endpoint retornó vóxeles y report correctamente")
        if not fit_ok:
            print("    • Aumentar lambda o usar auto_lambda=true")
            print("    • Verificar que las unidades de g sean consistentes (no mezclar mGal/µGal)")
        if not geom_ok:
            print("    • Aumentar nx/ny/nz o reducir block_size para mejor resolución")
            print("    • Verificar cobertura de sensores sobre la anomalía")

    print("=" * 60)
    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main_cli():
    import argparse
    parser = argparse.ArgumentParser(
        description="Valida la salida JSON de la API de inversión TerraQuantum"
    )
    parser.add_argument("--input", required=True, help="Path al JSON de resultado de la API")
    parser.add_argument("--observations", default=None,
                        help="(Opcional) CSV de observaciones originales")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        result = json.load(f)

    observations = None
    if args.observations:
        import pandas as pd
        observations = pd.read_csv(args.observations)

    ok = full_validation_report(result, observations)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    _main_cli()
