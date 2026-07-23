"""F8 — Presupuestos de rendimiento como tests.

El plan fija: ingesta 10k filas <5 s; inversión 30k vóxeles <3 min; render 100k
celdas >30 fps. Aquí:
  • ingesta: medida real (enrich-package de 10k filas ya con elevación, offline).
  • inversión: presupuesto de tiempo con malla acotada (el gate corre 30k/<3min).
  • render fps: DIFERIDO — requiere navegador (Playwright), que es la iteración
    frontend separada de F8 (decisión de sesión: núcleo backend sin deps nuevas).

Umbrales env-configurables: default GENEROSO en CI (no flakear en máquinas
lentas); el gate `f8_gate_storm.py` aplica el número ESTRICTO del plan y mide.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.f8_storm_lib as L  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _grav_csv_rows(n_rows: int) -> bytes:
    """CSV de gravimetría con elevación (offline) de exactamente n_rows filas."""
    import math
    lines = ["lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    side = int(math.ceil(n_rows ** 0.5))
    count = 0
    for i in range(side):
        for j in range(side):
            if count >= n_rows:
                break
            lat = -27.0 - i * 0.0005
            lon = -69.0 + j * 0.0005
            elev = 1000.0 + (i + j)
            val = 3.0 + ((i * j) % 7) * 0.5
            lines.append(f"{lat:.4f},{lon:.4f},{elev:.1f},{val:.3f},mGal,bouguer_anomaly")
            count += 1
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_budget_ingesta_10k_rows(client):
    """Ingesta de 10k filas dentro del presupuesto (default CI generoso; plan=5 s)."""
    budget_s = float(os.environ.get("TQ_F8_INGEST_BUDGET_S", "30"))
    body = _grav_csv_rows(10_000)
    L.reset_rate_limit()
    t0 = time.monotonic()
    r = client.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": ("perf10k.csv", body, "text/csv")},
        params={"enable_dem": "false"},
    )
    dt = time.monotonic() - t0
    assert r.status_code == 200, r.text[:200]
    print(f"\n[F8 perf] ingesta 10k filas = {dt:.2f}s (presupuesto {budget_s}s, plan 5s)")
    assert dt < budget_s, f"ingesta 10k filas tardó {dt:.2f}s > {budget_s}s"


@pytest.mark.slow
def test_budget_inversion(client):
    """Inversión acotada dentro de presupuesto (el gate mide 30k vóxeles <3 min)."""
    budget_s = float(os.environ.get("TQ_F8_INVERT_BUDGET_S", "120"))
    grid = int(os.environ.get("TQ_F8_INVERT_GRID", "8"))  # 8³=512 en CI; gate escala
    combo = L.Combo("grav", "clean", "medium", "latlon", False)
    t0 = time.monotonic()
    o = L.drive_e2e(client, combo, side=L.SIZES_FAST["medium"], grid=grid,
                    project_id="f8_perf_invert", run_id="perf")
    dt = time.monotonic() - t0
    assert o.ok, f"{o.outcome}: {o.detail}"
    n_vox = grid ** 3
    print(f"\n[F8 perf] inversión {n_vox} vóxeles = {dt:.2f}s (presupuesto {budget_s}s)")
    assert dt < budget_s, f"inversión {n_vox} vóxeles tardó {dt:.2f}s > {budget_s}s"


@pytest.mark.skip(reason="render 100k celdas >30fps: requiere navegador (Playwright); "
                         "diferido a la iteración frontend UI E2E de F8")
def test_budget_render_fps():
    """DIFERIDO: la medición de fps del visor 3D necesita Playwright + WebGL en un
    navegador headless — iteración frontend separada, fuera del núcleo backend."""
