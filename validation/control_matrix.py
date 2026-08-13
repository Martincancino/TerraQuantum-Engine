"""
MATRIZ DE ATRIBUCION — que explica la divergencia con el harness antiguo.

El control de lambda descarto la configuracion de lambda como causa: con lambda=1e-3
el hundimiento persistia. Quedan dos diferencias ESTRUCTURALES entre mi runner y
`error_budget.py`, y ambas eran elecciones arbitrarias mias:

    parametro              error_budget.py        mi runner (v1)
    density_min            BASE_DENSITY           base - 0.5   <- permite contraste NEGATIVO
    regularization_norm    "compact" (IRLS)       "L2"          <- suave, no localiza

Esta matriz aisla cada una. El valor del framework no es tener muchos escenarios:
es poder ATRIBUIR una diferencia a una causa.

    python -m validation.control_matrix
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .regimes import BASE_DENSITY, BLOCK_M, DIAGNOSTIC, W_BASE, campaigns_for
from .runner import run_case

SEED = 20260805
TRUE_DEPTH = 400.0

CONFIGS = [
    ("A  L2 + contraste negativo", "L2", BASE_DENSITY - 0.5),
    ("B  L2 + solo positivo", "L2", BASE_DENSITY),
    ("C  compact + contraste neg.", "compact", BASE_DENSITY - 0.5),
    ("D  compact + solo positivo", "compact", BASE_DENSITY),   # = error_budget.py
]


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    campaign = campaigns_for("matrix", W_BASE, {}, seeds=(SEED,))[0]

    print("=" * 88)
    print("MATRIZ DE ATRIBUCION  (mismo mundo, misma campana, misma semilla)")
    print("=" * 88)
    print(f"verdad: esfera r=150 m a {TRUE_DEPTH:.0f} m | fondo del dominio = 1687 m")
    print(f"\n{'config':30s} {'horizontal':>11s} {'centroide y':>12s} "
          f"{'PR-AUC':>9s} {'IoU@tau':>9s}")
    print("-" * 88)

    out = []
    for label, norm, dmin in CONFIGS:
        r = run_case(W_BASE, campaign, DIAGNOSTIC, block_m=BLOCK_M,
                     tau_frac_of_peak=0.5, error_is_large_above_m=200.0,
                     density_min_override=dmin, regularization_norm=norm)
        m = r.metrics
        rec_y = TRUE_DEPTH + m.depth_error_centroid_m
        print(f"{label:30s} {m.horizontal_error_m:8.1f} m {rec_y:10.0f} m "
              f"{m.pr_auc:9.4f} {m.iou_at_tau:9.4f}")
        out.append((label, m, rec_y))

    print("-" * 88)
    print("\nLECTURA:")
    a, b, c, d = (o[1] for o in out)
    print(f"  efecto de PROHIBIR contraste negativo (A->B): "
          f"horizontal {a.horizontal_error_m:.0f} -> {b.horizontal_error_m:.0f} m")
    print(f"  efecto de COMPACT sobre L2          (A->C): "
          f"horizontal {a.horizontal_error_m:.0f} -> {c.horizontal_error_m:.0f} m")
    print(f"  ambos juntos (= error_budget.py)    (A->D): "
          f"horizontal {a.horizontal_error_m:.0f} -> {d.horizontal_error_m:.0f} m")
    print(f"\n  centroide recuperado: A={out[0][2]:.0f} B={out[1][2]:.0f} "
          f"C={out[2][2]:.0f} D={out[3][2]:.0f} m   (verdad {TRUE_DEPTH:.0f} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
