"""
Nivel SMOKE del Validation Framework.

    python -m validation.run_smoke            # desde la raíz del repositorio

Presupuesto: < 5 min. Es el nivel que debe correr en CI (cierra el hueco H-4 de la
auditoría: hoy la regresión física no corre automáticamente).

Salida: código 0 si todo PASA; 1 si algo FALLA o si el oráculo no se valida.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):                     # permite `python validation/run_smoke.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .catalog import ERROR_LARGE_ABOVE_M, SMOKE, TAU_FRAC_OF_PEAK
from .generate import selfcheck_against_analytic
from .runner import run_case, tq_version
from .store import save

BLOCK_M = 50.0
ORACLE_TOLERANCE = 1e-6          # el oráculo debe coincidir con la forma cerrada


def _utf8_console() -> None:
    """La consola de Windows usa cp1252 y no puede representar λ, χ, τ.
    Se reconfigura a UTF-8 con reemplazo: mejor que empobrecer la salida."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _utf8_console()
    print("=" * 78)
    print("TerraQuantum - VALIDATION FRAMEWORK - nivel SMOKE")
    print("=" * 78)
    print(f"Version de TQ bajo prueba: {tq_version()}")

    # ── 0. El oráculo se valida a sí mismo ANTES de medir nada ──────────────
    err = selfcheck_against_analytic()
    ok_oracle = err <= ORACLE_TOLERANCE
    print(f"\n[oráculo] choclo vs fórmula cerrada de masa puntual: "
          f"error relativo max. {err:.2e}  -> {'OK' if ok_oracle else 'FALLO'}")
    if not ok_oracle:
        print("  ABORTADO: si el generador no es fiable, ninguna metrica lo es.")
        return 1

    failures, errors = 0, 0
    for world, campaign, acceptance in SMOKE:
        print("\n" + "-" * 78)
        print(f"{world.id}  x  {campaign.id}   [{world.metadata.regime}]")
        print(f"  hash del mundo : {world.provenance.content_hash[:16]}...")
        print(f"  generacion     : {campaign.generation_method.value}")
        print(f"  {campaign.generation_detail}")

        res = run_case(world, campaign, acceptance, block_m=BLOCK_M,
                       tau_frac_of_peak=TAU_FRAC_OF_PEAK,
                       error_is_large_above_m=ERROR_LARGE_ABOVE_M)

        m = res.metrics
        print(f"\n  λ elegido      : {res.tq_config.get('lambda_selected')} "
              f"({res.tq_config.get('lambda_selection')})")
        print(f"  topografia     : {res.tq_config.get('topography_used')}")
        print(f"  PRIMARIAS      : pr_auc={m.pr_auc:.4f}  iou_auc={m.iou_auc:.4f}")
        print(f"  localizacion   : horiz={m.horizontal_error_m:.1f} m  "
              f"prof={m.depth_error_centroid_m:.1f} m")
        print(f"  ajuste         : chi2={m.chi2_red:.3g}  misfit={m.misfit_pct:.3g} %")
        print(f"  secundarias    : IoU@tau={m.iou_at_tau:.4f} (tau={m.tau_used:.4g}) "
              f"vol_err={m.volume_error_pct:.1f} %")
        print(f"  honestidad     : confianza={res.calibration.declared_confidence} "
              f"prof={res.calibration.declared_depth_confidence} "
              f"-> {res.calibration.quadrant}")
        print(f"  tiempo         : {res.runtime_s:.1f} s")

        path = save(res)
        print(f"  guardado en    : {path}")

        if res.verdict == "ERROR":
            errors += 1
            print(f"  VEREDICTO      : ERROR - {res.error}")
        elif res.verdict == "PASS":
            print("  VEREDICTO      : PASS")
        else:
            failures += 1
            print(f"  VEREDICTO      : {res.verdict}")
            for f in res.failed_thresholds:
                print(f"     - {f}")
        if res.calibration.quadrant == "SOBRECONFIADO":
            failures += 1
            print("     * BUG DE HONESTIDAD: confianza alta con error grande")

    print("\n" + "=" * 78)
    total = len(SMOKE)
    print(f"RESUMEN: {total - failures - errors}/{total} PASS | "
          f"{failures} FAIL · {errors} ERROR")
    return 0 if (failures == 0 and errors == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
