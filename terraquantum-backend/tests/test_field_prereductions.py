"""F2B — Encadenado de pre-reducciones de campo en POST /gravity-corrections/apply.

Verdad sintética E2E: se genera un survey CRUDO = señal limpia + marea
Longman REAL (mismo modelo, evaluada en los tiempos del survey) + deriva
lineal conocida. Con apply_tide+apply_drift el endpoint debe devolver la
misma anomalía que el survey limpio equivalente (<0.001 mGal).

Guardarraíles: marea/deriva sobre dato ya reducido = 422; sin columna de
tiempo = 422 accionable; deriva sin base_station_id = 422 que PREGUNTA con
la candidata detectada.
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.earth_tide_service import solve_longman_tide  # noqa: E402

T0 = datetime(2012, 3, 1, 8, 0, 0)
LAT0, LON0, ELEV0 = -36.06, -70.50, 2200.0
DRIFT_MGAL_H = 0.04
G_ABS = 978000.0


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _raw_survey(n=10, with_tide=True, with_drift=True):
    """BASE al inicio/medio/fin + n estaciones; devuelve (stations, g_clean)."""
    stations, g_clean = [], []
    rng = np.random.RandomState(7)
    plan = ["BASE"] + [f"S{i}" for i in range(1, n // 2 + 1)] + ["BASE"] \
        + [f"S{i}" for i in range(n // 2 + 1, n + 1)] + ["BASE"]
    for k, sid in enumerate(plan):
        t = T0 + timedelta(minutes=40 * k)
        lat = LAT0 + 0.001 * k
        lon = LON0 - 0.001 * k
        elev = ELEV0 + 5.0 * k
        g_true = G_ABS + (0.0 if sid == "BASE" else float(rng.uniform(-15, 15)))
        reading = g_true
        if with_tide:
            reading += solve_longman_tide(lat, lon, elev, t)[2]
        if with_drift:
            reading += DRIFT_MGAL_H * (40.0 * k / 60.0)
        stations.append({
            "station_id": sid, "lat_deg": lat, "lon_deg": lon, "elev_m": elev,
            "g_obs_mgal": reading, "time_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
        })
        g_clean.append(g_true)
    return stations, np.array(g_clean)


def _apply(client, stations, **params):
    body = {
        "stations": stations,
        "params": {
            "apply_lat_correction": True, "apply_fac": True,
            "apply_bouguer": True, "apply_terrain": False, **params,
        },
        "gravity_type_in": "g_raw",
    }
    return client.post("/gravity-corrections/apply", json=body)


def test_tide_and_drift_recover_clean_anomaly():
    """Crudo con marea REAL + deriva 0.04 mGal/h → misma anomalía que el
    survey limpio (diferencia < 0.001 mGal por estación)."""
    client = _client()
    dirty, _ = _raw_survey(with_tide=True, with_drift=True)
    clean, _ = _raw_survey(with_tide=False, with_drift=False)

    r_dirty = _apply(
        client, dirty,
        apply_tide=True, apply_drift=True,
        drift_method="linear", base_station_id="BASE",
    )
    assert r_dirty.status_code == 200, r_dirty.text
    r_clean = _apply(client, clean)
    assert r_clean.status_code == 200, r_clean.text

    ba_dirty = np.array([s["g_bouguer_mgal"] for s in r_dirty.json()["corrected"]])
    ba_clean = np.array([s["g_bouguer_mgal"] for s in r_clean.json()["corrected"]])
    np.testing.assert_allclose(ba_dirty, ba_clean, atol=1e-3)

    rep = r_dirty.json()["report"]
    assert rep["corrections_applied"][:2] == [
        "earth_tide_longman1959", "instrument_drift_linear",
    ]
    assert abs(rep["drift_rate_mgal_per_day"] - DRIFT_MGAL_H * 24) < 0.01
    assert rep["drift_n_base"] == 3
    assert rep["tide_min_mgal"] is not None
    # g_obs por estación = lectura ORIGINAL (no la pre-reducida).
    assert r_dirty.json()["corrected"][0]["g_obs_mgal"] == dirty[0]["g_obs_mgal"]


def test_tide_on_reduced_data_is_422():
    client = _client()
    stations, _ = _raw_survey(with_tide=False, with_drift=False)
    body = {
        "stations": stations,
        "params": {"apply_tide": True},
        "gravity_type_in": "bouguer_anomaly",
    }
    r = client.post("/gravity-corrections/apply", json=body)
    assert r.status_code == 422
    assert "g_raw" in r.json()["detail"]


def test_missing_time_column_is_actionable_422():
    client = _client()
    stations, _ = _raw_survey(with_tide=True, with_drift=False)
    for s in stations:
        del s["time_utc"]
    r = _apply(client, stations, apply_tide=True)
    assert r.status_code == 422
    assert "columna de tiempo" in r.json()["detail"]


def test_drift_without_base_asks_with_candidate():
    """Sin base_station_id → 422 que PREGUNTA e incluye la candidata 'BASE'."""
    client = _client()
    stations, _ = _raw_survey(with_tide=False, with_drift=True)
    r = _apply(client, stations, apply_drift=True)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "base_station_id" in detail and "BASE" in detail
    assert "3 ocupaciones" in detail


def test_wrong_base_id_clear_error():
    client = _client()
    stations, _ = _raw_survey(with_tide=False, with_drift=True)
    r = _apply(client, stations, apply_drift=True, base_station_id="NO_EXISTE")
    assert r.status_code == 422
    assert "no aparece" in r.json()["detail"]
