"""
TAREA C — Mapeo de columnas del 2.º archivo (magnético) en /enrich-package.

El endpoint aceptaba gravity_file + magnetic_file pero un único column_map_json que
solo aplica al gravity_file. Un magnetic_file con encabezados no estándar caía SOLO
en auto-detección y fallaba. Ahora hay un Form param paralelo magnetic_column_map_json
que se pasa al import del magnético (data_kind="magnetic").

Cubre:
  • encabezados raros + magnetic_column_map_json correcto → magnético ingerido (joint).
  • MISMO archivo raro SIN el map → comportamiento histórico (auto-detección falla → 422).
  • magnético estándar SIN el map → flujo histórico intacto (joint), el nuevo param no rompe.
  • magnetic_column_map_json inválido → 422 con mensaje claro.

enrich-package NO invierte (importa+enriquece+empaqueta) → tests rápidos.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


_N = 4


def _coords():
    for i in range(_N):
        for j in range(_N):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0 + j * 2.0
            yield i, j, lat, lon, elev


def _grav_csv():
    lines = ["lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    for i, j, lat, lon, elev in _coords():
        val = 5.0 + 0.5 * ((i * _N + j) % 5)
        lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{val:.2f},mGal,bouguer_anomaly")
    return "\n".join(lines) + "\n"


def _mag_standard_csv():
    lines = ["lat,lon,elev_m,tmi_nt"]
    for i, j, lat, lon, elev in _coords():
        tmi = 51000.0 + 20.0 * ((i * _N + j) % 5)
        lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{tmi:.2f}")
    return "\n".join(lines) + "\n"


def _mag_weird_csv():
    """Mismas coordenadas que el estándar pero con encabezados que NINGÚN alias
    reconoce (aa=lon, bb=lat, cc=TMI). Sin un column_map la auto-detección falla."""
    lines = ["node,aa,bb,cc"]
    for i, j, lat, lon, elev in _coords():
        tmi = 51000.0 + 20.0 * ((i * _N + j) % 5)
        lines.append(f"N{i}{j},{lon:.4f},{lat:.4f},{tmi:.2f}")
    return "\n".join(lines) + "\n"


_GRAV = _grav_csv()
_MAG_STD = _mag_standard_csv()
_MAG_WEIRD = _mag_weird_csv()
# Mapeo del magnético raro: aa→x(lon), bb→y(lat), cc→TMI, coords latlon (para que
# alinee con la gravimetría latlon tras la transformación a metros locales).
_MAG_MAP = {"x": "aa", "y": "bb", "magnetic_value": "cc", "coordinate_system": "latlon"}


def _enrich(client, files, data=None):
    return client.post(
        "/v2/gravity-import/enrich-package", files=files, data=data or {},
    )


def test_weird_magnetic_headers_with_map_ingested_joint():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG_WEIRD, "text/csv"),
        },
        data={"magnetic_column_map_json": json.dumps(_MAG_MAP)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_magnetic_joint"


def test_weird_magnetic_headers_without_map_fails_historic():
    # Mismo archivo raro SIN el map: la auto-detección no resuelve columnas →
    # el import magnético falla con error claro (comportamiento histórico).
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG_WEIRD, "text/csv"),
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "MAGNETIC_CSV_IMPORT_FAILED"


def test_standard_magnetic_without_map_unchanged():
    # Guardrail: magnético con encabezados estándar y SIN el nuevo param → joint
    # como siempre (el nuevo magnetic_column_map_json no altera el flujo histórico).
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG_STD, "text/csv"),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_magnetic_joint"


def test_invalid_magnetic_column_map_json_422():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG_STD, "text/csv"),
        },
        data={"magnetic_column_map_json": "{not valid json"},
    )
    assert r.status_code == 422, r.text
    assert "magnetic_column_map_json inválido" in str(r.json()["detail"])


def test_non_dict_magnetic_column_map_json_422():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG_STD, "text/csv"),
        },
        data={"magnetic_column_map_json": json.dumps(["aa", "bb"])},
    )
    assert r.status_code == 422, r.text
    assert "objeto" in str(r.json()["detail"])
