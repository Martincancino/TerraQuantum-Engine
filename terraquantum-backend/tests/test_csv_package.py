"""FASE R4 — Tests del paquete CSV auto-contenido (build + load) por combo.

Cubren:
  - Funciones puras del servicio (build_package_text / parse_package_text): el
    cuerpo es un CSV importable (con unit/gravity_type) y el encabezado round-trips.
  - Endpoints E2E /v2/gravity-import/build-package y /load-package para cada combo:
    solo gravedad, solo magnetismo, joint (grav+mag co-localizado) y grav+sondajes.
    Se verifica el ruteo (plan multimodal) y que la inversión finaliza.
"""
import io
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv as _csv

from schemas.geophysics_schema import GravityObservation
from services.csv_package_service import (
    build_package_text,
    parse_package_text,
    align_magnetic_to_stations,
    PACKAGE_MAGIC,
)


def _rows(text):
    return list(_csv.reader(io.StringIO(text)))


# ── Funciones puras del servicio ─────────────────────────────────────────────
def _stub_gravity_result(n=12, with_mag=False):
    obs = [
        GravityObservation(x_m=float(i * 30), y_m=0.0, z_m=float((i % 4) * 30), g=(5.0 + 0.1 * i) * 1e-5)
        for i in range(n)
    ]
    return SimpleNamespace(
        observations=obs,
        station_elevations=None,
        station_uncertainties=None,
        magnetic_values=([51000.0 + i for i in range(n)] if with_mag else None),
        raw_latlon_elev=None,
    )


def test_build_package_gravity_body_is_importable():
    """El cuerpo gravimétrico incluye unit + gravity_type (exigidos por el import)."""
    res = _stub_gravity_result(n=12)
    text = build_package_text(
        primary_result=res, data_type="gravity",
        config={"region": "norte_chile"}, boreholes=[], plan={"route": "gravity_only"},
    )
    assert text.splitlines()[0].startswith(PACKAGE_MAGIC)
    parsed = parse_package_text(text)
    body_rows = _rows(parsed.body_csv)
    assert body_rows[0] == ["station_id", "x_m", "y_m", "z_m", "g_mgal", "unit", "gravity_type"]
    assert body_rows[1][5] == "mGal"
    assert body_rows[1][6] == "bouguer_anomaly"
    # round-trip de mGal: 5.0e-5 * 1e5 = 5.0
    assert abs(float(body_rows[1][4]) - 5.0) < 1e-6


def test_build_package_joint_adds_magnetic_column():
    res = _stub_gravity_result(n=12)
    mag_vals = [51000.0 + i for i in range(12)]
    text = build_package_text(
        primary_result=res, data_type="gravity", config={},
        magnetic_values=mag_vals, boreholes=[], plan={"route": "gravity_magnetic_joint"},
    )
    parsed = parse_package_text(text)
    body_rows = _rows(parsed.body_csv)
    assert body_rows[0][-1] == "magnetic_nt"
    assert abs(float(body_rows[1][-1]) - 51000.0) < 1e-6


def test_build_package_magnetic_uses_tmi():
    res = _stub_gravity_result(n=12)  # en magnetic, g lleva TMI tal cual
    text = build_package_text(
        primary_result=res, data_type="magnetic", config={}, plan={"route": "magnetic_only"},
    )
    parsed = parse_package_text(text)
    assert parsed.data_type == "magnetic"
    body_rows = _rows(parsed.body_csv)
    assert body_rows[0] == ["station_id", "x_m", "y_m", "z_m", "tmi_nt"]


def test_parse_package_header_roundtrips_config_and_boreholes():
    res = _stub_gravity_result(n=12)
    bhs = [{"x_m": 100.0, "z_m": 100.0, "y_from_m": 20.0, "y_to_m": 120.0, "density_t_m3": 2.8}]
    text = build_package_text(
        primary_result=res, data_type="gravity",
        config={"density_max": 4.0, "lambda_mag": 0.1}, boreholes=bhs,
        plan={"route": "gravity_with_constraints", "confidence": 0.8},
    )
    parsed = parse_package_text(text)
    assert parsed.config["density_max"] == 4.0
    assert parsed.config["lambda_mag"] == 0.1
    assert parsed.boreholes == bhs
    assert parsed.plan["route"] == "gravity_with_constraints"


def test_parse_package_rejects_non_package():
    import pytest
    with pytest.raises(ValueError):
        parse_package_text("lat,lon,g\n-27.1,-69.3,5.0\n")


# ── Fix R4 (riesgo 2): alineación joint por coordenada, no por índice ─────────
def test_align_magnetic_matches_by_coords_reordered():
    grav = [
        GravityObservation(x_m=0.0, y_m=0.0, z_m=0.0, g=1e-5),
        GravityObservation(x_m=100.0, y_m=0.0, z_m=0.0, g=2e-5),
        GravityObservation(x_m=0.0, y_m=0.0, z_m=100.0, g=3e-5),
    ]
    # Magnetometría DESORDENADA respecto a la gravimetría (TMI distinto por lugar).
    mag = [
        GravityObservation(x_m=0.0, y_m=0.0, z_m=100.0, g=300.0),
        GravityObservation(x_m=0.0, y_m=0.0, z_m=0.0, g=100.0),
        GravityObservation(x_m=100.0, y_m=0.0, z_m=0.0, g=200.0),
    ]
    out = align_magnetic_to_stations(grav, mag)
    # Emparejado por coordenada (no por índice): el viejo código por índice fallaría.
    assert out == [100.0, 200.0, 300.0]


def test_align_magnetic_raises_when_not_colocated():
    import pytest
    grav = [
        GravityObservation(x_m=0.0, y_m=0.0, z_m=0.0, g=1e-5),
        GravityObservation(x_m=100.0, y_m=0.0, z_m=0.0, g=2e-5),
    ]
    mag = [GravityObservation(x_m=5000.0, y_m=0.0, z_m=5000.0, g=100.0)]
    with pytest.raises(ValueError):
        align_magnetic_to_stations(grav, mag)


# ── Endpoints E2E por combo ──────────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def _grav_csv(n_side=4):
    lines = ["lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(n_side):
        for j in range(n_side):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0 + j * 2.0
            val = 5.0 + 0.5 * ((i * n_side + j) % 5)
            lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{val:.2f},mGal,bouguer_anomaly")
    return "\n".join(lines) + "\n"


def _mag_csv(n_side=4):
    lines = ["lat,lon,elev_m,tmi_nt"]
    for i in range(n_side):
        for j in range(n_side):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0 + j * 2.0
            tmi = 51000.0 + 20.0 * ((i * n_side + j) % 5)
            lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{tmi:.2f}")
    return "\n".join(lines) + "\n"


_GRAV = _grav_csv()
_MAG = _mag_csv()


def _build(client, files, params=None, data=None):
    return client.post(
        "/v2/gravity-import/build-package",
        files=files, params=params or {}, data=data or {},
    )


def _load(client, package_text):
    return client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("pkg.tqpkg.csv", package_text, "text/csv")},
    )


def test_e2e_gravity_only():
    c = _client()
    rb = _build(c, files={"file": ("grav.csv", _GRAV, "text/csv")})
    assert rb.status_code == 200, rb.text
    assert rb.headers["x-tq-package-route"] == "gravity_only"
    rl = _load(c, rb.text)
    assert rl.status_code == 200, rl.text
    body = rl.json()
    assert body["status"] == "done", body
    assert body["route"] == "gravity_only"
    assert body["inversionResult"]
    # Fix R4 (riesgo 4): sin project_id/run_id el endpoint los auto-genera y
    # persiste el block model (el visor puede recuperarlo).
    assert body["project_id"].startswith("pkg_")
    assert body["run_id"].startswith("run_pkg_")


def test_e2e_magnetic_only():
    c = _client()
    rb = _build(
        c, files={"file": ("mag.csv", _MAG, "text/csv")},
        params={"data_type": "magnetic", "strict": "false"},
    )
    assert rb.status_code == 200, rb.text
    assert rb.headers["x-tq-package-route"] == "magnetic_only"
    rl = _load(c, rb.text)
    assert rl.status_code == 200, rl.text
    body = rl.json()
    assert body["status"] == "done", body
    assert body["route"] == "magnetic_only"
    assert body["inversionResult"]


def test_e2e_joint_gravity_plus_magnetic():
    c = _client()
    rb = _build(
        c,
        files={
            "file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG, "text/csv"),
        },
    )
    assert rb.status_code == 200, rb.text
    assert rb.headers["x-tq-package-route"] == "gravity_magnetic_joint"
    # El cuerpo debe traer la columna magnética co-localizada.
    assert "magnetic_nt" in rb.text.splitlines()[-2] or "magnetic_nt" in rb.text
    rl = _load(c, rb.text)
    assert rl.status_code == 200, rl.text
    body = rl.json()
    assert body["status"] == "done", body
    assert body["route"] == "gravity_magnetic_joint"
    assert body["inversionResult"]


def test_e2e_gravity_with_boreholes():
    c = _client()
    bhs = [{"x_m": 150.0, "z_m": 150.0, "y_from_m": 20.0, "y_to_m": 120.0, "density_t_m3": 2.8}]
    rb = _build(
        c, files={"file": ("grav.csv", _GRAV, "text/csv")},
        data={"boreholes_json": json.dumps(bhs)},
    )
    assert rb.status_code == 200, rb.text
    assert rb.headers["x-tq-package-route"] == "gravity_with_constraints"
    parsed = parse_package_text(rb.text)
    assert parsed.boreholes == bhs
    rl = _load(c, rb.text)
    assert rl.status_code == 200, rl.text
    body = rl.json()
    assert body["status"] == "done", body
    assert body["route"] == "gravity_with_constraints"
    assert body["inversionResult"]


def _enrich(client, files, params=None, data=None):
    return client.post(
        "/v2/gravity-import/enrich-package",
        files=files, params=params or {}, data=data or {},
    )


def test_e2e_enrich_returns_summary_and_loadable_package():
    """enrich-package devuelve resumen + un TQPKG que load-package puede invertir."""
    c = _client()
    re = _enrich(c, files={"file": ("grav.csv", _GRAV, "text/csv")},
                 data={"config_json": json.dumps({"gravimeter_type": "scintrex_cg6"})})
    assert re.status_code == 200, re.text
    body = re.json()
    summ = body["enrichment_summary"]
    keys = {s["key"] for s in summ["steps"]}
    assert {"coordinates", "elevation", "sigma", "quality"} <= keys
    assert summ["nothing_fabricated"] is True
    # El dato ya es bouguer_anomaly → no se re-corrige; σ derivado con piso del CG-6.
    sigma = next(s for s in summ["steps"] if s["key"] == "sigma")
    assert sigma["status"] == "derived"
    # El package_text es un TQPKG válido y cargable.
    parsed = parse_package_text(body["package_text"])
    assert "sigma_mgal" in parsed.body_csv.splitlines()[0]
    rl = _load(c, body["package_text"])
    assert rl.status_code == 200, rl.text
    assert rl.json()["status"] == "done"


def test_e2e_enrich_magnetic_igrf_not_derivable():
    c = _client()
    re = _enrich(c, files={"file": ("mag.csv", _MAG, "text/csv")},
                 params={"data_type": "magnetic", "strict": "false"})
    assert re.status_code == 200, re.text
    summ = re.json()["enrichment_summary"]
    igrf = next(s for s in summ["steps"] if s["key"] == "igrf")
    assert igrf["status"] == "not_derivable"


def test_e2e_load_rejects_plain_csv():
    c = _client()
    r = _load(c, "lat,lon,bouguer_anomaly,unit,gravity_type\n-27.1,-69.3,5.0,mGal,bouguer_anomaly\n")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "INVALID_PACKAGE"


# ── Fix R4 (riesgo 3): gates aplicados al ENSAMBLAR (build no invierte → rápido) ─
def _local_grav_csv(n_side=4):
    """Coordenadas LOCALES (x_m,z_m) sin lat/lon ni ancla → LOCAL_UNANCHORED."""
    lines = ["x_m,z_m,g_mgal,unit,gravity_type"]
    for i in range(n_side):
        for j in range(n_side):
            x = i * 100.0
            z = j * 100.0
            val = 5.0 + 0.5 * ((i * n_side + j) % 5)
            lines.append(f"{x:.1f},{z:.1f},{val:.2f},mGal,bouguer_anomaly")
    return "\n".join(lines) + "\n"


def test_e2e_build_gate_blocks_unanchored_without_ack():
    c = _client()
    rb = _build(c, files={"file": ("local.csv", _local_grav_csv(), "text/csv")})
    assert rb.status_code == 422, rb.text
    assert rb.json()["detail"]["error"] == "SPATIAL_READINESS_GATE"


def test_e2e_build_gate_passes_with_ack():
    c = _client()
    rb = _build(
        c, files={"file": ("local.csv", _local_grav_csv(), "text/csv")},
        data={"config_json": json.dumps({"acknowledge_spatial_risk": True})},
    )
    assert rb.status_code == 200, rb.text
    # El plan en el encabezado registra el veredicto del gate.
    parsed = parse_package_text(rb.text)
    assert "spatial_readiness_level" in parsed.plan
