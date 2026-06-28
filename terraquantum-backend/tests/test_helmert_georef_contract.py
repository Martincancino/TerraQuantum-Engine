"""
FASE 19 (Caso B) — Contrato end-to-end de la georef Helmert en /gravity-import/invert.

Estos tests VERIFICAN el contrato que el endpoint `invert_gravity_csv` ejecuta inline
(api/gravity_import_api.py, bloque "FASE 19 (Caso B): Georef Helmert"), sin correr la
inversión completa — misma convención que test_invert_boreholes_param.py. Cubren:

  (1) <2 puntos de control → error CLARO (no silencioso) en las dos capas que el
      endpoint atraviesa: el schema HelmertControlPointsInput (ValidationError por
      min_length=2) y el helper georeference_stations_with_helmert (ValueError).
  (2) ≥2 puntos local↔real → estaciones georreferenciadas y residual_rms_m REPORTADO
      en la estructura que el endpoint guarda en auto_params_metadata["helmert_georef"].
  (3) Predicado de gateo del endpoint: sin helmert_control_points_json → no se
      georreferencia (flujo histórico); coords NO locales → se omite con razón.

NOTA HONESTA sobre el comportamiento HTTP: ante una entrada Helmert inválida el endpoint
NO devuelve 422 — captura (ValueError, ValidationError, JSONDecodeError) y DEGRADA con un
warning ("[Fase 19] Georef Helmert no aplicada (entrada inválida): ..."), continuando la
inversión sin georef. El error "claro, no silencioso" vive en las capas de schema/servicio
(abajo) y en ese warning; la inversión no se cae por unos puntos de control malos.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError

from schemas.gravity_import_schema import HelmertControlPoint, HelmertControlPointsInput
from services.gravity_import_service import georeference_stations_with_helmert


def _ctrl(points):
    return HelmertControlPointsInput(
        points=[HelmertControlPoint(local_x=lx, local_z=lz, real_e=e, real_n=n)
                for (lx, lz, e, n) in points]
    )


def _parse_helmert_json(helmert_control_points_json):
    """Réplica exacta del parseo del endpoint (api/gravity_import_api.py:~2009)."""
    return HelmertControlPointsInput(**json.loads(helmert_control_points_json))


# ── (1) <2 puntos → error CLARO, no crash silencioso ─────────────────────────

def test_schema_rejects_single_control_point():
    # Capa de schema: el endpoint hace HelmertControlPointsInput(**json...). Con 1
    # punto el min_length=2 dispara ValidationError ANTES de tocar la inversión.
    with pytest.raises(ValidationError):
        _parse_helmert_json(json.dumps({"points": [
            {"local_x": 0, "local_z": 0, "real_e": 1000, "real_n": 2000},
        ]}))


def test_schema_rejects_zero_control_points():
    with pytest.raises(ValidationError):
        _parse_helmert_json(json.dumps({"points": []}))


def test_service_raises_on_fewer_than_two_points():
    # Capa de servicio (doble guarda): aunque se construyera el input con 1 punto
    # por otra vía, el helper lanza ValueError explícito (no resultado silencioso).
    with pytest.raises(ValueError):
        georeference_stations_with_helmert(
            HelmertControlPointsInput.model_construct(
                points=[HelmertControlPoint(local_x=0, local_z=0, real_e=1, real_n=1)],
                residual_warn_m=10.0,
            ),
            [(10.0, 10.0)],
        )


def test_service_raises_on_coincident_points():
    # Puntos locales coincidentes → transformada indeterminada → ValueError claro.
    ctrl = _ctrl([(5, 5, 1000, 2000), (5, 5, 1100, 2000)])
    with pytest.raises(ValueError):
        georeference_stations_with_helmert(ctrl, [(5.0, 5.0)])


# ── (2) ≥2 puntos → georef + residual_rms_m reportado en helmert_georef ───────

def test_two_points_georeferences_and_reports_residual():
    # Exactamente 2 puntos: traslación pura por (1000, 2000), scale=1, rot=0.
    ctrl = _parse_helmert_json(json.dumps({"points": [
        {"local_x": 0, "local_z": 0, "real_e": 1000, "real_n": 2000},
        {"local_x": 100, "local_z": 0, "real_e": 1100, "real_n": 2000},
    ]}))
    # Esta es exactamente la dict que el endpoint guarda en
    # auto_params_metadata["helmert_georef"].
    helmert_georef = georeference_stations_with_helmert(ctrl, [(50.0, 0.0), (50.0, 100.0)])

    assert helmert_georef["version"] == "helmert_georef_v0_1"
    assert helmert_georef["n_stations"] == 2
    # El endpoint loguea _helmert_georef['transform'].get('residual_rms_m'): debe existir.
    assert "residual_rms_m" in helmert_georef["transform"]
    # 2 puntos = ajuste exacto → residual ~0 y confidence MEDIUM (sin redundancia).
    assert helmert_georef["transform"]["residual_rms_m"] == pytest.approx(0.0, abs=1e-6)
    assert helmert_georef["confidence"] == "MEDIUM"
    # Estaciones efectivamente georreferenciadas: (50,0)->(1050,2000); centro promedia.
    assert helmert_georef["georeferenced_center"]["e"] == pytest.approx(1050.0, abs=1e-6)
    assert helmert_georef["georeferenced_center"]["n"] == pytest.approx(2050.0, abs=1e-6)


def test_three_points_high_confidence_residual_reported():
    ctrl = _ctrl([(0, 0, 500, 700), (100, 0, 600, 700), (0, 100, 500, 800)])
    out = georeference_stations_with_helmert(ctrl, [(50.0, 50.0)])
    assert out["confidence"] == "HIGH"
    assert out["transform"]["residual_rms_m"] == pytest.approx(0.0, abs=1e-6)
    assert out["transform"]["n_control_points"] == 3


def test_inconsistent_anchor_reports_high_residual():
    # 4 puntos que NO encajan en una similitud (el 4.º está desplazado): el residual
    # crece y el contrato lo reporta (valida el anclaje en vez de ocultarlo).
    ctrl = _ctrl([
        (0, 0, 0, 0),
        (100, 0, 100, 0),
        (0, 100, 0, 100),
        (100, 100, 180, 130),  # incoherente con scale=1/rot=0
    ])
    out = georeference_stations_with_helmert(ctrl, [(50.0, 50.0)])
    assert out["transform"]["residual_rms_m"] > 10.0
    assert out["confidence"] == "LOW"


# ── (3) Gateo del endpoint: sin puntos / coords no locales → no se georreferencia ─

def _endpoint_should_apply_helmert(helmert_control_points_json, cs_detected):
    """Réplica del gateo del endpoint (api/gravity_import_api.py:~2004,~2010).

    El endpoint solo georreferencia si (a) llegó el JSON y (b) las coords del CSV son
    locales. Devuelve (aplica_georef, omitido_por_cs_no_local).
    """
    if not helmert_control_points_json:
        return (False, False)  # flujo histórico: no se toca georef
    cs_local = (cs_detected or "").lower() in ("local_meters", "local", "unknown")
    return (cs_local, not cs_local)


def test_no_helmert_json_keeps_historic_flow():
    # Sin helmert_control_points_json el bloque no corre → no se georreferencia.
    applies, skipped_non_local = _endpoint_should_apply_helmert(None, "local_meters")
    assert applies is False and skipped_non_local is False
    applies, _ = _endpoint_should_apply_helmert("", "local_meters")
    assert applies is False


def test_non_local_coords_skip_helmert_with_reason():
    payload = json.dumps({"points": [
        {"local_x": 0, "local_z": 0, "real_e": 1000, "real_n": 2000},
        {"local_x": 100, "local_z": 0, "real_e": 1100, "real_n": 2000},
    ]})
    # Coords ya georreferenciadas (UTM) → Helmert se omite con razón, no se aplica.
    applies, skipped_non_local = _endpoint_should_apply_helmert(payload, "utm")
    assert applies is False and skipped_non_local is True
    # Coords locales → sí aplica.
    applies, _ = _endpoint_should_apply_helmert(payload, "local_meters")
    assert applies is True
