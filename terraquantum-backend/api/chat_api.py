"""
FASE 6 — Copiloto IA para el consultor geofísico.

Chat en español anclado a LA corrida concreta: cada respuesta se construye sobre
el ``report_payload`` real (trilogía B1 targeting / B2 resolución de profundidad /
B3 veredicto reconciliado, χ², cobertura, warnings). Reglas duras:

  * NUNCA inventa un número — si el dato no está en el contexto, lo dice.
  * Guardrails de compliance JORC/NI 43-101 (prohibido estimar recursos/ley/
    tonelaje/valor económico) — escudo legal, se mantiene y se refuerza.
  * Puede EXPLICAR qué exige JORC (educación) sin generar una estimación.

Migrado del SDK deprecado ``google-generativeai`` al nuevo ``google-genai`` (F6).
El import del SDK es perezoso (dentro de la llamada) para que el arranque de la
app no dependa de que esté instalado.
"""

import os
import re
import json
import time
import hashlib
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from core.block_model_store import get_run_report_path, get_run_inputs_path
from core.logging import get_logger
from core.config import GEMINI_CHAT_MODEL, GEMINI_REPORT_MODEL

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])
_log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Capa 1 — Compliance (escudo legal). Redacción TOTAL si se detecta lenguaje de
# estimación de recursos. Dos sub-capas:
#   A) términos económicos en inglés (heredado);
#   B) patrones número+unidad de recurso (ES/EN) que SÍ constituyen una estimación
#      (p.ej. "5000 toneladas", "ley de 1.2 %", "VAN de $3M"). Las menciones
#      EDUCATIVAS de JORC ("recursos", "reservas") sin cifra NO se redactan.
# ─────────────────────────────────────────────────────────────────────────────
_BANNED_WORDS = [
    "reserve", "resource", "grade", "npv", "irr", "tonnage", "economic value",
]

# Número + unidad de recurso/economía → estimación prohibida.
_ECONOMIC_ESTIMATE_PATTERNS = [
    r"\d[\d.,]*\s*(?:toneladas?|tonnes?|tonnage|\bMt\b|\bkt\b)",          # tonelaje
    r"(?:ley|grade)\s*(?:de\s*|of\s*)?[:=]?\s*\d[\d.,]*\s*%?",             # ley
    r"(?:npv|van|tir|irr)\s*[:=]?\s*[-+]?\$?\s*\d",                        # económicos
    r"[$€]\s*\d[\d.,]*\s*(?:millones?|million|mill\.?|\bM\b|\bk\b|usd|dólares|dolares)?",  # dinero
]
_ECONOMIC_ESTIMATE_RE = [re.compile(p, re.IGNORECASE) for p in _ECONOMIC_ESTIMATE_PATTERNS]

_REDACTION_MESSAGE = (
    "[Respuesta redactada por guardrails de compliance JORC/NI-43-101. "
    "Este asistente no puede emitir estimaciones de recursos, ley, tonelaje o "
    "valores económicos. Puede, en cambio, explicar qué exige JORC/NI 43-101 y "
    "por qué esta herramienta no reporta recursos.]"
)


def _apply_compliance_filter(text: str) -> str:
    """Redacta la respuesta completa si contiene lenguaje de estimación de recursos."""
    text_lower = text.lower()
    for word in _BANNED_WORDS:
        if word in text_lower:
            return _REDACTION_MESSAGE
    for rx in _ECONOMIC_ESTIMATE_RE:
        if rx.search(text):
            return _REDACTION_MESSAGE
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Capa 2 — Guard de anclaje numérico (grounding). Toda cantidad física citada
# (número + unidad geofísica) debe existir en el contexto de la corrida. Si no,
# se anexa una advertencia honesta (no se destruye la respuesta): el copiloto
# nunca debe presentar como dato una cifra que no salió del modelo.
# ─────────────────────────────────────────────────────────────────────────────
_QUANTITY_RE = re.compile(
    r"(-?\d[\d.,]*)\s*"
    r"(t/m³|t/m3|g/cm³|mGal|nT|km|kil[oó]metros?|metros?|meters?|%|°|SI\b|m)"
    r"(?![\wáéíóúñ])",
    re.IGNORECASE,
)


def _to_float(raw: str) -> Optional[float]:
    """Parsea un token numérico tolerando separadores ES/EN de forma conservadora."""
    s = raw.strip()
    if "," in s and "." in s:
        # el separador más a la derecha es el decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        frac = s.split(",")[-1]
        s = s.replace(",", ".") if (s.count(",") == 1 and len(frac) <= 2) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_grounded_numbers(context: str) -> set:
    out = set()
    for tok in re.findall(r"-?\d[\d.,]*", context):
        v = _to_float(tok)
        if v is not None:
            out.add(v)
    return out


def find_ungrounded_quantities(response: str, context: str) -> list:
    """Cantidades físicas de la respuesta que NO están ancladas al contexto.

    Una cifra se considera anclada si aparece verbatim en el contexto o si está a
    <=2% (relativo) de algún número presente en el contexto. El resto se reporta.
    """
    grounded = _extract_grounded_numbers(context)
    suspicious: list = []
    for m in _QUANTITY_RE.finditer(response):
        raw = m.group(1)
        if raw in context:  # citación verbatim
            continue
        val = _to_float(raw)
        if val is None:
            continue
        if any(abs(val - g) <= 0.02 * max(abs(val), abs(g), 1e-9) for g in grounded):
            continue
        suspicious.append(m.group(0).strip())
    # dedup preservando orden
    seen = set()
    return [q for q in suspicious if not (q in seen or seen.add(q))]


def _apply_grounding_guard(response: str, context: str) -> tuple:
    """Devuelve (texto_final, cantidades_no_ancladas)."""
    ungrounded = find_ungrounded_quantities(response, context)
    if not ungrounded:
        return response, []
    note = (
        "\n\n⚠️ Verificación de anclaje: las siguientes cifras no se encontraron "
        "en los datos de esta corrida y podrían no ser confiables — "
        f"{', '.join(ungrounded)}. Considera solo las cifras presentes en el reporte."
    )
    return response + note, ungrounded


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de formateo del contexto.
# ─────────────────────────────────────────────────────────────────────────────
def _num(value, unit: str = "", dec: int = 2, fallback: str = "?") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return f"{value:.{dec}f}{unit}"


def _sino(value) -> str:
    if value is True:
        return "sí"
    if value is False:
        return "no"
    return "?"


def _format_trilogy(report_data: dict) -> str:
    """Ancla la trilogía honesta B1/B2/B3 del report_payload."""
    bt = report_data.get("best_target") or {}
    dr = report_data.get("depthResolution") or {}
    ov = report_data.get("overall_verdict") or {}
    per_axis = dr.get("per_axis") or {}
    horiz = per_axis.get("horizontal") or {}

    lines = [
        "",
        "B1 — TARGETING (mejor blanco recuperado):",
        f"- Clase de prioridad: {report_data.get('priority_class', '?')}",
        f"- Confiabilidad del modelo: {report_data.get('model_reliability_level', '?')}",
        f"- Nivel de riesgo: {report_data.get('risk_level', '?')}",
        f"- Señal preliminar: {report_data.get('preliminary_signal', '?')}",
        f"- Blanco: x={_num(bt.get('x_m'))} m, y={_num(bt.get('y_m'))} m, z={_num(bt.get('z_m'))} m",
        f"- Profundidad del blanco: {_num(bt.get('depth_m'))} m",
        f"- Densidad modelada del blanco: {_num(bt.get('density'), ' t/m³', dec=3)}",
        f"- Score relativo del target: {_num(bt.get('relative_target_score') or bt.get('target_score'), dec=3)}",
        f"- Confianza del blanco: {bt.get('confidence_level', '?')}",
        f"- ¿Profundidad resoluble?: {_sino(bt.get('is_resolvable_depth'))}",
        f"- ¿Artefacto de null-space?: {_sino(bt.get('is_null_space_artifact'))}",
        f"- Nota de selección: {bt.get('selection_note') or bt.get('anomaly_selection_note') or '—'}",
        "",
        "B2 — RESOLUCIÓN DE PROFUNDIDAD (qué se puede afirmar y qué no):",
        f"- Profundidad máx. resoluble: {_num(dr.get('resolvable_depth_max_m'), ' m')}",
        f"- Profundidad del cuerpo resoluble: {_num(dr.get('resolvable_body_depth_m'), ' m')}",
        f"- Profundidad geométricamente observable: {_num(dr.get('geometric_observable_depth_max_m'), ' m')}",
        f"- Extensión horizontal determinada: {_num(dr.get('horizontal_extent_m'), ' m')}",
        f"- Fracción de masa en cola profunda (null-space): {_num(dr.get('deep_mass_fraction'), dec=3)}",
        f"- Compacidad horizontal: {horiz.get('compactness', '?')}",
        f"- Enunciado B2: {dr.get('statement') or '—'}",
        "",
        "B3 — VEREDICTO RECONCILIADO (weakest-link, el más conservador):",
        f"- Nivel: {ov.get('level', '?')}",
        f"- Titular: {ov.get('headline') or '—'}",
        f"- Factores limitantes: {', '.join(ov.get('limiting_factors', []) or []) or '—'}",
        f"- Acción recomendada: {ov.get('recommended_action') or '—'}",
    ]
    return "\n".join(lines)


def _build_geological_context(
    project_id: str, run_id: str, report_data: dict
) -> tuple:
    """
    Build compact geological context string and auto-warnings from report + inputs.
    Returns (context_str: str, warnings: list[str]).
    """
    inputs_data: dict = {}
    inputs_path = get_run_inputs_path(project_id=project_id, run_id=run_id)
    if inputs_path and inputs_path.exists():
        try:
            with open(inputs_path, "r", encoding="utf-8") as f:
                inputs_data = json.load(f)
        except Exception as exc:
            _log.warning("No se pudo leer inputs.json para contexto IA", error=str(exc))

    obs_q = report_data.get("observationQuality", {})
    fit_d = report_data.get("fitDiagnostics", report_data.get("fit_diagnostics", {}))

    n_obs = obs_q.get("observation_count", report_data.get("n_observations", "?"))
    span_x = obs_q.get("spatial_span_x", 0)
    span_z = obs_q.get("spatial_span_z", 0)
    extent_x_km = round(span_x / 1000.0, 1) if span_x else "?"
    extent_z_km = round(span_z / 1000.0, 1) if span_z else "?"

    chi2 = fit_d.get(
        "chi_squared_final",
        fit_d.get("chi2_final_solver", report_data.get("chi_squared_final", None)),
    )
    rmse = fit_d.get("residual_rmse", fit_d.get("rmse", None))
    fit_level = fit_d.get("fit_level", report_data.get("fit_level", "?"))
    lambda_val = fit_d.get(
        "lambda_used",
        report_data.get("lambda_used", inputs_data.get("lambda_mag", "?")),
    )
    nrmse = fit_d.get("normalized_rmse", None)
    misfit_pct = fit_d.get(
        "misfit_error_percent", report_data.get("misfit_error_percent", None)
    )

    max_density = report_data.get("max_density", "?")
    depth_m = inputs_data.get("depth", report_data.get("depth_m", "?"))
    region = inputs_data.get("region", report_data.get("region", "desconocida"))
    gravity_type = inputs_data.get("gravity_type", "no especificado")
    corrections = inputs_data.get("corrections_applied", [])

    chi2_str = f"{chi2:.3f}" if isinstance(chi2, (int, float)) else "?"
    rmse_str = f"{rmse:.6f} m/s²" if isinstance(rmse, (int, float)) else "?"
    nrmse_str = f"{nrmse * 100:.1f}%" if isinstance(nrmse, (int, float)) else "?"
    misfit_str = f"{misfit_pct:.2f}%" if isinstance(misfit_pct, (int, float)) else "?"
    corrections_str = ", ".join(corrections) if corrections else "ninguna"

    context = (
        "CONTEXTO DEL LEVANTAMIENTO:\n"
        f"- Región: {region}\n"
        f"- N° observaciones: {n_obs}\n"
        f"- Extensión del survey: {extent_x_km} km × {extent_z_km} km\n"
        f"- Profundidad del modelo: {depth_m} m\n"
        f"- Tipo de dato: {gravity_type}\n"
        f"- Correcciones aplicadas: {corrections_str}\n"
        "\n"
        "PARÁMETROS DE INVERSIÓN:\n"
        f"- Lambda (regularización): {lambda_val}\n"
        "\n"
        "CALIDAD DEL AJUSTE:\n"
        f"- Chi² reducido final: {chi2_str}  (target ≈ 1.0; < 0.5 = sobreajuste; > 2.0 = subajuste)\n"
        f"- RMSE: {rmse_str}\n"
        f"- NRMSE: {nrmse_str}\n"
        f"- Misfit: {misfit_str}\n"
        f"- Nivel de ajuste: {fit_level}\n"
        "\n"
        "ANOMALÍAS DETECTADAS:\n"
        f"- Densidad máxima recuperada: {max_density} t/m³\n"
        f"{_format_trilogy(report_data)}"
    )

    warnings: list = []
    if isinstance(chi2, (int, float)) and chi2 > 2.0:
        warnings.append(
            f"⚠️ ADVERTENCIA DE CALIDAD: El chi² reducido final es {chi2:.3f} (> 2.0). "
            "El modelo no ajusta adecuadamente los datos observados. "
            "Los resultados pueden ser poco confiables; considera revisar lambda, "
            "los límites de densidad, o la calidad de los datos."
        )

    corrections_ok = bool(corrections) and gravity_type in (
        "complete_bouguer_anomaly",
        "bouguer_anomaly",
        "free_air_anomaly",
    )
    if not corrections_ok:
        warnings.append(
            "⚠️ ADVERTENCIA DE CORRECCIONES: Los datos no tienen correcciones geofísicas "
            "completas (Free-Air, Bouguer, Terreno). En zonas con relieve como los Andes, "
            "el efecto no corregido puede ser 10–10,000 veces mayor que la anomalía de interés. "
            "El modelo puede ser geológicamente sin sentido."
        )

    bt = report_data.get("best_target") or {}
    if bt.get("is_null_space_artifact") is True:
        warnings.append(
            "⚠️ ADVERTENCIA DE NULL-SPACE: El mejor blanco está marcado como artefacto "
            "de null-space (no restringido por los datos). Su profundidad NO es confiable."
        )

    return context, warnings


# ─────────────────────────────────────────────────────────────────────────────
# System prompt: base (compliance + grounding) + overlay por modo.
# ─────────────────────────────────────────────────────────────────────────────
_MODE_INSTRUCTIONS = {
    "explicar": (
        "MODO EXPLICAR: El usuario quiere entender ESTA corrida. Explica el "
        "veredicto (B3) y las métricas citando SOLO los valores del contexto "
        "(χ², B1 targeting, B2 resolución). Si preguntan por la profundidad "
        "exacta del cuerpo, cita B2 y la NO-UNICIDAD del campo potencial: la "
        "gravedad sola no fija la profundidad de forma única; entrega el rango "
        "resoluble, nunca un único número inventado."
    ),
    "redactar": (
        "MODO REDACTAR: Genera un BORRADOR de sección de informe geofísico en "
        "español con estructura de industria: (1) Introducción y objetivo, "
        "(2) Datos y cobertura, (3) Método (inversión + regularización), "
        "(4) Resultados (blanco, densidades, ajuste), (5) Limitaciones "
        "(no-unicidad, resolución en profundidad, DOI). Usa SOLO cifras del "
        "contexto. Cierra recordando que el consultor debe revisar, editar y "
        "FIRMAR el documento, y que NO es una estimación de recursos JORC/NI 43-101."
    ),
    "ensenar": (
        "MODO ENSEÑAR: El usuario es junior. Explica conceptos "
        "minero-geofísicos en español simple (qué es la anomalía de Bouguer, el "
        "χ² reducido, el DOI, la no-unicidad, la susceptibilidad magnética) con "
        "analogías. Si el concepto aplica a esta corrida, ilústralo con las "
        "cifras del contexto. No inventes valores."
    ),
}

_BASE_RULES = (
    "Eres el copiloto geofísico de TerraQuantum, experto en exploración minera e "
    "inversión gravimétrica 3D. Respondes en español, claro y honesto.\n"
    "\n"
    "REGLAS ESTRICTAS (inviolables):\n"
    "1. ANCLAJE: toda afirmación cuantitativa debe provenir EXCLUSIVAMENTE del "
    "contexto de la corrida. Si un dato no está en el contexto, responde "
    "explícitamente \"ese dato no está en esta corrida\" — NUNCA lo estimes.\n"
    '2. NUNCA uses las palabras "reservas", "recursos minerales", "ley", "NPV", '
    '"TIR", "tonelaje" ni "valor económico" para HACER una estimación. Puedes '
    "EXPLICAR qué exige JORC/NI 43-101 y por qué esta herramienta no reporta "
    "recursos (eso es educación, permitido).\n"
    '3. Describe anomalías como "zonas anómalas" o "targets geofísicos", no como '
    "cuerpos mineralizados.\n"
    "4. Este análisis es una interpretación geofísica cualitativa, NO una "
    "estimación de recursos bajo JORC ni NI 43-101.\n"
    "5. Si el χ² > 2 o no hay correcciones aplicadas, menciona esa limitación al "
    "inicio de tu respuesta.\n"
    "6. Ante preguntas de profundidad exacta, cita B2 y la no-unicidad; nunca des "
    "un número que el modelo no resuelve."
)


def build_system_instruction(
    geo_context: str, warnings: list, mode: Optional[str] = None
) -> str:
    warnings_block = ""
    if warnings:
        warnings_block = (
            "\n\nADVERTENCIAS AUTOMÁTICAS DETECTADAS:\n"
            + "\n".join(f"- {w}" for w in warnings)
        )
    mode_block = ""
    if mode and mode in _MODE_INSTRUCTIONS:
        mode_block = "\n\n" + _MODE_INSTRUCTIONS[mode]

    return (
        f"{_BASE_RULES}"
        f"{mode_block}\n"
        "\n"
        "--- CONTEXTO DEL MODELO GEOFÍSICO ACTIVO ---\n"
        f"{geo_context}"
        f"{warnings_block}\n"
        "---------------------------------------------\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Context caching (F6): el system prompt + contexto de la corrida es grande y se
# repite en cada turno de la MISMA sesión de chat → se cachea una vez y se reusa
# con descuento. OPT-IN (GEMINI_CONTEXT_CACHE=true) porque tiene costo/ciclo de
# vida y requiere que el contexto supere el mínimo de tokens del modelo; si la
# creación falla (contexto chico, modelo sin soporte) cae con gracia al inline.
# BYO-key: la caché vive en la cuenta del usuario; aquí solo recordamos su nombre.
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_ENABLED = os.getenv("GEMINI_CONTEXT_CACHE", "false").lower() == "true"
_CACHE_TTL_SECONDS = int(os.getenv("GEMINI_CONTEXT_CACHE_TTL", "600"))
_cache_registry: dict = {}  # cache_key -> (cache_name, expiry_monotonic)


def _cache_key(api_key: str, model: str, system_instruction: str) -> str:
    h = hashlib.sha256()
    for part in (api_key, model, system_instruction):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _get_or_create_cache(client, types_mod, *, model: str, system_instruction: str, api_key: str) -> Optional[str]:
    """Devuelve el nombre de una caché reutilizable para (api_key, model, system_instruction), o None."""
    key = _cache_key(api_key, model, system_instruction)
    now = time.monotonic()
    hit = _cache_registry.get(key)
    if hit and hit[1] > now:
        return hit[0]
    try:
        cache = client.caches.create(
            model=model,
            config=types_mod.CreateCachedContentConfig(
                system_instruction=system_instruction,
                ttl=f"{_CACHE_TTL_SECONDS}s",
                display_name="terraquantum-copilot",
            ),
        )
    except Exception as exc:  # contexto < mínimo de tokens, modelo sin soporte, etc.
        _log.info("context_cache_skip", reason=str(exc)[:200])
        return None
    _cache_registry[key] = (cache.name, now + _CACHE_TTL_SECONDS - 30)
    return cache.name


# ─────────────────────────────────────────────────────────────────────────────
# Llamada al SDK google-genai (único punto de contacto con la API — mockeable).
# ─────────────────────────────────────────────────────────────────────────────
def _call_gemini(
    *,
    api_key: str,
    model: str,
    system_instruction: str,
    history: list,
    user_message: str,
) -> str:
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    client = genai.Client(api_key=api_key)
    contents = []
    for msg in history:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content", ""))])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
    )

    cache_name = None
    if _CACHE_ENABLED:
        cache_name = _get_or_create_cache(
            client, types, model=model, system_instruction=system_instruction, api_key=api_key
        )

    if cache_name:
        # El system_instruction ya vive en la caché → no se reenvía (ahí está el ahorro).
        config = types.GenerateContentConfig(
            cached_content=cache_name, temperature=0.15, top_p=0.9
        )
    else:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction, temperature=0.15, top_p=0.9
        )

    response = client.models.generate_content(model=model, contents=contents, config=config)
    return response.text or ""


# ─────────────────────────────────────────────────────────────────────────────
# Contrato HTTP.
# ─────────────────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    project_id: str
    run_id: str
    messages: list[ChatMessage]
    # F6: modo del copiloto (opcional, retrocompatible).
    mode: Optional[Literal["explicar", "redactar", "ensenar"]] = None
    # F6: BYO-key — la clave del consultor viaja de su máquina a Google (opcional;
    # fallback a GEMINI_API_KEY del entorno del servidor).
    api_key: Optional[str] = None


def _resolve_api_key(request: "ChatRequest", header_key: Optional[str]) -> Optional[str]:
    return request.api_key or header_key or os.environ.get("GEMINI_API_KEY")


@router.post("")
async def chat_with_geophysics_ai(
    request: ChatRequest,
    x_gemini_api_key: Optional[str] = Header(default=None, alias="X-Gemini-Api-Key"),
):
    api_key = _resolve_api_key(request, x_gemini_api_key)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Falta la API key de Gemini. Envíala en el cuerpo (api_key), en el "
                "header X-Gemini-Api-Key, o configúrala como GEMINI_API_KEY en el servidor."
            ),
        )

    # Contexto anclado a la corrida.
    report_path = get_run_report_path(project_id=request.project_id, run_id=request.run_id)
    geo_context = "No hay datos del modelo cargado para este proyecto/corrida."
    auto_warnings: list = []

    if report_path and report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            geo_context, auto_warnings = _build_geological_context(
                request.project_id, request.run_id, report_data
            )
        except Exception as e:
            _log.error("Error leyendo report.json para IA", error=str(e))
            geo_context = f"Error al cargar el contexto geofísico: {e}"

    system_instruction = build_system_instruction(geo_context, auto_warnings, request.mode)

    # El modo "redactar" usa el tier de reporte (Pro); el chat usa el tier Flash.
    model = GEMINI_REPORT_MODEL if request.mode == "redactar" else GEMINI_CHAT_MODEL

    history = [{"role": m.role, "content": m.content} for m in request.messages[:-1]]
    last_user_message = request.messages[-1].content if request.messages else ""

    try:
        raw = _call_gemini(
            api_key=api_key,
            model=model,
            system_instruction=system_instruction,
            history=history,
            user_message=last_user_message,
        )
    except Exception as e:
        _log.error("Error en Gemini API", error=str(e))
        raise HTTPException(status_code=502, detail=f"Error en la IA: {str(e)}")

    # Capa 1: compliance (puede redactar todo).
    filtered = _apply_compliance_filter(raw)
    if filtered != raw:
        return {"response": filtered, "grounding": {"redacted": True, "ungrounded": []}}

    # Capa 2: guard de anclaje numérico (advertencia no destructiva).
    final_text, ungrounded = _apply_grounding_guard(filtered, geo_context)
    return {
        "response": final_text,
        "grounding": {"redacted": False, "ungrounded": ungrounded},
    }
