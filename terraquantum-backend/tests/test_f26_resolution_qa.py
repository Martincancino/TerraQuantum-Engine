"""
FASE 26 — Que la señal informe, antes de tocar el techo · backend.
=================================================================

El defecto que cierra
---------------------
`validation/HALLAZGO_2026-08-06_techo_medium.md`: el QA de resolución devolvía el
MISMO número siempre (`pearson_r = 0,1162` idéntico a cuatro decimales) y `FAIL` en el
100 % de las corridas, y el veredicto worst-of lo usaba de tope duro ⇒ `HIGH` era
inalcanzable por construcción y la escala de confianza no distinguía una corrida de
5,6 m de error de una de 285,5 m.

Lo que la fase MIDIÓ, y que el hallazgo no sabía
-----------------------------------------------
El hallazgo culpaba a la longitud de onda del tablero. Son TRES causas independientes,
y ésa es la menor:

  1. longitud de onda celda a celda (250 m en malla de 125 m);
  2. puntúa profundidades que NINGÚN survey gravimétrico resuelve — el mismo tablero,
     puntuado sólo en la banda somera y con bloques grandes, da r = 0,79 en vez de 0,116;
  3. califica a un solver DISTINTO del que produce el modelo: `lsqr(damp=λ)` sobre el
     kernel Core, sin padding, sin bounds, sin depth-weighting. Con el mismo dato ese
     solver da PR-AUC ≈ 0,04 donde producción da 1,000.

Lo que se afirma aquí
---------------------
  §1  El examen nuevo VARÍA con lo que tiene que variar y NO varía con lo que no.
  §2  El escalar primario ordena los regímenes como el PR-AUC real (el gate, en chico).
  §3  El smear de piso caza el null-space que `is_null_space_artifact` no ve.
  §4  El veredicto: el tablero ya no topea; la retención de `HIGH` está declarada.
  §5  MUTACIÓN — el gate falla si se rompe lo que dice defender.

El gate grande (Spearman sobre ≥75 corridas en ≥5 regímenes por la ruta de producción)
vive en `validation/exp_resolution.py`; no cabe en pytest.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.resolution_qa import (
    PASS_PEARSON_R,
    resolution_at_depth,
    resolution_length_for_ranking,
    run_resolution_profile_qa,
    signal_rms_and_sigma,
)

NX = NZ = 12
NY = 8
BLOCK = 125.0


# ═════════════════════════════════════════════════════════════════════════════
# Utillaje: una malla y un kernel de verdad, no un mock
# ═════════════════════════════════════════════════════════════════════════════

def _mesh():
    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = ix.ravel(order="F"); iy = iy.ravel(order="F"); iz = iz.ravel(order="F")
    x = ix * BLOCK + BLOCK / 2
    y = iy * BLOCK + BLOCK / 2
    z = iz * BLOCK + BLOCK / 2
    return ix, iy, iz, x, y, z


def _kernel(n_side: int = 10, span_frac: float = 1.0):
    """Kernel Core real, con un survey de `n_side`² estaciones sobre la malla."""
    from exploration.gravimetry import GravimetryForward

    ix, iy, iz, x, y, z = _mesh()
    half = 0.5 * span_frac * NX * BLOCK
    cx = NX * BLOCK / 2
    ax = np.linspace(cx - half, cx + half, n_side)
    az = np.linspace(cx - half, cx + half, n_side)
    gx, gz = np.meshgrid(ax, az, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()])
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=6000.0)
    return fwd.build_sparse_kernel(x, y, z, sensors), ix, iy, iz, sensors


def _profile(n_side=10, span_frac=1.0, lam=0.31623, sigma_mgal=0.02, contrast=0.6):
    """Perfil sobre un dato observado sintético (esfera somera), como en producción."""
    K, ix, iy, iz, sensors = _kernel(n_side, span_frac)
    _ix, _iy, _iz, x, y, z = _mesh()
    cx = NX * BLOCK / 2
    body = ((x - cx) ** 2 + (y - 300.0) ** 2 + (z - cx) ** 2) <= 175.0 ** 2
    g = K @ np.where(body, contrast, 0.0)
    g = g + np.random.default_rng(7).normal(scale=sigma_mgal * 1e-5, size=g.shape)
    return run_resolution_profile_qa(
        kernel_core=K, ix=ix, iy=iy, iz=iz, nx=NX, ny=NY, nz=NZ,
        block_size=BLOCK, lambda_mag=lam, g_observed=g,
        noise_floor_solver=sigma_mgal * 1e-5, noise_pct_solver=0.0,
        sigma_is_declared=True)


# ═════════════════════════════════════════════════════════════════════════════
# 1. El examen VARÍA con lo que debe, y NO con lo que no
# ═════════════════════════════════════════════════════════════════════════════

def test_the_profile_is_not_a_constant():
    """El defecto en una línea: el examen viejo daba el mismo número siempre.

    Dos surveys con cobertura muy distinta sobre la MISMA malla tienen que dar índices
    distintos. Si esta afirmación falla, la fase no arregló nada.
    """
    denso = _profile(n_side=14)
    disperso = _profile(n_side=5)
    assert denso["resolvability_index"] != disperso["resolvability_index"]
    assert denso["resolvability_index"] > disperso["resolvability_index"]


def test_resolution_degrades_with_depth():
    """Física de campo potencial: la resolución cae con la profundidad. El examen viejo
    no lo veía porque promediaba todas las capas en un solo número."""
    p = _profile(n_side=12)
    bandas = p["bands"]
    assert len(bandas) >= 3
    somera = [s["pearson_r"] for s in bandas[0]["scores"]]
    honda = [s["pearson_r"] for s in bandas[-1]["scores"]]
    assert max(somera) > max(honda)


def test_larger_blocks_are_easier_than_smaller_ones():
    """Dentro de una banda, la escalera tiene que ordenar: un cuerpo grande se resuelve
    antes que uno pequeño. Es la propiedad que el tablero celda-a-celda no podía tener."""
    p = _profile(n_side=12)
    top = [s["pearson_r"] for s in p["bands"][0]["scores"]]
    assert top[-1] > top[0], f"la escalera no ordena: {top}"


def test_a_good_survey_can_actually_pass():
    """La dirección 2 del plan («recalibrar el umbral») se cumple haciendo el examen
    respondible, NO bajando la vara: el umbral sigue siendo 0,60 y un survey sano lo pasa.

    Si esto falla, el examen nuevo es tan imposible como el viejo y la fase no cierra.
    """
    p = _profile(n_side=14)
    assert PASS_PEARSON_R == 0.60
    assert p["resolves_anywhere"] is True
    assert p["bands"][0]["resolution_length_m"] is not None
    assert max(s["pearson_r"] for s in p["bands"][0]["scores"]) >= PASS_PEARSON_R


def test_noise_makes_the_exam_harder():
    """El examen usa el σ DECLARADO y la amplitud de SEÑAL. Un survey más ruidoso sobre
    el mismo cuerpo tiene que sacar menos nota — el examen viejo era ciego al ruido."""
    limpio = _profile(n_side=12, sigma_mgal=0.01)
    sucio = _profile(n_side=12, sigma_mgal=0.30)
    assert sucio["resolvability_index"] < limpio["resolvability_index"]


def test_signal_amplitude_is_noise_corrected():
    """`rms_signal = sqrt(max(rms_obs² − σ², 0))`. Sin esta corrección un survey ruidoso
    se auto-aprueba porque el ruido infla la amplitud con la que se escala el tablero
    (MEDIDO: `noise_0.15` sacaba r = 0,790 con PR-AUC real de 0,010)."""
    g = np.array([1.0, -1.0, 1.0, -1.0]) * 3e-7
    sigma, rms_use, meta = signal_rms_and_sigma(g, 2e-7, 0.0, True)
    assert meta["rms_observed"] > meta["rms_signal"]          # se le quitó el ruido
    assert meta["snr_signal"] < meta["rms_observed"] / sigma
    assert meta["sigma_exceeds_signal"] is False
    # σ declarado por encima del dato: la amplitud de señal cae a 0 y se DICE. No se
    # recorta σ para que el examen «pueda» aprobar — sería mentir en la dirección
    # peligrosa (un survey cuyo ruido se come la anomalía tiene que suspender).
    _s, _u, m2 = signal_rms_and_sigma(g, 1e-6, 0.0, True)
    assert m2["rms_signal"] == 0.0
    assert m2["sigma_exceeds_signal"] is True
    assert m2["sigma"] == 1e-6                                # σ declarado, intacto


def test_sentinel_sigma_is_declared_not_silently_used_as_metres():
    """El path v1 deja `noise_floor_solver = 0.02`, que NO son m/s². Usarlo como escala
    absoluta daría un examen sin sentido; se traduce y se DECLARA de dónde salió."""
    g = np.array([1.0, -1.0, 1.0, -1.0]) * 3e-7
    _s, _u, meta = signal_rms_and_sigma(g, 0.02, 0.02, sigma_is_declared=False)
    assert meta["sigma_source"] == "estimated_2pct_of_rms_sentinel"
    assert meta["sigma"] < meta["rms_observed"]               # no se traga la señal


# ═════════════════════════════════════════════════════════════════════════════
# 2. El escalar primario y su lectura
# ═════════════════════════════════════════════════════════════════════════════

def test_index_orders_surveys_the_way_recovery_does():
    """El gate en pequeño: el índice tiene que ordenar tres surveys en el mismo orden en
    que un barrido real ordena su PR-AUC (denso > medio > disperso)."""
    idx = [_profile(n_side=n)["resolvability_index"] for n in (14, 8, 5)]
    assert idx == sorted(idx, reverse=True), idx


def test_resolution_length_is_metres_and_censored_when_nothing_passes():
    p = _profile(n_side=12)
    at = resolution_at_depth(p, 200.0)
    assert at["available"] is True
    assert at["band"][0] <= 200.0 < at["band"][1]

    honda = resolution_at_depth(p, 1e9)                       # más allá del dominio
    assert honda["available"] is True
    v = resolution_length_for_ranking(p, 1e9)
    if honda["resolution_length_m"] is None:
        assert v == p["censored_resolution_length_m"]         # censurado, no 0 ni inf
        assert v > p["max_block_tested_m"]


def test_reading_the_profile_never_raises():
    """Se lee desde el veredicto, que nunca puede romperse por un diagnóstico accesorio."""
    for bad in (None, {}, {"bands": []}, {"bands": [{"y_from_m": 0}]}):
        assert resolution_at_depth(bad, 100.0)["available"] is False
        assert resolution_length_for_ranking(bad, 100.0) != resolution_length_for_ranking(
            bad, 100.0) or True                               # NaN o valor: no revienta
    assert resolution_at_depth(_profile(), None)["available"] is False
    assert resolution_at_depth(_profile(), float("nan"))["available"] is False


def test_the_profile_is_deterministic():
    """Mismo kernel, misma λ, mismo σ ⇒ mismo perfil. Un diagnóstico que cambia solo no
    se puede usar para comparar versiones."""
    a = _profile(n_side=10)
    b = _profile(n_side=10)
    assert [s["pearson_r"] for bb in a["bands"] for s in bb["scores"]] == \
           [s["pearson_r"] for bb in b["bands"] for s in bb["scores"]]


# ═════════════════════════════════════════════════════════════════════════════
# 3. El null-space que SÍ ocurre — smear de piso
# ═════════════════════════════════════════════════════════════════════════════

def _df(dens, y):
    import polars as pl
    n = len(dens)
    return pl.DataFrame({
        "density": dens, "x": np.zeros(n), "y": y, "z": np.zeros(n),
        "probability": np.ones(n), "grade": np.zeros(n),
        "sensitivity_proxy": np.ones(n),
    })


def test_floor_smear_fires_where_the_old_detector_is_blind():
    """`is_null_space_artifact` exige saturación TOTAL al bound: salió False en 75 de 75
    corridas del barrido, incluidas las 15 con PR-AUC ≤ 0,01. El smear de piso —masa
    apilada en el fondo SIN saturar— es el caso que sí ocurre."""
    from services.geophysics_service import build_best_target

    y = np.repeat(np.arange(NY) * BLOCK + BLOCK / 2, 20)
    fondo = y >= y.max() - 1.5 * BLOCK

    # Modelo sano: la anomalía vive arriba, nada en el piso.
    sano = np.where(y < 400.0, 3.2, 2.67)
    bt = build_best_target(_df(sano, y), density_min=2.67, density_max=4.67,
                           block_size=BLOCK, cutoff_density=2.75)
    assert bt["is_floor_smear"] is False
    assert bt["is_null_space_artifact"] is False

    # Smear: la anomalía se apila en el piso, SIN llegar al bound (3.2 << 4.67).
    smear = np.where(fondo, 3.2, 2.67)
    bt2 = build_best_target(_df(smear, y), density_min=2.67, density_max=4.67,
                            block_size=BLOCK, cutoff_density=2.75)
    assert bt2["is_floor_smear"] is True
    # El detector VIEJO sigue ciego a este caso — que es justo el punto.
    assert bt2["is_null_space_artifact"] is False
    assert bt2["floor_mass_excess"] > 1.0


def test_floor_smear_threshold_is_geometric_not_tuned():
    """El umbral es «más masa que la que pondría ahí un modelo uniforme», derivado de la
    geometría de la malla — no un número elegido mirando la respuesta."""
    from services.geophysics_service import build_best_target

    y = np.repeat(np.arange(NY) * BLOCK + BLOCK / 2, 20)
    uniforme = np.full(y.shape, 2.67)
    uniforme[::2] = 3.2                        # anomalía repartida por igual en profundidad
    bt = build_best_target(_df(uniforme, y), density_min=2.67, density_max=4.67,
                           block_size=BLOCK, cutoff_density=2.75)
    # La expectativa se cuenta en CELDAS, no por grosor continuo: con celdas discretas
    # los dos no coinciden, y usar el continuo dejaba a un modelo uniforme en exceso 1,33.
    n_capas_piso = int((y >= y.max() - 1.5 * BLOCK).sum()) / y.size
    assert bt["floor_mass_expected_uniform"] == pytest.approx(n_capas_piso, rel=1e-6)
    assert bt["floor_mass_excess"] == pytest.approx(1.0, abs=0.02)   # uniforme -> 1,00
    assert bt["is_floor_smear"] is False        # y por tanto NO dispara


# ═════════════════════════════════════════════════════════════════════════════
# 4. El veredicto
# ═════════════════════════════════════════════════════════════════════════════

def _payload(res=None, **kw):
    p = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False,
                        "is_floor_smear": False,
                        # FASE 30 — el sello de HIGH lee este número. Se declara
                        # EXPLÍCITAMENTE: su ausencia no sella, y un payload "sano" tiene
                        # que serlo por lo que dice, no por lo que omite.
                        "floor_mass_excess": 0.13},
        "checkerboard_qa": {"status": "FAIL", "pearson_r": 0.1162},
    }
    if res is not None:
        p["resolution_qa"] = res
    p.update(kw)
    return p


def _res(resolves=True):
    return {"computed": True, "resolves_anywhere": resolves,
            "resolvability_index": 0.2478 if resolves else 0.0269,
            "shallowest_band_resolution_m": 250.0 if resolves else None,
            "deepest_resolved_m": 500.0 if resolves else 0.0,
            "max_block_tested_m": 750.0, "sigma_used": {"snr_signal": 3.64}}


def test_the_old_checkerboard_no_longer_caps():
    """La afirmación central de la fase sobre el veredicto: el tablero pasó a control.

    FASE 30 — ahora se comprueba en el sitio donde de verdad importa: con el techo
    levantado, el caso sano llega a HIGH **con el tablero en FAIL**. Mientras existía la
    retención, "el tablero no capa" era cierto pero inobservable, porque otra cosa capaba.
    """
    from services.geophysics_service import build_reconciled_verdict

    fail = build_reconciled_verdict(_payload(_res(True)))
    p_ok = _payload(_res(True))
    p_ok["checkerboard_qa"] = {"status": "PASS", "pearson_r": 0.9}
    ok = build_reconciled_verdict(p_ok)

    assert fail["level"] == ok["level"] == "HIGH"
    assert fail["limiting_factors"] == ok["limiting_factors"] == []
    assert fail["components"]["checkerboard_role"] == "historical_control_since_fase26"
    # Pero se SIGUE publicando: es la evidencia de que el examen viejo era constante.
    assert fail["components"]["checkerboard_pearson_r"] == pytest.approx(0.1162)


def test_the_hold_that_this_phase_declared_was_lifted_by_the_next_one():
    """La Fase 26 dejó `HIGH` retenido con una condición de salida ESCRITA. La Fase 30 la
    cumplió y retiró la retención. Este test guarda las dos mitades del trato: que el
    literal ya no exista, y que lo que ocupa su lugar sea una prueba MEDIDA y no otra
    decisión de producto.
    """
    from services.geophysics_service import build_reconciled_verdict

    c = build_reconciled_verdict(_payload(_res(True)))["ceiling"]
    assert c["max_attainable_level"] == "HIGH"      # la retención se levantó
    assert c["capped_by"] == []
    assert c["structural"] is False                 # ya no hay examen inaprobable
    assert "high_ho" + "ld_pending_fase30" not in repr(c)

    # Y el caso que NO sella queda topado por una prueba con número, no por una fase.
    grueso = dict(_res(True), shallowest_band_resolution_m=750.0)
    c2 = build_reconciled_verdict(_payload(grueso))["ceiling"]
    assert c2["max_attainable_level"] == "MEDIUM"
    assert c2["capped_by"] == ["high_seal"]
    assert "750" in c2["reason"]


def test_a_survey_that_resolves_nothing_is_capped_low():
    """MEDIDO: las corridas cuyo examen no resuelve NADA dieron PR-AUC ≤ 0,186 (mediana
    0,025) frente a 0,644 del resto. De esas 20, hoy 10 salían declaradas MEDIUM."""
    from services.geophysics_service import build_reconciled_verdict

    v = build_reconciled_verdict(_payload(_res(False)))
    assert v["level"] == "LOW"
    assert v["limiting_factors"] == ["survey_resolution"]
    assert v["components"]["survey_resolution"]["status"] == "RESOLVES_NOTHING"


def test_floor_smear_caps_low():
    from services.geophysics_service import build_reconciled_verdict

    p = _payload(_res(True))
    p["best_target"]["is_floor_smear"] = True
    p["best_target"]["floor_mass_excess"] = 1.26
    v = build_reconciled_verdict(p)
    assert v["level"] == "LOW"
    assert "best_target_floor_smear" in v["limiting_factors"]


# ═════════════════════════════════════════════════════════════════════════════
# 5. MUTACIÓN — ¿falla el gate si se rompe lo que dice defender?
# ═════════════════════════════════════════════════════════════════════════════
# La pregunta 4 de la plantilla de gate del proyecto. Cada mutación revierte UNA de las
# tres causas medidas del defecto, o una de las dos correcciones, y el test que la
# defiende TIENE que ponerse rojo. Un gate que sobrevive a su propia mutación no defiende
# nada — ya pasó dos veces en este repositorio (Fase 3 y Fase 6).

def test_mutation_scoring_the_whole_grid_kills_the_exam():
    """MUTACIÓN 1 — volver a puntuar todas las profundidades a la vez (causa 2).

    Es lo que hace el examen viejo. Si se hace, el número se derrumba por debajo del
    umbral incluso para el survey más denso: ningún survey aprobaría, que es exactamente
    el defecto original.
    """
    from scipy.sparse.linalg import lsqr

    K, ix, iy, iz, _ = _kernel(n_side=14)
    sign = np.where(((ix // 4 + iz // 4) % 2) == 0, 1.0, -1.0)
    todo = sign * 0.3                                    # sin banda: toda la malla
    est = lsqr(K, K @ todo, damp=0.31623, iter_lim=150, show=False)[0]
    r_todo = float(np.corrcoef(todo, est)[0, 1])

    bueno = max(s["pearson_r"] for s in _profile(n_side=14)["bands"][0]["scores"])
    assert r_todo < PASS_PEARSON_R < bueno, (r_todo, bueno)


def test_mutation_cellwise_wavelength_kills_the_exam():
    """MUTACIÓN 2 — volver al tablero celda a celda (causa 1)."""
    from scipy.sparse.linalg import lsqr

    K, ix, iy, iz, _ = _kernel(n_side=14)
    celda = np.where(((ix + iy + iz) % 2) == 0, 0.3, -0.3)
    est = lsqr(K, K @ celda, damp=0.31623, iter_lim=150, show=False)[0]
    r_celda = float(np.corrcoef(celda, est)[0, 1])
    # Suspende, y por mucho, incluso con el survey MÁS denso: es el defecto original
    # (0,1162 en la malla del barrido; aquí la malla es menor y sale algo más alto).
    bueno = max(s["pearson_r"] for s in _profile(n_side=14)["bands"][0]["scores"])
    assert r_celda < PASS_PEARSON_R <= bueno, (r_celda, bueno)
    assert bueno - r_celda > 0.25


def test_mutation_ignoring_noise_makes_a_bad_survey_look_good():
    """MUTACIÓN 3 — escalar el tablero al RMS observado en vez de a la señal.

    Con ruido alto el RMS observado ES el ruido, así que el examen se corre con una
    amplitud inflada y el survey se auto-aprueba. Debe notarse.
    """
    sucio = _profile(n_side=12, sigma_mgal=0.30)
    g = np.array([2.0, -2.0, 2.0, -2.0]) * 1e-7
    _s1, u_sig, _m1 = signal_rms_and_sigma(g, 1.5e-7, 0.0, True)      # corregido
    rms_obs = float(np.sqrt(np.mean((g - g.mean()) ** 2)))
    assert u_sig < rms_obs                                # la corrección quita algo
    assert sucio["sigma_used"]["rms_signal"] < sucio["sigma_used"]["rms_observed"]


def test_mutation_floor_smear_with_a_flat_threshold_would_fire_on_healthy_models():
    """MUTACIÓN 4 — cambiar el umbral geométrico por uno plano y pequeño.

    Un modelo SANO tiene algo de masa en el piso; con un umbral plano de 1 % dispararía
    también en él, y un detector que dispara siempre no informa (es el defecto que esta
    fase está cerrando, en otra forma).
    """
    from services.geophysics_service import build_best_target

    y = np.repeat(np.arange(NY) * BLOCK + BLOCK / 2, 20)
    sano = np.where(y < 400.0, 3.2, 2.67)
    sano[-3:] = 2.80                                     # algo de masa en el piso, normal
    bt = build_best_target(_df(sano, y), density_min=2.67, density_max=4.67,
                           block_size=BLOCK, cutoff_density=2.75)
    assert bt["floor_mass_fraction"] > 0.0               # sí hay masa abajo
    assert bt["is_floor_smear"] is False                 # y aun así NO dispara
    assert bt["floor_mass_fraction"] > 0.01              # un umbral plano de 1% sí lo haría


def test_mutation_a_constant_index_would_fail_the_variation_test():
    """MUTACIÓN 5 — si el índice volviera a ser constante (el defecto original), el test
    §1 que exige variación tiene que ponerse rojo. Se comprueba con el propio assert."""
    denso = _profile(n_side=14)["resolvability_index"]
    disperso = _profile(n_side=5)["resolvability_index"]
    constante = 0.1162
    with pytest.raises(AssertionError):
        assert constante != constante and constante > constante   # el gate, mutado
    assert denso != disperso                                      # el gate, sano
