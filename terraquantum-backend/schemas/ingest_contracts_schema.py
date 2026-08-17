"""FASE 10 — Contratos declarados de la cadena de ingesta (el camino dorado).

    CSV → analyze-columns (sniff + mapeo) → parse-rows → enrich-package → load-package

Es el tramo donde H-16 duele más: son los endpoints que el frontend consume con
tipos escritos a mano leyendo Python, y son los que **no declaraban esquema**, así
que el OpenAPI de todo el camino dorado salía vacío y no había nada que generar.

Tres advertencias que explican por qué los modelos son como son:

1. **`extra="allow"` en todos.** MEDIDO: un `response_model` estricto filtra en
   silencio los campos que no declara. Estos endpoints llevan años emitiendo
   campos que el frontend consume; un contrato incompleto no los documentaría,
   los **borraría**.

2. **`analyze-columns`, `parse-rows` y `enrich-package` devuelven `JSONResponse`.**
   FastAPI no valida ni serializa cuando el handler devuelve un `Response` ya
   construido: el `response_model` de esas tres rutas es **puramente
   declarativo** (alimenta el OpenAPI y, con él, los tipos del frontend). Eso lo
   hace de riesgo cero para producción y, a cambio, deja el contrato sin nadie
   que lo obligue a ser cierto — de ahí que `tests/test_fase10_contratos.py`
   llame a los endpoints de verdad y compare las claves.

3. **`SniffReport` y `ColumnMappingPlan` son ESPEJOS de estructuras que ya
   existen** (una `@dataclass` en `services/csv_sniffer_service.py` y un `dict`
   que arma `services/column_mapping_service.py`). Duplicar una forma es
   justo el pecado que esta fase persigue, así que el espejo **no se sostiene
   por buena voluntad**: hay un test que compara campo a campo el modelo con lo
   que la fuente produce de verdad, y falla si alguien añade un campo a un lado.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# Sniff físico del CSV (encoding / separador / decimal / preámbulo / filas rotas)
# ─────────────────────────────────────────────────────────────────────────────

class SniffDiscarded(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    reason: str


class SniffDetection(BaseModel):
    """Una detección CON EVIDENCIA. `evidence` es texto para el usuario: es lo
    que convierte «detecté coma decimal» en algo que se puede contradecir."""
    model_config = ConfigDict(extra="allow")

    value: str
    confidence: str
    evidence: str
    discarded: List[SniffDiscarded]


class SniffPreambleLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    line_number: int
    text: str
    reason: str


class SniffBrokenRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    line_number: int
    field_count: int
    expected_fields: int
    excerpt: str


class SniffReportContract(BaseModel):
    """Espejo de `services.csv_sniffer_service.SniffReport.to_dict()`.

    El sufijo `Contract` evita que el nombre choque con la `@dataclass` del
    servicio: son dos cosas distintas —una calcula, la otra describe el cable— y
    confundirlas fue lo que multiplicó las declaraciones que H-16 contó.
    """
    model_config = ConfigDict(extra="allow")

    version: str
    filename: str
    encoding: SniffDetection
    separator: SniffDetection
    decimal: SniffDetection
    preamble_count: int
    preamble_lines: List[SniffPreambleLine]
    #: `null` cuando no se pudo identificar la línea de encabezado.
    header_line_number: Optional[int]
    header_columns: List[str]
    broken_rows: List[SniffBrokenRow]
    broken_row_count: int
    n_lines_sampled: int
    sample_truncated: bool
    warnings: List[str]


# ─────────────────────────────────────────────────────────────────────────────
# Plan de mapeo de columnas (PILAR 1 del blindaje de ingesta)
# ─────────────────────────────────────────────────────────────────────────────

class IngestQuestionOption(BaseModel):
    """Una opción de respuesta. El backend las emite como `{value, label}`."""
    model_config = ConfigDict(extra="allow")

    value: str
    label: str


class IngestQuestion(BaseModel):
    """Pregunta ESTRUCTURADA (F2.4): un dato no-derivable se pregunta, jamás se
    adivina. `blocking` es la diferencia entre «avísame» y «no sigo sin esto»."""
    model_config = ConfigDict(extra="allow")

    key: str
    target: str
    kind: str
    blocking: bool
    question: str
    options: List[IngestQuestionOption]
    reason: str


class ColumnRangeCheck(BaseModel):
    model_config = ConfigDict(extra="allow")

    column: str
    verdict: str
    note: Optional[str] = None


class ColumnSuspicion(BaseModel):
    """Segunda opinión por RANGO físico sobre el mapeo por nombre: es lo que caza
    el clásico northing metido en `y` cuando `y` era profundidad."""
    model_config = ConfigDict(extra="allow")

    role: str
    column: str
    kind: str
    user_mapped: bool
    message: str
    suggested_role: Optional[str] = None


class ColumnSuggestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    column: str
    confidence: str
    reason: str


class InferredLiteral(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    source_column: str
    note: str


class ColumnMappingPlanContract(BaseModel):
    """Espejo de `services.column_mapping_service.build_column_mapping_plan()`.

    `needs_mapping` (falta un rol REQUERIDO) y `needs_confirmation` (están todos
    pero la confianza es baja) son estados distintos y el frontend los trata
    distinto: colapsarlos convertiría una duda en una certeza.
    """
    model_config = ConfigDict(extra="allow")

    data_kind: str
    raw_columns: List[str]
    auto_detected: Dict[str, Optional[str]]
    roles: Dict[str, Optional[str]]
    overridden: Dict[str, str]
    invalid_overrides: Dict[str, str]
    required_roles: List[str]
    optional_roles: List[str]
    missing_required: List[str]
    needs_mapping: bool
    confidence: str = Field(
        ...,
        description=(
            "`high` | `medium` | `low`. Va como cadena y no como enumerado a "
            "propósito: el backend NO lo valida contra un dominio cerrado, y "
            "cerrarlo aquí convertiría un valor inesperado en un HTTP 500 en "
            "plena ingesta. Se estrecha al pintarlo, no al transportarlo."
        ),
    )
    role_labels: Dict[str, str]
    #: `Dict[str, str]` y no `Any`: `build_column_mapping_plan` los construye del
    #: propio `column_map`, que son cadenas (`literals: Dict[str, str]` en la
    #: firma del servicio). Declararlo `Any` obligaba al frontend a castear para
    #: pintar un literal que siempre fue texto.
    literals: Dict[str, str]
    range_checks: Dict[str, ColumnRangeCheck]
    suspicions: List[ColumnSuspicion]
    role_confidence: Dict[str, str]
    suggestions: Dict[str, ColumnSuggestion]
    needs_confirmation: bool
    questions: List[IngestQuestion]
    inferred_literals: Dict[str, InferredLiteral]


# ─────────────────────────────────────────────────────────────────────────────
# POST /v2/gravity-import/analyze-columns
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeColumnsResponse(BaseModel):
    """El plan de mapeo SIN invertir ni fabricar nada: se leen encabezados, se
    corre la detección y se re-etiquetan columnas reales.

    `sample_rows` son filas **YA parseadas por el importador**, no las líneas
    crudas del archivo: un preview honesto muestra lo que el motor va a ver
    (con el decimal ya resuelto), no lo que el texto aparenta.
    """
    model_config = ConfigDict(extra="allow")

    column_mapping: ColumnMappingPlanContract
    sniff_report: SniffReportContract
    sample_rows: List[Dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# POST /v2/gravity-import/parse-rows
# ─────────────────────────────────────────────────────────────────────────────

class ParseRowsResponse(BaseModel):
    """Filas COMPLETAS ya parseadas por el pipeline oficial.

    Existe para que el frontend NO parsee CSV en TypeScript: hacerlo duplicaría
    el sniffer y reintroduciría el bug decimal-coma (`parseFloat("1,23")` = 1, en
    silencio) que ya costó una corrupción de datos medida.
    """
    model_config = ConfigDict(extra="allow")

    headers: List[str]
    rows: List[Dict[str, Any]]
    n_rows: int
    truncated: bool
    sniff_report: SniffReportContract


# ─────────────────────────────────────────────────────────────────────────────
# POST /v2/gravity-import/enrich-package
# ─────────────────────────────────────────────────────────────────────────────

class EnrichPackageResponse(BaseModel):
    """DOS respuestas distintas por la misma puerta, y el discriminante es
    `needs_mapping`:

    * `needs_mapping: true` → **no se enriqueció nada**; vienen `column_mapping`
      y `sniff_report` para que el usuario asigne roles o conteste las preguntas
      bloqueantes, y `package_text` NO existe.
    * ausente/`false` → vino el paquete: `package_text` + `enrichment_summary`.

    Un modelo único con todo opcional es lo máximo que OpenAPI expresa aquí sin
    mentir; el frontend conserva la unión discriminada, que es MÁS precisa, y un
    test comprueba que sus dos variantes existen en este contrato.
    """
    model_config = ConfigDict(extra="allow")

    # ── variante «falta mapeo» ────────────────────────────────────────────────
    needs_mapping: Optional[bool] = None
    needs_confirmation: Optional[bool] = None
    column_mapping: Optional[ColumnMappingPlanContract] = None
    sample_rows: Optional[List[Dict[str, Any]]] = None

    # ── variante «paquete enriquecido» ────────────────────────────────────────
    filename: Optional[str] = None
    #: El CSV completo como texto. Va por JSON, no como descarga, porque la UI lo
    #: previsualiza antes de que el usuario decida guardarlo.
    package_text: Optional[str] = None
    enrichment_summary: Optional[Dict[str, Any]] = None
    plan: Optional[Dict[str, Any]] = None
    needs_context: Optional[List[Dict[str, Any]]] = None
    n_stations: Optional[int] = None

    # ── comunes ───────────────────────────────────────────────────────────────
    sniff_report: Optional[SniffReportContract] = None
    warnings: List[str]


# ─────────────────────────────────────────────────────────────────────────────
# POST /v2/gravity-import/load-package
# ─────────────────────────────────────────────────────────────────────────────

class LoadPackagePoll(BaseModel):
    model_config = ConfigDict(extra="allow")

    status_url: Optional[str] = None
    cancel_url: Optional[str] = None


class LoadPackageResponse(BaseModel):
    """TRES respuestas por la misma puerta, discriminadas por `status`:

    * `error`   → falló la importación; `stage:"import"`, `errors` poblado.
    * `queued`  → **el camino por defecto**. La inversión se encoló en un worker
      de proceso y el progreso viaja por `GET /geophysics-status`. Se hizo así
      porque una inversión larga por HTTP síncrono acababa en «error interno del
      proxy» — el fallo se veía como un bug y era un timeout.
    * `done`    → ruta síncrona; trae `inversionResult` **sin `voxels`** (el
      modelo se pide aparte por Arrow/JSON, no cabe en esta respuesta).
    """
    model_config = ConfigDict(extra="allow")

    status: str
    stage: Optional[str] = None
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    route: Optional[str] = None
    multimodal_plan: Optional[Dict[str, Any]] = None
    budget: Optional[Dict[str, Any]] = None
    poll: Optional[LoadPackagePoll] = None
    #: camelCase heredado del contrato v1; el frontend lo consume así.
    inversionResult: Optional[Dict[str, Any]] = None
    warnings: List[str]
    errors: List[str]
