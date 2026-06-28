"""FASE 19 (Caso B) — Georef Helmert en /enrich-package (cierre de asimetría).

Hoy Helmert estaba cableado SOLO en /invert. Un usuario con coords LOCALES que entra
por «Generar CSV completo» (→/enrich-package) ahora también obtiene georef si aporta
≥2 puntos de control. Estos tests fijan el contrato:
  • ≥2 puntos + CSV local → 200 con summary["helmert_georef"] (confidence + residual).
  • <2 puntos / JSON malo → 422 claro (HELMERT_INPUT_INVALID), nunca crash.
  • SIN el param → summary byte-idéntico a hoy (la clave NO aparece).
  • CSV ya georreferenciado (lat/lon) + puntos → skipped con razón (no aplica).

NO se duplica la matemática: reusa georeference_stations_with_helmert (igual /invert).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def _local_grav_csv(n_side=4):
    """Coordenadas LOCALES (x_m,z_m) en metros → detectado como local_meters."""
    lines = ["x_m,z_m,g_mgal,unit,gravity_type"]
    for i in range(n_side):
        for j in range(n_side):
            x = i * 100.0
            z = j * 100.0
            val = 5.0 + 0.5 * ((i * n_side + j) % 5)
            lines.append(f"{x:.1f},{z:.1f},{val:.2f},mGal,bouguer_anomaly")
    return "\n".join(lines) + "\n"


def _latlon_grav_csv(n_side=4):
    lines = ["lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(n_side):
        for j in range(n_side):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0
            val = 5.0 + 0.5 * ((i * n_side + j) % 5)
            lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{val:.2f},mGal,bouguer_anomaly")
    return "\n".join(lines) + "\n"


# Puntos de control: local (x,z) ↔ real (E,N) UTM. Traslación pura por (500000, 7000000)
# sobre la grilla local 0..300 → georef sin rotación/escala.
_CTRL_2PTS = {
    "points": [
        {"local_x": 0.0, "local_z": 0.0, "real_e": 500000.0, "real_n": 7000000.0},
        {"local_x": 300.0, "local_z": 0.0, "real_e": 500300.0, "real_n": 7000000.0},
    ]
}
_CTRL_3PTS = {
    "points": [
        {"local_x": 0.0, "local_z": 0.0, "real_e": 500000.0, "real_n": 7000000.0},
        {"local_x": 300.0, "local_z": 0.0, "real_e": 500300.0, "real_n": 7000000.0},
        {"local_x": 0.0, "local_z": 300.0, "real_e": 500000.0, "real_n": 7000300.0},
    ]
}


def _enrich(client, files, data=None, params=None):
    return client.post(
        "/v2/gravity-import/enrich-package",
        files=files, data=data or {}, params=params or {},
    )


# ── ≥2 puntos sobre coords LOCALES → georef en el summary ─────────────────────
def test_helmert_two_points_georeferences_local_package():
    r = _enrich(
        _client(),
        files={"gravity_file": ("local.csv", _local_grav_csv(), "text/csv")},
        data={"helmert_control_points_json": json.dumps(_CTRL_2PTS)},
    )
    assert r.status_code == 200, r.text
    summary = r.json()["enrichment_summary"]
    assert "helmert_georef" in summary, summary
    g = summary["helmert_georef"]
    assert not g.get("skipped"), g
    assert g["confidence"] in ("HIGH", "MEDIUM"), g
    # residual_rms_m vive en transform (mismo helper que /invert).
    assert "residual_rms_m" in g["transform"], g["transform"]
    assert g["n_stations"] == 16  # grilla 4×4
    assert g["georeferenced_center"]["e"] > 100_000.0


def test_helmert_three_points_high_confidence():
    r = _enrich(
        _client(),
        files={"gravity_file": ("local.csv", _local_grav_csv(), "text/csv")},
        data={"helmert_control_points_json": json.dumps(_CTRL_3PTS)},
    )
    assert r.status_code == 200, r.text
    g = r.json()["enrichment_summary"]["helmert_georef"]
    assert g["confidence"] == "HIGH", g
    assert g["transform"]["residual_rms_m"] is not None


# ── <2 puntos / JSON malo → 422 claro (jamás crash) ───────────────────────────
def test_helmert_single_point_rejected_422():
    one = {"points": [{"local_x": 0.0, "local_z": 0.0, "real_e": 1.0, "real_n": 1.0}]}
    r = _enrich(
        _client(),
        files={"gravity_file": ("local.csv", _local_grav_csv(), "text/csv")},
        data={"helmert_control_points_json": json.dumps(one)},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "HELMERT_INPUT_INVALID"


def test_helmert_malformed_json_rejected_422():
    r = _enrich(
        _client(),
        files={"gravity_file": ("local.csv", _local_grav_csv(), "text/csv")},
        data={"helmert_control_points_json": "{not valid json"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "HELMERT_INPUT_INVALID"


# ── Guardrail: SIN el param → la clave NO aparece (histórico byte-idéntico) ────
def test_no_helmert_param_keeps_summary_historic():
    r = _enrich(
        _client(),
        files={"gravity_file": ("local.csv", _local_grav_csv(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert "helmert_georef" not in r.json()["enrichment_summary"]


# ── CSV ya georreferenciado (lat/lon) + puntos → skipped con razón ────────────
def test_helmert_skipped_when_coords_already_georeferenced():
    r = _enrich(
        _client(),
        files={"gravity_file": ("latlon.csv", _latlon_grav_csv(), "text/csv")},
        data={"helmert_control_points_json": json.dumps(_CTRL_2PTS)},
    )
    assert r.status_code == 200, r.text
    g = r.json()["enrichment_summary"]["helmert_georef"]
    assert g.get("skipped") is True, g
    assert "no son locales" in g["reason"]
