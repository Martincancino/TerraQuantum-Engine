"""
Router FastAPI — Estrategia de Fusión Multimodal (FASE 21).

Endpoint de PREVISUALIZACIÓN (no ejecuta inversión): dada la disponibilidad de
datos (cuántos sensores gravimétricos/magnéticos, cuántos sondajes con densidad,
calidad y cobertura), devuelve el plan de fusión — qué combo se usaría, su
confianza, el error de profundidad esperado y los avisos.

    POST /multimodal/plan
        El frontend manda CONTEOS de lo que el usuario tiene cargado; el backend
        decide la ruta y las métricas. Así el selector visual muestra "combo
        recomendado + confianza + error" ANTES de invertir, sin que el frontend
        calcule física ni confianza (Regla de Oro).

La misma lógica (services.multimodal_fusion_service) corre dentro de la inversión
y se adjunta a report.multimodal_plan, así que la previsualización y el resultado
final son coherentes.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.logging import get_logger
from services.multimodal_fusion_service import (
    InsufficientDataError,
    plan_multimodal,
)

router = APIRouter(prefix="/multimodal", tags=["Multimodal Fusion (Fase 21)"])
_log = get_logger(__name__)


class MultimodalPlanRequest(BaseModel):
    n_gravity_sensors: int = Field(
        0, ge=0, description="Número de estaciones gravimétricas cargadas.",
    )
    n_magnetic_sensors: int = Field(
        0, ge=0, description="Número de estaciones magnéticas cargadas.",
    )
    n_boreholes_with_density: int = Field(
        0, ge=0, description="Número de tramos de sondaje con densidad medida.",
    )
    data_quality: Optional[float] = Field(
        None, ge=0.0, le=100.0,
        description="Data Quality Score 0–100 (Fase 19). None = no ajustar confianza.",
    )
    coverage_pct: float = Field(
        1.0, ge=0.0, le=1.0,
        description="Fracción de cobertura espacial del survey [0–1].",
    )


class MultimodalPlanResponse(BaseModel):
    # Disponibilidad derivada (eco para el frontend).
    has_gravity: bool
    has_magnetic: bool
    has_borehole: bool
    n_sensors: int
    # Plan (None si los datos son insuficientes para invertir).
    plan: Optional[dict] = None
    insufficient_reason: Optional[str] = None


@router.post("/plan", response_model=MultimodalPlanResponse)
def multimodal_plan(req: MultimodalPlanRequest) -> MultimodalPlanResponse:
    has_g = req.n_gravity_sensors > 0
    has_m = req.n_magnetic_sensors > 0
    has_b = req.n_boreholes_with_density > 0
    # Para un campo potencial cuentan sus propias estaciones; el "n_sensors" del
    # ruteo es el mayor de los dos (el combo se decide por el dato disponible).
    n_sensors = max(req.n_gravity_sensors, req.n_magnetic_sensors)

    try:
        plan = plan_multimodal(
            has_gravity=has_g,
            has_magnetic=has_m,
            has_borehole=has_b,
            n_sensors=n_sensors,
            data_quality=req.data_quality,
            coverage_pct=req.coverage_pct,
        )
    except InsufficientDataError as exc:
        return MultimodalPlanResponse(
            has_gravity=has_g,
            has_magnetic=has_m,
            has_borehole=has_b,
            n_sensors=n_sensors,
            plan=None,
            insufficient_reason=str(exc),
        )

    return MultimodalPlanResponse(
        has_gravity=has_g,
        has_magnetic=has_m,
        has_borehole=has_b,
        n_sensors=n_sensors,
        plan=plan.to_dict(),
        insufficient_reason=None,
    )
