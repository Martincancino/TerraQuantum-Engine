import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import google.generativeai as genai

from core.block_model_store import get_run_report_path
from core.logging import get_logger

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])
_log = get_logger(__name__)

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
    
    # Obtener el reporte
    report_path = get_run_report_path(project_id=request.project_id, run_id=request.run_id)
    report_context = "No hay datos del modelo cargado."
    
    if report_path and report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
                
            # Extraer partes relevantes para no saturar el contexto si es inmenso
            # Especialmente excluir arrays masivos como residualSamples si son muy grandes, 
            # pero report.json suele ser manejable.
            report_context = json.dumps(report_data, indent=2)
        except Exception as e:
            _log.error("Error leyendo report.json para IA", error=str(e))
            report_context = f"Error al cargar el contexto geofísico: {e}"

    system_instruction = f"""
Eres TerraQuantum IA, un asistente B2B especializado en geofísica y estimación de recursos minerales.
Tu objetivo es ayudar al usuario a interpretar los resultados de la inversión geofísica y tomar decisiones.
A continuación se presenta el reporte técnico (report.json) del modelo geofísico actualmente cargado:

--- CONTEXTO DEL MODELO GEOFÍSICO ---
{report_context}
-------------------------------------

Responde a las preguntas del usuario utilizando esta información. Si te preguntan sobre el misfit, DOI, 
o incertidumbre, refiere a los datos de este reporte.
    """.strip()
    
    # Construir historial para Gemini
    # Convertimos messages a formato de Gemini
    formatted_messages = []
    for msg in request.messages[:-1]:
        role = "user" if msg.role == "user" else "model"
        formatted_messages.append({"role": role, "parts": [msg.content]})
        
    last_user_message = request.messages[-1].content if request.messages else ""

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            system_instruction=system_instruction
        )
        
        chat = model.start_chat(history=formatted_messages)
        response = chat.send_message(last_user_message)
        
        return {"response": response.text}
    except Exception as e:
        _log.error("Error en Gemini API", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error en la IA: {str(e)}")
