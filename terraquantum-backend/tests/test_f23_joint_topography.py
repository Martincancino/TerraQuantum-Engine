"""
FASE 23 (plan 15-26, NUEVO-1) — La inversión conjunta recupera topografía y avisos.
====================================================================================

**El defecto.** La Fase 1 cerró H-27 —la caída silenciosa a topografía plana llega al
usuario— en dos de las tres rutas. La que quedó fuera es la conjunta, que es justo la
que más diferencia al producto de una hoja de cálculo. Y era peor que «le falta el canal
de avisos»: `services/joint_inversion.py` pasaba `topography_elevations=None` **fijo** a
los dos motores, así que la columna de cota del CSV **no tocaba la física**.

**Medido antes de corregirlo** (ladera de 240 m de desnivel, malla 8×8×8 de 60 m):

  * la misma corrida con y sin `sensor_elevations_masl` devolvía el modelo **idéntico
    bit a bit** — huella `f1c661a942a511aa` en las dos;
  * el **15,93 %** del contraste de densidad recuperado caía en celdas que son **AIRE**;
  * el reporte no traía `topography_used`, `topography_degraded` ni `warnings`, así que
    el aviso no podía llegar a ninguna pantalla porque no existía.

Cablear sólo `topography_run_warnings` habría sido un gate **decorativo**: ese aviso sólo
se emite en `flat_fallback`, un estado que una ruta que nunca intenta interpolar no puede
alcanzar. Por eso esta fase hace las dos cosas —usar la topografía y declararla— y por eso
estos tests miden que la topografía **cambia el modelo**, no sólo que aparece un texto.

Los tres eslabones que exige la pregunta 2 de la plantilla de gate:
  1. **emisión** — `report["warnings"]`, `topography_used`, `topography_degraded`;
  2. **respuesta** — el `report.json` persistido por `write_run_report_snapshot`, que es
     lo que sirve `GET /projects/{id}/runs/{run}`;
  3. **componente montado** — `lib/terraquantum/runWarnings.ts::extractRunWarnings` lee
     `report.warnings[]` (y `report.technicalSummary.warnings[]`) y lo pinta en
     `Exploration3DView` y `DatosView`. Es genérico por corrida, no por motor: el
     contrato que consume se afirma aquí (test_contrato_de_avisos_*), y por eso esta
     fase es backend puro y no toca un solo `.tsx`.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import (
    TOPOGRAPHY_FLAT_FALLBACK_WARNING,
    run_geophysics_inversion,
)
from services.joint_inversion import run_joint_inversion

# Malla mínima: estos tests afirman CONTRATO y GEOMETRÍA, no calidad de recuperación.
NX, NY, NZ, BLOCK = 6, 6, 6, 20.0
RELIEVE_M = 60.0                      # 3 celdas de desnivel → hay aire de verdad
INC, DEC, B0 = -30.0, 2.0, 23500.0


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _malla():
    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = ix.flatten(order="F"); iy = iy.flatten(order="F"); iz = iz.flatten(order="F")
    return (ix * BLOCK + BLOCK / 2.0), (iy * BLOCK + BLOCK / 2.0), (iz * BLOCK + BLOCK / 2.0)


def _elevaciones(x):
    """Ladera: sube RELIEVE_M a lo largo del Este. Cota absoluta en msnm."""
    frac = (np.asarray(x, dtype=float) - BLOCK / 2.0) / max((NX - 1) * BLOCK, 1e-9)
    return 1000.0 + RELIEVE_M * np.clip(frac, 0.0, 1.0)


def superficie_y_aire():
    """Profundidad de superficie por columna y máscara de aire.

    Sale de las MISMAS dos funciones que usa producción
    (`prepare_topography_from_elevations` + `active_cells_from_topography`) y no de una
    copia analítica, por una razón medida: con 60 m de relieve sobre celdas de 20 m hay
    empates exactos entre el techo del vóxel y la profundidad del terreno, y el criterio
    `>=` los resuelve por el último bit de la interpolación — la copia analítica contaba
    66 celdas de aire donde el motor cuenta 67. Una copia así no mide la topografía: mide
    el redondeo. Lo que estos tests afirman es lo que el motor HACE con esa superficie
    (que ninguna celda de aire salga en el bloque, que `n_air` deje de mentir), no la
    superficie misma — de esa se ocupan los tests de la Fase 1 y
    `test_las_tres_rutas_hablan_el_mismo_vocabulario`.
    """
    from exploration.potential_field_core import active_cells_from_topography
    from services.geo_utils import prepare_topography_from_elevations

    x_c, y_c, z_c = _malla()
    sensores = _sensores()
    superficie, estado, _meta = prepare_topography_from_elevations(
        [float(v) for v in _elevaciones(sensores[:, 0])],
        len(sensores),
        sensores[:, [0, 2]],
        np.column_stack([x_c, z_c]),
    )
    assert estado.startswith("from_sensor_elevations_masl"), estado
    _topo, activas, _n = active_cells_from_topography(
        y_c, float(BLOCK), NX * NY * NZ, superficie,
    )
    return superficie, ~activas


def _sensores():
    sx = np.linspace(BLOCK / 2.0, (NX - 0.5) * BLOCK, 4)
    sz = np.linspace(BLOCK / 2.0, (NZ - 0.5) * BLOCK, 4)
    SX, SZ = np.meshgrid(sx, sz)
    return np.column_stack([SX.ravel(), np.zeros(SX.size), SZ.ravel()])


def joint_input(*, con_elevaciones: bool, run_id: str | None = None,
                **overrides) -> GeophysicsInvertInput:
    """Input conjunto con señal REAL en las dos físicas (el motor exige g≠0 y TMI≠0)."""
    from exploration.gravimetry import GravimetryForward
    from exploration.magnetometry import MagnetometryForward

    x_c, y_c, z_c = _malla()
    sensores = _sensores()
    # Superficie ANALÍTICA — sólo para colocar el cuerpo bajo tierra, donde un empate
    # de un bit no importa. No puede salir de `superficie_y_aire()`: el test del
    # fallback H-27 rompe a propósito la interpolación, y armar la ENTRADA no debe
    # depender de la función que ese test está saboteando.
    max_elev = float(_elevaciones(sensores[:, 0]).max())
    bajo_tierra = (y_c - BLOCK / 2.0) >= (max_elev - _elevaciones(x_c))

    # Cuerpo compacto bajo el terreno, centrado en la malla.
    r2 = ((x_c - NX * BLOCK / 2) ** 2 + (y_c - NY * BLOCK * 0.6) ** 2
          + (z_c - NZ * BLOCK / 2) ** 2)
    dentro = (r2 <= (1.4 * BLOCK) ** 2) & bajo_tierra
    contraste = np.where(dentro, 0.9, 0.0)
    susc = np.where(dentro, 0.4, 0.0)

    cutoff = float((NX + NZ) * BLOCK)
    kg = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=cutoff).build_sparse_kernel(
        x_c, y_c, z_c, sensores)
    km = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=cutoff,
                             inclination_deg=INC, declination_deg=DEC,
                             field_intensity_nt=B0).build_sparse_kernel(
        x_c, y_c, z_c, sensores)
    g_obs = kg @ contraste
    tmi_obs = km @ susc

    params = GeophysicsInvertInput(
        project_id="pytest_f23",
        run_id=run_id or f"f23_{uuid.uuid4().hex[:8]}",
        depth=int(NY * BLOCK), nir=83, fe=79,
        region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BLOCK), cutoff_radius=cutoff,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": float(s[1]), "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensores, g_obs)
        ],
        magnetic_nt=[float(v) for v in tmi_obs],
        inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0,
        susc_min=0.0, susc_max=1.0, density_min=2.6, density_max=4.2,
        joint_max_iter=2,
    )
    update = dict(overrides)
    if con_elevaciones:
        update["sensor_elevations_masl"] = [
            float(v) for v in _elevaciones(sensores[:, 0])
        ]
    return params.model_copy(update=update) if update else params


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — cada inversión conjunta cuesta segundos; se corren una vez por módulo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def corrida_plana():
    return run_joint_inversion(joint_input(con_elevaciones=False, run_id="f23_plana"))


@pytest.fixture(scope="module")
def corrida_con_topografia():
    return run_joint_inversion(joint_input(con_elevaciones=True, run_id="f23_topo"))


@pytest.fixture
def interpolacion_rota(monkeypatch):
    """Fuerza el fallback H-27: la interpolación de superficie levanta excepción."""
    import services.geo_utils as geo_utils

    def _boom(*_a, **_k):
        raise RuntimeError("fallo sintético de interpolación de superficie")

    monkeypatch.setattr(geo_utils, "interpolate_surface_depths", _boom)


def _voxel_index(v):
    ix = int(round((v["x_m"] - BLOCK / 2) / BLOCK))
    iy = int(round((v["y_m"] - BLOCK / 2) / BLOCK))
    iz = int(round((v["z_m"] - BLOCK / 2) / BLOCK))
    return ix + NX * iy + NX * NY * iz


# ═════════════════════════════════════════════════════════════════════════════
# 1. La topografía LLEGA a la física — el corazón de la fase
# ═════════════════════════════════════════════════════════════════════════════

def test_la_topografia_cambia_el_modelo(corrida_plana, corrida_con_topografia):
    """El gate anti-decorativo: si las elevaciones vuelven a ser inertes, esto falla.

    Antes de la Fase 23 los dos modelos salían IDÉNTICOS bit a bit — ése era el defecto,
    no una diferencia de matiz.
    """
    plana = {(_voxel_index(v), round(v["density_t_m3"], 9)) for v in corrida_plana["voxels"]}
    topo = {(_voxel_index(v), round(v["density_t_m3"], 9))
            for v in corrida_con_topografia["voxels"]}
    assert plana != topo, (
        "El modelo conjunto es idéntico con y sin `sensor_elevations_masl`: la topografía "
        "volvió a ser inerte."
    )


def test_ningun_voxel_del_bloque_queda_sobre_el_terreno(corrida_con_topografia):
    """Con topografía no puede salir masa en el aire. Antes salía el 15,93 % del contraste."""
    _superficie, aire = superficie_y_aire()
    assert aire.sum() > 0, "La geometría de prueba debe tener celdas de aire de verdad."
    en_el_aire = [v for v in corrida_con_topografia["voxels"] if aire[_voxel_index(v)]]
    assert not en_el_aire, (
        f"{len(en_el_aire)} vóxeles del bloque conjunto están SOBRE el terreno."
    )


def test_sin_topografia_el_modelo_si_pone_masa_en_el_aire(corrida_plana):
    """El caso de referencia no es trivial: sin topografía la masa en el aire existe.

    Sin este test, el anterior podría pasar por una geometría en la que nunca hay masa
    arriba — es decir, midiendo nada.
    """
    _superficie, aire = superficie_y_aire()
    en_el_aire = [v for v in corrida_plana["voxels"] if aire[_voxel_index(v)]]
    assert en_el_aire, (
        "La geometría de prueba no distingue los dos casos: revisar el relieve o el cuerpo."
    )


def test_la_malla_declara_cuantas_celdas_son_terreno(corrida_plana, corrida_con_topografia):
    """`mesh.n_active` contaba TODAS las celdas del core, aire incluido."""
    _superficie, aire = superficie_y_aire()
    n_total = NX * NY * NZ
    m_plana = corrida_plana["report"]["mesh"]
    m_topo = corrida_con_topografia["report"]["mesh"]

    assert m_plana["n_active"] == n_total and m_plana["n_air"] == 0
    assert m_topo["n_air"] == int(aire.sum()) > 0
    assert m_topo["n_active"] == n_total - int(aire.sum())
    assert m_topo["topography"].startswith("from_sensor_elevations_masl")
    assert m_plana["topography"] == "flat"


def test_la_mixtura_petrofisica_no_se_ajusta_sobre_aire(monkeypatch):
    """PGI + topografía: la GMM 2D se bootstrapea sólo con celdas de terreno.

    El aire entraría como un cúmulo enorme en (base_density, 0) y se llevaría una de las
    K clases. El reporte declara sobre cuántas celdas se ajustó.

    Y además **fuerza la iteración k=2**, que es la única que ejercita los bloques de
    acoplamiento PGI: con la parada temprana por defecto este sintético corta en k=1 y
    el recorte de las referencias PGI al espacio del solver no llegaba a ejecutarse —
    un gate que no pasa por el código que dice defender no defiende nada.
    """
    import services.joint_inversion as ji

    monkeypatch.setattr(ji, "_E_ABS_TOL", -1.0)
    monkeypatch.setattr(ji, "_DELTA_TOL", 0.0)
    monkeypatch.setattr(ji, "_E_REL_TOL", 0.0)
    _superficie, aire = superficie_y_aire()
    res = run_joint_inversion(joint_input(
        con_elevaciones=True, run_id="f23_pgi",
        joint_coupling_mode="pgi+cross", joint_pgi_n_classes=2,
    ))
    coupling = res["report"]["coupling"]
    assert coupling["use_pgi"] is True, coupling["pgi_disabled_reason"]
    assert coupling["pgi_bootstrap_cells"] == NX * NY * NZ - int(aire.sum())
    # k=2 corrió con PGI activo: los bloques y las referencias PGI pasaron por el
    # recorte al espacio del solver (aire → observables) sin romper la conformabilidad.
    historia = res["report"]["convergence_history"]
    assert any(h.get("pgi_active") for h in historia[1:]), historia
    # Y el acoplamiento estructural también se aplicó en la misma iteración.
    assert any(float(h.get("lambda_cross") or 0.0) > 0.0 for h in historia[1:]), historia


def test_el_acoplamiento_estructural_conforma_con_la_topografia(monkeypatch):
    """cross-gradient + topografía: el bloque tiene que conformar con el espacio del solver.

    **Este test existe porque el gate era ciego aquí.** Sin forzar la iteración, este
    sintético converge en k=1 — donde el acoplamiento está apagado por diseño (warm-up) —
    y el bloque cross-gradient **nunca se construye**: dos mutaciones que rompían su
    recorte al espacio del solver ESCAPARON en la primera campaña. Un gate que no pasa
    por el código que dice defender no defiende nada.
    """
    import services.joint_inversion as ji

    monkeypatch.setattr(ji, "_E_ABS_TOL", -1.0)
    monkeypatch.setattr(ji, "_DELTA_TOL", 0.0)
    monkeypatch.setattr(ji, "_E_REL_TOL", 0.0)
    _superficie, aire = superficie_y_aire()
    res = run_joint_inversion(joint_input(
        con_elevaciones=True, run_id=f"f23_cross_{uuid.uuid4().hex[:6]}",
    ))
    report = res["report"]
    assert report["coupling"]["use_cross_gradient"] is True
    historia = report["convergence_history"]
    assert any(float(h.get("lambda_cross") or 0.0) > 0.0 for h in historia[1:]), historia
    assert report["mesh"]["n_air"] == int(aire.sum()) > 0
    assert not [v for v in res["voxels"] if aire[_voxel_index(v)]]


def test_el_aire_nunca_llega_con_contraste_al_bloque(corrida_con_topografia):
    """El invariante que el filtro de aire protege, publicado en vez de supuesto."""
    assert corrida_con_topografia["report"]["mesh"]["n_air_cells_filtered"] == 0


def test_con_padding_la_mascara_de_aire_viaja_con_el_modelo():
    """Con `joint_padding` el modelo se reduce al core al final — y la máscara también.

    Si la máscara no se redujera con él, el bloque 3D dejaría de saber cuál de sus celdas
    es terreno: o revienta por longitud, o marca como roca lo que es cielo. Es la única
    rama donde `_active_out` es distinto de `_active_cells`, y sin este caso ninguna
    mutación sobre ella se caza.
    """
    _superficie, aire = superficie_y_aire()
    res = run_joint_inversion(joint_input(
        con_elevaciones=True, run_id=f"f23_pad_{uuid.uuid4().hex[:6]}",
        joint_padding=True, joint_n_pad=2,
    ))
    malla = res["report"]["mesh"]
    assert malla["padding"]["active"] is True
    assert malla["n_air"] == int(aire.sum()) > 0
    assert malla["n_active"] == NX * NY * NZ - int(aire.sum())
    en_el_aire = [v for v in res["voxels"] if aire[_voxel_index(v)]]
    assert not en_el_aire, f"{len(en_el_aire)} vóxeles sobre el terreno con padding"


# ═════════════════════════════════════════════════════════════════════════════
# 2. La degradación se DECLARA — H-27 en la tercera ruta
# ═════════════════════════════════════════════════════════════════════════════

def test_flat_fallback_llega_a_warnings(interpolacion_rota):
    """La interpolación falla, la corrida sigue con terreno plano y lo DICE."""
    res = run_joint_inversion(joint_input(con_elevaciones=True, run_id="f23_fallback"))
    report = res["report"]
    assert report["topography_used"] == "flat_fallback"
    assert report["topography_degraded"] is True
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING in report["warnings"]


def test_topografia_sana_no_genera_ruido(corrida_con_topografia):
    """El aviso es señal, no decoración: sin degradación no aparece."""
    report = corrida_con_topografia["report"]
    assert report["topography_used"].startswith("from_sensor_elevations_masl")
    assert report["topography_degraded"] is False
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING not in report["warnings"]


def test_survey_sin_cota_no_es_una_degradacion(corrida_plana):
    """`flat` es una entrada declarada por el usuario, no un fallo del motor."""
    report = corrida_plana["report"]
    assert report["topography_used"] == "flat"
    assert report["topography_degraded"] is False
    assert report["warnings"] == []


def test_el_aviso_de_contraste_efectivo_tambien_viaja():
    """Paridad con la Fase 20: la conjunta invierte densidad con los mismos bounds.

    `density_min` > `base_density` deja la roca caja fuera de la caja permitida; el aviso
    viaja por el MISMO canal que el de topografía.
    """
    res = run_joint_inversion(joint_input(
        con_elevaciones=False, run_id="f23_bound",
        density_min=4.5, density_max=5.5, base_density=2.6,
    ))
    avisos = res["report"]["warnings"]
    assert any("Contraste efectivo INCOHERENTE" in w for w in avisos), avisos


# ═════════════════════════════════════════════════════════════════════════════
# 3. Los tres eslabones: emisión → respuesta → componente
# ═════════════════════════════════════════════════════════════════════════════

def test_contrato_de_avisos_identico_al_de_la_ruta_gravimetrica(corrida_plana):
    """El frontend lee `report.warnings[]` sin preguntar qué motor corrió.

    `extractRunWarnings` (lib/terraquantum/runWarnings.ts) filtra por `typeof === "string"`
    y descarta vacíos: si la conjunta publicara otra forma, el banner se quedaría mudo sin
    error visible. Se afirma la forma, contra la ruta que ya funciona.
    """
    joint = corrida_plana["report"]
    for clave in ("topography_used", "topography_degraded", "warnings"):
        assert clave in joint, f"la conjunta no publica `{clave}`"
    assert isinstance(joint["topography_used"], str)
    assert isinstance(joint["topography_degraded"], bool)
    assert isinstance(joint["warnings"], list)
    assert all(isinstance(w, str) and w.strip() for w in joint["warnings"])


def test_el_reporte_persistido_lleva_los_avisos(interpolacion_rota):
    """Eslabón 2: lo que sirve `GET /projects/{id}/runs/{run}` es el report.json del disco."""
    from services.block_model_store import get_run_block_model_reference

    params = joint_input(con_elevaciones=True, run_id=f"f23_disco_{uuid.uuid4().hex[:6]}")
    run_joint_inversion(params)
    ruta = get_run_block_model_reference(
        project_id=params.project_id, run_id=params.run_id
    ).path.parent / "report.json"
    assert ruta.exists(), f"no se persistió el reporte en {ruta}"
    persistido = json.loads(ruta.read_text(encoding="utf-8"))
    assert persistido["topography_degraded"] is True
    assert TOPOGRAPHY_FLAT_FALLBACK_WARNING in persistido["warnings"]


def test_las_tres_rutas_hablan_el_mismo_vocabulario():
    """Gravimétrica y conjunta declaran el MISMO estado para la MISMA entrada.

    La divergencia entre rutas es exactamente lo que produjo NUEVO-1: dos copias de la
    regla y un olvido. Aquí se ata: si una ruta cambia el vocabulario, esto falla.
    """
    conjunta = run_joint_inversion(
        joint_input(con_elevaciones=True, run_id=f"f23_voc_{uuid.uuid4().hex[:6]}")
    )["report"]
    gravimetrica = run_geophysics_inversion(
        joint_input(con_elevaciones=True, run_id=f"f23_voc_g_{uuid.uuid4().hex[:6]}",
                    magnetic_nt=None)   # lista de ceros = lista NO vacía ⇒ iría al motor magnético
    )["report"]
    assert conjunta["topography_used"] == gravimetrica["topography_used"]
    assert conjunta["topography_used"].startswith("from_sensor_elevations_masl")


# ═════════════════════════════════════════════════════════════════════════════
# 4. El motor deja de aceptar un kernel que no conforma
# ═════════════════════════════════════════════════════════════════════════════

def test_kernel_cacheado_que_no_conforma_es_rechazado():
    """Un kernel de malla COMPLETA en una corrida con topografía no es un error de forma
    detectable río abajo: empareja la columna k con la celda k equivocada y devuelve un
    modelo desplazado con cara de bueno. El motor magnético ya lo comprobaba; ahora los dos.
    """
    from exploration.gravimetry import GravimetryForward, GravimetryInversion

    x_c, y_c, z_c = _malla()
    superficie, aire = superficie_y_aire()
    sensores = _sensores()
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=(NX + NZ) * BLOCK)
    kernel_malla_completa = fwd.build_sparse_kernel(x_c, y_c, z_c, sensores)
    inv = GravimetryInversion(NX, NY, NZ, BLOCK)

    # Observaciones con variación lateral: un vector constante lo rechaza la validación
    # de entrada ANTES de llegar al kernel, y el test mediría otra cosa.
    g_obs = kernel_malla_completa @ np.where(
        ((x_c - NX * BLOCK / 2) ** 2 + (y_c - NY * BLOCK * 0.6) ** 2
         + (z_c - NZ * BLOCK / 2) ** 2) <= (1.4 * BLOCK) ** 2, 0.9, 0.0)
    with pytest.raises(ValueError, match="no coincide con"):
        inv.solve_inversion_lsqr(
            g_obs, kernel_malla_completa, y_c,
            lambda_mag=1e-3, alpha_spatial=1.0,
            topography_elevations=superficie,       # ⇒ n_active < total_voxels
            sensor_coords=sensores, x_c=x_c, z_c=z_c, forward_model=fwd,
        )
    assert aire.sum() > 0
