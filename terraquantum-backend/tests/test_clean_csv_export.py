"""
FASE 19 — Tests del export "CSV limpio".

Cubren:
  - build_clean_csv_from_import: serialización determinista (columnas, unidades,
    columnas opcionales presentes/ausentes) usando un stub liviano (sin import real).
  - POST /v2/gravity-import/export-clean-csv: integración end-to-end (CSV sucio →
    text/csv descargable) con TestClient.
"""
import io
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv as _csv

from schemas.geophysics_schema import GravityObservation
from services.gravity_import_service import build_clean_csv_from_import


def _rows(text):
    return list(_csv.reader(io.StringIO(text)))


# ── Función pura de serialización ───────────────────────────────────────────
def test_clean_csv_gravity_minimal_columns():
    # Solo coordenadas + valor (sin sigma/elev/latlon) → 5 columnas.
    res = SimpleNamespace(
        observations=[
            GravityObservation(x_m=10.0, y_m=0.0, z_m=20.0, g=10.0e-5),   # 10 mGal
            GravityObservation(x_m=30.0, y_m=0.0, z_m=40.0, g=12.5e-5),   # 12.5 mGal
        ],
        station_elevations=None, station_uncertainties=None,
        magnetic_values=None, raw_latlon_elev=None,
    )
    rows = _rows(build_clean_csv_from_import(res, data_kind="gravity"))
    assert rows[0] == ["station_id", "x_m", "y_m", "z_m", "g_mgal"]
    assert rows[1][0] == "ST0001"
    # m/s² → mGal: 10e-5 * 1e5 = 10.
    assert float(rows[1][4]) == 10.0
    assert float(rows[2][4]) == 12.5


def test_clean_csv_gravity_full_optional_columns():
    res = SimpleNamespace(
        observations=[GravityObservation(x_m=10.0, y_m=0.0, z_m=20.0, g=10.0e-5)],
        station_elevations=[1234.5],
        station_uncertainties=[0.01],
        magnetic_values=[51000.0],
        raw_latlon_elev=[{"lat_deg": -27.1, "lon_deg": -69.3, "elev_m": 1234.5}],
    )
    rows = _rows(build_clean_csv_from_import(res, data_kind="gravity"))
    assert rows[0] == [
        "station_id", "x_m", "y_m", "z_m", "g_mgal",
        "sigma_mgal", "elev_masl", "lat_deg", "lon_deg", "magnetic_nt",
    ]
    assert float(rows[1][5]) == 0.01            # sigma
    assert float(rows[1][6]) == 1234.5          # elev
    assert float(rows[1][7]) == -27.1           # lat
    assert float(rows[1][9]) == 51000.0         # magnetic


def test_clean_csv_magnetic_uses_tmi_no_gravity_conversion():
    res = SimpleNamespace(
        observations=[GravityObservation(x_m=10.0, y_m=0.0, z_m=20.0, g=51000.0)],
        station_elevations=None, station_uncertainties=None,
        magnetic_values=None, raw_latlon_elev=None,
    )
    rows = _rows(build_clean_csv_from_import(res, data_kind="magnetic"))
    assert rows[0] == ["station_id", "x_m", "y_m", "z_m", "tmi_nt"]
    # TMI tal cual (sin ×1e5).
    assert float(rows[1][4]) == 51000.0


def test_clean_csv_empty_observations_header_only():
    res = SimpleNamespace(
        observations=[], station_elevations=None, station_uncertainties=None,
        magnetic_values=None, raw_latlon_elev=None,
    )
    rows = _rows(build_clean_csv_from_import(res, data_kind="gravity"))
    assert len(rows) == 1
    assert rows[0][0] == "station_id"


# ── Endpoint de integración ─────────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def _make_valid_csv(n_side=4):
    """Grilla 2D de estaciones (≥10 obs, cobertura no degenerada) que el import acepta."""
    lines = ["lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(n_side):
        for j in range(n_side):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0 + j * 2.0
            val = 5.0 + 0.1 * ((i * n_side + j) % 5)
            lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{val:.2f},mGal,bouguer_anomaly")
    return "\n".join(lines) + "\n"


_VALID_CSV = _make_valid_csv()  # 16 estaciones en grilla 4×4


def test_endpoint_export_clean_csv_ok():
    r = _client().post(
        "/v2/gravity-import/export-clean-csv",
        files={"file": ("dirty.csv", _VALID_CSV, "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('dirty_clean.csv"')
    rows = _rows(r.text)
    assert rows[0][:5] == ["station_id", "x_m", "y_m", "z_m", "g_mgal"]
    assert len(rows) == 17  # cabecera + 16 estaciones
    assert int(r.headers["x-tq-clean-rows"]) == 16


def test_endpoint_export_clean_csv_rejects_non_csv():
    r = _client().post(
        "/v2/gravity-import/export-clean-csv",
        files={"file": ("data.txt", _VALID_CSV, "text/plain")},
    )
    assert r.status_code == 400
