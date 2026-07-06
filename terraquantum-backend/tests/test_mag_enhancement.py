"""F2B — Suite de realce magnético: validación contra referencias INDEPENDIENTES.

Oráculos:
  - Dipolo puntual TMI de FORMA CERRADA implementado AQUÍ (μ0/4π·[3(m̂·r̂)r̂−m̂]/r³,
    proyectado en f̂) — independiente del motor y de la suite.
  - Armónicos exactos: 1VD de cos(kx) es k·cos(kx); THD máx = k·A (±2%).
  - Propiedades físicas: RTP centra el pico sobre la fuente y correlaciona
    >0.97 con el campo calculado EN el polo; |AS| pica sobre el epicentro;
    TILT acotado [−π/2, π/2] con signo correcto sobre/fuera de la fuente.
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mag_enhancement_service import (  # noqa: E402
    MagEnhancementError,
    analytic_signal,
    correct_diurnal,
    first_vertical_derivative,
    reduce_to_pole,
    run_mag_enhancement,
    tilt_derivative,
    total_horizontal_derivative,
)


# ── Oráculo: dipolo TMI de forma cerrada (independiente) ─────────────────────
def _unit(inc_deg, dec_deg):
    """(E, N, ABAJO): D desde el norte hacia el este; I>0 apunta hacia abajo."""
    inc, dec = np.radians(inc_deg), np.radians(dec_deg)
    return np.array([
        np.cos(inc) * np.sin(dec), np.cos(inc) * np.cos(dec), np.sin(inc),
    ])


def _dipole_tmi_grid(n, d_m, depth_m, inc_deg, dec_deg, moment=1e6):
    """TMI (nT arbitrarios) de un dipolo bajo el centro de la grilla."""
    u = _unit(inc_deg, dec_deg)         # magnetización ∥ campo (sin remanencia)
    xi = (np.arange(n) - n / 2) * d_m
    XX, YY = np.meshgrid(xi, xi)
    rx, ry, rz = XX, YY, -depth_m * np.ones_like(XX)   # fuente→obs (z abajo)
    r = np.sqrt(rx * rx + ry * ry + rz * rz)
    mdotr = (u[0] * rx + u[1] * ry + u[2] * rz) / r    # m̂·r̂
    # B = C·[3(m̂·r̂)r̂ − m̂]/r³, componente a componente con r̂ = (rx,ry,rz)/r.
    bx = moment * (3.0 * mdotr * rx / r - u[0]) / r ** 3
    by = moment * (3.0 * mdotr * ry / r - u[1]) / r ** 3
    bz = moment * (3.0 * mdotr * rz / r - u[2]) / r ** 3
    return u[0] * bx + u[1] * by + u[2] * bz


N, D = 96, 25.0
DEPTH = 150.0


# ── 1. RTP contra el campo calculado EN el polo ──────────────────────────────
def test_rtp_matches_pole_computed_field():
    tmi_inclined = _dipole_tmi_grid(N, D, DEPTH, inc_deg=-55.0, dec_deg=10.0)
    tmi_pole = _dipole_tmi_grid(N, D, DEPTH, inc_deg=90.0, dec_deg=0.0)
    rtp, warns = reduce_to_pole(tmi_inclined, D, D, inc_deg=-55.0, dec_deg=10.0)
    assert warns == []
    core = slice(N // 4, 3 * N // 4)
    a, b = rtp[core, core].ravel(), tmi_pole[core, core].ravel()
    corr = float(np.corrcoef(a, b)[0, 1])
    assert corr > 0.97, corr
    # El pico del RTP cae sobre la fuente (centro) a ≤2 celdas.
    iy, ix = np.unravel_index(np.argmax(rtp), rtp.shape)
    assert abs(iy - N // 2) <= 2 and abs(ix - N // 2) <= 2, (iy, ix)


def test_rtp_low_latitude_warns_and_offers_tilt():
    tmi = _dipole_tmi_grid(N, D, DEPTH, inc_deg=5.0, dec_deg=0.0)
    _, warns = reduce_to_pole(tmi, D, D, inc_deg=5.0, dec_deg=0.0)
    assert any("inestable" in w and "TILT" in w for w in warns)


# ── 2. Derivadas contra armónicos exactos ────────────────────────────────────
def test_vd1_harmonic_exact():
    n, d = 128, 50.0
    k = 2.0 * np.pi / 1600.0
    grid = np.cos(k * (np.arange(n) * d))[None, :].repeat(n, axis=0)
    vd = first_vertical_derivative(grid, d, d)
    core = vd[n // 4:3 * n // 4, n // 4:3 * n // 4]
    amp = float(np.sqrt(2.0) * core.std())
    assert abs(amp - k) / k < 0.02, (amp, k)


def test_thd_harmonic_exact():
    n, d = 128, 50.0
    k = 2.0 * np.pi / 1600.0
    grid = np.cos(k * (np.arange(n) * d))[None, :].repeat(n, axis=0)
    thd = total_horizontal_derivative(grid, d, d)
    core = thd[n // 4:3 * n // 4, n // 4:3 * n // 4]
    assert abs(float(core.max()) - k) / k < 0.03


def test_tilt_bounded_and_signed():
    tmi_pole = _dipole_tmi_grid(N, D, DEPTH, 90.0, 0.0)
    tilt = tilt_derivative(tmi_pole, D, D)
    assert float(np.abs(tilt).max()) <= np.pi / 2 + 1e-9
    assert tilt[N // 2, N // 2] > 0.5          # sobre la fuente: positivo
    assert tilt[N // 2, 5] < 0.0               # lejos: negativo


def test_analytic_signal_peaks_over_source():
    tmi_pole = _dipole_tmi_grid(N, D, DEPTH, 90.0, 0.0)
    asig = analytic_signal(tmi_pole, D, D)
    assert np.all(asig >= 0)
    iy, ix = np.unravel_index(np.argmax(asig), asig.shape)
    assert abs(iy - N // 2) <= 2 and abs(ix - N // 2) <= 2


def test_analytic_signal_peak_robust_to_inclination():
    """La virtud del |AS|: el pico queda cerca del epicentro AUN inclinado."""
    tmi = _dipole_tmi_grid(N, D, DEPTH, inc_deg=-55.0, dec_deg=10.0)
    asig = analytic_signal(tmi, D, D)
    iy, ix = np.unravel_index(np.argmax(asig), asig.shape)
    assert np.hypot(iy - N // 2, ix - N // 2) <= 3, (iy, ix)


# ── 3. Corrección diurna ─────────────────────────────────────────────────────
def test_diurnal_removes_known_variation():
    t0 = datetime(2016, 7, 1, 8, 0)
    base_times = [t0 + timedelta(minutes=10 * i) for i in range(60)]
    var = lambda t: 30.0 * np.sin((t - t0).total_seconds() / 3600.0)  # noqa: E731
    base_nt = np.array([23500.0 + var(t) for t in base_times])
    survey_times = [t0 + timedelta(minutes=7 + 23 * i) for i in range(20)]
    tmi_true = 100.0 * np.ones(20)
    survey_nt = tmi_true + np.array([var(t) for t in survey_times])
    corrected, meta = correct_diurnal(survey_times, survey_nt, base_times, base_nt)
    # corrected = survey − (base(t) − ref) = tmi_true + (ref − 23500).
    ref = meta["base_reference_nt"]
    np.testing.assert_allclose(corrected, tmi_true + (ref - 23500.0), atol=0.5)
    assert meta["n_base_readings"] == 60


def test_diurnal_guardrails():
    t0 = datetime(2016, 7, 1, 8, 0)
    with pytest.raises(MagEnhancementError, match="≥2 lecturas"):
        correct_diurnal([t0], np.array([1.0]), [t0], np.array([23500.0]))
    # Fuera de ventana → warning, no crash.
    base_times = [t0, t0 + timedelta(hours=1)]
    corrected, meta = correct_diurnal(
        [t0 + timedelta(hours=5)], np.array([10.0]),
        base_times, np.array([23500.0, 23510.0]),
    )
    assert any("fuera de la ventana" in w for w in meta["warnings"])


# ── 4. Suite integrada sobre estaciones dispersas ────────────────────────────
def test_run_suite_all_products_on_scattered_stations():
    rng = np.random.RandomState(11)
    n_st = 500
    x = rng.uniform(-1100, 1100, n_st)
    y = rng.uniform(-1100, 1100, n_st)
    u = _unit(-55.0, 10.0)
    rx, ry, rz = x, y, -DEPTH * np.ones_like(x)
    r = np.sqrt(rx * rx + ry * ry + rz * rz)
    mdotr = (u[0] * rx + u[1] * ry + u[2] * rz) / r
    bx = 1e6 * (3.0 * mdotr * rx / r - u[0]) / r ** 3
    by = 1e6 * (3.0 * mdotr * ry / r - u[1]) / r ** 3
    bz = 1e6 * (3.0 * mdotr * rz / r - u[2]) / r ** 3
    tmi = u[0] * bx + u[1] * by + u[2] * bz

    res = run_mag_enhancement(
        x, y, tmi,
        products=["rtp", "vd1", "thd", "tilt", "analytic_signal", "upward_continuation"],
        inc_deg=-55.0, dec_deg=10.0, uc_height_m=300.0,
    )
    assert set(res.products.keys()) == {
        "rtp", "vd1", "thd", "tilt", "analytic_signal", "upward_continuation",
    }
    ny, nx = res.grid.values.shape
    for name, g in res.products.items():
        assert g.shape == (ny, nx), name
        assert np.all(np.isfinite(g)), name
    # La continuación atenúa: menos energía que la TMI original.
    assert res.products["upward_continuation"].std() < res.grid.values.std()


def test_run_suite_unknown_product_clear_error():
    with pytest.raises(MagEnhancementError, match="desconocido"):
        run_mag_enhancement(
            np.arange(20.0), np.arange(20.0) % 5, np.ones(20), products=["fft_magic"],
        )


# ── 5. Endpoint HTTP ─────────────────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _http_stations(n_side=14):
    rng = np.random.RandomState(5)
    g = np.linspace(-800, 800, n_side)
    XX, YY = np.meshgrid(g, g)
    x, y = XX.ravel(), YY.ravel()
    u = _unit(-55.0, 10.0)
    rx, ry, rz = x, y, -DEPTH * np.ones_like(x)
    r = np.sqrt(rx * rx + ry * ry + rz * rz)
    mdotr = (u[0] * rx + u[1] * ry + u[2] * rz) / r
    tmi = (u[0] * 1e6 * (3 * mdotr * rx / r - u[0]) / r ** 3
           + u[1] * 1e6 * (3 * mdotr * ry / r - u[1]) / r ** 3
           + u[2] * 1e6 * (3 * mdotr * rz / r - u[2]) / r ** 3)
    tmi = tmi + rng.normal(0, 0.01, tmi.shape)
    return [
        {"station_id": f"M{i}", "x_m": float(x[i]), "y_m": float(y[i]),
         "magnetic_nt": float(tmi[i])}
        for i in range(len(x))
    ]


def test_endpoint_json_products_and_meta():
    r = _client().post("/v2/mag-enhance", json={
        "stations": _http_stations(),
        "products": ["tilt", "analytic_signal", "upward_continuation"],
        "inclination_deg": -55.0, "declination_deg": 10.0, "uc_height_m": 300.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["products"].keys()) == {"tilt", "analytic_signal", "upward_continuation"}
    assert body["grid_meta"]["nx"] >= 16
    assert len(body["observed_tmi"]) == body["grid_meta"]["ny"]


def test_endpoint_csv_export():
    r = _client().post("/v2/mag-enhance", json={
        "stations": _http_stations(),
        "products": ["tilt"], "output_format": "csv", "csv_product": "tilt",
        "inclination_deg": -55.0,
    })
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[1] == "x_m,y_m,value"


def test_endpoint_missing_tmi_column_422():
    r = _client().post("/v2/mag-enhance", json={
        "stations": [{"station_id": "a", "x_m": 0.0, "y_m": 0.0}] * 9,
        "products": ["tilt"],
    })
    assert r.status_code == 422
    assert "magnetic_nt" in r.json()["detail"]
