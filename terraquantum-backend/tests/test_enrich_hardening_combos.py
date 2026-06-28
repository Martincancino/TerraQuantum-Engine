"""PART A — Hardening de los combos sin cobertura E2E dura en /enrich-package.

Los combos magnético-SOLO y JOINT (grav+mag co-localizados) deben terminar SIEMPRE
en «limpio (200) O error claro (4xx)», NUNCA en 500/traceback crudo — incluso con
entradas sucias: encabezado raro + (magnetic_)column_map_json, fila-basura tipo IGRF,
y BOM. Esta es la red de seguridad que faltaba; no cambia la lógica de producción.

Invariante central (_assert_clean_or_clear): status ∈ {200,400,413,422}, jamás 500, y
si no es 200 el cuerpo trae un `detail` accionable (no un traceback).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def _enrich(client, files, data=None, params=None):
    return client.post(
        "/v2/gravity-import/enrich-package",
        files=files, data=data or {}, params=params or {},
    )


def _assert_clean_or_clear(r):
    """Invariante dura: limpio (200) o error CLARO (4xx), jamás 500/crash."""
    assert r.status_code != 500, f"CRASH 500: {r.text}"
    assert r.status_code in (200, 400, 413, 422), r.text
    if r.status_code != 200:
        body = r.json()
        assert "detail" in body, f"Error sin detail accionable: {body}"


# ── Generadores de CSV (lat/lon co-localizados grav↔mag) ──────────────────────
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


def _mag_csv(n_side=4, header="lat,lon,elev_m,tmi_nt"):
    lines = [header]
    for i in range(n_side):
        for j in range(n_side):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0 + j * 2.0
            tmi = 51000.0 + 20.0 * ((i * n_side + j) % 5)
            lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{tmi:.2f}")
    return "\n".join(lines) + "\n"


# Encabezado RARO (no auto-detectable) → requiere mapeo manual de columnas.
_WEIRD_MAG_HEADER = "px,py,height,field_value"
_WEIRD_MAG_MAP = {"x": "px", "y": "py", "elevation": "height", "magnetic_value": "field_value"}


def _mag_csv_with_junk(n_side=4):
    """Magnético con filas-basura tipo IGRF intercaladas (inc/dec/intensidad)."""
    rows = _mag_csv(n_side).splitlines()
    rows.insert(1, "# IGRF inclination_deg=83.8 declination_deg=25.4 intensity_nt=60308")
    rows.insert(3, "NaN,NaN,,")
    return "\n".join(rows) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# MAGNÉTICO-SOLO
# ══════════════════════════════════════════════════════════════════════════════
def test_mag_only_clean_is_200_magnetic_route():
    r = _enrich(_client(), files={"magnetic_file": ("mag.csv", _mag_csv(), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "magnetic_only"


def test_mag_only_bom_header_tolerated():
    # BOM en el encabezado (UTF-8-SIG) no debe romper la ingesta.
    bom = "﻿" + _mag_csv()
    r = _enrich(_client(), files={"magnetic_file": ("magbom.csv", bom, "text/csv")})
    _assert_clean_or_clear(r)


def test_mag_only_weird_header_without_map_needs_mapping_not_crash():
    r = _enrich(
        _client(),
        files={"magnetic_file": ("weird.csv", _mag_csv(header=_WEIRD_MAG_HEADER), "text/csv")},
    )
    _assert_clean_or_clear(r)
    # Encabezado no reconocible → el backend pide MAPEO (200), no revienta.
    if r.status_code == 200:
        assert r.json().get("needs_mapping") is True, r.text


def test_mag_only_weird_header_with_column_map_resolves():
    # En mag-SOLO el primario es el magnético → column_map_json aplica al primario.
    r = _enrich(
        _client(),
        files={"magnetic_file": ("weird.csv", _mag_csv(header=_WEIRD_MAG_HEADER), "text/csv")},
        data={"column_map_json": json.dumps(_WEIRD_MAG_MAP)},
    )
    _assert_clean_or_clear(r)
    if r.status_code == 200 and not r.json().get("needs_mapping"):
        assert r.json()["plan"]["route"] == "magnetic_only"


def test_mag_only_igrf_junk_rows_no_crash():
    r = _enrich(_client(), files={"magnetic_file": ("junk.csv", _mag_csv_with_junk(), "text/csv")})
    _assert_clean_or_clear(r)


# ══════════════════════════════════════════════════════════════════════════════
# JOINT (grav + mag co-localizados)
# ══════════════════════════════════════════════════════════════════════════════
def test_joint_clean_is_200_joint_route():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _grav_csv(), "text/csv"),
            "magnetic_file": ("mag.csv", _mag_csv(), "text/csv"),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_magnetic_joint"


def test_joint_weird_magnetic_header_with_magnetic_column_map():
    # El 2.º archivo (magnético) lleva encabezado raro → magnetic_column_map_json.
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _grav_csv(), "text/csv"),
            "magnetic_file": ("weird.csv", _mag_csv(header=_WEIRD_MAG_HEADER), "text/csv"),
        },
        data={"magnetic_column_map_json": json.dumps(_WEIRD_MAG_MAP)},
    )
    _assert_clean_or_clear(r)
    if r.status_code == 200:
        assert r.json()["plan"]["route"] == "gravity_magnetic_joint"


def test_joint_magnetic_bom_tolerated():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _grav_csv(), "text/csv"),
            "magnetic_file": ("magbom.csv", "﻿" + _mag_csv(), "text/csv"),
        },
    )
    _assert_clean_or_clear(r)


def test_joint_magnetic_igrf_junk_rows_no_crash():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _grav_csv(), "text/csv"),
            "magnetic_file": ("junk.csv", _mag_csv_with_junk(), "text/csv"),
        },
    )
    _assert_clean_or_clear(r)


def test_joint_non_colocated_magnetic_is_clear_422_not_crash():
    # Magnético en otra ubicación → no co-localiza con la gravimetría: error CLARO.
    far = _mag_csv().replace("-69.3", "-50.1").replace("-27.1", "-10.1")
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _grav_csv(), "text/csv"),
            "magnetic_file": ("far.csv", far, "text/csv"),
        },
    )
    _assert_clean_or_clear(r)
    if r.status_code == 422:
        det = r.json()["detail"]
        # detail puede ser dict estructurado o str; ambos son «claros».
        assert det, r.text
