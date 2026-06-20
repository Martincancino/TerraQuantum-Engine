"""
FASE 20 — Contrato del parámetro boreholes_json de /gravity-import/invert.

El endpoint parsea boreholes_json (JSON del frontend) a List[BoreholeInterval] y
lo inyecta en GeophysicsInvertInput.boreholes (anclaje combo grav+sondajes). Aquí
verificamos ESE contrato de parseo (rápido, sin correr la inversión completa), que
es exactamente lo que ejecuta el endpoint inline.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from schemas.geophysics_schema import BoreholeInterval, GeophysicsInvertInput, GravityObservation


def _parse_boreholes_json(boreholes_json: str):
    """Réplica exacta del parseo del endpoint (tolera lista o {'boreholes':[...]})."""
    raw = json.loads(boreholes_json)
    if isinstance(raw, dict):
        raw = raw.get("boreholes") or raw.get("intervals") or []
    return [BoreholeInterval(**b) for b in raw]


def test_parse_boreholes_json_list():
    payload = json.dumps([
        {"x_m": 150.0, "z_m": 150.0, "y_from_m": 110.0, "y_to_m": 190.0, "density_t_m3": 3.4},
        {"x_m": 270.0, "z_m": 150.0, "y_from_m": 110.0, "y_to_m": 190.0, "density_t_m3": 2.6},
    ])
    bhs = _parse_boreholes_json(payload)
    assert len(bhs) == 2
    assert bhs[0].density_t_m3 == 3.4
    assert bhs[1].x_m == 270.0


def test_parse_boreholes_json_wrapped_dict():
    payload = json.dumps({"boreholes": [
        {"x_m": 0.0, "z_m": 0.0, "y_from_m": 50.0, "y_to_m": 100.0, "density_t_m3": 2.9},
    ]})
    bhs = _parse_boreholes_json(payload)
    assert len(bhs) == 1 and bhs[0].density_t_m3 == 2.9


def test_boreholes_feed_geophysics_invert_input():
    # El contrato final: la lista parseada entra en GeophysicsInvertInput.boreholes.
    bhs = _parse_boreholes_json(json.dumps([
        {"x_m": 10.0, "z_m": 20.0, "y_from_m": 30.0, "y_to_m": 60.0, "density_t_m3": 3.1},
    ]))
    inp = GeophysicsInvertInput(
        project_id="p", run_id="r", depth=300, nir=0, fe=0, region="test",
        nx=12, ny=12, nz=12, block_size=25, cutoff_radius=8000.0,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            GravityObservation(x_m=float(i * 10), y_m=0.0, z_m=float(i % 4 * 10), g=1e-5)
            for i in range(12)
        ],
        boreholes=bhs,
    )
    assert len(inp.boreholes) == 1
    assert inp.boreholes[0].density_t_m3 == 3.1


def test_parse_boreholes_json_rejects_empty_interval():
    # BoreholeInterval exige ≥1 propiedad (density o susceptibility).
    with pytest.raises(Exception):
        _parse_boreholes_json(json.dumps([
            {"x_m": 1.0, "z_m": 1.0, "y_from_m": 0.0, "y_to_m": 10.0},
        ]))
