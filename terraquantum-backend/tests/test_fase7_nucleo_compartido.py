# -*- coding: utf-8 -*-
"""FASE 7 — la extraccion compartida, convertida en invariantes ejecutables.

La Fase 7 (auditoria 06 §10, hallazgos H-9 y H-33) hizo tres cosas, y este archivo
defiende las tres. No repite las mediciones —esas viven en
`scripts/validation/fase7_lambda_identity_probe.py` y `fase7_byte_identity.py`—;
fija las afirmaciones de las que depende todo lo que la fase concluyo.

1. **Un solo sitio.** El nucleo compartido existe y los dos motores lo usan de
   verdad, no "por convencion". Se comprueba por AST (quien importa que) y con el
   gate de duplicacion medido (`scripts/ci/study_duplication.py`).

2. **El funcional es explicito y declarado.** `build_model_weights` es el unico
   sitio donde se elige el peso de modelo, y `declare_functional` dice si entra en
   el funcional. Se comprueba que la declaracion coincide con la REALIDAD medida:
   para cada motor y cada configuracion, mover `depth_beta` mueve la solucion si y
   solo si la corrida declaro que lo haria. Este es el criterio (c) de la fase, y
   la auditoria advirtio que "hoy ese test fallaria en tres de las combinaciones y
   nadie lo sabia".

3. **El escaner de lambda escanea EL funcional que el solver resuelve.** Es la
   recomendacion de §994 y el test que la auditoria pidio por su nombre: el chi²
   que el escaner promete para lambda* debe ser el que el solve consigue con
   lambda*, dentro de una tolerancia MEDIDA.

    python -m pytest tests/test_fase7_nucleo_compartido.py -v
"""
from __future__ import annotations

import ast
import contextlib
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from exploration import potential_field_core as pfc          # noqa: E402
from exploration.gravimetry import (                          # noqa: E402
    GravimetryForward,
    GravimetryInversion,
)
from exploration.magnetometry import (                        # noqa: E402
    MagnetometryForward,
    MagnetometryInversion,
)

NX = NZ = 8
NY = 6
BLOCK = 100.0
BASE_DENSITY = 2.67
DENSITY_MAX = BASE_DENSITY + 1.5
CUTOFF = 3000.0
ALPHA = 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Utilidades del escenario
# ══════════════════════════════════════════════════════════════════════════════

def _centers():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * BLOCK,
            (iy.ravel(order="F") + 0.5) * BLOCK,
            (iz.ravel(order="F") + 0.5) * BLOCK)


def _sensors():
    ax = np.linspace(BLOCK, (NX - 1) * BLOCK, 7)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    return np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)


def _cuerpo(x_c, y_c, z_c, amplitud):
    cx = cz = NX * BLOCK / 2.0
    m = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
         & (y_c >= 2 * BLOCK) & (y_c <= 3 * BLOCK))
    c = np.zeros(x_c.size, dtype=np.float64)
    c[m] = amplitud
    return c


def _padding_mask(x_c, z_c):
    cx = cz = NX * BLOCK / 2.0
    lim = (NX / 2.0 - 1.0) * BLOCK
    return (np.abs(x_c - cx) > lim) | (np.abs(z_c - cz) > lim)


@contextlib.contextmanager
def _perillas_fijas():
    """Fija las perillas que eligen el solver interno (leccion medida en la Fase 4).

    Sin esto los tests son orden-dependientes: `solve_*` lee `core.config` en cada
    llamada, y otros tests de la suite reemplazan ese modulo con
    `sys.modules.pop(...)`, de modo que una referencia tomada al importar queda
    huerfana. Por eso se resuelve el modulo VIVO aqui, en cada uso.
    """
    cfg = importlib.import_module("core.config")
    prev = (cfg.USE_BOUNDED_SOLVER, cfg.USE_PROJECTED_SOLVER, cfg.USE_LSMR_LARGE)
    cfg.USE_BOUNDED_SOLVER = False
    cfg.USE_PROJECTED_SOLVER = True
    cfg.USE_LSMR_LARGE = False
    try:
        yield
    finally:
        (cfg.USE_BOUNDED_SOLVER, cfg.USE_PROJECTED_SOLVER, cfg.USE_LSMR_LARGE) = prev


@pytest.fixture(scope="module")
def caso_mag():
    x_c, y_c, z_c = _centers()
    S = _sensors()
    contraste = _cuerpo(x_c, y_c, z_c, 0.05)
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    d = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, S) @ contraste).ravel()
    rng = np.random.default_rng(20260816)
    nf = 0.02 * float(np.max(np.abs(d)))
    d = d + nf * rng.standard_normal(d.size)
    return dict(x_c=x_c, y_c=y_c, z_c=z_c, S=S, d=d, nf=nf,
                pad=_padding_mask(x_c, z_c), fwd=fwd)


@pytest.fixture(scope="module")
def caso_grav():
    x_c, y_c, z_c = _centers()
    S = _sensors()
    contraste = _cuerpo(x_c, y_c, z_c, 0.8)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, S) @ contraste).ravel()
    rng = np.random.default_rng(20260815)
    nf = 0.02 * float(np.max(np.abs(g)))
    g = g + nf * rng.standard_normal(g.size)
    return dict(x_c=x_c, y_c=y_c, z_c=z_c, S=S, g=g, nf=nf,
                pad=_padding_mask(x_c, z_c), fwd=fwd)


def _invertir_mag(c, *, depth_beta, **kw):
    inv = MagnetometryInversion(NX, NY, NZ, BLOCK)
    meta: dict = {}
    with _perillas_fijas():
        susc, _s, _m, _e = inv.solve_magnetic_inversion_lsqr(
            c["d"], c["y_c"], lambda_mag=1e-3, alpha_spatial=ALPHA,
            forward_model=c["fwd"], sensor_coords=c["S"], x_c=c["x_c"], z_c=c["z_c"],
            susc_min=0.0, susc_max=1.0, noise_floor=c["nf"], noise_pct=0.02,
            depth_beta=depth_beta, detect_outliers=False, solver_meta=meta, **kw)
    return np.asarray(susc, dtype=np.float64), meta


# ══════════════════════════════════════════════════════════════════════════════
# 1. Un solo sitio: el nucleo existe y los dos motores lo usan
# ══════════════════════════════════════════════════════════════════════════════

def _importadores(modulo: str) -> set[str]:
    """Que archivos del backend importan `modulo`, por AST (no por texto)."""
    out: set[str] = set()
    for pkg in ("api", "core", "exploration", "middleware", "reporting", "schemas",
                "services"):
        base = BACKEND_ROOT / pkg
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.ImportFrom) and (nodo.module or "") == modulo:
                    out.add(p.relative_to(BACKEND_ROOT).as_posix())
                elif isinstance(nodo, ast.Import):
                    if any(a.name == modulo for a in nodo.names):
                        out.add(p.relative_to(BACKEND_ROOT).as_posix())
    return out


def test_los_dos_motores_usan_el_nucleo_compartido():
    """H-9 midio 228 ventanas duplicadas entre los dos motores. La solucion no es
    "acordarse de no copiar": es que los dos importen el mismo modulo."""
    quien = _importadores("exploration.potential_field_core")
    assert "exploration/gravimetry.py" in quien, (
        "gravimetry.py dejo de importar el nucleo compartido: la extraccion de la "
        "Fase 7 se revirtio y H-9 vuelve a estar abierto."
    )
    assert "exploration/magnetometry.py" in quien, (
        "magnetometry.py dejo de importar el nucleo compartido (H-9)."
    )


def test_el_peso_de_modelo_se_construye_en_un_solo_sitio():
    """Nadie vuelve a escribir la cadena de pesos a mano dentro de los motores.

    Es EL entregable de la fase: `build_model_weights` decide y declara. Si alguien
    vuelve a calcular `1/norma_de_columna` o `(z+z0)**(beta/2)` dentro de un motor,
    la decision vuelve a estar repartida y H-33 puede repetirse sin que nadie lo vea.
    """
    # El idioma completo, no cualquier norma de columna: `gravimetry` calcula
    # tambien un proxy de sensibilidad para el DOI que NO es un peso de modelo.
    # Lo que no puede volver es la CADENA (norma -> piso -> reciproco -> diags).
    prohibidos = {
        "exploration/gravimetry.py": [
            "col_norms = np.maximum(col_norms, 1e-12)",
            "np.maximum(np.sqrt(G_w.power(2).sum(axis=0)).A1, 1e-12)",
        ],
        "exploration/magnetometry.py": [
            "** (0.5 * float(depth_beta))",
        ],
    }
    for archivo, patrones in prohibidos.items():
        texto = (BACKEND_ROOT / archivo).read_text(encoding="utf-8")
        for pat in patrones:
            assert pat not in texto, (
                f"{archivo} volvio a construir el peso de modelo a mano ({pat!r}). "
                f"Debe pedirselo a potential_field_core.build_model_weights, que es "
                f"donde la Fase 7 concentro la decision y la declaracion. Con la "
                f"cadena repartida, H-33 puede repetirse sin que nadie lo vea."
            )


def test_el_gate_de_duplicacion_cumple_el_criterio_de_la_fase():
    """Criterio de aceptacion (a): ventanas duplicadas grav<->mag por debajo de 40.

    La linea base medida con este mismo script antes de la fase eran 192 (el informe
    reportaba 228 con una herramienta que no quedo en el repositorio; ver el
    docstring de `study_duplication.py` sobre por que el absoluto puede diferir).
    """
    spec = importlib.util.spec_from_file_location(
        "tq_study_dup", BACKEND_ROOT / "scripts" / "ci" / "study_duplication.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tq_study_dup"] = mod
    spec.loader.exec_module(mod)

    medido = mod.measure()
    n = mod.fase7_pair_count(medido)
    assert n < mod.FASE7_MAX, (
        f"gravimetry.py <-> magnetometry.py tiene {n} ventanas duplicadas de 12 "
        f"lineas (criterio de la Fase 7: < {mod.FASE7_MAX}). La extraccion al nucleo "
        f"compartido se esta deshaciendo."
    )
    # Canario: un medidor roto que devuelve 0 pasaria el assert de arriba siempre.
    assert medido["n_ventanas"] > 5000, (
        "el medidor de duplicacion devolvio casi nada: esta roto, no es que el "
        "codigo este limpio."
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. El funcional declarado coincide con el funcional REAL — criterio (c)
# ══════════════════════════════════════════════════════════════════════════════

CONFIGS_MAG = [
    pytest.param({}, True, id="rutaA_L2_sin_padding_sin_anclas"),
    pytest.param({"padding": True}, False, id="rutaB_con_padding"),
    pytest.param({"anclas": True}, False, id="rutaB_con_anclas"),
    pytest.param({"compacto": True}, False, id="rutaB_IRLS_compacto"),
    pytest.param({"padding": True, "compacto": True}, False, id="rutaB_padding+compacto"),
]


@pytest.mark.parametrize("cfg,espera_activo", CONFIGS_MAG)
def test_lo_declarado_es_lo_que_pasa_magnetometria(caso_mag, cfg, espera_activo):
    """Para cada configuracion: `depth_beta` mueve la solucion <=> la corrida lo declaro.

    Este es el test que la auditoria pidio y advirtio que "hoy fallaria en tres de
    las combinaciones". No comprueba que el peso ACTUE —esa decision la tomo la
    fase: se conserva la fisica validada y se declara la verdad—, comprueba que
    **lo que la corrida dice de si misma sea cierto**, que es lo que faltaba.
    """
    kw = {}
    if cfg.get("padding"):
        kw["padding_mask"] = caso_mag["pad"]
    if cfg.get("anclas"):
        cx = cz = NX * BLOCK / 2.0
        kw["boreholes"] = np.array(
            [[cx + BLOCK / 2, cz + BLOCK / 2, 2 * BLOCK, 3 * BLOCK, 0.05]], dtype=np.float64)
    kw["regularization_norm"] = "compact" if cfg.get("compacto") else "L2"
    if cfg.get("compacto"):
        kw["compact_max_irls"] = 4

    m_a, meta_a = _invertir_mag(caso_mag, depth_beta=0.5, **kw)
    m_b, _meta_b = _invertir_mag(caso_mag, depth_beta=3.0, **kw)

    decl = meta_a["regularization_functional"]

    # (i) La regla ALGEBRAICA de H-33 no se negocia: con padding, anclas o IRLS
    #     compacto, todos los bloques llevan W y el funcional es invariante en beta.
    assert decl["model_weight_enters_functional"] is espera_activo, (
        f"para {cfg} la corrida declaro model_weight_enters_functional="
        f"{decl['model_weight_enters_functional']}; H-33 midio {espera_activo}."
    )

    pico = max(float(np.max(np.abs(np.nan_to_num(m_b)))), 1e-30)
    rel = float(np.max(np.abs(np.nan_to_num(m_a) - np.nan_to_num(m_b)))) / pico

    # (ii) Y la declaracion tiene que ser cierta del RESULTADO, no solo del algebra:
    #      si el solver no convergio, el peso —precondicionador por la derecha—
    #      mueve el resultado por parada temprana. La Fase 7 midio 66%-86% ahi,
    #      con la solucion exacta invariante a 1e-11. La corrida debe decirlo.
    assert decl["depth_beta_has_effect"] is (rel > 1e-6), (
        f"para {cfg} la corrida declara depth_beta_has_effect="
        f"{decl['depth_beta_has_effect']}, pero mover beta de 0,5 a 3,0 cambio la "
        f"solucion {rel:.3e}. La declaracion tiene que ser cierta del RESULTADO: "
        f"mecanismo declarado={decl['effect_mechanism']!r}, "
        f"solver_converged={decl['solver_converged']}, istop={decl['lsqr_istop']}."
    )

    if espera_activo:
        assert rel > 1e-3, (
            f"la corrida DECLARA que depth_beta entra en el funcional, pero mover "
            f"beta de 0,5 a 3,0 cambio la solucion solo {rel:.3e}. La declaracion "
            f"miente: es exactamente el problema que H-33 nombro."
        )
        assert decl["effect_mechanism"] == "functional"
    elif rel > 1e-6:
        # RUTA B que SI mueve el resultado. No es una contradiccion con H-33: es su
        # caveat, el que la auditoria dejo escrito y sin cuantificar. El funcional es
        # invariante en beta (medido: solucion exacta por `lstsq` denso, 1e-11), pero
        # W es ademas un precondicionador por la derecha, el LSQR termina con
        # `istop=7` (limite de iteraciones, 500/500) y por tanto DONDE se detiene
        # depende de beta. Lo unico inaceptable seria que la corrida siguiera
        # declarandose inerte.
        assert decl["effect_mechanism"] == "early_stopping", (
            f"mover beta cambio la solucion {rel:.3e} en una configuracion cuyo "
            f"funcional es invariante, y la corrida NO lo atribuyo a parada temprana "
            f"(mecanismo declarado: {decl['effect_mechanism']!r}). Si el solver "
            f"convergio y aun asi beta mueve el resultado, el funcional cambio y hay "
            f"que investigarlo, no declararlo."
        )
        assert decl["solver_converged"] is False
        assert decl["lsqr_istop"] in (3, 7)
    else:
        # RUTA B con el solver convergido: cambio de variable puro, y lo que queda es
        # ruido de punto flotante (la auditoria midio ~1e-10).
        assert decl["effect_mechanism"] == "none"
        assert decl["solver_converged"] is not False


def test_gravimetria_declara_ponderacion_por_sensibilidad(caso_grav):
    """El solver de grilla regular declara que su peso NO es un depth weighting.

    Es H-1 escrito en la salida de la corrida en vez de en un comentario. La Fase 4
    ya habia quitado `depth_beta` de la firma; lo que faltaba era que la corrida
    dijera QUE aplica en su lugar.
    """
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    meta: dict = {}
    with _perillas_fijas():
        inv.solve_inversion_lsqr(
            caso_grav["g"], None, caso_grav["y_c"], lambda_mag=0.31623,
            alpha_spatial=ALPHA, forward_model=caso_grav["fwd"],
            sensor_coords=caso_grav["S"], x_c=caso_grav["x_c"], z_c=caso_grav["z_c"],
            density_min=BASE_DENSITY, density_max=DENSITY_MAX,
            noise_floor=caso_grav["nf"], noise_pct=0.02, solver_meta=meta,
            prune_observable_domain=True, regularization_norm="L2",
            detect_outliers=False)

    decl = meta["regularization_functional"]
    assert decl["model_weight_kind"] == pfc.MODEL_WEIGHT_SENSITIVITY
    assert decl["depth_weighting_active"] is False
    assert decl["model_weight_enters_functional"] is True, (
        "la smallness de gravimetria es identidad en m~, luego el peso de modelo SI "
        "entra en el funcional (ponderacion por sensibilidad). Si esto cambio a "
        "False, alguien metio `Ws` en el bloque de smallness y el peso se anulo."
    )
    # La corrida mide a que Li & Oldenburg equivale SU malla, y cuan limpia es la
    # ley de potencia. El numero es especifico de la geometria: la Fase 4 midio
    # beta~2,63 con 5,3% de desviacion sobre la malla del producto; aqui la malla es
    # de juguete y da otra cosa. Lo que se defiende es que el numero EXISTE y viene
    # acompanado de su desviacion, no un valor concreto.
    assert decl["effective_beta_equivalente"] is not None
    assert decl["effective_desviacion_max_pct"] is not None


def test_la_regla_del_funcional_es_una_sola_y_esta_escrita():
    """`declare_functional` deriva las tres filas de H-33 de UNA regla, no de tablas."""
    depths = np.linspace(50.0, 500.0, 20)
    w_prof = pfc.build_model_weights(
        pfc.MODEL_WEIGHT_DEPTH, depths=depths, z0=50.0, depth_beta=1.5)

    ruta_a = pfc.declare_functional(w_prof, smallness=pfc.SMALLNESS_IDENTITY_IN_TILDE)
    ruta_b = pfc.declare_functional(w_prof, smallness=pfc.SMALLNESS_SCALED_BY_W)
    assert ruta_a["depth_weighting_active"] is True
    assert ruta_b["depth_weighting_active"] is False
    assert ruta_b["model_weight_is_pure_change_of_variable"] is True

    # Y el peso por sensibilidad nunca se declara como depth weighting, aunque su
    # forma se parezca a una ley de potencia en profundidad.
    G = __import__("scipy.sparse", fromlist=["diags"]).diags(1.0 / (depths + 50.0) ** 1.5)
    w_sens = pfc.build_model_weights(pfc.MODEL_WEIGHT_SENSITIVITY, G_w=G.tocsr())
    # `depths` a secas usaria z0=0 y el ajuste saldria sesgado: el exponente solo
    # se recupera si el ajuste usa el MISMO z0 con el que se construyo el peso.
    d_sens = pfc.declare_functional(w_sens, smallness=pfc.SMALLNESS_IDENTITY_IN_TILDE,
                                    depths=depths + 50.0)
    assert d_sens["depth_weighting_active"] is False
    assert d_sens["model_weight_enters_functional"] is True
    assert d_sens["effective_beta_equivalente"] == pytest.approx(3.0, rel=0.05), (
        "el ajuste de ley de potencia dejo de recuperar el exponente que se le "
        "inyecto: `effective_depth_exponent` esta roto y la corrida publicaria un "
        "numero sin significado."
    )


def test_declare_functional_rechaza_un_bloque_de_smallness_inventado():
    """Un valor no previsto debe fallar, no elegir una rama por defecto en silencio."""
    w = pfc.build_model_weights(pfc.MODEL_WEIGHT_DEPTH, depths=np.array([10.0, 20.0]),
                                z0=5.0, depth_beta=1.5)
    with pytest.raises(ValueError, match="smallness"):
        pfc.declare_functional(w, smallness="lo_que_sea")


# ══════════════════════════════════════════════════════════════════════════════
# 3. El escaner de lambda escanea EL funcional que el solver resuelve
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.slow
def test_el_chi2_prometido_por_el_escaner_es_el_que_el_solve_consigue(caso_grav):
    """El test que §994 de la auditoria pidio por su nombre.

    «un test que verifique la identidad que hoy nadie comprueba: el chi² predicho
    por el escaner para lambda* debe coincidir con el chi² obtenido por el solve con
    lambda*, dentro de una tolerancia medida.»

    Tolerancia MEDIDA (`scripts/validation/fase7_lambda_identity_probe.py`): con el
    box petrofisico ABIERTO el ratio es 1,0000 a las cuatro profundidades probadas —
    identidad exacta. El box es la unica diferencia que le queda al escaner, porque
    no modela bounds; con el box de produccion el ratio medido fue 1,12–1,70.

    Antes de la Fase 7 este ratio iba de 23x a 12.700x y crecia con la profundidad.
    """
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    candidatos = [1e-1, 3.16e-1, 1.0, 3.16]
    esc = inv.select_lambda_chi2_target(
        g_observed=caso_grav["g"], y_c=caso_grav["y_c"], forward_model=caso_grav["fwd"],
        sensor_coords=caso_grav["S"], x_c=caso_grav["x_c"], z_c=caso_grav["z_c"],
        lambda_candidates=candidatos, chi2_target=1.0, alpha_spatial=ALPHA,
        noise_floor=caso_grav["nf"], noise_pct=0.02)
    lam = float(esc["lambda_selected"])
    prometido = float(esc["chi2_achieved"])

    meta: dict = {}
    with _perillas_fijas():
        inv.solve_inversion_lsqr(
            caso_grav["g"], None, caso_grav["y_c"], lambda_mag=lam, alpha_spatial=ALPHA,
            forward_model=caso_grav["fwd"], sensor_coords=caso_grav["S"],
            x_c=caso_grav["x_c"], z_c=caso_grav["z_c"],
            density_min=-1e6, density_max=1e6,          # box abierto: aisla el funcional
            noise_floor=caso_grav["nf"], noise_pct=0.02, solver_meta=meta,
            prune_observable_domain=True, regularization_norm="L2",
            detect_outliers=False)
    real = float(meta["chi2_final"])

    ratio = real / max(prometido, 1e-30)
    assert ratio == pytest.approx(1.0, rel=2e-2), (
        f"el escaner de lambda volvio a escanear un funcional distinto del que el "
        f"solver resuelve: promete chi²={prometido:.4g} para lambda={lam:.3g} y el "
        f"solve consigue {real:.4g} (ratio {ratio:.3g}, esperado 1,00 +-2% con el box "
        f"abierto). Revisar que los tres bloques del trial sigan siendo los de "
        f"solve_inversion_lsqr: datos Wd.G.Ws, suavidad lambda_sp.L.Ws SIN w_reg, y "
        f"smallness IDENTIDAD en m~ con lambda_eff = lambda*sqrt(n/256)."
    )


def test_el_escaner_de_lambda_acepta_el_sigma_del_llamador():
    """El sigma del escaner dejo de estar cableado.

    chi² es `sum((r/sigma)^2)/n`: comparar dos chi² calculados con sigmas distintos
    no mide el funcional, mide el sigma. El escaner llamaba a `_sigma_adaptive` sin
    parametros — la otra mitad del diagnostico que el propio codigo de produccion
    habia escrito sobre el ("column scaling viejo + sigma adaptivo hardcodeado").
    """
    import inspect
    params = inspect.signature(GravimetryInversion.select_lambda_chi2_target).parameters
    for p in ("noise_floor", "noise_pct", "detect_outliers"):
        assert p in params, (
            f"`select_lambda_chi2_target` perdio el parametro {p!r}: su chi² vuelve a "
            f"calcularse con un sigma que el llamador no controla, y deja de ser "
            f"comparable con el del solve."
        )
    # Y el default sigue siendo el centinela historico: quien no lo pase obtiene el
    # sigma adaptativo de antes, sin cambio de comportamiento.
    assert params["noise_floor"].default == 0.02
    assert params["noise_pct"].default == 0.02


# ══════════════════════════════════════════════════════════════════════════════
# 4. La red de byte-identidad existe, cubre y puede ponerse roja
# ══════════════════════════════════════════════════════════════════════════════

def test_la_linea_base_de_byte_identidad_existe_y_cubre_los_dos_motores():
    """Criterio (b): un solo bit de diferencia debe verse. Sin linea base, no se ve."""
    base_path = (BACKEND_ROOT / "scripts" / "validation"
                 / "fase7_byte_identity_baseline.json")
    assert base_path.is_file(), (
        "falta la linea base de byte-identidad de la Fase 7. Sin ella el criterio "
        "(b) —byte-identidad obligatoria— no es verificable: correr "
        "`python scripts/validation/fase7_byte_identity.py --freeze`."
    )
    base = json.loads(base_path.read_text(encoding="utf-8"))
    grav = {k for k in base if k.startswith("grav/")}
    mag = {k for k in base if k.startswith("mag/")}
    assert len(grav) >= 14 and len(mag) >= 14, (
        f"la linea base encogio (grav={len(grav)}, mag={len(mag)}): esta cubriendo "
        f"menos ramas de las que la extraccion toca."
    )
    con_error = [k for k, v in base.items() if str(v).startswith("ERROR::")]
    assert not con_error, (
        f"la linea base congelo casos en ERROR: {con_error}. Un caso que no corre no "
        f"defiende nada; hay que arreglar la llamada antes de congelarla."
    )
    # Las rutas A y B magneticas tienen que estar las dos: son el corazon de H-33.
    assert any("rutaA" in k for k in mag) and any("rutaB" in k for k in mag)


def test_el_nucleo_no_importa_a_los_motores():
    """El nucleo compartido no puede depender de quien lo usa.

    Un ciclo `potential_field_core -> gravimetry` convertiria la extraccion en un
    enredo con pasos extra, y ademas romperia el orden de import del paquete.
    """
    fuente = (BACKEND_ROOT / "exploration" / "potential_field_core.py").read_text(
        encoding="utf-8")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        mod = ""
        if isinstance(nodo, ast.ImportFrom):
            mod = nodo.module or ""
        elif isinstance(nodo, ast.Import):
            mod = ",".join(a.name for a in nodo.names)
        assert "gravimetry" not in mod and "magnetometry" not in mod, (
            f"potential_field_core importa un motor ({mod}): el nucleo compartido "
            f"debe ser hoja, no depender de sus consumidores."
        )
