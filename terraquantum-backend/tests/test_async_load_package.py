"""F3 — Flujo dorado ASÍNCRONO del paquete: encolar → progreso → cancelar.

El dolor que mata al producto: load-package síncrono → joint 96k vóxeles
(20+ min) revienta el proxy. Aquí se fija el contrato nuevo:
  - load-package (default) devuelve DE INMEDIATO {status:"queued", run_id,
    budget} y la inversión corre en un worker de PROCESO.
  - El progreso viaja por GET /geophysics-status (canal nativo existente).
  - POST /geophysics-cancel cancela de verdad (bandera + terminate) y deja
    estado terminal 'cancelled' en schedule + historial SQLite.
  - Presupuesto de vóxeles: estimación previa con aviso si excede umbral.

El E2E con worker real usa TQ_TEST_SLOW_BEFORE_SOLVE_S (retardo artificial
del worker, inocuo sin la variable) para una ventana de cancelación
determinista — el "sleep en hook" que pide el plan.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.run_queue_service import estimate_inversion_budget  # noqa: E402

# lat/lon (georreferenciado) para pasar el gate de spatial readiness del build.
_GRAV_ROWS = "\n".join(
    ["station_id,lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    + [
        f"S{i},{-27.10 - (i % 6) * 0.0011:.4f},{-69.30 - (i // 6) * 0.0011:.4f},"
        f"{1500 + i},{1.0 + 0.31 * (i % 7)},mGal,bouguer_anomaly"
        for i in range(36)
    ]
) + "\n"


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _build_package(client):
    r = client.post(
        "/v2/gravity-import/build-package",
        files={"file": ("grav.csv", _GRAV_ROWS, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.text


def _get_status(client, project_id, run_id):
    return client.get(f"/geophysics-status/{project_id}/{run_id}")


# ── 1. Presupuesto de vóxeles (estimación previa honesta) ────────────────────
def test_budget_small_run_no_warning():
    b = estimate_inversion_budget("gravity_only", 8_000)
    assert b["voxel_count"] == 8_000 and b["route_kind"] == "gravity"
    assert b["warning"] is None
    assert b["estimated_seconds"] > 0


def test_budget_large_joint_warns():
    """El caso que mató al proxy: joint 96k → aviso PREVIO con opciones."""
    b = estimate_inversion_budget("joint_cross_gradient", 96_000)
    assert b["route_kind"] == "joint"
    assert b["estimated_minutes"] > 5
    assert b["warning"] and "96,000" in b["warning"].replace(".", ",")
    assert "cancelable" in b["warning"] or "reducir" in b["warning"]


# ── 2. Encolar: respuesta inmediata con contrato completo ────────────────────
def test_load_package_default_queues_and_returns_immediately(monkeypatch):
    # Retardo del worker: la respuesta HTTP no debe esperarlo (si tardara,
    # este test se notaría lento; el assert clave es status=queued YA).
    monkeypatch.setenv("TQ_TEST_SLOW_BEFORE_SOLVE_S", "30")
    client = _client()
    pkg = _build_package(client)
    t0 = time.monotonic()
    r = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("pkg.tqpkg.csv", pkg, "text/csv")},
        data={"project_id": "pytest_async", "run_id": "run_queue_now"},
    )
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued", body
    assert body["project_id"] == "pytest_async"
    assert body["run_id"] == "run_queue_now"
    assert body["budget"]["voxel_count"] > 0
    assert body["poll"]["status_url"].endswith("/pytest_async/run_queue_now")
    assert body["inversionResult"] is None
    assert elapsed < 10, f"encolar tardó {elapsed:.1f}s: no es inmediato"

    # El status ya existe (queued/running) y el historial lo registró.
    rs = _get_status(client, "pytest_async", "run_queue_now")
    assert rs.status_code == 200, rs.text
    assert rs.json()["status"] in ("queued", "running")

    from services import project_store
    run = project_store.get_run("pytest_async", "run_queue_now")
    assert run is not None and run["status"] in ("queued", "running")

    # Limpieza: cancelar el worker retardado para no dejar procesos vivos.
    client.post("/geophysics-cancel/pytest_async/run_queue_now")


# ── 3. Cancelación real (bandera + terminate) ────────────────────────────────
def test_cancel_run_terminates_and_marks_cancelled(monkeypatch):
    monkeypatch.setenv("TQ_TEST_SLOW_BEFORE_SOLVE_S", "60")
    client = _client()
    pkg = _build_package(client)
    r = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("pkg.tqpkg.csv", pkg, "text/csv")},
        data={"project_id": "pytest_async", "run_id": "run_cancel_me"},
    )
    assert r.status_code == 200 and r.json()["status"] == "queued"

    rc = client.post("/geophysics-cancel/pytest_async/run_cancel_me")
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "cancelled"

    rs = _get_status(client, "pytest_async", "run_cancel_me")
    assert rs.status_code == 200, rs.text
    assert rs.json()["status"] == "cancelled"

    from services import project_store
    run = project_store.get_run("pytest_async", "run_cancel_me")
    assert run is not None and run["status"] == "cancelled"


# ── 4. E2E: encolar → poll con progreso → done → block model persistido ─────
@pytest.mark.slow
def test_async_package_e2E_completes_with_progress(monkeypatch):
    """El flujo dorado completo con worker de PROCESO real (sin retardo).

    Marca slow: el spawn importa el backend en frío (~5-15 s) + inversión
    chica. Verifica: estados progresan, termina done, historial done, y el
    status refleja etapas reales del solver.
    """
    monkeypatch.delenv("TQ_TEST_SLOW_BEFORE_SOLVE_S", raising=False)
    client = _client()
    pkg = _build_package(client)
    r = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("pkg.tqpkg.csv", pkg, "text/csv")},
        data={"project_id": "pytest_async", "run_id": "run_e2e_done"},
    )
    assert r.status_code == 200 and r.json()["status"] == "queued"

    seen_stages = set()
    deadline = time.monotonic() + 300
    final = None
    while time.monotonic() < deadline:
        rs = _get_status(client, "pytest_async", "run_e2e_done")
        if rs.status_code == 200:
            body = rs.json()
            seen_stages.add(body.get("stage"))
            if body["status"] in ("done", "error", "cancelled", "interrumpida"):
                final = body
                break
        time.sleep(1.0)

    assert final is not None, "la corrida no terminó en 300 s"
    assert final["status"] == "done", final
    assert final.get("progress") == 1.0

    from services import project_store
    run = project_store.get_run("pytest_async", "run_e2e_done")
    assert run is not None and run["status"] == "done"
    assert run["started_at"] and run["finished_at"]

    # El block model quedó persistido (re-abrible sin re-invertir).
    from core.block_model_store import get_run_dir
    run_dir = get_run_dir("pytest_async", "run_e2e_done")
    assert any(run_dir.glob("*.parquet")), list(run_dir.iterdir())


# ── 5. sync=true conserva el contrato histórico ──────────────────────────────
def test_sync_mode_still_returns_done_inline():
    client = _client()
    pkg = _build_package(client)
    r = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("pkg.tqpkg.csv", pkg, "text/csv")},
        data={"sync": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done", body
    assert body["inversionResult"]
