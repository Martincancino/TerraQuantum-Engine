"""F7 — Endpoints de licenciamiento local-first (Ed25519, offline).

    GET  /license/status    — estado y tier efectivo de la licencia activa
    POST /license/activate  — verifica un token y lo guarda si es válido

Sin licencia el estado es siempre válido (modo local libre) — estos endpoints
JAMÁS bloquean el arranque ni el camino dorado; solo informan y activan.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from core import license_service

router = APIRouter(prefix="/license", tags=["license"])


class ActivateRequest(BaseModel):
    token: str


@router.get("/status")
def license_status():
    """Estado de la licencia activa + límites del tier efectivo."""
    return license_service.get_license_status()


@router.post("/activate")
def activate(body: ActivateRequest):
    """Verifica un token de licencia; si es válido lo persiste en el directorio
    de datos del usuario. Devuelve el estado resultante (nunca lanza 500)."""
    return license_service.activate_license(body.token)
