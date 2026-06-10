import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import google.generativeai as genai

from core.block_model_store import get_run_report_path, get_run_inputs_path
from core.logging import get_logger
from core.config import GEMINI_MODEL_NAME

# Palabras prohibidas por compliance JORC/NI-43-101 — misma lista que gemini_agent.py
_BANNED_WORDS = [
    "reserve", "resource", "grade", "npv", "irr", "tonnage", "economic value",
]

def _apply_compliance_filter(text: str) -> str:
    text_lower = text.lower()
    for word in _BANNED_WORDS:
        if word in text_lower:
            return (
                "[Respuesta redactada por guardrails de compliance JORC/NI-43-101. "
                "Este asistente no puede emitir estimaciones de recursos o valores económicos.]"
            )
    return text

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])
_log = get_logger(__name__)


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
        f"- Densidad máxima recuperada: {max_density} t/m³"
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

    return context, warnings

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    project_id: str
    run_id: str
    messages: list[ChatMessage]

@router.post("")
async def chat_with_geophysics_ai(request: ChatRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada en el entorno del servidor.")
    
    # Configurar genai
    genai.configure(api_key=api_key)
    
    # Obtener el reporte y construir contexto estructurado
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

    warnings_block = ""
    if auto_warnings:
        warnings_block = (
            "\n\nADVERTENCIAS AUTOMÁTICAS DETECTADAS:\n"
            + "\n".join(f"- {w}" for w in auto_warnings)
        )

    system_instruction = (
        "Eres un geofísico experto en exploración minera, especializado en inversión gravimétrica 3D.\n"
        "Responde en español. Sé específico con números cuando los datos estén disponibles.\n"
        "No inventes datos que no estén en el contexto proporcionado.\n"
        "Cuando el chi² sea > 2, advierte explícitamente que el ajuste de datos no es satisfactorio.\n"
        "Cuando no haya correcciones aplicadas, advierte que el modelo puede ser artefactual.\n"
        "\n"
        "--- CONTEXTO DEL MODELO GEOFÍSICO ACTIVO ---\n"
        f"{geo_context}"
        f"{warnings_block}\n"
        "---------------------------------------------\n"
        "\n"
        "REGLAS ESTRICTAS:\n"
        '1. NUNCA uses las palabras "reservas", "recursos minerales", "ley", "NPV", "TIR", "tonelaje" ni "valor económico".\n'
        '2. Describe anomalías como "zonas anómalas" o "targets geofísicos", no como cuerpos mineralizados.\n'
        "3. Toda afirmación cuantitativa debe provenir exclusivamente del contexto adjunto.\n"
        "4. Este análisis es una interpretación geofísica cualitativa, NO una estimación de recursos bajo JORC ni NI-43-101.\n"
        "5. Si el chi² > 2 o no hay correcciones, menciona esta limitación al inicio de tu respuesta."
    )
    
    # Construir historial para Gemini
    # Convertimos messages a formato de Gemini
    formatted_messages = []
    for msg in request.messages[:-1]:
        role = "user" if msg.role == "user" else "model"
        formatted_messages.append({"role": role, "parts": [msg.content]})
        
    last_user_message = request.messages[-1].content if request.messages else ""

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=system_instruction
        )

        chat = model.start_chat(history=formatted_messages)
        response = chat.send_message(last_user_message)

        filtered = _apply_compliance_filter(response.text)
        return {"response": filtered}
    except Exception as e:
        _log.error("Error en Gemini API", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error en la IA: {str(e)}")
