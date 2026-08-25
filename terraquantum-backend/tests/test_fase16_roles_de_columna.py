# -*- coding: utf-8 -*-
"""FASE 16 (plan 15-26) — H-F11-1: la ingesta deja de adivinar el rol de una columna.

EL DEFECTO. `_LOCAL_Y_ALIASES = {"y", "local_y", "coord_y"}` mandaba la columna
al slot `y_m`, que en la convención interna **es la profundidad**. Con la
cabecera más común del mundo —`X,Y,Z` = este, norte, cota— eso significaba que
el NORTHING pasaba a profundidad bajo superficie y la COTA pasaba a norte. Sin
un aviso. La inversión corría y entregaba un modelo.

LA CONTRADICCIÓN CABE EN UNA LÍNEA: en el vocabulario del mapeo manual y del
plan (`column_mapping_service.ROLE_Y`) la letra `y` significa NORTE; en el
sniffer significaba PROFUNDIDAD. La misma letra, roles opuestos, y nada que los
comparara. Y `y` nunca estuvo en el contrato: el propio mensaje de error del
resolver declara las formas admitidas como «(x_m, z_m), (lat/lon),
(easting/northing), o **(x, z)**». La terna `x, y, z` no figura.

POR QUÉ NO BASTABA CON BORRAR `"y"` DE LA LISTA, que es lo que pedía el punto 1
del plan. Medido: quitándolo y nada más, un `X,Y,Z` queda así →
`x`=este ✔, `z`=**norte** ✘ (es la cota), `y`=descartada ✘ (era el norte).
Es decir, se cambia una corrupción silenciosa por otra **peor de ver**, porque
ya no hay un número absurdo (7e6 m de profundidad) que delate el problema.
De ahí el punto 2: cuando las tres letras están desnudas, **el rol se pregunta**.

POR QUÉ LA AMBIGÜEDAD SE CIERRA POR NOMBRE Y NO POR RANGO. La guarda por rango
ya existía (`northing_in_depth_slot`, umbral `> 1e5 m`) y es CIEGA a los
archivos en coordenadas locales: caza a DO-27 (northing 7,1e6) y **no** a Raglan
(4,1e4). Ese es justamente el hallazgo que la Fase 11 dejó pinchado. El nombre
`y` no informa del rol en NINGÚN rango, así que la guarda que cierra el hueco
tiene que mirar el nombre.

LO QUE ESTE FICHERO DEFIENDE, y por qué cada test:
  · el gate del plan, con valores chilenos reales;
  · que el arreglo no se pueda deshacer devolviendo `"y"` a una lista que asigne
    profundidad — comprobado por CONDUCTA y no por el nombre de la constante,
    que es la lección de las Fases 6 y 13 (un guard que mira el nombre se anula
    dejando el `import` sin la llamada);
  · que el contrato documentado `(x, z)` NO cambió, que es la mitad que un
    arreglo apurado rompe;
  · que la pregunta llega POR HTTP y no sólo desde la función del servicio
    (eslabón 2 del criterio de la Fase 9), y que el rechazo es 422 y no 500;
  · que las dos guardas se COMPONEN: la de nombre pregunta, la de rango refuta
    una respuesta que los valores desmienten;
  · y un test de CONTROL que demuestra que la comprobación de geometría sabe
    distinguir una corrupta de una sana — sin él, «no hay northing en el eje
    vertical» podría ser cierto y vacío.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.column_mapping_service import build_column_mapping_plan  # noqa: E402
from services.gravity_import_service import (  # noqa: E402
    _resolve_coordinate_columns,
    import_gravity_csv_v1,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── El mundo del gate: gravimetría en UTM 19S, que es el caso de uso declarado ──
# Este ~3,6e5 · Norte ~6,9e6 · Cota 800-930 m. Los tres rangos son separables a
# ojo, que es precisamente lo que hace que la corrupción sea invisible: ningún
# valor es absurdo POR SÍ MISMO, sólo en el eje equivocado.
_N_FILAS = 12
_ESTE = [360_000.0 + i * 250.0 for i in range(_N_FILAS)]
_NORTE = [6_900_000.0 + i * 250.0 for i in range(_N_FILAS)]
_COTA = [800.0 + i * 12.0 for i in range(_N_FILAS)]
_BOUGUER = [round(-12.0 + i * 0.3, 2) for i in range(_N_FILAS)]

_MAPEO_ESTE_NORTE_COTA = {
    "x": "X", "y": "Y", "elevation": "Z",
    "gravity_value": "Bouguer_mGal", "unit": "mGal",
    "gravity_type": "bouguer_anomaly",
}
_MAPEO_ESTE_NORTE_PROFUNDIDAD = {
    "x": "X", "y": "Z", "depth": "Y",
    "gravity_value": "Bouguer_mGal", "unit": "mGal",
    "gravity_type": "bouguer_anomaly",
}


def _csv_chileno(cabecera: str = "X,Y,Z,Bouguer_mGal") -> str:
    filas = "\n".join(
        f"{_ESTE[i]:.0f},{_NORTE[i]:.0f},{_COTA[i]:.0f},{_BOUGUER[i]}"
        for i in range(_N_FILAS)
    )
    return cabecera + "\n" + filas


def _importar(texto: str, column_map: "dict | None" = None):
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(texto)
    f.close()
    try:
        return import_gravity_csv_v1(f.name, strict=False, column_map=column_map)
    finally:
        os.unlink(f.name)


def _ejes(resultado) -> "dict[str, list[float]]":
    """Los tres ejes internos: x_m=este, y_m=PROFUNDIDAD, z_m=norte."""
    obs = [o.model_dump() for o in (resultado.observations or [])]
    return {
        "este": [o["x_m"] for o in obs],
        "profundidad": [o["y_m"] for o in obs],
        "norte": [o["z_m"] for o in obs],
    }


def _hay_northing_en_el_eje(valores: "list[float]") -> bool:
    """¿Estos números son un northing UTM disfrazado?

    El criterio es el mismo que usa la guarda de rango del plan (`> 1e5 m`), y
    se aplica al eje VERTICAL, donde 100 km de profundidad no existen: la corteza
    continental entera son ~35 km y ninguna campaña gravimétrica mide bajo ella.
    """
    if not valores:
        return False
    orden = sorted(abs(v) for v in valores)
    return orden[len(orden) // 2] > 1e5


# ═════════════════════════════════════════════════════════════════════════════
# 1. EL GATE DEL PLAN
# ═════════════════════════════════════════════════════════════════════════════
def test_gate_un_csv_XYZ_chileno_no_manda_el_northing_a_profundidad():
    """El criterio del plan, literal: «o se rechaza pidiendo el mapeo, o asigna
    los tres roles correctos».

    Se aceptan las DOS salidas porque las dos son honestas; lo que no se acepta
    es la tercera, que es la que había: ingerir con la geometría cambiada.
    """
    resultado = _importar(_csv_chileno())
    ejes = _ejes(resultado)

    if resultado.observations:
        # Salida B: ingirió → los tres roles tienen que estar bien.
        assert not _hay_northing_en_el_eje(ejes["profundidad"]), (
            "El northing sigue cayendo en el eje de PROFUNDIDAD: H-F11-1 volvió. "
            f"mediana |y_m| = {sorted(abs(v) for v in ejes['profundidad'])[len(ejes['profundidad'])//2]:,.0f} m"
        )
        assert max(ejes["norte"]) - min(ejes["norte"]) > 1.0, (
            "El eje NORTE quedó degenerado (todos los puntos en la misma línea): "
            "señal de que ahí entró la COTA y no el northing."
        )
    else:
        # Salida A: se negó a adivinar → tiene que DECIR QUÉ HACER.
        assert resultado.errors, "Rechazó el archivo sin un solo mensaje de error."
        texto = " ".join(resultado.errors)
        assert "Y" in texto and "ambigua" in texto.lower(), (
            f"El rechazo no nombra la columna ambigua: {texto[:200]}"
        )
        assert "column_map" in texto or "mapeo" in texto.lower(), (
            "El rechazo no dice CÓMO resolverlo. Un error que no propone la "
            f"salida es un muro: {texto[:200]}"
        )


def test_el_mensaje_de_error_ofrece_las_DOS_lecturas():
    """No basta con nombrar el problema: hay que poder copiar la solución.

    El mensaje ofrece las dos lecturas porque el NOMBRE no permite descartar
    ninguna — es exactamente el motivo por el que se pregunta. Cuál de las dos
    es la buena lo decide el usuario (o, si sus valores lo delatan, la guarda por
    rango: ver el test siguiente).
    """
    fallo = _importar(_csv_chileno())
    if fallo.observations:
        pytest.skip("la ingesta resolvió los roles sola; este test cubre el rechazo")
    texto = " ".join(fallo.errors)
    assert "elevation" in texto and "depth" in texto, (
        "El mensaje tiene que ofrecer las dos lecturas (cota y profundidad); "
        f"si sólo ofrece una, está eligiendo por el usuario: {texto[:250]}"
    )

    cota = _importar(_csv_chileno(), _MAPEO_ESTE_NORTE_COTA)
    assert cota.observations, f"el mapeo (este,norte,cota) no ingiere: {cota.errors}"
    ejes = _ejes(cota)
    assert not _hay_northing_en_el_eje(ejes["profundidad"]), (
        "Con Z=cota, la profundidad tiene que ser 0 (estaciones de superficie)."
    )
    assert max(ejes["norte"]) - min(ejes["norte"]) > 1.0, (
        "el northing no llegó al eje norte pese a estar mapeado ahí"
    )


def test_las_dos_guardas_se_componen_la_de_nombre_pregunta_y_la_de_rango_refuta():
    """La segunda línea de defensa: preguntar no obliga a aceptar cualquier respuesta.

    Este es el hallazgo de montar el gate. La ambigüedad de NOMBRE se cierra
    preguntando (Fase 16), pero si el usuario contesta algo que sus propios
    VALORES desmienten —aquí, mandar un northing de 6,9e6 m al eje vertical—, la
    guarda por rango que ya existía (`northing_in_depth_slot`) lo RECHAZA.

    Las dos son necesarias y ninguna sustituye a la otra:
      · sólo rango  → ciega en coordenadas locales (Raglan, 4,1e4: no dispara);
      · sólo nombre → aceptaría una respuesta absurda sin mirar el dato.
    Y el orden importa: la de nombre actúa ANTES de que exista una respuesta,
    la de rango DESPUÉS de que la haya.
    """
    absurdo = _importar(_csv_chileno(), _MAPEO_ESTE_NORTE_PROFUNDIDAD)
    assert not absurdo.observations, (
        "Se aceptó mandar un northing UTM de 6,9e6 m al eje de PROFUNDIDAD. "
        "La guarda por rango dejó de defender, y el mapeo manual se vuelve una "
        "forma de reintroducir H-F11-1 a mano."
    )
    texto = " ".join(absurdo.errors)
    assert "PROFUNDIDAD" in texto and "NORTE" in texto.upper(), (
        f"el rechazo no explica qué eje está mal: {texto[:200]}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. LA ANTI-REGRESIÓN — «debe fallar si alguien devuelve "y" a la lista»
#    Por CONDUCTA, no por el nombre de la constante.
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "trio",
    [("x", "y", "z"), ("local_x", "local_y", "local_z"), ("coord_x", "coord_y", "coord_z")],
    ids=["x/y/z", "local_*", "coord_*"],
)
def test_ninguna_familia_de_letras_desnudas_asigna_profundidad_sola(trio):
    """Punto 3 del plan: las tres familias tienen el MISMO problema.

    `coord_x/coord_y/coord_z` es tan ambiguo como `x/y/z`. Si alguien devuelve
    cualquiera de las tres letras a una lista que asigne el slot `y_m`, este
    test cae — y cae por lo que HACE el resolver, no por cómo se llama una
    constante, que es la trampa en la que ya cayeron dos guards de este
    repositorio (Fases 6 y 13).
    """
    xc, yc, zc = trio
    headers = [xc, yc, zc, "g_mgal"]
    r = _resolve_coordinate_columns([h.lower() for h in headers], headers, None)

    assert r["y_col"] != yc, (
        f"'{yc}' volvió a auto-asignarse al slot de PROFUNDIDAD (y_m). Eso es "
        "H-F11-1 exactamente: con la cabecera más común del mundo, el northing "
        "acaba bajo tierra. Si hace falta una columna de profundidad, tiene que "
        "llamarse por su nombre (depth/profundidad) o venir en el column_map."
    )
    assert r["z_col"] != zc, (
        f"'{zc}' se auto-asignó al eje NORTE mientras '{yc}' quedaba sin rol. "
        "Ése es el segundo defecto, el que aparece al borrar la letra de la "
        "lista sin más: la cota pasa a norte y el norte se descarta. Peor que "
        "el original, porque ya no hay un número absurdo que lo delate."
    )
    assert r["coord_type"] is None and r["errors"], (
        "La terna desnuda tiene que PREGUNTAR, no resolverse en silencio."
    )


@pytest.mark.parametrize(
    "headers",
    [
        ["x", "y", "z", "depth_m", "g"],
        ["x", "y", "z", "elevation", "g"],
    ],
    ids=["con_depth_declarada", "con_elevation_declarada"],
)
def test_la_terna_desnuda_pregunta_AUNQUE_haya_columna_vertical_declarada(headers):
    """DECISIÓN EXPLÍCITA, y se aparta de la letra del punto 1 del plan.

    El punto 1 ofrecía pedir confirmación «cuando `y` aparece junto a `x` y `z`
    SIN columna de profundidad declarada», lo que deja entender que con un
    `depth_m` presente se podría resolver solo. No se hace, por dos razones:

    1. El punto 2 —la regla nueva de la fase— no tiene excepción: «si las tres
       columnas son `x/y/z` desnudas, el rol de cada una SE PREGUNTA, nunca se
       asume». Los dos puntos están en tensión y gana el segundo, que es el que
       enuncia la regla.
    2. Aunque `depth_m` deje a `y` como horizontal, sigue sin decir cuál de
       `y`/`z` es el NORTE y cuál la COTA. Resolverlo exigiría asumir que `z` es
       la vertical — la misma clase de suposición que causó H-F11-1, sólo que
       una capa más adentro y por eso más difícil de ver.

    El coste es un mapeo manual en un encabezado poco frecuente. El beneficio es
    que la regla no tiene bordes: `x/y/z` desnudas SIEMPRE se preguntan, y eso se
    puede explicar en una frase a un usuario.
    """
    r = _resolve_coordinate_columns([h.lower() for h in headers], headers, None)
    assert r["coord_type"] is None and r["errors"], (
        "Se resolvió una terna desnuda por tener otra columna vertical al lado. "
        "Si esto es deliberado, la regla de la fase pasa a tener una excepción y "
        "hay que escribirla donde el usuario pueda leerla."
    )


def test_el_contrato_documentado_x_z_sigue_intacto():
    """La otra mitad: un arreglo que rompe `(x, z)` no es un arreglo.

    `(x, z)` SÍ está en el contrato —lo declara el mensaje de error del propio
    resolver— y ahí no hay ambigüedad: dos horizontales, sin tercera letra.
    """
    headers = ["x", "z", "g_mgal"]
    r = _resolve_coordinate_columns([h.lower() for h in headers], headers, None)
    assert r["coord_type"] == "local", f"se rompió (x, z): {r['errors']}"
    assert r["x_col"] == "x" and r["z_col"] == "z"
    assert r["y_col"] is None
    assert any("y_m=0" in w for w in r["warnings"]), (
        "Sin columna vertical se asume y_m=0, y eso se avisa. El aviso es parte "
        "del contrato: sin él, «profundidad 0» es una invención silenciosa."
    )


@pytest.mark.parametrize(
    "headers,esperado_depth",
    [
        (["x_m", "y_m", "z_m", "g"], "y_m"),          # convención interna EXPLÍCITA
        (["x", "z", "depth_m", "g"], "depth_m"),      # profundidad por nombre propio
        (["x", "z", "profundidad", "g"], "profundidad"),
    ],
    ids=["x_m/y_m/z_m", "depth_m", "profundidad_ES"],
)
def test_lo_que_SI_declara_su_rol_sigue_sin_preguntar(headers, esperado_depth):
    """El arreglo no puede volverse una molestia universal.

    `y_m` lleva el sufijo de la convención interna (es lo que EXPORTA
    TerraQuantum) y `depth`/`profundidad` dicen su rol en el nombre. Ninguno es
    una letra suelta, así que ninguno se pregunta.
    """
    r = _resolve_coordinate_columns([h.lower() for h in headers], headers, None)
    assert r["coord_type"] is not None, (
        f"{headers} dejó de resolverse: el arreglo se pasó de celoso. {r['errors']}"
    )
    assert r["y_col"] == esperado_depth


# ═════════════════════════════════════════════════════════════════════════════
# 3. EL CONTROL — sin esto, «no hay northing en el eje vertical» puede ser
#    cierto y VACÍO (la lección del gate de física de la Fase 3).
# ═════════════════════════════════════════════════════════════════════════════
def test_control_el_detector_de_geometria_corrompida_sabe_distinguir():
    """Se le da la corrupción EXACTA que había y tiene que cazarla.

    Si este test pasara con ambas entradas, el del gate no probaría nada.
    """
    assert _hay_northing_en_el_eje(_NORTE), (
        "El detector no reconoce un northing UTM puesto en el eje vertical: "
        "entonces el gate de arriba pasa por vacuidad."
    )
    assert not _hay_northing_en_el_eje([0.0] * _N_FILAS), (
        "El detector marca como corrupta una profundidad 0 legítima."
    )
    assert not _hay_northing_en_el_eje(_COTA), (
        "El detector marca como corrupta una cota de 800 m."
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. EL OTRO EXTREMO: el plan tiene que PREGUNTAR, y preguntar bien
# ═════════════════════════════════════════════════════════════════════════════
def test_el_plan_pregunta_y_sugiere_los_roles_correctos_por_rango():
    """Negarse a adivinar por NOMBRE no puede dejar al usuario sin pistas.

    El nombre no informa; los VALORES sí. El plan marca `needs_mapping` y el
    sugeridor por rango propone el par (este, norte) correcto — confianza media,
    para que el usuario confirme en un clic en vez de teclear el mapeo entero.
    """
    headers = ["X", "Y", "Z", "Bouguer_mGal"]
    sample = {
        "X": [str(v) for v in _ESTE],
        "Y": [str(v) for v in _NORTE],
        "Z": [str(v) for v in _COTA],
        "Bouguer_mGal": [str(v) for v in _BOUGUER],
    }
    plan = build_column_mapping_plan(headers, "gravity", None, sample)

    assert plan["needs_mapping"] is True, (
        "El plan aceptó `X,Y,Z` sin preguntar: el punto 2 de la fase no se cumple."
    )
    sug = plan.get("suggestions") or {}
    assert sug.get("x", {}).get("column") == "X", f"sugerencias: {sug}"
    assert sug.get("y", {}).get("column") == "Y", (
        "El sugeridor por rango no propone el northing como coordenada Y. "
        f"sugerencias: {sug}"
    )
    for rol in ("x", "y"):
        assert sug[rol]["confidence"] != "high", (
            "Una sugerencia por rango NUNCA es de confianza alta: se propone, "
            "se confirma, no se aplica sola."
        )


def test_la_pregunta_llega_por_HTTP_y_el_rechazo_es_422_no_500():
    """Eslabón 2 del criterio de la Fase 9: emitir no es lo mismo que entregar.

    Comprobar sólo la función del servicio dejaría sin verificar la capa por la
    que pasa el usuario. Se exige lo que un consultor ve de verdad:
      · `analyze-columns` responde 200 con el plan que PREGUNTA y con la
        sugerencia por rango dentro —no un error—, porque preguntar es una
        respuesta legítima y el flujo continúa;
      · `build-package` RECHAZA con 422 (petición inválida) y no con 500: un
        CSV ambiguo es un problema del dato, no una caída del servidor, y la
        diferencia decide si el usuario ve un mensaje o «error interno».
    """
    os.environ.setdefault("TQ_AUTH_ENABLED", "false")
    from fastapi.testclient import TestClient
    from main import app

    cliente = TestClient(app)
    csv = _csv_chileno()

    r = cliente.post(
        "/v2/gravity-import/analyze-columns",
        files={"file": ("g.csv", csv, "text/csv")},
        data={"data_kind": "gravity"},
    )
    assert r.status_code == 200, r.text
    plan = r.json()["column_mapping"]
    assert plan["needs_mapping"] is True, "por HTTP no se pregunta"
    assert set(plan["missing_required"]) == {"x", "y"}
    sug = plan.get("suggestions") or {}
    assert sug.get("x", {}).get("column") == "X", f"sin sugerencia útil: {sug}"
    assert sug.get("y", {}).get("column") == "Y", f"sin sugerencia útil: {sug}"

    r2 = cliente.post(
        "/v2/gravity-import/build-package",
        files={"file": ("g.csv", csv, "text/csv")},
    )
    assert r2.status_code == 422, (
        f"se esperaba 422 (dato inválido) y llegó {r2.status_code}. "
        "Un 500 le diría al usuario que el servidor se cayó, cuando lo que pasa "
        "es que su CSV necesita un mapeo."
    )
    assert "ambigua" in r2.text.lower(), r2.text[:300]


def test_raglan_el_dataset_al_que_la_guarda_por_rango_era_ciega():
    """El caso real que la Fase 11 dejó pinchado.

    Raglan trae `X,Y,Z` con coordenadas LOCALES (northing 4,1e4), así que la
    guarda por rango —umbral 1e5 m— no lo veía: `needs_mapping=False`,
    `needs_confirmation=False`, `suspicions=[]`. Silencio absoluto. Es el
    contraejemplo que demuestra por qué la ambigüedad se cierra por nombre.
    """
    raglan = REPO_ROOT / "Raglan_Magnetic" / "Raglan_Magnetic_TMI_nT.csv"
    if not raglan.is_file():
        pytest.skip("el dataset Raglan no está en este árbol")

    cabecera = raglan.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    headers = [h.strip() for h in cabecera.split(",")]
    r = _resolve_coordinate_columns([h.lower() for h in headers], headers, None)
    assert r["coord_type"] is None, (
        f"Raglan ({headers}) volvió a auto-resolverse sin preguntar."
    )
    assert r["y_col"] is None, "el northing de Raglan volvió al slot de profundidad"


def test_el_mapeo_de_los_ejemplos_sigue_siendo_el_correcto():
    """`examples/02_datasets_canonicos.py` trae el column_map de Raglan escrito.

    Era la MITIGACIÓN cuando el defecto estaba vivo; ahora es la RESPUESTA a la
    pregunta que la ingesta hace. Tiene que seguir funcionando, y el test existe
    porque si el arreglo lo invalidara, el ejemplo publicado quedaría roto.
    """
    ejemplo = REPO_ROOT / "terraquantum-backend" / "examples" / "02_datasets_canonicos.py"
    if not ejemplo.is_file():
        pytest.skip("el ejemplo 02 no está en este árbol")
    texto = ejemplo.read_text(encoding="utf-8")
    assert '"x": "X", "y": "Y", "elevation": "Z"' in texto, (
        "El column_map de Raglan en el ejemplo 02 cambió. Si la convención de "
        "roles se movió, hay que revisar esta fase entera; si sólo se reformateó, "
        "actualiza este test."
    )
