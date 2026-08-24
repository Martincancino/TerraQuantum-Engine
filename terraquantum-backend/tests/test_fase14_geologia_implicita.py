"""FASE 14 (auditoría 06 §10) — El modelamiento implícito llega al usuario, y lo
que llega dice la verdad sobre sí mismo.

La fase pide cablear `exploration/implicit_modeling.py` **como restricción
geométrica de la inversión**. Al medir antes de ejecutar salió que el motor ya
estaba cableado desde la Fase 7.2 (`_build_implicit_geology_reference`) y que lo
que faltaba era **el interruptor**: los contactos litológicos ya viajaban en el
bloque `#BOREHOLES` del paquete, pero `implicit_geology` no estaba en la allowlist
de `csv_package_service._CONFIG_DEFAULTS`, así que un `config_json` que lo pidiera
se descartaba **en silencio**.

Este fichero fija lo que la fase MIDIÓ, no lo que la fase se propuso. Cada test
pincha un hecho comprobado con números; ninguno afirma que el prior mejore nada
—eso lo responde `scripts/validation/f14_implicit_geology_experiment.py`, y su respuesta
está escrita en `docs/06_AUDITORIA_TECNICA_INTEGRAL.md` §FASE 14—.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from fastapi import HTTPException

from exploration.gravimetry import GravimetryInversion
from exploration.implicit_modeling import (
    ImplicitGeologicalModel,
    build_spatial_prior_from_implicit,
)
from schemas.geophysics_schema import (
    BoreholeInterval,
    GeophysicsInvertInput,
    ImplicitGeologyParams,
)
from services.geophysics_service import _build_implicit_geology_reference


# ── Grilla y sondajes de apoyo ───────────────────────────────────────────────
NX, NY, NZ, BS = 20, 20, 20, 30.0
BASE_DENSITY = 2.6
TARGET_DENSITY = 3.6
CX, CZ = 10 * BS, 10 * BS


def _centros():
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    return ((ix.ravel() + 0.5) * BS, (iy.ravel() + 0.5) * BS, (iz.ravel() + 0.5) * BS)


def _params(boreholes=None, geo=None, **extra):
    return GeophysicsInvertInput(
        project_id="p", run_id="r", depth=int(NY * BS), nir=0, fe=0, region="test",
        nx=8, ny=8, nz=8, block_size=int(BS), cutoff_radius=4000,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[{"x_m": float(i * BS), "y_m": 0.0, "z_m": float((i % 4) * BS),
                       "g": 1e-6} for i in range(12)],
        boreholes=boreholes, implicit_geology=geo, **extra,
    )


def _pozo(x, z, tramos):
    return [BoreholeInterval(x_m=x, z_m=z, y_from_m=a, y_to_m=b, lithology=l)
            for a, b, l in tramos]


# ════════════════════════════════════════════════════════════════════════════
# 1. El hecho que gobierna TODO el cableado: m_ref entra sólo por la suavidad,
#    y la suavidad es un Laplaciano de grafo. Luego un prior constante es
#    EXACTAMENTE inerte. Todo lo demás de esta fase se deduce de aquí.
# ════════════════════════════════════════════════════════════════════════════
def test_el_laplaciano_aniquila_las_constantes_luego_un_prior_constante_no_hace_nada():
    """`L = W − D` ⇒ suma de filas 0 ⇒ `L·1 = 0` EXACTO.

    El prior implícito entra al funcional únicamente como
    `d_reg = λ_spatial · (L · m_ref)` (`exploration/gravimetry.py:2374`). Si el
    campo φ clasifica toda la malla como una sola unidad, `m_ref` es constante,
    `L·m_ref = 0` y la inversión sale **byte-idéntica** a no haber pedido prior.
    Por eso `_build_implicit_geology_reference` tiene que declararlo (`inert_no_contrast`)
    en vez de reportar `enabled: true` a secas.
    """
    inv = GravimetryInversion(nx=8, ny=6, nz=8, block_size=20.0)
    unos = np.ones(inv.total_voxels)

    L = inv._build_laplacian()
    assert np.abs(L @ unos).max() == 0.0, "malla uniforme: L·1 debe ser 0 EXACTO"
    assert np.abs(np.asarray(L.sum(axis=1)).ravel()).max() == 0.0

    hx, hy, hz = np.full(8, 20.0), np.full(6, 20.0), np.full(8, 20.0)
    L_nu = inv._build_laplacian(hx=hx, hy=hy, hz=hz)
    assert np.abs(L_nu @ unos).max() < 1e-12, "malla no-uniforme: L·1 ≈ 0"


def test_un_prior_sin_contraste_se_declara_inerte_en_vez_de_decir_enabled():
    """Si NINGÚN intervalo es de la litología objetivo, φ < 0 en toda la malla:
    el prior es constante y no puede mover nada. Se dice."""
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 200, "granite"), (200, 400, "granite")])
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    m_ref, meta = _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                    BASE_DENSITY)
    assert meta["inert_no_contrast"] is True
    assert meta["n_target_cells"] == 0
    assert np.ptp(m_ref) == 0.0, "sin contraste, m_ref es constante"
    assert any("igual que sin prior" in w for w in meta["warnings"]), meta["warnings"]


# ════════════════════════════════════════════════════════════════════════════
# 2. El hallazgo de la fase: con contactos a la MISMA profundidad el HRBF
#    degenera a su deriva polinómica — «la superficie» es un plano infinito.
# ════════════════════════════════════════════════════════════════════════════
def test_contacto_plano_degenera_el_hrbf_a_una_rampa_y_se_declara():
    """MEDIDO: 1 sondaje vertical con contacto a 90 m ⇒ los pesos RBF salen ~0 y
    φ = 2·ỹ (rampa lineal en profundidad). Consecuencia: φ ≥ 0 en el **85 %** de
    la malla, hasta 403 m del único collar, sobre una malla cuya semidiagonal es
    424 m. No es una superficie interpolada: es un plano extrapolado sin límite.
    """
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 180, "kimberlite")])
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    _m_ref, meta = _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                     BASE_DENSITY)

    assert meta["degenerate_planar_field"] is True
    assert meta["n_boreholes"] == 1
    # El número exacto: 17 de 20 capas en y (y ≥ 90) × 20 × 20.
    assert meta["n_target_cells"] == 6800
    assert meta["target_volume_fraction"] == pytest.approx(0.85, abs=1e-9)
    assert meta["extrapolation_max_m"] > 400.0
    assert any("PLANO" in w for w in meta["warnings"]), meta["warnings"]
    assert any("extrapola" in w for w in meta["warnings"]), meta["warnings"]


def test_la_degeneracion_es_una_propiedad_del_interpolante_no_del_servicio():
    """`degenerado_a_plano` vive en `HermiteRBFImplicit` porque es un hecho del
    interpolante. Se comprueba en los dos sentidos sobre datos crudos, sin pasar
    por el servicio: si el detector dijera siempre lo mismo, no mediría nada."""
    import numpy as _np

    # Contactos a la MISMA profundidad ⇒ un polinomio de grado 1 los satisface.
    plano = ImplicitGeologicalModel.from_boreholes(
        _pozo(CX, CZ, [(0, 90, "granite"), (90, 180, "kimberlite")])
        + _pozo(CX + 90, CZ, [(0, 90, "granite"), (90, 180, "kimberlite")]),
        ["kimberlite"],
    )
    assert plano.field.degenerado_a_plano is True
    # …y el campo es una rampa: sólo sobrevive el término lineal en profundidad.
    assert _np.abs(plano.field._alpha).max() < 1e-8
    assert abs(plano.field._poly[2]) > 1.0

    # Contactos a profundidades DISTINTAS ⇒ hay curvatura que interpolar.
    inclinado = ImplicitGeologicalModel.from_boreholes(
        _pozo(CX - 90, CZ, [(0, 60, "granite"), (60, 200, "kimberlite")])
        + _pozo(CX, CZ, [(0, 120, "granite"), (120, 260, "kimberlite")])
        + _pozo(CX + 90, CZ, [(0, 180, "granite"), (180, 320, "kimberlite")]),
        ["kimberlite"],
    )
    assert inclinado.field.degenerado_a_plano is False


def test_tres_sondajes_al_mismo_nivel_no_aportan_mas_que_uno():
    """El corolario incómodo, medido: si el contacto está a la misma cota en los
    tres pozos, φ es IDÉNTICO al de un solo pozo. Triplicar el dato no cambia la
    restricción — y el reporte tiene que poder decirlo."""
    import numpy as _np

    x_c, y_c, z_c = _centros()
    pts = _np.column_stack([x_c, y_c, z_c])
    uno = ImplicitGeologicalModel.from_boreholes(
        _pozo(CX, CZ, [(0, 90, "granite"), (90, 180, "kimberlite")]), ["kimberlite"])
    tres = ImplicitGeologicalModel.from_boreholes(
        _pozo(CX, CZ, [(0, 90, "granite"), (90, 180, "kimberlite")])
        + _pozo(CX + 90, CZ, [(0, 90, "granite"), (90, 180, "kimberlite")])
        + _pozo(CX, CZ + 90, [(0, 90, "granite"), (90, 180, "kimberlite")]),
        ["kimberlite"])
    assert tres.n_value_points == 3 * uno.n_value_points
    assert _np.abs(uno.field.evaluate(pts) - tres.field.evaluate(pts)).max() < 1e-9


def test_el_campo_deja_de_degenerar_cuando_los_contactos_fijan_curvatura():
    """Control del test de arriba: si el detector marcase SIEMPRE «degenerado» no
    estaría midiendo nada. Con un cuerpo acotado arriba y abajo la RBF se activa."""
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite"), (150, 400, "granite")])
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    _m_ref, meta = _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                     BASE_DENSITY)
    assert meta["degenerate_planar_field"] is False
    assert meta["n_target_cells"] < 6800
    assert not any("PLANO" in w for w in meta["warnings"])


# ════════════════════════════════════════════════════════════════════════════
# 3. Las perillas que NO actúan se declaran en vez de disimularse.
# ════════════════════════════════════════════════════════════════════════════
def test_el_sigma_declarado_del_prior_no_pesa_y_el_reporte_lo_dice():
    """`build_spatial_prior_from_implicit` calcula un σ por celda, pero el servicio
    sólo consume `prior.mean`: `target_std_t_m3`/`host_std_t_m3` son perillas de API
    que no entran al funcional. Se declara (`declared_std_is_inert`) y además se
    comprueba que efectivamente no cambian el m_ref."""
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite"), (150, 400, "granite")])

    def _m(**kw):
        geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                    target_density_t_m3=TARGET_DENSITY, **kw)
        return _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                 BASE_DENSITY)

    m_a, meta_a = _m(target_std_t_m3=0.3, host_std_t_m3=0.5)
    m_b, _ = _m(target_std_t_m3=2.9, host_std_t_m3=4.1)
    assert meta_a["declared_std_is_inert"] is True
    assert np.array_equal(m_a, m_b), "cambiar σ no cambió nada, como estaba previsto"


def test_solo_actua_la_DIFERENCIA_de_densidades_no_su_valor_absoluto():
    """Corolario de `L·1 = 0`: desplazar objetivo y caja por igual deja el m_ref
    desplazado por una constante ⇒ mismo `L·m_ref` ⇒ misma inversión. Las dos
    perillas de densidad no son independientes; sólo su resta actúa."""
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite"), (150, 400, "granite")])
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BS)
    L = inv._build_laplacian()

    def _m(target, host):
        geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                    target_density_t_m3=target, host_density_t_m3=host)
        m, _ = _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                 BASE_DENSITY)
        return m

    m1 = _m(3.6, 2.6)   # Δ = 1.0
    m2 = _m(4.1, 3.1)   # Δ = 1.0, ambos +0.5
    assert np.allclose(m2 - m1, 0.5), "el desplazamiento es una constante"
    assert np.abs(L @ m1 - L @ m2).max() < 1e-9, "y la constante no llega al funcional"


# ════════════════════════════════════════════════════════════════════════════
# 4. La colisión medida: el prior de profundidad puede pisar al geológico.
# ════════════════════════════════════════════════════════════════════════════
def test_avisa_cuando_el_prior_de_profundidad_va_a_pisar_al_geologico():
    """Un intervalo con litología pero SIN densidad medida —que es justo el input
    que `implicit_geology` exige— no entra al array de anclaje. Entonces
    `enable_depth_prior` encuentra `boreholes_arr is None` y fuerza
    `anchor_mode="hard"` (`geophysics_service.py:2994`), que fija celdas a
    `base_density` y las ELIMINA del sistema. Antes no avisaba nadie."""
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite"), (150, 400, "granite")])
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    _m, meta = _build_implicit_geology_reference(
        _params(bhs, geo, enable_depth_prior=True), x_c, y_c, z_c, BASE_DENSITY)
    assert any("prior de profundidad" in w for w in meta["warnings"]), meta["warnings"]


def test_control_sin_depth_prior_no_hay_aviso_de_colision():
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite"), (150, 400, "granite")])
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    _m, meta = _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                 BASE_DENSITY)
    assert not any("prior de profundidad" in w for w in meta["warnings"])


# ════════════════════════════════════════════════════════════════════════════
# 5. EL INTERRUPTOR: lo que la fase vino a abrir.
# ════════════════════════════════════════════════════════════════════════════
def test_implicit_geology_sobrevive_la_allowlist_del_paquete():
    """`merge_config` sólo conserva claves conocidas. Antes de la Fase 14
    `implicit_geology` NO estaba en `_CONFIG_DEFAULTS`, así que un paquete que lo
    pidiera lo perdía **sin decir nada**. Éste es el test que impide que vuelva."""
    from services.csv_package_service import _CONFIG_DEFAULTS, merge_config

    assert "implicit_geology" in _CONFIG_DEFAULTS
    assert _CONFIG_DEFAULTS["implicit_geology"] is None, "OFF por defecto = byte-idéntico"

    pedido = {"enabled": True, "target_lithologies": ["kimberlite"],
              "target_density_t_m3": 3.6}
    assert merge_config({"implicit_geology": pedido})["implicit_geology"] == pedido
    assert merge_config(None)["implicit_geology"] is None


def test_las_dos_rutas_de_inversion_aceptan_el_prior_geologico():
    """El camino dorado (paquete) y el directo (`/invert`, que es el que usa la API
    de scripting de la Fase 11) tienen que poder activarlo los dos."""
    import inspect
    from api import gravity_import_api as api

    fuente = inspect.getsource(api)
    assert 'cfg.get("implicit_geology")' in fuente, "el paquete no lo lee"
    assert "implicit_geology_json" in fuente, "/invert no lo acepta"
    assert fuente.count("implicit_geology=_") >= 2, (
        "ambas rutas deben pasarlo al GeophysicsInvertInput"
    )
    assert "implicit_geology_json" in inspect.signature(api._cfg_corrida).parameters


def test_un_prior_mal_formado_avisa_en_vez_de_desaparecer_en_silencio():
    """Sus vecinos (`pgi_params`, `remanence`) se descartan en silencio. Aquí no:
    devolverle al usuario una inversión SIN la geología que pidió, sin decírselo,
    es el defecto que la auditoría llama «el camino del usuario se detiene ahí».

    Se comprueba por AST y no por ventana de texto: la primera versión de este test
    miraba 1200 caracteres alrededor y **una mutación demostró que era inerte**
    —bastaba dejar el `except` mudo para que el `elif` vecino lo hiciera pasar—.
    Aquí se exige que CADA manejador de excepción que envuelve el parseo del prior
    avise, que es justo lo que la mutación rompía.
    """
    import ast
    import inspect

    from api import gravity_import_api as api

    arbol = ast.parse(inspect.getsource(api))
    manejadores = 0
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Try):
            continue
        cuerpo = ast.dump(ast.Module(body=nodo.body, type_ignores=[]))
        # Las dos rutas usan el mismo alias local; el import va dentro del try en
        # una y fuera en la otra, así que se busca por el alias, no por el import.
        if "_GeoParams" not in cuerpo:
            continue
        for handler in nodo.handlers:
            manejadores += 1
            avisa = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "append"
                and "warning" in ast.dump(n.func.value).lower()
                for n in ast.walk(ast.Module(body=handler.body, type_ignores=[]))
            )
            assert avisa, (
                "un except que descarta el prior geológico sin escribir un warning: "
                f"línea {handler.lineno}. El usuario se quedaría sin su geología y "
                "sin enterarse."
            )
    assert manejadores >= 2, (
        f"esperaba el parseo del prior en las DOS rutas (paquete y /invert); "
        f"encontré {manejadores} manejadores"
    )


def test_activarlo_sin_litologia_sigue_siendo_422_no_geologia_inventada():
    """Invariante heredado de la Fase 7.2 que la 14 NO relaja: sin contactos
    litológicos no se infiere geología, se rechaza."""
    x_c, y_c, z_c = _centros()
    geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                target_density_t_m3=TARGET_DENSITY)
    with pytest.raises(HTTPException) as exc:
        _build_implicit_geology_reference(_params(None, geo), x_c, y_c, z_c, BASE_DENSITY)
    assert exc.value.status_code == 422


def test_apagado_no_toca_nada():
    """`None` y `enabled=False` devuelven `(None, None)`: la inversión histórica
    queda byte-idéntica."""
    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite")])
    assert _build_implicit_geology_reference(_params(bhs, None), x_c, y_c, z_c,
                                             BASE_DENSITY) == (None, None)
    geo_off = ImplicitGeologyParams(enabled=False, target_lithologies=["kimberlite"],
                                    target_density_t_m3=TARGET_DENSITY)
    assert _build_implicit_geology_reference(_params(bhs, geo_off), x_c, y_c, z_c,
                                             BASE_DENSITY) == (None, None)


# ════════════════════════════════════════════════════════════════════════════
# 6. El instrumento de medición existe y dice lo que mide.
# ════════════════════════════════════════════════════════════════════════════
def test_el_instrumento_de_medicion_existe_y_declara_su_control():
    """El criterio de aceptación de la fase es «se MIDE la mejora contra verdad
    conocida». El instrumento vive en el repo, tiene brazo de control con geología
    FALSA y declara qué métricas sobreviven a ese control."""
    import pathlib

    p = (pathlib.Path(__file__).resolve().parents[1]
         / "scripts" / "validation" / "f14_implicit_geology_experiment.py")
    assert p.exists(), "sin instrumento no hay criterio de aceptación"
    src = p.read_text(encoding="utf-8")
    assert "CONTROL_geologia_falsa" in src, "sin control, la medición no distingue"
    assert "METRICAS_QUE_DECIDEN" in src
    assert "anti-inverse-crime" in src.lower()
    assert "centroid_err_m" not in src.split("METRICAS_QUE_DECIDEN")[1].split(")")[0], (
        "el error de centroide mejora también con geología falsa: no puede decidir"
    )


# ════════════════════════════════════════════════════════════════════════════
# 7. La fase no se cierra dejando su nombre en deudas ajenas.
#    (Mismo mecanismo que la Fase 13 estrenó; aquí para la 14, que es la última
#     del plan §10 y por tanto la que no puede endosarle nada a nadie.)
# ════════════════════════════════════════════════════════════════════════════
def test_ninguna_lista_tolerada_sigue_nombrando_a_la_fase_14_como_duena():
    """Al cerrar, sus deudas heredadas o se cumplen o se devuelven CON MOTIVO.

    La Fase 14 tenía dos: `/borehole/lithology-properties` (CUMPLIDA — el
    formulario de geología implícita lee la tabla petrofísica del backend, así que
    salió de `RUTAS_SIN_UI_TOLERADAS`) y `/borehole/desurvey` (DEVUELTA — el
    modelamiento implícito consume pozos verticales, así que cablear desurvey no
    habría hecho llegar la geología a nadie).
    """
    import pathlib
    import re

    raiz = pathlib.Path(__file__).resolve().parents[1] / "tests"
    pendientes = []
    for f in sorted(raiz.glob("test_*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue
        for n, linea in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"Due[ñn]a:\s*Fase 14\b", linea):
                pendientes.append(f"{f.name}:{n}")
    assert not pendientes, (
        "Estas entradas siguen esperando a la Fase 14, que ya cerró — y es la "
        "ÚLTIMA del plan §10, así que no hay a quién endosárselas. O se arreglan, "
        "o se re-declaran diciendo por qué no le tocaban.\n  " + "\n  ".join(pendientes)
    )


def test_control_el_barrido_sabe_encontrar_una_duena_cuando_la_hay():
    """Anti-inercia: si el regex no encontrara nada, el test de arriba pasaría por
    vacuidad.

    Las muestras se COMPONEN en runtime a propósito. Escribirlas literales metía la
    cadena en este fichero, y el barrido equivalente de la Fase 13 —que recorre
    TODOS los `test_*.py`— las contaba como declaraciones reales: un test de
    control fabricaba la deuda que otro test vigilaba. Lo destapó ese test
    poniéndose rojo, no una lectura.
    """
    import re

    patron = r"Due[ñn]a:\s*Fase 14" + r"\b"   # el MISMO que usa el test de arriba
    marca = "Due" + "ña: " + "Fase "
    assert re.search(patron, marca + "14 (geología implícita).")
    assert not re.search(patron, marca + "11.")
    assert not re.search(patron, marca + "140."), "sin frontera, Fase 140 colaría"


def test_la_lista_de_rutas_toleradas_ya_no_menciona_la_tabla_petrofisica():
    """`/borehole/lithology-properties` salió de la lista porque GANÓ consumidor,
    no porque se tapara: el proxy y el formulario existen."""
    import pathlib

    from tests.test_fase9_camino_de_usuario import RUTAS_SIN_UI_TOLERADAS

    assert "/borehole/lithology-properties" not in RUTAS_SIN_UI_TOLERADAS

    web = pathlib.Path(__file__).resolve().parents[2] / "terraquantum-web"
    proxy = web / "app" / "api" / "borehole" / "lithology-properties" / "route.ts"
    assert proxy.exists(), "sin proxy no hay consumidor: la entrada tendría que volver"
    assert "/borehole/lithology-properties" in proxy.read_text(encoding="utf-8")

    form = web / "componentes" / "ImplicitGeologyForm.tsx"
    assert form.exists()
    assert "fetchLithologyProperties" in form.read_text(encoding="utf-8"), (
        "el formulario debe LEER la tabla, no traer los números duplicados en TS"
    )


# ════════════════════════════════════════════════════════════════════════════
# 8. El binding nuevo llega al solver de verdad, y apagado no toca nada.
#    (La PREGUNTA de si mejora la contesta el instrumento, no un test.)
# ════════════════════════════════════════════════════════════════════════════
def _mundo_pequeno():
    """Esfera compacta a media profundidad; malla chica para que sea un test."""
    import core.config as _cfg  # noqa: F401  (se lee dentro del solver)
    from exploration.gravimetry import GravimetryForward, GravimetryInversion

    nx, ny, nz, bs = 8, 6, 8, 20.0
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    x_c = gx.flatten(order="F") * bs + bs / 2
    y_c = gy.flatten(order="F") * bs + bs / 2
    z_c = gz.flatten(order="F") * bs + bs / 2
    r = np.sqrt((x_c - nx * bs / 2) ** 2 + (y_c - 60.0) ** 2 + (z_c - nz * bs / 2) ** 2)
    contraste = np.where(r <= 25.0, 0.6, 0.0)

    fwd = GravimetryForward(bs, bs, bs, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(np.arange(5, nx * bs, bs), np.arange(5, nz * bs, bs), indexing="ij")
    sensores = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g = fwd.build_sparse_kernel(x_c, y_c, z_c, sensores) @ contraste
    inv = GravimetryInversion(nx, ny, nz, bs)
    m_ref = np.where(y_c > 45.0, 0.6, 0.0)
    return inv, fwd, sensores, g, x_c, y_c, z_c, m_ref


def _resolver(inv, fwd, sensores, g, x_c, y_c, z_c, **kw):
    dens, _, _, _ = inv.solve_inversion_lsqr(
        g, None, y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensores, x_c=x_c, z_c=z_c, **kw
    )
    return dens - inv.base_density


@pytest.mark.slow
def test_alpha_cero_es_byte_identico_a_no_pedir_el_binding_nuevo():
    """La rama nueva no puede cambiar NADA de lo que ya corría. `geo_prior_alpha=0`
    no apila bloque, así que el sistema aumentado es el mismo array."""
    mundo = _mundo_pequeno()
    inv, fwd, sensores, g, x_c, y_c, z_c, m_ref = mundo
    sin = _resolver(inv, fwd, sensores, g, x_c, y_c, z_c, m_ref=m_ref)
    cero = _resolver(inv, fwd, sensores, g, x_c, y_c, z_c, m_ref=m_ref, geo_prior_alpha=0.0)
    assert np.array_equal(sin, cero), "alpha=0 tiene que ser byte-idéntico"


@pytest.mark.slow
def test_el_binding_de_smallness_llega_al_solver_y_mueve_el_modelo():
    """Prueba de CABLEADO, no de calidad: con alpha>0 el modelo tiene que cambiar,
    o el bloque no está entrando al sistema. Cuánto mejora —o si mejora— lo
    responde `scripts/validation/f14_implicit_geology_experiment.py`."""
    inv, fwd, sensores, g, x_c, y_c, z_c, m_ref = _mundo_pequeno()
    suave = _resolver(inv, fwd, sensores, g, x_c, y_c, z_c, m_ref=m_ref)
    small = _resolver(inv, fwd, sensores, g, x_c, y_c, z_c, m_ref=m_ref, geo_prior_alpha=1.0)
    assert np.nanmax(np.abs(small - suave)) > 1e-4, (
        "el bloque de smallness no está entrando al sistema aumentado"
    )
    # NO se afirma aquí que el resultado sea MEJOR. Se intentó y el test se puso
    # rojo: en este mundo de juguete —una esfera con un m_ref de media malla— la
    # rama de suavidad queda MÁS cerca del m_ref (0,3928 vs 0,3970 de error medio).
    # Es un recordatorio útil: la mejora medida vale para el mundo donde se midió
    # (dique inclinado, anti-inverse-crime, 25 semillas pareadas), no para
    # cualquier configuración. Un test de cableado afirma cableado.


def test_el_servicio_traduce_binding_a_peso_y_lo_dice_en_el_reporte():
    """`binding='smoothness'` ⇒ alpha 0 (comportamiento histórico);
    `binding='smallness'` ⇒ alpha = prior_weight. Y el reporte lo publica, para
    que un usuario pueda saber en qué término entró su geología."""
    from services.geophysics_service import _geo_prior_alpha

    x_c, y_c, z_c = _centros()
    bhs = _pozo(CX, CZ, [(0, 90, "granite"), (90, 150, "kimberlite"), (150, 400, "granite")])

    def _meta(**kw):
        geo = ImplicitGeologyParams(target_lithologies=["kimberlite"],
                                    target_density_t_m3=TARGET_DENSITY, **kw)
        return _build_implicit_geology_reference(_params(bhs, geo), x_c, y_c, z_c,
                                                 BASE_DENSITY)[1]

    m_small = _meta(binding="smallness", prior_weight=2.5)
    assert m_small["binding_term"] == "smallness"
    assert m_small["prior_weight"] == 2.5
    assert _geo_prior_alpha(m_small) == 2.5

    m_suave = _meta(binding="smoothness", prior_weight=2.5)
    assert m_suave["binding_term"] == "smoothness"
    assert m_suave["prior_weight"] == 0.0
    assert _geo_prior_alpha(m_suave) == 0.0, "smoothness NO puede apilar el bloque"

    # Sin prior no hay peso que aplicar (y no puede reventar).
    assert _geo_prior_alpha(None) == 0.0

    # El default del esquema es el que la medición eligió.
    assert ImplicitGeologyParams(target_lithologies=["x"],
                                 target_density_t_m3=3.0).binding == "smallness"


def test_todo_solve_que_lleva_el_prior_lleva_tambien_su_peso():
    """El acoplamiento que casi se escapa, convertido en guard.

    `m_ref` y `geo_prior_alpha` describen el MISMO prior en dos términos del
    funcional. Si un sitio pasa uno y no el otro, esa inversión corre con una
    física distinta de la de al lado — y en el DOI eso es peor que un matiz: su
    «inversión 1» ES la corrida principal (`m1 = est_density`), así que una pass-2
    con otro funcional infla el índice sin que nada avise.

    Se comprueba por AST sobre las llamadas reales, no contando cadenas.
    """
    import ast
    import inspect

    from services import geophysics_service as svc

    arbol = ast.parse(inspect.getsource(svc))
    sitios = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        claves = {kw.arg for kw in nodo.keywords if kw.arg}
        if "m_ref" not in claves:
            continue
        sitios.append((nodo.lineno, "geo_prior_alpha" in claves))

    assert sitios, "no se encontró ninguna llamada al solver con m_ref: el barrido es inerte"
    huerfanos = [ln for ln, tiene in sitios if not tiene]
    assert not huerfanos, (
        "estas llamadas pasan m_ref SIN geo_prior_alpha, así que correrían con un "
        f"funcional distinto del resto: líneas {huerfanos}"
    )
    # Las cuatro medidas al cerrar la fase: solve principal (que es también el que
    # usa el barrido de Morozov), pass-2 del IRLS compacto, y la 2ª del DOI.
    assert len(sitios) >= 3, f"esperaba al menos 3 sitios; encontré {len(sitios)}"


def test_el_barrido_de_lambda_ve_el_mismo_funcional_que_el_solve_final():
    """Morozov elige λ corriendo inversiones REALES. Si esas inversiones no
    llevaran el bloque geológico, la λ elegida sería la de otro funcional y el
    solve final la heredaría. Ambos pasan por el mismo helper, y eso es lo que
    se fija aquí: el barrido no puede coger un atajo propio."""
    import inspect

    from services import geophysics_service as svc

    fuente = inspect.getsource(svc)
    # El barrido llama a _solve_full_grid → _solve_grilla_completa, el mismo helper
    # que ejecuta la corrida principal.
    assert "_solve_full_grid" in fuente
    helper = inspect.getsource(svc._solve_grilla_completa)
    assert "m_ref=_geo_m_ref" in helper
    assert "geo_prior_alpha=" in helper, (
        "el helper compartido por el barrido de λ y la corrida principal perdió el "
        "peso del prior: la λ se elegiría con una física y se usaría con otra"
    )
