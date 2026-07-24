# -*- coding: utf-8 -*-
"""F9 — Validación física como REGRESIÓN AUTOMÁTICA.

Congela la física YA validada (DO-27, Raglan, San Nicolás, LdM + sintéticos) con
tolerancias EXPLÍCITAS. Cada test RE-EJECUTA el motor real (no lee modelos cacheados),
así que una degradación futura del motor (p.ej. romper el depth-weighting W_z) hace
FALLAR la suite y suena la alarma.

Estos tests son LENTOS (minutos: cada uno re-invierte). Van marcados `validation` y se
SALTAN en la suite normal / CI rápido (ver tests/conftest.py). Se corren a demanda:

    TQ_RUN_VALIDATION=1  python -m pytest tests/test_f9_physics_regression.py -v
    python -m pytest tests/test_f9_physics_regression.py -v --run-validation
    python scripts/validation/f9_gate_regression.py     # gate + reporte HTML

Las tolerancias no se tunean para pasar: son los números MEDIDOS con el motor sano,
con margen. El límite físico de la gravedad-sola (ambigüedad de profundidad) se valida
como EXPECTATIVA (debe reproducirse), no como fallo.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validation import f9_regression_lib as F9  # noqa: E402

pytestmark = [pytest.mark.validation, pytest.mark.slow]


def _assert_case(case: dict):
    """Falla con un mensaje legible que incluye valor, tolerancia y métricas secundarias."""
    sec = " · ".join(f"{s['label']}={s['value']}" for s in case.get("secondary", []))
    msg = (f"[{case['key']}] {case['title']}\n"
           f"    métrica: {case['metric']} = {case['value']} {case.get('unit','')}\n"
           f"    tolerancia: {case['tolerance_str']}\n"
           f"    secundarias: {sec}\n"
           f"    nota: {case.get('note')}")
    assert case["passed"], msg


def test_synthetic_sphere_recovery():
    """Esfera sintética (anti-inverse-crime): correlación Pearson + compacidad + horizontal.
    Es el canario directo del depth-weighting W_z."""
    _assert_case(F9.case_synthetic_sphere())


def test_depth_ambiguity_is_a_documented_limit():
    """La gravedad-sola NO resuelve profundidad: el z-error sin restricción DEBE ser grande.
    Se valida como LÍMITE conocido (expectativa), no como fallo."""
    _assert_case(F9.case_depth_ambiguity())


def test_do27_targeting():
    """DO-27 (kimberlita): error horizontal de targeting ≤ tolerancia vs ground truth externo."""
    _assert_case(F9.case_do27())


def test_san_nicolas_field_fit():
    """San Nicolás (dato real): re-inversión desde observaciones guardadas ajusta al nivel de ruido."""
    _assert_case(F9.case_san_nicolas())


def test_ldm_field_chi2():
    """Laguna del Maule (dato real): χ² de Morozov ∈ banda sana (ajuste al ruido)."""
    _assert_case(F9.case_ldm())


def test_raglan_targeting():
    """Raglan (dato real): error del cuerpo dominante interior ≤ tolerancia vs referencia."""
    _assert_case(F9.case_raglan())
