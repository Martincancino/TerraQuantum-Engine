"""PILAR 2 — Contrato HONESTO por ROL del enriquecimiento (/enrich-package).

Verifica cada combinación de datos termina en una salida válida O un error claro,
sin exigir gravimetría y sin crash silencioso:
  • grav-sola / mag-sola / grav+mag (joint) / +sondajes → 200 con el route correcto.
  • sondajes-solo / vacío → 422 INSUFFICIENT_DATA (los sondajes no definen inversión).
  • roles explícitos (gravity_file/magnetic_file) Y legacy (file+data_type) funcionan.

enrich-package NO invierte (solo importa+enriquece+empaqueta) → tests rápidos.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
_BHS = [{"x_m": 150.0, "z_m": 150.0, "y_from_m": 20.0, "y_to_m": 120.0, "density_t_m3": 2.8}]


def _enrich(client, files, params=None, data=None):
    return client.post(
        "/v2/gravity-import/enrich-package",
        files=files, params=params or {}, data=data or {},
    )


# ── Combos válidos (por ROL) ──────────────────────────────────────────────────
def test_gravity_only_role_based():
    r = _enrich(_client(), files={"gravity_file": ("grav.csv", _GRAV, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_only"


def test_magnetic_only_role_based_no_data_type():
    # Sólo magnetic_file, SIN data_type ni file → el backend deriva magnético.
    r = _enrich(_client(), files={"magnetic_file": ("mag.csv", _MAG, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "magnetic_only"


def test_joint_role_based():
    r = _enrich(
        _client(),
        files={
            "gravity_file": ("grav.csv", _GRAV, "text/csv"),
            "magnetic_file": ("mag.csv", _MAG, "text/csv"),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_magnetic_joint"


def test_gravity_with_boreholes():
    r = _enrich(
        _client(),
        files={"gravity_file": ("grav.csv", _GRAV, "text/csv")},
        data={"boreholes_json": json.dumps(_BHS)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_with_constraints"


# ── Rechazos claros (PILAR 6) ─────────────────────────────────────────────────
def test_boreholes_only_rejected():
    r = _enrich(_client(), files={}, data={"boreholes_json": json.dumps(_BHS)})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "INSUFFICIENT_DATA"


def test_empty_rejected():
    r = _enrich(_client(), files={})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "INSUFFICIENT_DATA"


# ── Back-compat legacy (file + data_type) ─────────────────────────────────────
def test_legacy_gravity_file_param():
    r = _enrich(_client(), files={"file": ("grav.csv", _GRAV, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "gravity_only"


def test_legacy_magnetic_file_param():
    r = _enrich(
        _client(),
        files={"file": ("mag.csv", _MAG, "text/csv")},
        params={"data_type": "magnetic", "strict": "false"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["route"] == "magnetic_only"
