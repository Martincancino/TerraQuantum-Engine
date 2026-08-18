"""FASE 11 — Errores de la API de scripting.

El backend ya tiene un catálogo de 60+ errores en español con `code`,
`user_message` y `suggested_action` (`core/errors.py`, Fase 23), y el contrato
«nunca crashea» de la Fase 2 garantiza que incluso un fallo interno llega al
cliente con ese payload completo. **Esta capa no inventa un vocabulario nuevo:
transporta el que ya existe.**

La regla, que es la del proyecto: *un fallo nunca se convierte en un valor de
retorno plausible*. Un 4xx/5xx es una excepción con el código del catálogo
dentro; y una PREGUNTA del pipeline (falta el mapeo de columnas) tampoco es un
error genérico, es su propia excepción con el plan adjunto para poder
responderla.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class TerraquantumError(RuntimeError):
    """Base de la API de scripting. Lleva el payload del catálogo del backend.

    `code` es el identificador estable (`CSV_EMPTY`, `TQ_INTERNAL`, …) y es lo
    que un script debe mirar para decidir: los textos son para el humano.
    """

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
        suggested_action: str = "",
        details: Optional[Dict[str, Any]] = None,
        path: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.suggested_action = suggested_action
        self.details: Dict[str, Any] = details or {}
        self.path = path

    def __str__(self) -> str:  # pragma: no cover - formato de presentación
        cabeza = f"[{self.code}] " if self.code else ""
        cola = f"\n  Acción sugerida: {self.suggested_action}" if self.suggested_action else ""
        ruta = f" ({self.path})" if self.path else ""
        return f"{cabeza}{self.message}{ruta}{cola}"

    @classmethod
    def from_response(cls, path: str, status: int, body: Any) -> "TerraquantumError":
        """Construye la excepción desde la respuesta HTTP del backend.

        Formas que emite el backend, todas contempladas:
          · `{"detail": {"error"/"code", "message"/"user_message", "suggested_action", …}}`
            — el catálogo, vía los handlers globales de la Fase 2.
          · `{"detail": "texto"}` — `HTTPException` con cadena suelta.
          · texto plano — el borde raro (proxy, 413 del servidor).
        """
        detalle: Any = body
        if isinstance(body, dict):
            detalle = body.get("detail", body)

        if isinstance(detalle, dict):
            code = detalle.get("code") or detalle.get("error")
            mensaje = (
                detalle.get("user_message")
                or detalle.get("message")
                or str(detalle)[:400]
            )
            if status == 429:
                # `slowapi` no emite un código: su cuerpo es
                # `{"error": "Rate limit exceeded: 10 per 1 minute"}`, y ese texto
                # NO es un identificador estable (cambia si cambia el límite). Un
                # script decide por `code`, así que aquí se fija uno propio y el
                # texto del servidor sigue siendo el mensaje.
                return RateLimited(
                    mensaje, code="RATE_LIMITED", http_status=429,
                    details=detalle, path=path,
                )
            return cls(
                mensaje,
                code=code,
                http_status=status,
                suggested_action=detalle.get("suggested_action", "") or "",
                details=detalle,
                path=path,
            )

        mensaje = str(detalle)[:400] if detalle is not None else f"HTTP {status}"
        if status == 429:
            return RateLimited(mensaje, code="RATE_LIMITED", http_status=429, path=path)
        return cls(mensaje, http_status=status, path=path)


class RateLimited(TerraquantumError):
    """429 del rate-limiter del backend.

    MEDIDO al construir esta API: `slowapi` responde 429 **sin cabecera
    `Retry-After`**, así que ningún cliente puede saber cuánto esperar. Por eso
    la espera de la política `"wait"` es un backoff CIEGO y está declarado como
    tal en `Session`.
    """


class NeedsColumnMapping(TerraquantumError):
    """El CSV no se auto-mapeó: el pipeline PREGUNTA, y hay que responder.

    No es un fallo del archivo: es el Pilar 1 de la ingesta («mapeo manual de
    columnas») funcionando. Se responde volviendo a llamar con
    `column_map={rol: columna}`.

    Atributos:
      · `plan`         — el plan de mapeo completo (roles, confianza, columnas crudas)
      · `questions`    — preguntas explícitas del plan (las `blocking` hay que responderlas)
      · `suggestions`  — sugerencias por rango físico (la heurística sospecha algo)
      · `raw_columns`  — los encabezados tal como vienen en el archivo
      · `sample_rows`  — primeras filas YA parseadas (lo que el importador ve)
    """

    def __init__(self, message: str, *, plan: Dict[str, Any], sample_rows: Optional[List[dict]] = None,
                 path: str = "") -> None:
        super().__init__(message, code="NEEDS_COLUMN_MAPPING", http_status=200, path=path,
                         details={"column_mapping": plan})
        self.plan = plan or {}
        self.questions: List[dict] = list(self.plan.get("questions") or [])
        self.suggestions = self.plan.get("suggestions")
        self.suspicions = self.plan.get("suspicions")
        self.raw_columns: List[str] = list(self.plan.get("raw_columns") or [])
        self.required_roles: List[str] = list(self.plan.get("required_roles") or [])
        self.missing_required: List[str] = list(self.plan.get("missing_required") or [])
        self.sample_rows: List[dict] = list(sample_rows or [])
        self.suggested_action = (
            "Vuelve a llamar con column_map={rol: columna}. Roles que faltan: "
            + (", ".join(self.missing_required) or "(ninguno requerido: revisa `questions`)")
        )


class InversionFailed(TerraquantumError):
    """La corrida terminó en un estado NO exitoso (error/cancelled/interrumpida).

    `run_status` lleva el estado terminal tal como lo publica
    `GET /geophysics-status`, con su `stage` y su `message`: el contrato F3 es
    que ese estado SIEMPRE se escribe, incluso si el worker muere.
    """

    def __init__(self, message: str, *, run_status: Optional[Dict[str, Any]] = None,
                 code: Optional[str] = None, path: str = "") -> None:
        super().__init__(message, code=code or "INVERSION_FAILED", path=path,
                         details=run_status or {})
        self.run_status: Dict[str, Any] = run_status or {}


class RunTimeout(TerraquantumError):
    """`Run.wait()` agotó su plazo. La corrida SIGUE VIVA en el backend.

    No se cancela sola a propósito: un timeout del cliente no es una decisión
    de abortar el trabajo. Se cancela con `Run.cancel()` si eso es lo que se
    quiere.
    """

    def __init__(self, message: str, *, run_status: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code="RUN_TIMEOUT", details=run_status or {})
        self.run_status: Dict[str, Any] = run_status or {}
        self.suggested_action = (
            "La corrida sigue en marcha: vuelve a llamar a wait() con más plazo, "
            "consulta status_now(), o abórtala con cancel()."
        )


__all__ = [
    "TerraquantumError",
    "RateLimited",
    "NeedsColumnMapping",
    "InversionFailed",
    "RunTimeout",
]
