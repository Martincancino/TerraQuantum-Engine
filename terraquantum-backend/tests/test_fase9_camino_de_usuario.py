"""FASE 9 (auditoría 06 §10) — El criterio de gate «un usuario puede hacer/ver X».

La auditoría encontró CUATRO veces el mismo patrón (H-10 F7 sin UI, H-20 updater
sin invocar, H-17 arranque sin mensaje, H-27 degradación sólo en el log) y lo
resumió así: *el backend hace lo honesto y el camino del usuario se detiene ahí*.
A esa altura ya no es un descuido puntual sino una propiedad del criterio de
cierre — los gates medían el endpoint, no al usuario.

La Fase 9 introduce el criterio de proceso que lo impide. **Escribirlo en la
plantilla no basta**: la Fase 6 dejó demostrado que los tests que NOMBRAN cosas
defienden borrados concretos y no detectan nada nuevo, mientras que los que MIDEN
sí. Así que el criterio se mide, en tres eslabones, porque romper cualquiera deja
la capacidad igual de inalcanzable:

    endpoint del backend  →  proxy/cliente del frontend  →  componente MONTADO

El tercero es el que la Fase 6 encontró roto por el otro lado: `SliceControls`,
`MultiPhysicsControls` y `MultimodalComboPanel` estaban terminados, importaban
bien, compilaban… y no había forma de llegar a ellos.

Cada excepción va con MOTIVO y FASE DUEÑA, como `HUERFANOS_TOLERADOS` en la
Fase 6. Una lista sin motivo es una lista que nadie vuelve a mirar.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_ROOT = (BACKEND_ROOT.parent / "terraquantum-web").resolve()

#: Dónde puede vivir una referencia a una ruta del backend.
_WEB_SCAN_DIRS = ("app", "lib", "componentes", "store", "workers", "types", "e2e", "scripts")
_WEB_SUFFIXES = (".ts", ".tsx", ".mjs", ".js")

#: Rutas del backend sin consumidor en el frontend, TOLERADAS con motivo y dueño.
#: Si una desaparece de la app o gana consumidor, hay que quitarla de aquí: la
#: lista es portante, no decorativa (hay un test que lo comprueba).
RUTAS_SIN_UI_TOLERADAS: dict[str, str] = {
    "/api/keys/": (
        "Gestión de API keys. Es administración del despliegue, no del consultor: "
        "en local-first la auth va apagada y las claves las emite Martín por CLI. "
        "Dueña: Fase 11 (API de scripting), que es donde una key tiene sentido."
    ),
    "/models": (
        "Sirve los GLB estáticos; el visor los pide por URL directa desde Three.js, "
        "no por un cliente TS, así que la ruta literal no aparece en el código."
    ),
    "/borehole/desurvey": (
        "Desurvey de sondajes: capacidad del motor sin UI. El frontend sube "
        "intervalos ya desurveyados. Dueña: Fase 14 (geología implícita)."
    ),
    "/borehole/lithology-properties": (
        "Catálogo de propiedades litológicas. Lo consume el propio backend al "
        "construir bounds por unidad; no hay pantalla que lo liste. Dueña: Fase 14."
    ),
    "/geophysics-live-update": (
        "Actualización incremental durante una corrida. Nunca se cableó: el visor "
        "recarga el block model al terminar. Dueña: Fase 13 (UX experta)."
    ),
    "/gravity-import/invert": (
        "Ruta v1 superada por `/v2/gravity-import/invert-with-corrections`; se "
        "conserva por compatibilidad de scripts. Dueña: Fase 11."
    ),
    "/v2/gravity-import/invert-with-corrections": (
        "El frontend invierte por `/api/gravity-import/load-package` (asíncrono). "
        "Ésta es la entrada síncrona para scripts. Dueña: Fase 11."
    ),
    "/v2/geophysics-invert": (
        "Entrada directa al motor con payload completo; el camino de usuario pasa "
        "por el paquete. Es la superficie natural del scripting. Dueña: Fase 11."
    ),
    "/v2/depth-estimate": (
        "Estimación espectral de profundidad; su UI quedó fuera del camino dorado. "
        "Dueña: Fase 11."
    ),
    "/v2/block-model-profile": (
        "Perfil 1D del block model. El visor resuelve el perfil con el corte "
        "(`/api/section`, montado en la Fase 9). Dueña: Fase 11."
    ),
}

#: Proxies Next existentes que ningún componente llama, TOLERADOS con motivo.
PROXIES_SIN_LLAMADOR_TOLERADOS: dict[str, str] = {
    "/api/system-check": (
        "Lo consume el ORQUESTADOR (src-tauri/src/lib.rs) y el smoke test .mjs, no "
        "un componente React: comprueba el arranque antes de que exista interfaz. "
        "El estado que sí ve el usuario va por `/api/backend-health`, cableado en "
        "la Fase 9 al indicador de la barra y a la vista de Sistema."
    ),
}


def _web_disponible() -> bool:
    return WEB_ROOT.is_dir() and (WEB_ROOT / "app").is_dir()


pytestmark = pytest.mark.skipif(
    not _web_disponible(),
    reason="terraquantum-web no está presente: este guard cruza backend↔frontend.",
)


def _leer_web(dirs: tuple[str, ...]) -> list[tuple[pathlib.Path, str]]:
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


def _rutas_del_backend() -> dict[str, set[str]]:
    os.environ.setdefault("TQ_AUTH_ENABLED", "false")
    import main  # import perezoso: monta la app entera

    ignorar = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
    rutas: dict[str, set[str]] = {}
    for r in main.app.routes:
        path = getattr(r, "path", None)
        if not path or path in ignorar:
            continue
        metodos = {m for m in (getattr(r, "methods", set()) or set())
                   if m not in ("HEAD", "OPTIONS")}
        rutas.setdefault(path, set()).update(metodos)
    return rutas


# ── Eslabón 1: endpoint → alguna referencia en el frontend ────────────────────

def test_todo_endpoint_tiene_consumidor_o_excusa_escrita():
    """H-10: 5 endpoints de F7 sin consumidor pasaron el gate de su fase.

    Este test es lo que habría fallado entonces. No exige que TODO endpoint tenga
    UI —hay entradas legítimas de scripting— sino que la ausencia esté DECLARADA,
    con motivo y fase dueña, en vez de descubrirse dos auditorías después.
    """
    web = "\n".join(txt for _, txt in _leer_web(_WEB_SCAN_DIRS))
    rutas = _rutas_del_backend()

    sin_consumidor = []
    for path in sorted(rutas):
        # El prefijo estable de la ruta (antes de cualquier parámetro de path).
        base = path.split("{")[0].rstrip("/")
        if base and base != "/" and base in web:
            continue
        if path in RUTAS_SIN_UI_TOLERADAS:
            continue
        sin_consumidor.append(f"{sorted(rutas[path])} {path}")

    assert not sin_consumidor, (
        "Endpoints sin ningún consumidor en el frontend y sin excusa declarada.\n"
        "O se les da camino de usuario, o se añaden a RUTAS_SIN_UI_TOLERADAS con "
        "motivo y fase dueña:\n  " + "\n  ".join(sin_consumidor)
    )


def test_la_lista_de_rutas_toleradas_es_portante():
    """Cada excusa tiene que corresponder a una ruta REAL y sin consumidor.

    Sin esto la lista se pudre: una ruta que desaparece o que gana UI se quedaría
    tolerada para siempre y el guard perdería fuerza en silencio.
    """
    web = "\n".join(txt for _, txt in _leer_web(_WEB_SCAN_DIRS))
    rutas = _rutas_del_backend()

    for path, motivo in RUTAS_SIN_UI_TOLERADAS.items():
        assert path in rutas, f"{path} ya no existe en la app: quítala de la lista."
        assert motivo.strip(), f"{path} tolerada sin motivo escrito."
        base = path.split("{")[0].rstrip("/")
        assert base not in web, (
            f"{path} YA tiene consumidor en el frontend: quítala de "
            "RUTAS_SIN_UI_TOLERADAS (la excusa ya no describe la realidad)."
        )


# ── Eslabón 2: proxy Next → algún llamador ────────────────────────────────────

def test_todo_proxy_next_tiene_llamador():
    """Un proxy sin llamador es un endpoint sin UI con un paso más.

    Medido en la Fase 9: `/api/backend-health` y `/api/system-check` existían y no
    los llamaba **ningún** componente — sólo el shell de Tauri y un smoke test.
    Tener proxy parecía tener camino de usuario, y no lo era.
    """
    api_dir = WEB_ROOT / "app" / "api"
    consumidores = "\n".join(txt for _, txt in _leer_web(("lib", "componentes", "store", "workers")))

    sin_llamador = []
    for route_file in sorted(api_dir.rglob("route.ts")):
        ruta = "/api/" + route_file.parent.relative_to(api_dir).as_posix()
        if ruta in consumidores:
            continue
        if ruta in PROXIES_SIN_LLAMADOR_TOLERADOS:
            continue
        sin_llamador.append(ruta)

    assert not sin_llamador, (
        "Proxies de Next que ningún componente ni cliente llama:\n  "
        + "\n  ".join(sin_llamador)
    )


def test_la_lista_de_proxies_tolerados_es_portante():
    api_dir = WEB_ROOT / "app" / "api"
    existentes = {
        "/api/" + f.parent.relative_to(api_dir).as_posix()
        for f in api_dir.rglob("route.ts")
    }
    consumidores = "\n".join(txt for _, txt in _leer_web(("lib", "componentes", "store", "workers")))
    for ruta, motivo in PROXIES_SIN_LLAMADOR_TOLERADOS.items():
        assert ruta in existentes, f"{ruta} ya no existe: quítalo de la lista."
        assert motivo.strip(), f"{ruta} tolerado sin motivo escrito."
        assert ruta not in consumidores, (
            f"{ruta} YA tiene llamador: quítalo de PROXIES_SIN_LLAMADOR_TOLERADOS."
        )


# ── Eslabón 3: componente → montado (el que la Fase 6 encontró roto) ──────────

def test_ningun_componente_queda_sin_montar():
    """«UI escrita y nunca montada» — el hallazgo del cierre de la Fase 6.

    `SliceControls`, `MultiPhysicsControls` y `MultimodalComboPanel` estaban
    terminados, compilaban y tenían el backend respondiendo detrás. No había
    absolutamente nada que los importara, así que el usuario no podía llegar a
    ellos: el plano de corte tipo Leapfrog existía de punta a punta y nada lo
    encendía. Este test lo mide en vez de nombrarlo, así que también caza el
    próximo panel que alguien escriba y olvide montar.
    """
    componentes = [
        f for f in (WEB_ROOT / "componentes").rglob("*.tsx")
        if "node_modules" not in f.parts
    ]
    fuentes = _leer_web(("app", "lib", "componentes", "store", "workers"))

    huerfanos = []
    for f in componentes:
        stem = re.escape(f.stem)
        # Import estático o dinámico que termine en el nombre del módulo.
        patron = re.compile(
            rf'(?:from|import\()\s*["\'][^"\']*/{stem}["\']'
        )
        if any(otro != f and patron.search(txt) for otro, txt in fuentes):
            continue
        huerfanos.append(str(f.relative_to(WEB_ROOT)))

    assert not huerfanos, (
        "Componentes sin ningún importador: están escritos y el usuario NO puede "
        "llegar a ellos (el patrón que la Fase 6 midió y la Fase 9 cerró).\n  "
        + "\n  ".join(huerfanos)
    )


def test_la_superficie_f7_tiene_camino_de_usuario():
    """El cierre concreto de H-10, afirmado por nombre.

    Los tests de arriba miden la propiedad general; éste ancla el caso que dio
    origen a la fase, para que un refactor que borre la vista de Sistema falle
    diciendo POR QUÉ importa y no sólo «un componente perdió su importador».
    """
    web = "\n".join(txt for _, txt in _leer_web(_WEB_SCAN_DIRS))
    for ruta in (
        "/license/status",
        "/license/activate",
        "/diagnostics/manifest",
        "/diagnostics/export",
        "/system/connectivity",
    ):
        assert ruta in web, f"{ruta} volvió a quedarse sin interfaz (H-10)."

    # Y no basta con el proxy: tiene que haber componente que lo use.
    componentes = "\n".join(txt for _, txt in _leer_web(("componentes",)))
    for llamada in ("getLicenseStatus", "activateLicense", "getConnectivity",
                    "getDiagnosticManifest", "DIAGNOSTICS_EXPORT_URL"):
        assert llamada in componentes, (
            f"`{llamada}` no lo usa ningún componente: el proxy existiría y la "
            "capacidad seguiría siendo inalcanzable."
        )
