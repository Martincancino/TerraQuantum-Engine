"""F2B — Euler + espectro radial: los DOS casos con verdad conocida del gate.

  1. Dipolo magnético (forma cerrada, SI=3) a 150 m → mediana de la nube
     dentro de ±20% y epicentro a ≤2 celdas (tolerancia DOCUMENTADA del método).
  2. Esfera gravimétrica (masa puntual, forma cerrada, SI=2) a 200 m → ídem.
  + DO-27 real (corpus): smoke honesto — nube coherente sobre el cuerpo con
    profundidades en banda plausible (la verdad publicada es cualitativa).
  + Espectro radial: el ensamble profundo de un dipolo a 300 m cae en banda
    generosa (los métodos espectrales son de ensamble: ±40% documentado).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.euler_spectral_service import (  # noqa: E402
    euler_deconvolution,
    radial_power_spectrum,
)
from services.potential_field_grid_service import ScatteredGrid  # noqa: E402

CORPUS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "csv_reales"
)


def _unit(inc_deg, dec_deg):
    inc, dec = np.radians(inc_deg), np.radians(dec_deg)
    return np.array([
        np.cos(inc) * np.sin(dec), np.cos(inc) * np.cos(dec), np.sin(inc),
    ])


def _dipole_grid(n, d, depth, inc_deg=90.0, dec_deg=0.0, moment=1e6):
    u = _unit(inc_deg, dec_deg)
    xi = (np.arange(n) - n / 2) * d
    XX, YY = np.meshgrid(xi, xi)
    rx, ry, rz = XX, YY, -depth * np.ones_like(XX)
    r = np.sqrt(rx * rx + ry * ry + rz * rz)
    mdotr = (u[0] * rx + u[1] * ry + u[2] * rz) / r
    bx = moment * (3.0 * mdotr * rx / r - u[0]) / r ** 3
    by = moment * (3.0 * mdotr * ry / r - u[1]) / r ** 3
    bz = moment * (3.0 * mdotr * rz / r - u[2]) / r ** 3
    tmi = u[0] * bx + u[1] * by + u[2] * bz
    return _to_sg(tmi, d, x0=float(xi[0]), y0=float(xi[0]))


def _sphere_gravity_grid(n, d, depth, mass_c=1e7):
    """gz de masa puntual (esfera): C·z0/(x²+y²+z0²)^{3/2} — forma cerrada."""
    xi = (np.arange(n) - n / 2) * d
    XX, YY = np.meshgrid(xi, xi)
    gz = mass_c * depth / (XX ** 2 + YY ** 2 + depth ** 2) ** 1.5
    return _to_sg(gz, d, x0=float(xi[0]), y0=float(xi[0]))


def _to_sg(grid, d, x0, y0):
    ny, nx = grid.shape
    return ScatteredGrid(
        values=grid, x0=x0, y0=y0, dx=d, dy=d, nx=nx, ny=ny,
        inside_hull=np.ones_like(grid, dtype=bool),
    )


# ── 1. Verdad conocida: dipolo magnético SI=3 a 150 m ────────────────────────
def test_euler_magnetic_dipole_si3_depth_within_20pct():
    depth = 150.0
    sg = _dipole_grid(96, 25.0, depth, inc_deg=90.0)
    res = euler_deconvolution(sg, structural_index=3.0, window_cells=10)
    assert res.n_accepted >= 10, res.report
    med = res.report["depth_median_m"]
    assert abs(med - depth) / depth < 0.20, med
    xs = np.array([s.x_m for s in res.solutions])
    ys = np.array([s.y_m for s in res.solutions])
    assert abs(float(np.median(xs))) < 2 * 25.0
    assert abs(float(np.median(ys))) < 2 * 25.0


def test_euler_dipole_inclined_field_still_recovers():
    """Con campo inclinado (I=-55) Euler sigue centrando profundidad (±25%)."""
    depth = 150.0
    sg = _dipole_grid(96, 25.0, depth, inc_deg=-55.0, dec_deg=10.0)
    res = euler_deconvolution(sg, structural_index=3.0, window_cells=10)
    assert res.n_accepted >= 10
    assert abs(res.report["depth_median_m"] - depth) / depth < 0.25


# ── 2. Verdad conocida: esfera gravimétrica SI=2 a 200 m ─────────────────────
def test_euler_gravity_sphere_si2_depth_within_20pct():
    depth = 200.0
    sg = _sphere_gravity_grid(96, 25.0, depth)
    res = euler_deconvolution(sg, structural_index=2.0, window_cells=10)
    assert res.n_accepted >= 10, res.report
    med = res.report["depth_median_m"]
    assert abs(med - depth) / depth < 0.20, med
    xs = np.array([s.x_m for s in res.solutions])
    ys = np.array([s.y_m for s in res.solutions])
    assert abs(float(np.median(xs))) < 2 * 25.0
    assert abs(float(np.median(ys))) < 2 * 25.0


def test_euler_wrong_si_biases_depth():
    """Con el SI equivocado la profundidad se corre — por eso el SI lo elige
    el usuario y se documenta (no hay SI 'automático' honesto)."""
    depth = 200.0
    sg = _sphere_gravity_grid(96, 25.0, depth)
    res_si1 = euler_deconvolution(sg, structural_index=1.0, window_cells=10)
    if res_si1.n_accepted >= 5:
        assert res_si1.report["depth_median_m"] < depth * 0.9


# ── 3. Espectro radial ───────────────────────────────────────────────────────
def test_spectrum_single_source_depth_band():
    depth = 300.0
    sg = _dipole_grid(128, 25.0, depth, inc_deg=90.0)
    spec = radial_power_spectrum(sg)
    deep = spec["ensemble_depth_deep_m"]
    assert deep >= spec["ensemble_depth_shallow_m"] - 1e-9
    # Método de ensamble: banda generosa ±40% documentada.
    assert 0.6 * depth < deep < 1.4 * depth, deep
    assert "honesty_note" in spec


# ── 4. Guardarraíles ─────────────────────────────────────────────────────────
def test_euler_guardrails():
    sg = _dipole_grid(48, 25.0, 150.0)
    with pytest.raises(ValueError, match="Índice estructural"):
        euler_deconvolution(sg, structural_index=5.0)
    with pytest.raises(ValueError, match="window_cells"):
        euler_deconvolution(sg, window_cells=2)


# ── 5. DO-27 real (corpus): smoke honesto ────────────────────────────────────
def test_euler_do27_real_gravity_coherent_cluster():
    """Datos reales del corpus: nube coherente con profundidades plausibles
    (20-600 m; la kimberlita DO-27 es somera bajo overburden) y centro de la
    nube cerca del máximo gravimétrico (targeting validado del proyecto)."""
    import pandas as pd

    from services.potential_field_grid_service import grid_scattered

    path = os.path.join(CORPUS, "do27_gravity_LISTO.csv")
    df = pd.read_csv(path)
    sg = grid_scattered(
        df["easting"].to_numpy(float),
        df["northing"].to_numpy(float),
        df["bouguer_anomaly"].to_numpy(float),
    )
    res = euler_deconvolution(sg, structural_index=2.0, window_cells=10)
    assert res.n_accepted >= 5, res.report
    med_depth = res.report["depth_median_m"]
    assert 20.0 < med_depth < 600.0, med_depth

    iy, ix = np.unravel_index(np.argmax(np.abs(sg.values)), sg.values.shape)
    peak_x = sg.x0 + ix * sg.dx
    peak_y = sg.y0 + iy * sg.dy
    xs = np.array([s.x_m for s in res.solutions])
    ys = np.array([s.y_m for s in res.solutions])
    dist = float(np.hypot(np.median(xs) - peak_x, np.median(ys) - peak_y))
    assert dist < 500.0, dist


# ── 6. Endpoint HTTP ─────────────────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _stations_from_sg(sg, colname):
    out = []
    step = 2
    for iy in range(0, sg.ny, step):
        for ix in range(0, sg.nx, step):
            out.append({
                "station_id": f"P{iy}_{ix}",
                "x_m": float(sg.x0 + ix * sg.dx),
                "y_m": float(sg.y0 + iy * sg.dy),
                colname: float(sg.values[iy, ix]),
            })
    return out


def test_endpoint_json_and_csv():
    sg = _dipole_grid(64, 25.0, 150.0, inc_deg=90.0)
    stations = _stations_from_sg(sg, "magnetic_nt")
    client = _client()
    r = client.post("/v2/depth-estimate", json={
        "stations": stations, "structural_index": 3.0, "window_cells": 8,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["euler"]["report"]["n_accepted"] >= 5
    assert body["spectrum"] is not None
    assert "honesty_note" in body["euler"]["report"]

    r2 = client.post("/v2/depth-estimate", json={
        "stations": stations, "structural_index": 3.0, "window_cells": 8,
        "output_format": "csv",
    })
    assert r2.status_code == 200
    assert r2.text.splitlines()[3] == "x_m,y_m,depth_m,background,rel_uncertainty"
