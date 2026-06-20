"""
FASE 19 (Caso B) — Tests del cableado Helmert al flujo de inversión.

Cubren el contrato de entrada (HelmertControlPointsInput) y el helper de servicio
georeference_stations_with_helmert (puro, sin correr la inversión completa):
  - traslación pura (scale=1, rot=0) → centro georeferenciado correcto
  - rotación + traslación → escala/rotación recuperadas
  - <2 puntos → el schema rechaza
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from schemas.gravity_import_schema import HelmertControlPoint, HelmertControlPointsInput
from services.gravity_import_service import georeference_stations_with_helmert


def _ctrl(points):
    return HelmertControlPointsInput(
        points=[HelmertControlPoint(local_x=lx, local_z=lz, real_e=e, real_n=n)
                for (lx, lz, e, n) in points]
    )


def test_helmert_pure_translation_georeferences_center():
    # local→real = traslación por (500, 700); scale=1, rot=0.
    ctrl = _ctrl([(0, 0, 500, 700), (100, 0, 600, 700), (0, 100, 500, 800)])
    out = georeference_stations_with_helmert(ctrl, [(50.0, 50.0)])
    assert out["confidence"] == "HIGH"
    assert out["transform"]["scale"] == pytest.approx(1.0, abs=1e-6)
    assert out["transform"]["rotation_deg"] == pytest.approx(0.0, abs=1e-6)
    # estación (50,50) → (550, 750)
    assert out["georeferenced_center"]["e"] == pytest.approx(550.0, abs=1e-6)
    assert out["georeferenced_center"]["n"] == pytest.approx(750.0, abs=1e-6)
    assert out["n_stations"] == 1


def test_helmert_rotation_recovered():
    # Rotación 90° + escala 1: local (1,0)->real (0,1); (0,1)->(-1,0); origen fijo.
    ctrl = _ctrl([(0, 0, 0, 0), (1, 0, 0, 1), (0, 1, -1, 0)])
    out = georeference_stations_with_helmert(ctrl, [(2.0, 0.0)])
    assert out["transform"]["scale"] == pytest.approx(1.0, abs=1e-6)
    assert abs(out["transform"]["rotation_deg"]) == pytest.approx(90.0, abs=1e-6)
    # estación (2,0) → (0, 2)
    assert out["georeferenced_center"]["e"] == pytest.approx(0.0, abs=1e-6)
    assert out["georeferenced_center"]["n"] == pytest.approx(2.0, abs=1e-6)


def test_helmert_two_points_medium_confidence():
    ctrl = _ctrl([(0, 0, 1000, 2000), (100, 0, 1100, 2000)])
    out = georeference_stations_with_helmert(ctrl, [(50.0, 0.0)])
    assert out["transform"]["n_control_points"] == 2
    assert out["confidence"] == "MEDIUM"  # 2 puntos = exacto sin redundancia


def test_helmert_schema_rejects_single_point():
    with pytest.raises(Exception):
        HelmertControlPointsInput(points=[HelmertControlPoint(
            local_x=0, local_z=0, real_e=1, real_n=1)])


def test_helmert_no_stations_returns_none_center():
    ctrl = _ctrl([(0, 0, 500, 700), (100, 0, 600, 700)])
    out = georeference_stations_with_helmert(ctrl, [])
    assert out["georeferenced_center"] is None
    assert out["n_stations"] == 0
