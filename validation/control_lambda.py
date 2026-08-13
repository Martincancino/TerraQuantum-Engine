"""
EXPERIMENTO DE CONTROL — ¿el hundimiento es de la CONFIGURACIÓN o de mi harness?

El barrido del Sprint 2 midió, con configuración de PRODUCCIÓN (Morozov), que el
centroide recuperado cae SIEMPRE al fondo del dominio (~1650 m) sea cual sea la
profundidad verdadera (250/400/600/900 m). El harness antiguo (`error_budget.py`),
con λ FIJO = 1e-3 y la MISMA malla, reporta 14 m de error horizontal en baseline.

Hay dos explicaciones posibles y hay que separarlas antes de afirmar nada:
    (A) la configuración de producción degrada la recuperación en este régimen
    (B) mi harness tiene un defecto y ninguno de sus números vale

Control: el MISMO mundo, la MISMA campaña, el MISMO comparador — cambiando SOLO λ.
    · Si con λ=1e-3 recupero ~14 m  -> el harness es correcto  -> (A)
    · Si con λ=1e-3 sigo en ~150 m  -> el defecto es mío       -> (B)

    python -m validation.control_lambda
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .regimes import BLOCK_M, DIAGNOSTIC, W_BASE, campaigns_for
from .runner import run_case

SEED = 20260805
LAMBDA_OLD_HARNESS = 1e-3          # el valor que fija error_budget.py


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    campaign = campaigns_for("control", W_BASE, {}, seeds=(SEED,))[0]

    print("=" * 84)
    print("CONTROL: mismo mundo y misma campana, unico cambio = lambda")
    print("=" * 84)
    print(f"mundo   : {W_BASE.id} (esfera r=150 m a 400 m, contraste +0.6 t/m3)")
    print(f"campana : 12x12 estaciones sobre 1500 m, ruido 0.02 mGal, semilla {SEED}")
    print(f"malla   : 18x14x18 @ {BLOCK_M:.0f} m (identica a error_budget.py)")
    print(f"\n{'config':28s} {'horizontal':>12s} {'profundidad':>13s} "
          f"{'centroide y':>12s} {'PR-AUC':>9s}")
    print("-" * 84)

    rows = []
    for label, override in (("PRODUCCION (Morozov)", None),
                            (f"FIJO lambda={LAMBDA_OLD_HARNESS:g}", LAMBDA_OLD_HARNESS)):
        r = run_case(W_BASE, campaign, DIAGNOSTIC, block_m=BLOCK_M,
                     tau_frac_of_peak=0.5, error_is_large_above_m=200.0,
                     lambda_override=override)
        m = r.metrics
        rec_y = 400.0 + m.depth_error_centroid_m
        print(f"{label:28s} {m.horizontal_error_m:9.1f} m {m.depth_error_centroid_m:11.1f} m "
              f"{rec_y:10.0f} m {m.pr_auc:9.4f}")
        rows.append((label, m, r))

    print("-" * 84)
    fixed = rows[1][1]
    print("\nVEREDICTO DEL CONTROL:")
    if fixed.horizontal_error_m < 60.0:
        print("  Con lambda=1e-3 el harness recupera bien -> el harness es CORRECTO.")
        print("  La degradacion con configuracion de produccion es un HALLAZGO REAL.")
    elif fixed.horizontal_error_m < 0.5 * rows[0][1].horizontal_error_m:
        print("  Con lambda=1e-3 mejora sustancialmente pero no llega a ~14 m.")
        print("  La configuracion explica PARTE; queda diferencia por investigar")
        print("  (candidatos: padding, cutoff_radius, IRLS, dominio mas profundo).")
    else:
        print("  Con lambda=1e-3 NO mejora -> la diferencia NO es la configuracion.")
        print("  Hay un defecto en el harness o una diferencia estructural con")
        print("  error_budget.py. NO usar los numeros del barrido hasta resolverlo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
