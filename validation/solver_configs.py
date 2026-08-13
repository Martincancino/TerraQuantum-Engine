"""
Configuraciones del sistema bajo prueba, DECLARADAS.

El Sprint 2 midió que `density_min` cambia el resultado de forma material y además
altera el λ que Morozov selecciona en un orden de magnitud, con el efecto INVERTIDO
según el régimen:

    w001 (malla 50 m, esfera somera 300 m):  permisiva 2.3 m / PR-AUC 0.96
                                             estricta  9.8 m / PR-AUC 0.48
    w_base (malla 125 m, 400 m):             permisiva -> HUNDIMIENTO al fondo
                                             estricta  -> centroide a 655 m

Por eso no hay un "valor correcto" que elegir: hay dos brazos que se miden.
"""
from __future__ import annotations

from .contract import Provenance, SolverConfig

SCHEMA = "solver_config/1"


def _cfg(cid, dmin_rel, rationale, norm="L2", mode="morozov", lam=None):
    return SolverConfig(
        schema_version=SCHEMA, id=cid, lambda_mode=mode, lambda_fixed=lam,
        density_min_rel_base=dmin_rel, density_max_rel_base=2.0,
        regularization_norm=norm, rationale=rationale,
        provenance=Provenance(seed=0, generator_version="solver_configs/1"),
    )


# ── Los dos brazos del experimento ──────────────────────────────────────────

PERMISSIVE = _cfg(
    "s_permissive_L2", -0.5,
    rationale=(
        "Permite contraste NEGATIVO (hasta -0.5 t/m3). MEDIDO: en malla fina y "
        "somera (w001) da la mejor recuperacion del framework (2.3 m, PR-AUC 0.96); "
        "en malla gruesa (w_base) hunde la masa al fondo del dominio. Se mantiene "
        "como brazo del experimento porque su efecto depende del regimen, no "
        "porque se sepa que es correcta."),
)

STRICT = _cfg(
    "s_strict_L2", 0.0,
    rationale=(
        "Prohibe contraste negativo (density_min = densidad de fondo). Es lo mas "
        "cercano al default de produccion (2.6 t/m3 de esquema, que para un fondo "
        "de 2.67 deja apenas -0.07). MEDIDO: cura el hundimiento en malla gruesa "
        "(centroide 1653 -> 655 m, PR-AUC 0.04 -> 0.70) pero degrada la malla fina."),
)

# ── Referencia historica: la config del harness antiguo (error_budget.py) ───
LEGACY_HARNESS = _cfg(
    "s_legacy_errorbudget", 0.0, norm="compact", mode="fixed", lam=1e-3,
    rationale=(
        "Reproduce la configuracion de scripts/validation/error_budget.py "
        "(lambda fijo 1e-3, IRLS compacto, sin contraste negativo) para poder "
        "comparar contra sus numeros publicados. NO es configuracion de "
        "produccion: docs/05 A' midio que ese lambda sobreajusta en profundo."),
)

ARMS = (PERMISSIVE, STRICT)
ALL = (PERMISSIVE, STRICT, LEGACY_HARNESS)
