"""
Compatibilidad temporal.

La ruta /geophysics-invert ahora vive en:
api/geophysics_api.py

Este archivo queda solo para evitar confusión si algún módulo antiguo todavía lo importa.
"""

from api.geophysics_api import router