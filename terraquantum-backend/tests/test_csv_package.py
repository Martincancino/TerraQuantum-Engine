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


def test_e2e_load_rejects_plain_csv():
    c = _client()
    r = _load(c, "lat,lon,bouguer_anomaly,unit,gravity_type\n-27.1,-69.3,5.0,mGal,bouguer_anomaly\n")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "INVALID_PACKAGE"
