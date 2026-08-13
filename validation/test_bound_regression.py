"""
Candado de regresión del bound de densidad — el hallazgo del 2026-08-06.

Fija por medición la relación que nadie estaba comprobando: **lo que determina si el
modelo se recupera o se hunde no es `density_min` ni `base_density` por separado, sino
su DIFERENCIA** — el contraste permitido.

Medido (`HALLAZGO_2026-08-06_bound_por_defecto.md`, 48 inversiones):

    contraste >= 0.00  ->  PR-AUC mediano 1.000, error 25 m,  2/8 caidas
    contraste >= -0.01 ->  PR-AUC mediano 0.035, error 134 m, 8/8 caidas
    contraste >= -2.60 ->  PR-AUC mediano 0.035, error 147 m, 8/8 caidas

ALCANCE — leer antes de interpretar estos tests como una afirmacion sobre el producto:
estan medidos con la malla FORZADA (18x14x18 @125 m sobre un survey de 1500 m, es decir
una malla mayor que el survey). El E2E multi-semilla por HTTP mostro que **con la grilla
derivada del CSV —el flujo real— el efecto catastrofico NO ocurre**: PR-AUC 0.837 vs 0.835.
Lo que sobrevive alli es un costo de PROFUNDIDAD (247.6 m vs 18.8 m, rangos sin solape) sin
costo horizontal (13.1 m en ambos). Ver §7.1 del hallazgo.

Estos tests siguen siendo utiles porque fijan una propiedad REAL del solver —el bound hace
el trabajo de regularizacion donde el dato no restringe— pero **no son evidencia de que el
default del producto este roto**.

Estos tests son CAROS (una inversión real cada uno, ~1-2 min) y por eso están apagados
por defecto, siguiendo la convención del repositorio:

    TQ_RUN_VALIDATION=1 pytest validation/test_bound_regression.py -v

QUÉ PASA SI EL DEFAULT SE ARREGLA: nada. Estos tests no afirman cuál es el default; afirman
la RELACIÓN entre contraste permitido y calidad, que seguirá siendo cierta. Un arreglo del
default los deja verdes.
"""
from __future__ import annotations

import os

import pytest

from .contract import Provenance, SolverConfig
from .regimes import BLOCK_M, DIAGNOSTIC, W_BASE, _campaign
from .runner import run_case

RUN = os.getenv("TQ_RUN_VALIDATION") == "1"
# Se usa sólo `skipif` y no un marcador propio: `validation/` vive fuera de los `testpaths`
# del backend, así que un `pytest.mark.validation` quedaría SIN REGISTRAR y ensuciaría cada
# corrida con un warning. La variable de entorno es la misma que usa la suite F9.
pytestmark = pytest.mark.skipif(
    not RUN, reason="inversión real (~1-2 min c/u): usar TQ_RUN_VALIDATION=1")

# Semillas de las que se conoce el desenlace con contraste >= 0 (medidas 2026-08-06).
SEED_OK = 810845      # dio 1.1 m / PR-AUC 1.000
SEED_OK_2 = 810001    # dio 5.1 m / PR-AUC 1.000


def _solver(rel: float, tag: str) -> SolverConfig:
    return SolverConfig(
        schema_version="solver_config/1", id=f"s_regr_{tag}",
        lambda_mode="morozov", lambda_fixed=None,
        density_min_rel_base=rel, density_max_rel_base=2.0,
        regularization_norm="L2",
        rationale=("Brazo del candado de regresion del bound. Fija por medicion que el "
                   "contraste permitido (density_min - base_density) es lo que decide "
                   "si el modelo se recupera o se hunde."),
        provenance=Provenance(seed=0, generator_version="test_bound_regression/1"),
    )


def _run(rel: float, tag: str, seed: int):
    camp = _campaign(f"c_regrbound{tag}_s{seed}", W_BASE, seed)
    res = run_case(W_BASE, camp, DIAGNOSTIC, block_m=BLOCK_M, tau_frac_of_peak=0.50,
                   error_is_large_above_m=200.0, solver=_solver(rel, tag))
    assert res.verdict != "ERROR", f"la corrida falló: {res.error}"
    return res


def test_contraste_no_negativo_recupera_el_cuerpo():
    """Con contraste >= 0 el cuerpo se recupera. Umbrales holgados frente a lo medido
    (1.1 m y PR-AUC 1.000) para no fallar por ruido de semilla."""
    res = _run(0.0, "p000", SEED_OK)
    assert res.metrics.pr_auc >= 0.50, (
        f"PR-AUC {res.metrics.pr_auc:.3f} < 0.50 con contraste >= 0. Medido 1.000 el "
        f"2026-08-06 con esta misma semilla: algo cambió en el motor.")
    assert res.metrics.horizontal_error_m <= 200.0, (
        f"error horizontal {res.metrics.horizontal_error_m:.1f} m > 200 m. Medido 1.1 m.")


def test_un_contraste_negativo_minimo_ya_hunde_el_modelo():
    """El acantilado está en −0.01: un 1.7 % del contraste del cuerpo basta.

    Es el test que le habría puesto un nombre a este fallo antes de encontrarlo por
    accidente. Nótese que el error HORIZONTAL no lo delata (75 m, de aspecto sano):
    hace falta una métrica de campo independiente del umbral.
    """
    res = _run(-0.01, "m001", SEED_OK)
    assert res.metrics.pr_auc <= 0.20, (
        f"PR-AUC {res.metrics.pr_auc:.3f} > 0.20 con contraste >= -0.01. Medido 0.036 en "
        f"8/8 semillas el 2026-08-06. Si esto sube, el motor MEJORÓ y hay que re-medir "
        f"el hallazgo del bound — no silenciar el test.")


def test_el_contraste_permitido_es_lo_que_manda_no_los_valores_absolutos():
    """density_min y base_density sólo importan por su diferencia.

    Es la invariante que el esquema NO comprueba (`_validate_box` sólo mira min < max) y
    que las pruebas del backend no cubren (`test_bounds_variability.py` sólo usa pares
    acoplados). Dos configuraciones con el mismo contraste permitido y valores absolutos
    distintos deben dar el mismo desenlace cualitativo.
    """
    a = _run(0.0, "p000", SEED_OK_2)          # density_min = 2.67 (base 2.67)
    b = _run(-0.01, "m001", SEED_OK_2)        # density_min = 2.66
    assert a.metrics.pr_auc > b.metrics.pr_auc * 3, (
        f"contraste 0.00 dio PR-AUC {a.metrics.pr_auc:.3f} y contraste -0.01 dio "
        f"{b.metrics.pr_auc:.3f}. La separación medida era 1.000 vs 0.041.")
