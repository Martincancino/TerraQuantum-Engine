"""FASE 11 — El camino dorado, en funciones.

Cada función de aquí es un endpoint del backend con los papeles cambiados: el
script escribe diccionarios de Python y recibe objetos, en vez de armar
`multipart/form-data` y adivinar qué clave del JSON mirar. **No hay física, ni
decisiones, ni valores por defecto propios**: los defaults son los del backend,
que es donde están medidos.

El orden del camino dorado:

    analyze_columns()   ¿cómo se van a leer mis columnas?      (no invierte)
    enrich()            → Package (TQPKG: config + dato + plan)
    run_inversion()     → Run (modelo 3D persistido)
    batch()             lo mismo, N veces, con la misma configuración
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ._package import ColumnPlan, Package
from ._run import Run
from ._session import Session, as_json_form, csv_payload
from .errors import NeedsColumnMapping, TerraquantumError

#: Físicas que el pipeline acepta como dato primario. Los dos valores se
#: ejercitan en la suite (criterio 3 de la plantilla de gate).
DATA_TYPES = ("gravity", "magnetic")

_ENRICH = "/v2/gravity-import/enrich-package"
_ANALYZE = "/v2/gravity-import/analyze-columns"
_PARSE_ROWS = "/v2/gravity-import/parse-rows"
_LOAD = "/v2/gravity-import/load-package"
_FIELD = "/v2/gravity-import/invert-with-corrections"
_DEPTH = "/v2/depth-estimate"


# ─────────────────────────────────────────────────────────────────────────────
# Paso 0 — mirar las columnas sin invertir
# ─────────────────────────────────────────────────────────────────────────────
def analyze_columns(csv: Any, *, data_type: str = "gravity",
                    column_map: Optional[Mapping[str, Any]] = None,
                    session: Optional[Session] = None) -> ColumnPlan:
    """Cómo se van a interpretar las columnas de un CSV. No invierte nada.

    El paso que ahorra el lote entero: se mira UNA planilla, se fija el
    `column_map` y se reutiliza en los N surveys que vienen con el mismo
    formato de exportación.
    """
    _validar_data_type(data_type)
    ses = session or default_session()
    nombre, cuerpo = csv_payload(csv, nombre_por_defecto="survey.csv")
    datos: Dict[str, Any] = {}
    if column_map is not None:
        datos["column_map_json"] = as_json_form(dict(column_map))
    respuesta = ses.post(
        _ANALYZE,
        files={"file": (nombre, cuerpo, "text/csv")},
        params={"data_type": data_type},
        data=datos or None,
    )
    return ColumnPlan(
        mapping=dict(respuesta.get("column_mapping") or {}),
        sniff=dict(respuesta.get("sniff_report") or {}),
        sample_rows=list(respuesta.get("sample_rows") or []),
    )


def parse_rows(csv: Any, *, max_rows: int = 50_000,
               session: Optional[Session] = None) -> List[dict]:
    """Las filas del CSV YA parseadas por el pipeline oficial.

    Con los valores canónicos (punto decimal), el preámbulo saltado y el
    encoding resuelto. Existe para que nadie vuelva a parsear un CSV chileno a
    mano: `float("1,23")` no falla, devuelve 1.
    """
    ses = session or default_session()
    nombre, cuerpo = csv_payload(csv, nombre_por_defecto="survey.csv")
    respuesta = ses.post(
        _PARSE_ROWS,
        files={"file": (nombre, cuerpo, "text/csv")},
        params={"max_rows": max_rows},
    )
    return list(respuesta.get("rows") or [])


# ─────────────────────────────────────────────────────────────────────────────
# Paso 1 — preparar y enriquecer
# ─────────────────────────────────────────────────────────────────────────────
def enrich(
    gravity: Any = None,
    *,
    magnetic: Any = None,
    boreholes: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[Mapping[str, Any]] = None,
    column_map: Optional[Mapping[str, Any]] = None,
    magnetic_column_map: Optional[Mapping[str, Any]] = None,
    helmert_control_points: Optional[Any] = None,
    enable_dem: bool = True,
    strict: bool = False,
    allow_g_raw: bool = True,
    session: Optional[Session] = None,
) -> Package:
    """CSV(s) crudos → paquete TQPKG completo, derivando con física real.

    Completa elevación desde un DEM, reduce gravedad cruda a anomalía de
    Bouguer (GRS80/FAC/BC), reconstruye lat/lon desde UTM con `pyproj`, resuelve
    el IGRF offline y decide la ruta multimodal. **Lo que no puede derivar no lo
    inventa**: queda en `Package.needs_context`.

    Se le pasa gravimetría, magnetometría, o las dos (joint). Los sondajes
    ANCLAN: no definen una inversión por sí solos y el backend rechaza un
    paquete que sólo los traiga.

    Si la auto-detección no reconoce los roles requeridos, sube
    `NeedsColumnMapping` con el plan adjunto — la PREGUNTA del Pilar 1, no un
    fallo. Se responde volviendo a llamar con `column_map={rol: columna}`.
    """
    if gravity is None and magnetic is None:
        raise TerraquantumError(
            "Hace falta al menos un campo potencial: gravity= y/o magnetic=.",
            code="INSUFFICIENT_DATA",
            suggested_action=(
                "Un CSV de sólo sondajes no define una inversión. Pásalos con "
                "boreholes= junto a gravimetría o magnetometría."
            ),
        )
    ses = session or default_session()
    archivos: Dict[str, Any] = {}
    if gravity is not None:
        nombre, cuerpo = csv_payload(gravity, nombre_por_defecto="gravimetria.csv")
        archivos["gravity_file"] = (nombre, cuerpo, "text/csv")
    if magnetic is not None:
        nombre, cuerpo = csv_payload(magnetic, nombre_por_defecto="magnetometria.csv")
        archivos["magnetic_file"] = (nombre, cuerpo, "text/csv")

    datos: Dict[str, Any] = {}
    for clave, valor in (
        ("config_json", dict(config) if config else None),
        ("boreholes_json", [dict(b) for b in boreholes] if boreholes else None),
        ("column_map_json", dict(column_map) if column_map else None),
        ("magnetic_column_map_json", dict(magnetic_column_map) if magnetic_column_map else None),
        ("helmert_control_points_json", helmert_control_points),
    ):
        serializado = as_json_form(valor)
        if serializado is not None:
            datos[clave] = serializado

    respuesta = ses.post(
        _ENRICH,
        files=archivos,
        data=datos or None,
        params={
            "data_type": "gravity" if gravity is not None else "magnetic",
            "strict": str(bool(strict)).lower(),
            "allow_g_raw": str(bool(allow_g_raw)).lower(),
            "enable_dem": str(bool(enable_dem)).lower(),
        },
    )

    # 200 sin paquete: el pipeline PREGUNTA. Nunca un valor plausible en su lugar.
    if respuesta.get("needs_mapping"):
        raise NeedsColumnMapping(
            str(respuesta.get("message") or "Falta el mapeo de columnas."),
            plan=dict(respuesta.get("column_mapping") or {}),
            sample_rows=list(respuesta.get("sample_rows") or []),
            path=_ENRICH,
        )
    texto = respuesta.get("package_text")
    if not texto:
        raise TerraquantumError(
            "El enriquecimiento no devolvió paquete ni pregunta de mapeo.",
            code="ENRICH_NO_PACKAGE",
            details=respuesta if isinstance(respuesta, dict) else {},
            path=_ENRICH,
            suggested_action="Revisa `needs_context` y los avisos de la respuesta.",
        )
    return Package(
        text=texto,
        filename=str(respuesta.get("filename") or "package.tqpkg.csv"),
        n_stations=int(respuesta.get("n_stations") or 0),
        plan=dict(respuesta.get("plan") or {}),
        enrichment=dict(respuesta.get("enrichment_summary") or {}),
        warnings=list(respuesta.get("warnings") or []),
        needs_context=list(respuesta.get("needs_context") or []),
        sniff=dict(respuesta.get("sniff_report") or {}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Paso 2 — invertir
# ─────────────────────────────────────────────────────────────────────────────
def run_inversion(
    package: Any,
    *,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    wait: bool = True,
    timeout_s: float = 3600.0,
    poll_s: float = 2.0,
    on_progress: Optional[Any] = None,
    session: Optional[Session] = None,
) -> Run:
    """Paquete TQPKG → modelo 3D persistido.

    `wait=True` (por defecto) usa el camino SÍNCRONO del endpoint: sin proxy en
    medio, un script no necesita la vía asíncrona, y el error del solver llega
    con su código de catálogo en la misma llamada.

    `wait=False` ENCOLA en un worker de proceso y devuelve al instante; el
    progreso se sigue con `Run.wait()` o `Run.status_now()`.

    **El compromiso entre las dos, MEDIDO**, porque no es obvio y afecta a lo
    que el usuario ve después:

    ==================  =========================  ==========================
    .                   `wait=True` (síncrono)     `wait=False` (cola)
    ==================  =========================  ==========================
    Script mínimo       sí                         **exige guard `__main__`**
    Cancelable          no                         sí (`Run.cancel()`)
    Progreso por etapas no                         sí (`on_progress`)
    Sale en «Historial» **NO** — ver abajo         sí
    ==================  =========================  ==========================

    Lo de la última fila es un hallazgo de esta fase: la rama síncrona escribe
    `schedule.json` pero **no llama a `project_store.record_run`**, así que la
    corrida no entra en la base del historial y la pantalla que lo lista sale
    vacía. El modelo sí queda en disco y `open_run()` lo recupera. Está
    declarado en `docs/08_API_SCRIPTING.md` §6 y pinchado por un test; el
    default sigue siendo el síncrono porque el criterio de aceptación de la
    fase es que un script de veinte líneas funcione sin ceremonias.

    ⚠️ **`wait=False` exige que el script tenga el guard
    `if __name__ == "__main__":`**. El worker se lanza con `multiprocessing` en
    modo *spawn*, y spawn RE-IMPORTA el módulo principal en el hijo. MEDIDO sin
    el guard, en este orden: el encolado del padre responde `queued`; el hijo
    re-ejecuta el script entero (aparece como `__mp_main__`); su propio encolado
    muere en el `RuntimeError` del `freeze_support()`; y la corrida del padre
    acaba en **`interrumpida`** («El proceso de inversión terminó sin estado
    final»). Es una restricción de la biblioteca estándar de Python, no algo que
    esta API pueda arreglar — lo que sí hace es traducir ese fallo a
    `SPAWN_REQUIRES_MAIN_GUARD` con su acción, en vez de dejarlo salir como un
    `TQ_INTERNAL` con un traceback dentro.
    """
    ses = session or default_session()
    texto, nombre = _texto_de_paquete(package)
    datos: Dict[str, Any] = {"sync": "true" if wait else "false"}
    if project_id:
        datos["project_id"] = project_id
    if run_id:
        datos["run_id"] = run_id

    try:
        respuesta = ses.post(
            _LOAD,
            files={"file": (nombre, texto, "text/csv")},
            data=datos,
        )
    except TerraquantumError as exc:
        raise _traducir_fallo_de_spawn(exc, wait=wait) from exc

    estado = str(respuesta.get("status") or "")
    corrida = Run(
        ses,
        str(respuesta.get("project_id") or project_id or ""),
        str(respuesta.get("run_id") or run_id or ""),
        route=respuesta.get("route"),
        status=estado or None,
        warnings=list(respuesta.get("warnings") or []),
        budget=dict(respuesta.get("budget") or {}),
        plan=dict(respuesta.get("multimodal_plan") or {}),
        inversion_result=dict(respuesta.get("inversionResult") or {}),
    )

    # `status: "error"` con HTTP 200 es una forma real de la respuesta (fallo de
    # importación del cuerpo del paquete). No se deja pasar como éxito.
    if estado == "error":
        raise TerraquantumError(
            "; ".join(str(e) for e in (respuesta.get("errors") or []))
            or "La carga del paquete falló en la etapa de importación.",
            code="PACKAGE_IMPORT_FAILED",
            details=respuesta if isinstance(respuesta, dict) else {},
            path=_LOAD,
        )
    if wait and estado != "done":
        # Camino síncrono que no acabó: se espera igualmente, nunca se supone.
        corrida.wait(timeout_s=timeout_s, poll_s=poll_s, on_progress=on_progress)
    return corrida


def batch(
    surveys: Iterable[Mapping[str, Any]],
    *,
    config: Optional[Mapping[str, Any]] = None,
    project_prefix: str = "lote",
    stop_on_error: bool = False,
    session: Optional[Session] = None,
    **enrich_kwargs: Any,
) -> List[Any]:
    """*«Procesa estos 12 surveys con la misma configuración.»*

    Es la frase con la que el informe justifica esta fase, así que es una
    función y tiene un test que corre doce.

    Cada elemento de `surveys` es un dict con las mismas claves que `enrich`
    (`gravity`, `magnetic`, `boreholes`, `column_map`…) más un `name` opcional
    que se usa para el `project_id`. `config` se aplica a TODOS — es el punto
    del lote — y cada survey puede sobreescribirla con su propio `config`.

    Devuelve una lista con un `Run` por survey en el mismo orden. Con
    `stop_on_error=False` (por defecto) un survey que falla deja en su posición
    la excepción en vez de abortar el lote: procesar once de doce y saber cuál
    falló es más útil que perder las once. Con `stop_on_error=True` sube la
    primera excepción.
    """
    ses = session or default_session()
    resultados: List[Any] = []
    for indice, survey in enumerate(surveys):
        entrada = dict(survey)
        nombre = str(entrada.pop("name", "") or f"{indice + 1:02d}")
        cfg = {**(config or {}), **(entrada.pop("config", None) or {})}
        pid = entrada.pop("project_id", None) or _id_seguro(f"{project_prefix}_{nombre}")
        rid = entrada.pop("run_id", None) or f"run_{uuid.uuid4().hex[:12]}"
        try:
            paquete = enrich(session=ses, config=cfg, **{**enrich_kwargs, **entrada})
            resultados.append(
                run_inversion(paquete, project_id=pid, run_id=rid, session=ses)
            )
        except Exception as exc:  # noqa: BLE001 — el lote informa, no se rinde
            if stop_on_error:
                raise
            resultados.append(exc)
    return resultados


def invert_field_csv(
    csv: Any,
    *,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    gravimeter_type: str = "unknown",
    reduction_density: float = 2.67,
    apply_terrain: bool = True,
    terrain_radius: float = 22000.0,
    dem_type: str = "COP30",
    noise_pct: float = 0.0,
    session: Optional[Session] = None,
    **grid: Any,
) -> Run:
    """Gravimetría de campo CRUDA → correcciones + inversión, en una llamada.

    (`POST /v2/gravity-import/invert-with-corrections`, la entrada síncrona que
    la Fase 9 declaró «superficie natural del scripting».)

    Aplica FAC/BC/TC/GRS80 con `reduction_density` cuando el `gravity_type` del
    CSV es crudo, y deriva σ del tipo de gravímetro
    (`scintrex_cg6`=0.005 mGal, `zls_burris`=0.002, `lacoste_romberg`=0.010,
    `unknown`=0.020). Si el CSV ya trae anomalía, **no la vuelve a reducir**.

    A diferencia de `enrich()`+`run_inversion()`, aquí no hay paquete TQPKG
    intermedio: es más corto y menos reproducible. Para un lote que hay que
    poder repetir dentro de un año, el camino del paquete es el bueno.
    """
    ses = session or default_session()
    nombre, cuerpo = csv_payload(csv, nombre_por_defecto="campo.csv")
    datos: Dict[str, Any] = {
        "gravimeter_type": gravimeter_type,
        "reduction_density": reduction_density,
        "apply_terrain": str(bool(apply_terrain)).lower(),
        "terrain_radius": terrain_radius,
        "dem_type": dem_type,
        "noise_pct": noise_pct,
    }
    if project_id:
        datos["project_id"] = project_id
    if run_id:
        datos["run_id"] = run_id
    for clave, valor in grid.items():
        datos[clave] = valor

    respuesta = ses.post(_FIELD, files={"file": (nombre, cuerpo, "text/csv")}, data=datos)
    corrida = Run(
        ses,
        str(respuesta.get("project_id") or project_id or ""),
        str(respuesta.get("run_id") or run_id or ""),
        warnings=list(respuesta.get("warnings") or []),
        inversion_result=dict(
            respuesta.get("inversionResult") or respuesta.get("inversion_result") or {}
        ),
    )
    # MEDIDO: esta ruta contesta `status: "success"`, un vocabulario distinto del
    # de la máquina de estados F3 (`queued/running/done/error/cancelled/
    # interrumpida`) que usan `/geophysics-status` y el historial. Traducir
    # "success"→"done" aquí sería inventarse una equivalencia; en su lugar se
    # pregunta al canal canónico, que es el mismo que mira la interfaz. Si esa
    # consulta falla, el estado queda como lo dijo el endpoint — nunca ascendido.
    try:
        corrida.status_now()
    except TerraquantumError:
        corrida.status = str(respuesta.get("status") or "")
    return corrida


def invert_direct(
    params: Mapping[str, Any],
    *,
    wait: bool = True,
    timeout_s: float = 3600.0,
    poll_s: float = 2.0,
    session: Optional[Session] = None,
) -> Run:
    """Entrada DIRECTA al motor, con el payload completo de la inversión.

    (`POST /v2/geophysics-invert`, la tercera ruta que la Fase 9 declaró
    «superficie natural del scripting»: *«entrada directa al motor con payload
    completo; el camino de usuario pasa por el paquete»*.)

    Aquí no hay CSV, ni enriquecimiento, ni auto-grid: se entregan las
    observaciones y la malla ya decididas. Es la vía para lo que la interfaz no
    permite y un experto sí quiere — barrer λ, repetir una corrida cambiando un
    solo parámetro, comparar dos regularizaciones sobre el MISMO dato.

    `params` es el esquema `GeophysicsInvertInputV2` tal cual; se pasa sin
    tocar. Dos cosas medidas que conviene saber:

    * `lambda_strategy="lcurve"` se **rechaza** con
      `LAMBDA_STRATEGY_UNAVAILABLE` (Fase 1/H-37b): prometía la esquina de la
      L-curve y caía en la misma rama que `chi2`. No es un fallo de esta API.
    * El endpoint responde `queued` y resuelve en una tarea de fondo. Con
      `wait=True` se espera por el canal de estado, que es donde vive la verdad.

    Para el camino normal —CSV del cliente → modelo— usa `enrich` +
    `run_inversion`: ahí el paquete deja el experimento reproducible.
    """
    ses = session or default_session()
    respuesta = ses.post("/v2/geophysics-invert", json_body=dict(params))
    corrida = Run(
        ses,
        str(respuesta.get("project_id") or params.get("project_id") or "default"),
        str(respuesta.get("run_id") or params.get("run_id") or ""),
        status=str(respuesta.get("status") or "queued"),
    )
    if wait:
        corrida.wait(timeout_s=timeout_s, poll_s=poll_s)
    return corrida


# ─────────────────────────────────────────────────────────────────────────────
# Estimaciones independientes de la inversión
# ─────────────────────────────────────────────────────────────────────────────
def estimate_depth(
    stations: Sequence[Mapping[str, Any]],
    *,
    value_column: str = "magnetic_nt",
    structural_index: float = 3.0,
    window_cells: int = 10,
    step_cells: int = 2,
    max_rel_uncertainty: float = 0.15,
    include_spectrum: bool = True,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Profundidad por Euler + espectro radial, SIN invertir.

    (`POST /v2/depth-estimate`, otra de las rutas que la Fase 9 dejó declaradas.)

    Es el chequeo cruzado independiente: si la inversión y la deconvolución de
    Euler no se parecen, hay algo que mirar antes de recomendar un sondaje. Cada
    salida trae la nota de honestidad del método (±15-25% típico; resuelve
    ENSAMBLES, no cuerpos).

    Las estaciones se sacan de un CSV con `parse_rows()`, que las devuelve ya
    parseadas por el pipeline oficial.
    """
    ses = session or default_session()
    return ses.post(
        _DEPTH,
        json_body={
            "stations": [dict(s) for s in stations],
            "value_column": value_column,
            "structural_index": structural_index,
            "window_cells": window_cells,
            "step_cells": step_cells,
            "max_rel_uncertainty": max_rel_uncertainty,
            "include_spectrum": include_spectrum,
            "output_format": "json",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Historial
# ─────────────────────────────────────────────────────────────────────────────
def open_run(project_id: str, run_id: str, *, session: Optional[Session] = None) -> Run:
    """Re-abre una corrida anterior sin re-invertir.

    El estado se lee del backend: si la corrida no existe, `Run.status_now()`
    lo dirá. No se finge un `done`.
    """
    ses = session or default_session()
    corrida = Run(ses, project_id, run_id)
    try:
        corrida.status_now()
    except TerraquantumError:
        pass
    return corrida


def list_runs(*, project_id: Optional[str] = None, limit: int = 50,
              session: Optional[Session] = None) -> List[dict]:
    """Historial persistente de corridas (`GET /v2/history/runs`)."""
    ses = session or default_session()
    params: Dict[str, Any] = {"limit": limit}
    if project_id:
        params["project_id"] = project_id
    respuesta = ses.get("/v2/history/runs", params=params)
    return list(respuesta.get("runs") or [])


# ─────────────────────────────────────────────────────────────────────────────
# Sesión por defecto
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULT: Optional[Session] = None


def default_session() -> Session:
    """La sesión que usan las funciones de módulo si no se les pasa una.

    En proceso, creada al primer uso. Un script que quiera hablar con un backend
    remoto crea su `Session(base_url=...)` y la pasa (o llama a
    `set_default_session`).
    """
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Session()
    return _DEFAULT


def set_default_session(session: Optional[Session]) -> None:
    """Fija (o limpia con `None`) la sesión por defecto del módulo."""
    global _DEFAULT
    _DEFAULT = session


# ─────────────────────────────────────────────────────────────────────────────
def _validar_data_type(valor: str) -> None:
    if valor not in DATA_TYPES:
        raise ValueError(f"data_type inválido: {valor!r}. Válidos: {DATA_TYPES}.")


def _texto_de_paquete(package: Any) -> tuple[str, str]:
    """Acepta un `Package`, una ruta a `.tqpkg`/`.csv`, o el texto del paquete."""
    if isinstance(package, Package):
        return package.text, package.filename
    import pathlib

    if isinstance(package, pathlib.Path) or (
        isinstance(package, str) and "\n" not in package and "\r" not in package
    ):
        ruta = pathlib.Path(package)
        if not ruta.is_file():
            raise TerraquantumError(
                f"No existe el paquete: {ruta}",
                code="PACKAGE_FILE_NOT_FOUND",
                suggested_action="Comprueba la ruta del .tqpkg guardado con Package.save().",
            )
        nombre = ruta.name
        if not nombre.lower().endswith((".csv", ".tqpkg")):
            nombre = f"{ruta.stem}.tqpkg.csv"
        return ruta.read_text(encoding="utf-8"), nombre
    if isinstance(package, str):
        return package, "package.tqpkg.csv"
    if isinstance(package, bytes):
        return package.decode("utf-8", errors="replace"), "package.tqpkg.csv"
    raise TypeError(
        f"Paquete no reconocido: {type(package).__name__}. Usa un Package, una "
        "ruta o el texto del TQPKG."
    )


def _id_seguro(valor: str) -> str:
    limpio = "".join(c if c.isalnum() else "_" for c in valor).strip("_")
    return (limpio or "lote")[:48]


#: Huellas del fallo de *spawn* sin guard `__main__`, tal como lo emite la
#: biblioteca estándar (MEDIDO ejecutando un script sin guard).
_HUELLAS_SPAWN = ("freeze_support", "is not going to be frozen", "spawn")


def _traducir_fallo_de_spawn(exc: TerraquantumError, *, wait: bool) -> TerraquantumError:
    """Convierte el 500 opaco del worker sin guard en un error accionable.

    Sin `if __name__ == "__main__":` el hijo de *spawn* re-ejecuta el script y
    `multiprocessing` aborta con el `RuntimeError` del `freeze_support()`. Por
    la vía HTTP eso llega como `TQ_INTERNAL` con el traceback dentro: cierto,
    pero ilegible. El contrato del proyecto es que un fallo nunca es genérico.
    """
    if wait:
        return exc
    rastro = " ".join(
        str(exc.details.get(clave) or "") for clave in ("traceback", "message", "type")
    ) or str(exc)
    if not any(h in rastro for h in _HUELLAS_SPAWN):
        return exc
    return TerraquantumError(
        "La corrida no se pudo encolar: el worker se lanza con multiprocessing "
        "en modo spawn y tu script no tiene el guard `if __name__ == \"__main__\":`, "
        "así que el proceso hijo vuelve a ejecutar el módulo entero.",
        code="SPAWN_REQUIRES_MAIN_GUARD",
        http_status=exc.http_status,
        path=exc.path,
        details=exc.details,
        suggested_action=(
            "Envuelve el script en `def main(): ...` + "
            "`if __name__ == \"__main__\": main()`, o usa wait=True (camino "
            "síncrono), que no lanza ningún proceso hijo."
        ),
    )
