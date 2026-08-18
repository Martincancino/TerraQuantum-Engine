"""TerraQuantum — API de scripting para el consultor experto (FASE 11).

El pipeline completo desde Python, sin abrir la interfaz:

    import terraquantum as tq

    paquete = tq.enrich(gravity="survey.csv", config={"utm_zone": "19S"})
    corrida = tq.run_inversion(paquete, project_id="cerro_x")

    print(corrida.verdict["level"])          # veredicto reconciliado
    print(corrida.best_target)               # dónde perforar, con procedencia
    print(corrida.depth_resolution)          # y qué NO resuelve el dato
    corrida.save_bundle("entrega/")          # el ZIP del gabinete

Y el caso que motivó la fase — doce surveys con la misma configuración:

    corridas = tq.batch(
        [{"name": f"s{i}", "gravity": f"surveys/s{i}.csv"} for i in range(1, 13)],
        config={"utm_zone": "19S", "nx": 24, "ny": 24, "nz": 16},
    )

## Qué es y qué no es

**Es un CLIENTE del backend**, no una segunda implementación. Por defecto monta
la app en el propio proceso (ni servidor, ni puerto, ni red) y la recorre por
los MISMOS endpoints que usa la interfaz web. Consecuencia comprobada por un
test: cuando cambia el motor, cambian las dos a la vez.

**No hay física aquí.** Ni un cálculo, ni un umbral, ni un valor por defecto
propio: los defaults son los del backend, que es donde están medidos. Esta capa
traduce diccionarios de Python a `multipart/form-data` y respuestas a objetos.

## Versión y promesa de estabilidad

`API_VERSION = "0"`. **v0 significa que las firmas pueden cambiar**, y está
declarado a propósito: publicar una API es un compromiso, y prometer estabilidad
antes de que la use alguien es prometer de más. Lo que sí se promete en v0, y lo
que hará falta para llegar a v1, está escrito en `docs/08_API_SCRIPTING.md` —
un test comprueba que ese documento existe y que nombra esta misma versión.

## Cómo se importa

El módulo vive dentro del backend, que es quien tiene el motor:

    import sys; sys.path.insert(0, "<ruta>/terraquantum-backend")
    import terraquantum as tq

    # o, equivalente:  cd terraquantum-backend && python mi_script.py

Ejemplos ejecutables en `terraquantum-backend/examples/`.
"""
from __future__ import annotations

from . import admin
from ._package import ColumnPlan, Package
from ._pipeline import (
    DATA_TYPES,
    analyze_columns,
    batch,
    default_session,
    enrich,
    estimate_depth,
    invert_direct,
    invert_field_csv,
    list_runs,
    open_run,
    parse_rows,
    run_inversion,
    set_default_session,
)
from ._run import ESTADO_OK, ESTADOS_TERMINALES, Run
from ._session import RATE_LIMIT_POLICIES, Session, backend_root
from .errors import (
    InversionFailed,
    NeedsColumnMapping,
    RateLimited,
    RunTimeout,
    TerraquantumError,
)

#: Versión de ESTA API (no del backend: `Session.health()` da la del backend).
#: "0" = superficie en observación, las firmas pueden cambiar. Ver
#: `docs/08_API_SCRIPTING.md`, que es la promesa escrita.
API_VERSION = "0"

#: Documento con la promesa de estabilidad, relativo a la raíz del repositorio.
STABILITY_DOC = "docs/08_API_SCRIPTING.md"

__all__ = [
    # versión y promesa
    "API_VERSION",
    "STABILITY_DOC",
    # sesión
    "Session",
    "RATE_LIMIT_POLICIES",
    "default_session",
    "set_default_session",
    "backend_root",
    # camino dorado
    "analyze_columns",
    "parse_rows",
    "enrich",
    "run_inversion",
    "batch",
    "invert_field_csv",
    "invert_direct",
    "estimate_depth",
    # historial
    "open_run",
    "list_runs",
    # objetos
    "Package",
    "ColumnPlan",
    "Run",
    "ESTADO_OK",
    "ESTADOS_TERMINALES",
    "DATA_TYPES",
    # errores
    "TerraquantumError",
    "NeedsColumnMapping",
    "RateLimited",
    "InversionFailed",
    "RunTimeout",
    # administración
    "admin",
]
