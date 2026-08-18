"""FASE 11 — Los datasets canónicos por el camino del usuario.

El informe propone esto como estrategia de pruebas de la fase: *«un script que
corra los datasets canónicos de punta a punta es simultáneamente el ejemplo de la
documentación y un test E2E»*. Aquí está, y lo ejecuta también
`tests/test_fase11_api_scripting.py`.

Ojo con lo que este script NO demuestra: recorrer el camino no es validar la
física. La validación de los benchmarks vive en la suite F9
(`pytest -m validation`), que compara contra verdad publicada con tolerancias
medidas. Esto comprueba que **la ruta del consultor llega hasta el final** con
dato real y sucio, que es otra cosa y también hace falta.

    cd terraquantum-backend
    python examples/02_datasets_canonicos.py
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import terraquantum as tq  # noqa: E402

RAIZ = tq.backend_root().parent
FIXTURES = tq.backend_root() / "tests/fixtures/csv_reales"

#: Configuración COMPARTIDA por los cuatro: vacía. No es pereza — es el modo en
#: que un consultor procesa un lote: la malla y la profundidad las deriva el
#: auto-grid **de cada survey**, que es lo único que puede acertar cuando los
#: surveys tienen extensiones distintas.
#:
#: MEDIDO por qué NO se fija una malla común. Fijar `nx/ny/nz` sin fijar `depth`
#: parece lo natural y **está roto en los dos extremos del lote**:
#:   · DO-27 mini con `depth=900` → rechazo: «profundidad máxima física: 224 m».
#:   · Laguna del Maule con malla 8×8×6 y `depth` automático → rechazo:
#:     «depth=5023 m … máxima física: 4160 m».
#: La causa es que `load-package` toma `nx/ny/nz` del paquete pero `depth` del
#: auto-grid, que se calculó para OTRA malla. Ninguna de las dos entradas es
#: inválida por separado; la combinación sí. Queda anotado como hallazgo de la
#: fase, no parcheado aquí: es conducta del backend, no de esta API.
MALLA: dict = {}

#: Modo rápido (`--rapido`, el que usa la suite): malla chica CON su profundidad
#: por dataset, justamente porque las dos van juntas.
MALLA_RAPIDA = {"nx": 6, "ny": 6, "nz": 5}

#: Los cuatro canónicos, con la procedencia del dato y su estado en el repositorio.
#: `csv=None` no significa «no lo probamos»: significa **no se puede** desde aquí,
#: con el motivo escrito. Es la misma disciplina que `DatosNoVersionados` en el
#: gate F9 — ni llamar fallo a lo que no se midió, ni PASS a una suite incompleta.
CANONICOS = [
    {
        "nombre": "Laguna del Maule (Chile)",
        "fisica": "gravity",
        "csv": FIXTURES / "LdM_gravimetria_CRUDO_usuario.csv",
        "config": {"utm_zone": "19S"},
        "rapido": {"depth": 1200},
        "nota": "CSV crudo de Excel-ES: preámbulo, ';', coma decimal, cabeceras en español.",
    },
    {
        "nombre": "DO-27 kimberlita (Canadá)",
        "fisica": "gravity",
        "csv": FIXTURES / "do27_gravity_LISTO_mini.csv",
        "config": {},
        "rapido": {"depth": 150},
        "nota": "Submuestreo del paquete UBC-GIF publicado.",
    },
    {
        "nombre": "Raglan Ni-Cu (Canadá)",
        "fisica": "magnetic",
        "csv": RAIZ / "Raglan_Magnetic" / "Raglan_Magnetic_TMI_nT.csv",
        "config": {},
        "rapido": {"depth": 600},
        # ⚠️ Este mapeo NO es cosmético: sin él, el dataset se corrompe EN
        # SILENCIO. Ver el hallazgo H-F11-1 al pie de este archivo.
        "column_map": {"x": "X", "y": "Y", "elevation": "Z",
                       "magnetic_value": "TMI_nT", "sigma": "Std_nT"},
        "nota": "TMI de campo CRUDO. Exige column_map explícito (ver hallazgo al pie).",
    },
    {
        "nombre": "San Nicolás VMS (México)",
        "fisica": "gravity",
        "csv": None,
        "config": {},
        "rapido": {},
        "nota": (
            "NO EVALUABLE por esta vía: el dato es `data/external/san_nicolas/"
            "realdata.mat`, que ni está versionado (`data/` va en .gitignore) ni "
            "es un CSV — y el repositorio no tiene conversor de .mat. La suite F9 "
            "lo cubre re-invirtiendo sus observaciones guardadas."
        ),
    },
]


def procesar(caso: dict, sesion: tq.Session, *, rapido: bool = False) -> dict:
    """Un dataset por el camino del usuario. Devuelve SIEMPRE un dict, con
    `estado` en {done, no_evaluado, error}: un fallo de un dataset no puede
    llevarse por delante el informe de los otros tres."""
    if caso["csv"] is None or not pathlib.Path(caso["csv"]).is_file():
        return {"estado": "no_evaluado", "motivo": caso["nota"]}
    config = {**(MALLA_RAPIDA if rapido else MALLA), **caso["config"]}
    if rapido:
        config.update(caso.get("rapido") or {})
    t0 = time.perf_counter()
    try:
        paquete = tq.enrich(session=sesion, config=config, enable_dem=False,
                            column_map=caso.get("column_map"),
                            **{caso["fisica"]: caso["csv"]})
        corrida = tq.run_inversion(
            paquete, session=sesion,
            project_id="canonico_" + caso["nombre"].split()[0].lower(),
            run_id="api_v0",
        )
    except tq.TerraquantumError as exc:
        return {"estado": "error", "code": exc.code, "motivo": exc.message,
                "segundos": round(time.perf_counter() - t0, 1)}
    return {
        "estado": corrida.status,
        "ruta": corrida.route,
        "estaciones": paquete.n_stations,
        "veredicto": (corrida.verdict or {}).get("level"),
        "chi2": corrida.chi2,
        "misfit_pct": corrida.misfit_pct,
        "avisos": len(paquete.warnings),
        "sin_derivar": len(paquete.needs_context),
        "segundos": round(time.perf_counter() - t0, 1),
    }


def main(rapido: bool = False) -> list:
    sesion = tq.Session()
    salidas = []
    for caso in CANONICOS:
        salida = procesar(caso, sesion, rapido=rapido)
        salidas.append((caso, salida))
        print(f"\n■ {caso['nombre']}  [{caso['fisica']}]")
        if salida["estado"] == "no_evaluado":
            print(f"  NO EVALUADO — {salida['motivo']}")
            continue
        if salida["estado"] == "error":
            print(f"  ERROR [{salida['code']}] — {salida['motivo'][:160]}")
            continue
        print(f"  {salida['estaciones']} estaciones → ruta {salida['ruta']}, "
              f"{salida['estado']} en {salida['segundos']} s")
        print(f"  veredicto {salida['veredicto']} · χ² {salida['chi2']} · "
              f"misfit {salida['misfit_pct']}% · "
              f"{salida['avisos']} avisos · {salida['sin_derivar']} sin derivar")
        print(f"  ({caso['nota']})")
    return salidas


if __name__ == "__main__":
    main(rapido="--rapido" in sys.argv)


# ═════════════════════════════════════════════════════════════════════════════
# LO QUE ENCONTRÓ ESTE SCRIPT (Fase 11) — dos defectos del backend, medidos
# ═════════════════════════════════════════════════════════════════════════════
#
# El informe decía que la API de scripting «se vuelve el mejor test de
# integración del proyecto». Lo fue el primer día. Ninguno es de esta API — los
# dos están en el backend, y los dos se reproducen con tres líneas.
#
# H-F11-1 · Un CSV `X,Y,Z` corrompe la geometría EN SILENCIO  🔴 ALTO
#   `X,Y,Z` es el encabezado de los DOS benchmarks magnéticos publicados. El
#   auto-mapeo devuelve `{x: X, y: Z, depth: Y}`: el NORTHING queda en el rol
#   PROFUNDIDAD y la elevación constante en el rol norte. Existe una guarda para
#   exactamente esto (`northing_in_depth_slot`, column_mapping_service) y su
#   umbral es `> 1e5 m`:
#     · DO-27  — northing 7,1e6 → LA GUARDA DISPARA (`needs_confirmation=True`).
#     · Raglan — northing 4,1e4 → **NO dispara**. `needs_mapping=False`,
#       `needs_confirmation=False`, `suspicions=[]`. Silencio absoluto.
#   Consecuencia medida: área degenerada → `El kernel magnético G_active quedó
#   vacío. Revisa cutoff_radius…`, un mensaje que apunta al sitio equivocado.
#   El umbral asume coordenadas UTM; Raglan las tiene LOCALES (496–4504 m).
#
# H-F11-2 · El auto-grid propone mallas que el esquema rechaza  🟠 MEDIO
#   Con el mapeo YA correcto, el auto-grid de Raglan propone `nx=82, nz=81` y
#   `GeophysicsInvertInput` exige `≤ 80`. El usuario recibe un error CRUDO de
#   Pydantic con una URL de errors.pydantic.dev, no un mensaje del catálogo.
#   La asimetría está a la vista en `load-package::_eff_dim`: acota el valor del
#   USUARIO a 1..80 y devuelve el AUTOMÁTICO sin acotar.
#
# Ninguno se arregla aquí a propósito: son conducta de la ingesta y del esquema,
# no de esta API, y tocarlos cambia el camino dorado de todos los usuarios. Van
# declarados en `docs/06` y pinchados por tests de caracterización en
# `tests/test_fase11_api_scripting.py`, que se pondrán rojos el día que alguien
# los arregle — que es cuando hay que volver a este comentario y borrarlo.
