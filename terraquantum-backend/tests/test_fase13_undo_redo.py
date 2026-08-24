# -*- coding: utf-8 -*-
"""FASE 13 (auditoría 06 §10) — Undo/redo por deltas, atajos y persistencia.

El plan de la fase (`docs/06_AUDITORIA_TECNICA_INTEGRAL.md:2863`) pide un
Command Pattern sobre las mutaciones del store, atajos y persistencia de layout,
y el informe 04 aporta el diseño concreto que hay que seguir (`:1112`, `:1120`):
**deltas, no instantáneas** — guardar incrementos, nunca clonar el documento
entero. Este guard vigila justamente lo que un compilador no puede afirmar solo.

Lo que vigila, y por qué cada punto:

1. **Todo campo del store está clasificado** como deshacible o no-deshacible con
   motivo escrito. Es el cierre del patrón que la auditoría encontró CINCO veces
   (§1.2): «los criterios de cierre miden que la pieza exista, no que el camino
   esté conectado». Aquí un campo nuevo sin clasificar no compila en TypeScript;
   este test lo comprueba además desde fuera, que es lo que corre en CI.
2. **Ningún dato del backend es deshacible.** Es la frase literal del diseño:
   comandos «para las acciones del usuario, NO para datos derivados del backend».
3. **El delta no es una instantánea**, comprobado prohibiendo los patrones de
   clonado total en los módulos del historial. Con su test de CONTROL.
4. **El historial tiene techo** — el criterio «no crece sin límite», medido.
5. **Los atajos se declaran una sola vez** y **ningún listener global de teclado
   ignora el foco**, que es el defecto de §9H.2 que esta fase repara en
   `Scene3D` y que no puede volver por la puerta de atrás.
6. **La interfaz de deshacer está montada** (eslabón de la Fase 9).
7. **Sólo se persisten preferencias**, nunca datos de una corrida.
8. **Ninguna lista tolerada del repositorio sigue nombrando a la Fase 13 como
   dueña**: al cerrarse, o cumplió la deuda o la devolvió con motivo escrito.

LO QUE ESTA SUITE NO PRUEBA
---------------------------
· Que deshacer funcione. Eso se ejerce en el navegador, en
  `terraquantum-web/e2e/fase13_undo_redo.spec.ts` (8 recorridos), porque un
  historial es una SECUENCIA y leer el código no demuestra una secuencia.
· Que el secuestro de flechas fuera literalmente «el slider no se mueve». Eso se
  dedujo del código y de la especificación HTML; lo MEDIDO e indiscutible es que
  no había filtro de foco y que el `preventDefault` era incondicional.
· Nada del backend: esta fase no toca una línea de Python de producción. El
  guard vive aquí porque es donde vive la CI de guardas del repositorio.
"""

from __future__ import annotations

import pathlib
import re

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_ROOT = (BACKEND_ROOT.parent / "terraquantum-web").resolve()

_WEB_SCAN_DIRS = ("app", "lib", "componentes", "store", "workers", "e2e")
_WEB_SUFFIXES = (".ts", ".tsx")

STORE = WEB_ROOT / "store" / "useAppStore.ts"
DESHACIBLE = WEB_ROOT / "store" / "deshacible.ts"
HISTORIAL_VISOR = WEB_ROOT / "store" / "historialVisor.ts"
COMANDOS = WEB_ROOT / "lib" / "historial" / "comandos.ts"
USE_HISTORIAL = WEB_ROOT / "lib" / "historial" / "useHistorial.ts"
USE_REDUCER = WEB_ROOT / "lib" / "historial" / "useReducerConHistorial.ts"
TECLAS = WEB_ROOT / "lib" / "atajos" / "teclas.ts"
FOCO = WEB_ROOT / "lib" / "atajos" / "foco.ts"
PREFERENCIAS = WEB_ROOT / "lib" / "preferencias" / "preferenciasVisuales.ts"

#: Los módulos que implementan el historial. En ellos NO puede aparecer un
#: clonado del estado entero: sería exactamente el diseño que el informe 04
#: descarta, y el que un desarrollador solo escribiría primero.
MODULOS_DEL_HISTORIAL = (COMANDOS, HISTORIAL_VISOR, USE_REDUCER, USE_HISTORIAL)

#: Patrones de INSTANTÁNEA. Si alguno aparece en un módulo del historial, el
#: undo dejó de ser por deltas aunque el comentario siga diciendo que lo es.
PATRONES_DE_INSTANTANEA = (
    r"\{\s*\.\.\.\s*get\(\)\s*\}",
    r"\{\s*\.\.\.\s*getState\(\)\s*\}",
    r"structuredClone\s*\(",
    r"JSON\.parse\s*\(\s*JSON\.stringify\s*\(",
)

#: Campos del store que son DATOS del backend o telemetría del render. Ninguno
#: puede ser deshacible: restaurarlos crearía una vista con los datos de una
#: corrida y el encabezado de otra. La lista no puede encogerse — si un nombre
#: desaparece del store hay que quitarlo de aquí, y hay un test que lo obliga.
JAMAS_DESHACIBLES: dict[str, str] = {
    "model": "Resultado de una corrida, sellado con `modelRunKey` (H-28).",
    "modelRunKey": "Sello de procedencia del modelo.",
    "activeRun": "Identidad de la corrida; cambiarla invalida doce campos.",
    "report": "Reporte devuelto por el backend.",
    "isosurfaceData": "Malla servida por /v2/isosurface.",
    "boreholeData": "Sondajes servidos por /boreholes.",
    "sectionData": "Raster de la cara del corte.",
    "doiOverlayData": "Horizonte DOI: juicio de incertidumbre de una inversión.",
    "terrainData": "Matriz DEM del proyecto.",
    "percentileStats": "Estadísticos calculados por el backend.",
    "resultIsStale": "Aviso de honestidad: deshacerlo sería esconderlo.",
    "isBlockModelLoading": "Bandera de vuelo.",
    "isWorkerProcessing": "Bandera de vuelo.",
    "capturePngSnapshot": "Puntero a una función viva del renderer.",
    "view": "Navegación: deshacerla desmonta LoadPanel y abandona la corrida.",
    "show3D": "Lo escribe la máquina de inversión al terminar.",
}

#: Claves que un almacén de PREFERENCIAS jamás puede contener. Persistir
#: cualquiera de ellas rompería la regla que la Fase 1 impuso con H-28: nada de
#: una corrida sobrevive a esa corrida.
JAMAS_PERSISTIDAS = (
    "model", "modelRunKey", "activeRun", "report", "isosurfaceData",
    "boreholeData", "sectionData", "doiOverlayData", "terrainData",
    "percentileStats", "capturePngSnapshot", "fileGravimetry",
    "fileMagnetometry", "heatmapData", "bestTarget", "bestVoxel",
)

#: Techo del historial que el criterio de aceptación exige. El número vive en el
#: frontend; aquí sólo se comprueba que EXISTE, que es finito y que se aplica.
#: 200 es un tope de cordura: por encima de ahí «acotado» deja de significar algo
#: para el uso de memoria de una sesión larga.
TECHO_MAXIMO_ACEPTABLE = 200


def _web_disponible() -> bool:
    return WEB_ROOT.is_dir() and (WEB_ROOT / "app").is_dir()


pytestmark = pytest.mark.skipif(
    not _web_disponible(),
    reason="terraquantum-web no está presente: este guard cruza backend↔frontend.",
)


def _leer_web(dirs: tuple[str, ...] = _WEB_SCAN_DIRS) -> list[tuple[pathlib.Path, str]]:
    salida: list[tuple[pathlib.Path, str]] = []
    for d in dirs:
        base = WEB_ROOT / d
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if f.suffix not in _WEB_SUFFIXES:
                continue
            if "node_modules" in f.parts or ".next" in f.parts:
                continue
            salida.append((f, f.read_text(encoding="utf-8", errors="ignore")))
    return salida


def _sin_comentarios(texto: str) -> str:
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"//[^\n]*", "", texto)


def _campos_del_store() -> list[str]:
    """Miembros de `AppState` que son ESTADO y no acciones.

    Se cuenta la profundidad de llaves/paréntesis, nunca de `<>`: un `=>` trae un
    `>` sin su `<` y descuadra cualquier contador ingenuo. (Este error lo cometí
    al medir la fase y salían 2 campos en vez de 100.)
    """
    src = STORE.read_text(encoding="utf-8")
    i = src.index("export interface AppState {") + len("export interface AppState {")
    j = src.index("\n}", i)
    cuerpo = _sin_comentarios(src[i:j])

    miembros: list[str] = []
    buf, prof = "", 0
    for ch in cuerpo:
        if ch in "{([":
            prof += 1
        elif ch in "})]":
            prof -= 1
        if ch == ";" and prof == 0:
            miembros.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        miembros.append(buf.strip())

    campos: list[str] = []
    for m in miembros:
        m = " ".join(m.split())
        mm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\??\s*:\s*(.+)$", m, re.S)
        if not mm:
            continue
        nombre, tipo = mm.group(1), mm.group(2).strip()
        es_funcion = tipo.startswith("(") and "=>" in tipo
        # `capturePngSnapshot: ((n) => string) | null` es ESTADO, no acción.
        if es_funcion and re.search(r"\)\s*\|\s*null\s*$", tipo):
            es_funcion = False
        if not es_funcion:
            campos.append(nombre)
    return campos


def _claves_de_bloque(texto: str, apertura: str) -> set[str]:
    """Claves de primer nivel de un objeto literal que empieza en `apertura`."""
    i = texto.index(apertura) + len(apertura)
    prof, fin = 1, i
    while prof > 0 and fin < len(texto):
        if texto[fin] in "{([":
            prof += 1
        elif texto[fin] in "})]":
            prof -= 1
        fin += 1
    cuerpo = _sin_comentarios(texto[i:fin - 1])

    claves: set[str] = set()
    prof, inicio = 0, 0
    for pos, ch in enumerate(cuerpo):
        if ch in "{([":
            prof += 1
        elif ch in "})]":
            prof -= 1
        elif ch == "," and prof == 0:
            trozo = cuerpo[inicio:pos]
            mm = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", trozo)
            if mm:
                claves.add(mm.group(1))
            inicio = pos + 1
    mm = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", cuerpo[inicio:])
    if mm:
        claves.add(mm.group(1))
    return claves


def _deshacibles() -> set[str]:
    t = DESHACIBLE.read_text(encoding="utf-8")
    return _claves_de_bloque(t, "export const CLAVES_DESHACIBLES = {")


def _no_deshacibles() -> set[str]:
    t = DESHACIBLE.read_text(encoding="utf-8")
    return _claves_de_bloque(
        t, "export const NO_DESHACIBLE: Record<Exclude<CampoDeEstado, ClaveDeshacible>, string> = {"
    )


def _persistidas() -> set[str]:
    t = PREFERENCIAS.read_text(encoding="utf-8")
    return _claves_de_bloque(t, "export const PREFERENCIAS_PERSISTIDAS = {")


# ── 1. Cada campo del store tiene una decisión escrita ───────────────────────


def test_todo_campo_del_store_esta_clasificado():
    campos = set(_campos_del_store())
    assert len(campos) > 50, (
        f"el lector de `AppState` sólo encontró {len(campos)} campos: se rompió el "
        "parseo, no el store. Revisa `_campos_del_store`."
    )
    clasificados = _deshacibles() | _no_deshacibles()
    sin_decidir = sorted(campos - clasificados)
    assert not sin_decidir, (
        "Hay campos del store sin decisión sobre si son deshacibles. Un campo sin "
        "clasificar es el sexto agujero del patrón de §1.2: existe y nadie "
        "comprobó si tiene camino.\n"
        "Arreglo: o entra en `CLAVES_DESHACIBLES` con su etiqueta, o entra en "
        "`NO_DESHACIBLE` con el MOTIVO escrito.\n  " + "\n  ".join(sin_decidir)
    )


def test_la_clasificacion_no_inventa_campos_que_el_store_no_tiene():
    campos = set(_campos_del_store())
    sobran = sorted((_deshacibles() | _no_deshacibles()) - campos)
    assert not sobran, (
        "`deshacible.ts` clasifica claves que ya NO existen en `AppState`: la "
        "lista dejó de describir la realidad.\n  " + "\n  ".join(sobran)
    )


def test_ningun_dato_del_backend_es_deshacible():
    deshacibles = _deshacibles()
    delitos = sorted(deshacibles & set(JAMAS_DESHACIBLES))
    assert not delitos, (
        "El diseño de la fase dice literalmente: comandos inversibles «para las "
        "acciones del usuario (no para datos derivados del backend)». Estas "
        "claves son datos o telemetría y están declaradas deshacibles:\n  "
        + "\n  ".join(f"{k} — {JAMAS_DESHACIBLES[k]}" for k in delitos)
    )


def test_la_lista_de_jamas_deshacibles_es_portante():
    campos = set(_campos_del_store())
    for clave, motivo in JAMAS_DESHACIBLES.items():
        assert clave in campos, (
            f"`{clave}` ya no existe en el store: quítala de JAMAS_DESHACIBLES."
        )
        assert motivo.strip(), f"`{clave}` prohibida sin motivo escrito."


def test_cada_no_deshacible_dice_por_que():
    t = _sin_comentarios(DESHACIBLE.read_text(encoding="utf-8"))
    i = t.index("export const NO_DESHACIBLE")
    bloque = t[i:]
    mudos = []
    for clave in sorted(_no_deshacibles()):
        # El motivo es la cadena (o concatenación de cadenas) que sigue a la clave.
        mm = re.search(rf"\b{re.escape(clave)}\s*:\s*((?:\s*\"[^\"]*\"\s*\+?)+)", bloque)
        motivo = mm.group(1) if mm else ""
        if len(re.sub(r"[\"+\s]", "", motivo)) < 25:
            mudos.append(clave)
    assert not mudos, (
        "Estas claves están excluidas del historial sin explicar por qué. Una "
        "excusa vacía es peor que no tenerla: parece una decisión y es un "
        "olvido.\n  " + "\n  ".join(mudos)
    )


# ── 2. Deltas, no instantáneas ───────────────────────────────────────────────


def test_el_historial_no_guarda_instantaneas_del_estado():
    delitos = []
    for f in MODULOS_DEL_HISTORIAL:
        texto = _sin_comentarios(f.read_text(encoding="utf-8"))
        for patron in PATRONES_DE_INSTANTANEA:
            if re.search(patron, texto):
                delitos.append(f"{f.name}: {patron}")
    assert not delitos, (
        "El historial clona el estado entero en vez de guardar el incremento. Es "
        "exactamente lo que el informe 04 descarta (docs/06:1112) y lo que esta "
        "fase existe para no hacer: `csvRows` guarda un CSV completo y el modelo "
        "llega a ~1,7 M de vóxeles.\n  " + "\n  ".join(delitos)
    )


def test_control_el_detector_de_instantaneas_discrimina():
    """Sin esto, el test de arriba pasaría aunque su regex no cazara nada."""
    fabricado = "const copia = { ...get() };\nconst otra = structuredClone(x);"
    cazados = [p for p in PATRONES_DE_INSTANTANEA if re.search(p, fabricado)]
    assert len(cazados) >= 2, (
        "el detector no caza una instantánea fabricada a mano: es inerte"
    )
    limpio = "const d = calcularDelta(ambito, grupo, antes, despues, vigiladas, etq, t);"
    assert not [p for p in PATRONES_DE_INSTANTANEA if re.search(p, limpio)], (
        "el detector marca como instantánea un cálculo de delta legítimo: es un "
        "falso positivo, y un guard que grita en falso se acaba desactivando"
    )


def test_el_delta_solo_lleva_las_claves_que_cambiaron():
    t = COMANDOS.read_text(encoding="utf-8")
    assert "if (!Object.is(antes[k], despues[k])) claves.push(k)" in t, (
        "`calcularDelta` dejó de comparar clave a clave. Ése es el punto en el "
        "que el historial deja de ser por deltas."
    )
    assert "for (const k of claves) {" in t, (
        "el delta ya no se construye a partir de las claves que cambiaron"
    )


# ── 3. El historial no crece sin límite ──────────────────────────────────────


def test_el_historial_tiene_techo_y_lo_aplica():
    t = COMANDOS.read_text(encoding="utf-8")
    mm = re.search(r"export const TECHO_HISTORIAL\s*=\s*(\d+)\s*;", t)
    assert mm, (
        "No hay `TECHO_HISTORIAL`. El criterio de aceptación de la fase es «el "
        "historial no crece sin límite», y sin una constante no hay límite."
    )
    techo = int(mm.group(1))
    assert 0 < techo <= TECHO_MAXIMO_ACEPTABLE, (
        f"TECHO_HISTORIAL = {techo}: fuera del rango razonable "
        f"(1..{TECHO_MAXIMO_ACEPTABLE})."
    )
    cuerpo = _sin_comentarios(t)
    assert re.search(r"if\s*\(\s*p\.deshacer\.length\s*>\s*TECHO_HISTORIAL\s*\)", cuerpo), (
        "`TECHO_HISTORIAL` está declarado pero `registrar` no lo aplica: una "
        "constante que nadie comprueba es el mismo pecado que USE_SPARSE_DIRECT."
    )


def test_una_accion_nueva_invalida_la_pila_de_rehacer():
    cuerpo = _sin_comentarios(COMANDOS.read_text(encoding="utf-8"))
    i = cuerpo.index("export function registrar(")
    j = cuerpo.index("function mismasClaves(")
    assert "p.rehacer.length = 0;" in cuerpo[i:j], (
        "`registrar` no limpia la pila de rehacer. Sin eso, rehacer aplicaría un "
        "comando calculado sobre un estado que ya no existe — el fallo clásico "
        "de los undo caseros."
    )


# ── 4. Teclado: una sola declaración, y nunca sin mirar el foco ──────────────


def test_los_atajos_se_declaran_una_sola_vez():
    culpables = []
    for f, texto in _leer_web(("app", "lib", "componentes", "store", "workers")):
        if f == TECLAS:
            continue
        if re.search(r"\b(ctrlKey|metaKey)\b", _sin_comentarios(texto)):
            culpables.append(str(f.relative_to(WEB_ROOT)).replace("\\", "/"))
    assert not culpables, (
        "Las combinaciones de teclas se comparan fuera de `lib/atajos/teclas.ts`. "
        "Dos sitios que deciden qué es Ctrl+Z acaban divergiendo: es el mismo "
        "defecto que la Fase 10 encontró con el estado duplicado.\n"
        "Arreglo: usar `esDeshacer` / `esRehacer`.\n  " + "\n  ".join(culpables)
    )


def test_ningun_listener_global_de_teclado_ignora_el_foco():
    """§9H.2: el listener de `Scene3D` capturaba las flechas sin mirar el foco y
    con `preventDefault` incondicional, dejando inoperables por teclado los 8
    sliders del visor. Ese arreglo no puede deshacerse por descuido."""
    culpables = []
    for f, texto in _leer_web(("app", "lib", "componentes", "store", "workers")):
        limpio = _sin_comentarios(texto)
        if not re.search(r"addEventListener\(\s*[\"']keydown[\"']", limpio):
            continue
        # Se exige la LLAMADA, no la mención. La primera versión de este test
        # miraba si el nombre aparecía en el fichero, y con eso bastaba dejar el
        # `import` para que pasara: al mutar `Scene3D` quitando el guard, el test
        # seguía VERDE. Era inerte, y sólo se supo al mutarlo.
        sin_imports = "\n".join(
            l for l in limpio.splitlines() if not l.lstrip().startswith("import ")
        )
        if re.search(r"\b(elFocoEstaEnUnControl|elFocoTieneDeshacerPropio)\s*\(", sin_imports):
            continue
        culpables.append(str(f.relative_to(WEB_ROOT)).replace("\\", "/"))
    assert not culpables, (
        "Hay listeners globales de `keydown` que no consultan dónde está el "
        "foco. Un atajo global que se dispara con el foco en un control deja ese "
        "control inoperable por teclado.\n"
        "Arreglo: usar los guards de `lib/atajos/foco.ts`.\n  "
        + "\n  ".join(culpables)
    )


def test_control_el_barrido_de_listeners_encuentra_el_de_scene3d():
    """Anti-inercia: si el barrido no viera NINGÚN listener, el test de arriba
    pasaría por vacuidad."""
    vistos = [
        str(f.relative_to(WEB_ROOT)).replace("\\", "/")
        for f, texto in _leer_web(("app", "lib", "componentes", "store", "workers"))
        if re.search(r"addEventListener\(\s*[\"']keydown[\"']", _sin_comentarios(texto))
    ]
    assert vistos, "el barrido no encuentra ni un `addEventListener('keydown')`: es inerte"
    assert any("Scene3D" in v for v in vistos), (
        "el barrido no ve el listener de `Scene3D`, que es el que originó el "
        f"hallazgo. Encontrados: {vistos}"
    )


# ── 5. La interfaz existe y está montada (eslabón de la Fase 9) ──────────────


def test_el_usuario_puede_deshacer_desde_la_interfaz():
    archivos = {
        str(f.relative_to(WEB_ROOT)).replace("\\", "/"): texto for f, texto in _leer_web()
    }
    cadena = [
        ("componentes/historial/ControlesHistorial.tsx", "ControlesHistorial"),
        ("componentes/viewport/HistorialVisorControls.tsx", "HistorialVisorControls"),
        ("componentes/prep/HistorialPrepControls.tsx", "HistorialPrepControls"),
    ]
    for ruta, _ in cadena:
        assert ruta in archivos, f"falta {ruta}: la fase no entregó interfaz."

    for ruta, nombre in cadena:
        importadores = [
            r for r, t in archivos.items()
            if r != ruta and re.search(rf'(?:from|import\()\s*["\'][^"\']*/{nombre}["\']', t)
        ]
        assert importadores, (
            f"`{nombre}` existe y NADIE lo importa. Es el hallazgo H-10 otra vez: "
            "la pieza está construida y no tiene camino de usuario."
        )

    # Y los dos paneles tienen que colgar de una vista que se monta de verdad.
    assert "HistorialVisorControls" in archivos["componentes/views/Exploration3DView.tsx"], (
        "el historial del visor no está montado en la vista 3D"
    )
    assert "HistorialPrepControls" in archivos["componentes/views/PreparacionView.tsx"], (
        "el historial de preparación no está montado en la vista de Preparación"
    )


def test_los_botones_dicen_por_que_no_se_puede_en_vez_de_solo_apagarse():
    t = (WEB_ROOT / "componentes" / "viewport" / "HistorialVisorControls.tsx").read_text(
        encoding="utf-8"
    )
    assert "bloqueadoPorque" in t and "inversión en curso" in t, (
        "El visor no explica por qué el historial está bloqueado. «No se puede» "
        "sin motivo es el defecto que esta auditoría persigue (H-17: un producto "
        "que no puede decir «no arranqué» no se puede vender)."
    )


def test_deshacer_se_bloquea_mientras_hay_una_corrida_en_curso():
    t = _sin_comentarios(HISTORIAL_VISOR.read_text(encoding="utf-8"))
    for bandera in ('s.activeRun.status === "loading"', "s.isBlockModelLoading", "s.isWorkerProcessing"):
        assert bandera in t, (
            f"`sePuedeOperarElHistorial` no consulta `{bandera}`. El criterio de "
            "aceptación dice «no interfiere con corridas en curso»."
        )
    assert "if (!sePuedeOperarElHistorial()) return false;" in t, (
        "la puerta existe y deshacer/rehacer no la cruzan"
    )


# ── 6. Persistencia: preferencias, nunca datos de una corrida ───────────────


def test_solo_se_persisten_preferencias_que_el_usuario_puede_cambiar():
    persistidas = _persistidas()
    assert persistidas, "no hay ninguna preferencia declarada: la fase no entregó persistencia"
    deshacibles = _deshacibles()
    huerfanas = sorted(persistidas - deshacibles)
    assert not huerfanas, (
        "Se persisten claves que NO son deshacibles, es decir que ningún control "
        "montado puede cambiar. Guardar entre sesiones una perilla que el usuario "
        "no puede mover es teatro.\n  " + "\n  ".join(huerfanas)
    )


def test_jamas_se_persiste_el_resultado_de_una_corrida():
    persistidas = _persistidas()
    delitos = sorted(persistidas & set(JAMAS_PERSISTIDAS))
    assert not delitos, (
        "Se persisten datos que pertenecen a UNA corrida. La Fase 1 selló el "
        "modelo con `modelRunKey` (H-28) justamente para que nada de una corrida "
        "sobreviva a ella; el almacenamiento del navegador no puede ser la puerta "
        "de atrás por la que vuelva.\n  " + "\n  ".join(delitos)
    )


def test_lo_que_se_lee_del_almacen_se_valida_clave_a_clave():
    t = _sin_comentarios(PREFERENCIAS.read_text(encoding="utf-8"))
    assert "if ((valida as (x: unknown) => boolean)(v)) salida[clave] = v;" in t, (
        "`leerPreferencias` no valida cada valor. El contenido de `localStorage` "
        "es entrada NO confiable: lo edita cualquiera desde la consola y "
        "sobrevive a los cambios de versión. Un enum inventado ahí rompe el visor "
        "en el arranque."
    )
    assert "esUnoDe(" in t and "esNumeroEntre(" in t, (
        "faltan validadores de enumerado o de rango"
    )


def test_la_lista_de_no_persistidas_es_portante():
    t = PREFERENCIAS.read_text(encoding="utf-8")
    no_persistidas = _claves_de_bloque(t, "export const NO_PERSISTIDA: Record<string, string> = {")
    campos = set(_campos_del_store())
    persistidas = _persistidas()
    for clave in sorted(no_persistidas):
        assert clave in campos, f"`{clave}` ya no existe en el store: quítala de NO_PERSISTIDA."
        assert clave not in persistidas, (
            f"`{clave}` está en NO_PERSISTIDA y ADEMÁS se persiste: la excusa ya "
            "no describe la realidad."
        )


def test_la_rehidratacion_no_entra_en_el_historial():
    t = _sin_comentarios(
        (WEB_ROOT / "lib" / "preferencias" / "usePreferenciasVisuales.ts").read_text(encoding="utf-8")
    )
    assert "aplicarSinRegistrar(guardadas)" in t, (
        "Las preferencias guardadas se aplican por el camino que SÍ graba. El "
        "primer Ctrl+Z de la sesión desharía «lo que había al abrir la app», que "
        "no es una acción del usuario en esta sesión."
    )


def test_el_almacen_se_lee_en_un_efecto_y_no_en_el_render():
    t = (WEB_ROOT / "lib" / "preferencias" / "usePreferenciasVisuales.ts").read_text(
        encoding="utf-8"
    )
    i = t.index("leerPreferencias()")
    anterior = t[:i]
    assert anterior.count("useEffect(") >= 1, (
        "`leerPreferencias` se llama fuera de un efecto. `localStorage` no existe "
        "en el render del servidor: leerlo durante el render produce un desajuste "
        "de hidratación."
    )


# ── 7. La fase se cierra: no deja su nombre en deudas ajenas ────────────────


def test_ninguna_lista_tolerada_sigue_nombrando_a_la_fase_13_como_duena():
    """Al cerrar una fase, sus deudas heredadas o se cumplen o se devuelven CON
    MOTIVO. Dejar «Dueña: Fase 13» en una lista después de cerrarla es el mismo
    defecto que la auditoría llama declarar sin conectar."""
    pendientes = []
    for f in sorted((BACKEND_ROOT / "tests").glob("test_*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue
        texto = f.read_text(encoding="utf-8", errors="ignore")
        for n, linea in enumerate(texto.splitlines(), 1):
            if re.search(r"Due[ñn]a:\s*Fase 13\b", linea):
                pendientes.append(f"{f.name}:{n}")
    assert not pendientes, (
        "Estas entradas siguen esperando a la Fase 13, que ya cerró. O se "
        "arreglan, o se re-declaran diciendo por qué NO le tocaban.\n  "
        + "\n  ".join(pendientes)
    )


def test_control_el_barrido_de_duenas_encuentra_otras_fases():
    """Anti-inercia: si el regex no encontrara ninguna «Dueña: Fase N», el test
    de arriba pasaría por vacuidad. Y de paso deja MEDIDO que hay entradas
    esperando a fases ya cerradas — deuda AJENA que esta fase no arregla."""
    encontradas: dict[str, int] = {}
    for f in sorted((BACKEND_ROOT / "tests").glob("test_*.py")):
        texto = f.read_text(encoding="utf-8", errors="ignore")
        for mm in re.finditer(r"Due[ñn]a:\s*(Fase \d+)", texto):
            encontradas[mm.group(1)] = encontradas.get(mm.group(1), 0) + 1
    assert encontradas, (
        "el barrido no encuentra ninguna declaración de dueña: el regex es inerte"
    )
    # MEDIDO al cerrar la Fase 13: quedan entradas cuya dueña es la Fase 11, que
    # ya está cerrada. Es deuda AJENA y se deja con nombre, no se arregla aquí:
    # tocarla sería hacer el trabajo de otra fase sin haberlo medido.
    #
    # ── ACTUALIZADO por la Fase 14 (2026-08-21), y conviene decir por qué ──
    # Aquí decía `assert "Fase 14" in encontradas`, con el motivo «es la única del
    # plan §10 que sigue abierta». Ese enunciado dejó de ser cierto al cerrarse la
    # Fase 14: sus DOS entradas se resolvieron —`/borehole/lithology-properties`
    # ganó consumidor (el formulario de geología implícita lee la tabla petrofísica)
    # y `/borehole/desurvey` se devolvió con motivo escrito—. Mantener la cláusula
    # habría obligado a dejar una deuda falsa sólo para que un test pasara, que es
    # exactamente lo que este fichero condena.
    #
    # Lo que NO se relaja es la pregunta anti-inercia: el barrido tiene que seguir
    # encontrando declaraciones reales, y aquí queda MEDIDO cuáles. Si algún día
    # este número baja a cero, el `assert encontradas` de arriba lo dice.
    assert set(encontradas) <= {"Fase 11", "Fase 13"}, (
        "apareció una fase dueña que no estaba medida al cerrar la Fase 14. El plan "
        f"§10 no tiene más fases: o la deuda tiene dueño real, o sobra. {encontradas}"
    )
    assert encontradas.get("Fase 11"), (
        "la deuda AJENA de la Fase 11 desapareció sin que nadie la declarara cerrada: "
        f"si se arregló, dilo aquí. Encontradas: {encontradas}"
    )
