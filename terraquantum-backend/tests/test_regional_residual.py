"""F2B — Regional-residual + utilitario de grilla FFT.

Oráculo ANALÍTICO de la continuación ascendente: para un armónico puro
cos(k·x), la teoría de potencial da EXACTAMENTE exp(−|k|·h) de atenuación —
cualquier error de convención FFT (2π, ejes, padding) rompe ese test.

Separación con verdad sintética: regional polinomial conocido + anomalía
local compacta → el polinomio recupera el regional y el residual conserva la
anomalía; con continuación, la fuente ancha-profunda va al regional y la
angosta-somera queda en el residual.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.potential_field_grid_service import (  # noqa: E402
    grid_scattered,
    sample_grid,
    upward_continue_grid,
)
from services.regional_residual_service import (  # noqa: E402
    MEASURED_WARNING,
    separate_regional_residual,
)


def _stations_grid(n_side=24, span=4000.0, seed=3):
    rng = np.random.RandomState(seed)
    g = np.linspace(0, span, n_side)
    XX, YY = np.meshgrid(g, g)
    x = (XX + rng.uniform(-40, 40, XX.shape)).ravel()
    y = (YY + rng.uniform(-40, 40, YY.shape)).ravel()
    return x, y


# ── 1. Utilitario de grilla ──────────────────────────────────────────────────
def test_upward_continuation_analytic_harmonic():
    """cos(kx·x) continuado a h → amplitud × exp(−kx·h) EXACTA (±2%)."""
    n, d = 128, 50.0
    wavelength = 1600.0
    k = 2.0 * np.pi / wavelength
    xi = np.arange(n) * d
    grid = np.cos(k * xi)[None, :].repeat(n, axis=0)
    for h in (200.0, 500.0):
        cont = upward_continue_grid(grid, d, d, h)
        # Amplitud medida en la franja central (lejos de bordes del padding).
        core = cont[n // 4:3 * n // 4, n // 4:3 * n // 4]
        amp = float(np.sqrt(2.0) * core.std())
        expected = float(np.exp(-k * h))
        assert abs(amp - expected) / expected < 0.02, (h, amp, expected)


def test_upward_continuation_zero_height_identity_and_negative_rejected():
    grid = np.random.RandomState(0).randn(32, 32)
    np.testing.assert_allclose(upward_continue_grid(grid, 10, 10, 0.0), grid)
    with pytest.raises(ValueError, match="DESCENDENTE"):
        upward_continue_grid(grid, 10, 10, -100.0)


def test_grid_roundtrip_smooth_function():
    x, y = _stations_grid()
    v = 2.0 + 0.001 * x - 0.0005 * y
    sg = grid_scattered(x, y, v)
    back = sample_grid(sg, x, y)
    assert float(np.abs(back - v).max()) < 0.05


def test_grid_guardrails():
    with pytest.raises(ValueError, match="≥8"):
        grid_scattered([0, 1], [0, 1], [1.0, 2.0])
    with pytest.raises(ValueError, match="línea"):
        grid_scattered(np.arange(10.0), np.zeros(10), np.arange(10.0))


# ── 2. Separación polinomial ─────────────────────────────────────────────────
def test_polynomial_recovers_known_regional():
    x, y = _stations_grid()
    regional_true = 5.0 + 0.002 * x - 0.001 * y   # plano (orden 1)
    anomaly = 8.0 * np.exp(-(((x - 2000) ** 2 + (y - 2000) ** 2) / (2 * 300.0 ** 2)))
    v = regional_true + anomaly
    res = separate_regional_residual(x, y, v, method="polynomial", order=1)
    # Lejos de la anomalía el residual ~0; en el centro conserva la amplitud.
    far = (np.hypot(x - 2000, y - 2000) > 1500)
    assert float(np.abs(res.residual[far]).mean()) < 0.35
    near = np.hypot(x - 2000, y - 2000) < 150
    assert float(res.residual[near].mean()) > 6.0
    assert res.report["r2"] > 0.4
    assert MEASURED_WARNING in res.report["warnings"]


def test_polynomial_order_out_of_range():
    x, y = _stations_grid()
    with pytest.raises(ValueError, match="fuera de rango"):
        separate_regional_residual(x, y, np.ones_like(x), order=5)


# ── 3. Separación por continuación: ancha-profunda vs angosta-somera ────────
def test_upward_continuation_keeps_broad_kills_narrow():
    x, y = _stations_grid(n_side=28, span=6000.0)
    broad = 10.0 * np.exp(-(((x - 3000) ** 2 + (y - 3000) ** 2) / (2 * 2500.0 ** 2)))
    narrow = 6.0 * np.exp(-(((x - 1500) ** 2 + (y - 4200) ** 2) / (2 * 250.0 ** 2)))
    v = broad + narrow
    res = separate_regional_residual(
        x, y, v, method="upward_continuation", height_m=1500.0,
    )
    near_narrow = np.hypot(x - 1500, y - 4200) < 150
    # El residual conserva la mayor parte de la fuente angosta...
    assert float(res.residual[near_narrow].mean()) > 0.6 * 6.0
    # ...y el regional en ese punto es esencialmente la fuente ancha (±25%).
    reg_near = float(res.regional[near_narrow].mean())
    broad_near = float(broad[near_narrow].mean())
    assert abs(reg_near - broad_near) < 0.25 * 10.0


# ── 4. Endpoint HTTP (JSON + CSV + advertencia medida) ───────────────────────
def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _payload_stations():
    x, y = _stations_grid(n_side=12, span=2000.0)
    v = 1.0 + 0.001 * x + 3.0 * np.exp(-(((x - 900) ** 2 + (y - 900) ** 2) / (2 * 150.0 ** 2)))
    return [
        {"station_id": f"S{i}", "x_m": float(x[i]), "y_m": float(y[i]),
         "g_bouguer_mgal": float(v[i])}
        for i in range(len(v))
    ]


def test_endpoint_json_with_grids_and_warning():
    r = _client().post("/gravity-corrections/regional-residual", json={
        "stations": _payload_stations(), "method": "polynomial", "order": 1,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["stations"]) == len(_payload_stations())
    assert "regional" in body["stations"][0] and "residual" in body["stations"][0]
    assert any("NO se aplica automática" in w for w in body["report"]["warnings"])
    assert body["grids"]["nx"] >= 16 and len(body["grids"]["residual"]) == body["grids"]["ny"]


def test_endpoint_csv_download():
    r = _client().post("/gravity-corrections/regional-residual", json={
        "stations": _payload_stations(), "method": "polynomial", "order": 1,
        "output_format": "csv",
    })
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[2].startswith("station_id,x_m,y_m,")
    assert len(lines) == 3 + len(_payload_stations())


def test_endpoint_missing_coords_422():
    r = _client().post("/gravity-corrections/regional-residual", json={
        "stations": [{"station_id": "a", "g_bouguer_mgal": 1.0}] * 9,
    })
    assert r.status_code == 422
    assert "x_m/y_m" in r.json()["detail"]
