"""F3 — Historial SQLite de corridas (services/project_store).

Fija el contrato local-first: un archivo, cero config, sobrevive reinicios;
las corridas huérfanas (queued/running al arrancar) se reconcilian a
"interrumpida" — jamás quedan colgadas (gate F3).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import project_store as ps  # noqa: E402


def _db(tmp_path):
    return tmp_path / "test_tq.db"


def test_record_mark_get_roundtrip(tmp_path):
    db = _db(tmp_path)
    ps.init_db(db)
    ps.record_run("p1", "r1", config={"nx": 10}, route="gravity_only", db_path=db)
    run = ps.get_run("p1", "r1", db_path=db)
    assert run["status"] == ps.STATUS_QUEUED
    assert run["config"] == {"nx": 10}
    assert run["route"] == "gravity_only"
    assert run["created_at"] and run["started_at"] is None

    ps.mark_run("p1", "r1", ps.STATUS_RUNNING, db_path=db)
    run = ps.get_run("p1", "r1", db_path=db)
    assert run["status"] == "running" and run["started_at"]

    ps.mark_run("p1", "r1", ps.STATUS_DONE, artifacts={"block_model": "x.parquet"}, db_path=db)
    run = ps.get_run("p1", "r1", db_path=db)
    assert run["status"] == "done" and run["finished_at"]
    assert run["artifacts"] == {"block_model": "x.parquet"}


def test_list_runs_ordering_and_filter(tmp_path):
    db = _db(tmp_path)
    ps.init_db(db)
    ps.record_run("pA", "r1", db_path=db)
    ps.record_run("pA", "r2", db_path=db)
    ps.record_run("pB", "r3", db_path=db)
    assert len(ps.list_runs(db_path=db)) == 3
    only_a = ps.list_runs(project_id="pA", db_path=db)
    assert {r["run_id"] for r in only_a} == {"r1", "r2"}


def test_survives_reopen(tmp_path):
    """El historial es un ARCHIVO: cerrar y reabrir (reinicio) no pierde nada."""
    db = _db(tmp_path)
    ps.init_db(db)
    ps.record_run("p1", "r1", db_path=db)
    ps.mark_run("p1", "r1", ps.STATUS_DONE, db_path=db)
    # "Reinicio": nueva conexión desde cero sobre el mismo archivo.
    run = ps.get_run("p1", "r1", db_path=db)
    assert run is not None and run["status"] == "done"


def test_reconcile_marks_orphans_interrupted(tmp_path):
    """GATE F3: backend muere con corridas en curso → al reiniciar figuran
    'interrumpida' (con explicación), NUNCA colgadas en running."""
    db = _db(tmp_path)
    ps.init_db(db)
    ps.record_run("p1", "muerta_en_cola", db_path=db)                    # queued
    ps.record_run("p1", "muerta_corriendo", db_path=db)
    ps.mark_run("p1", "muerta_corriendo", ps.STATUS_RUNNING, db_path=db)
    ps.record_run("p1", "terminada", db_path=db)
    ps.mark_run("p1", "terminada", ps.STATUS_DONE, db_path=db)

    n = ps.reconcile_interrupted(db_path=db)
    assert n == 2
    assert ps.get_run("p1", "muerta_en_cola", db_path=db)["status"] == "interrumpida"
    interrupted = ps.get_run("p1", "muerta_corriendo", db_path=db)
    assert interrupted["status"] == "interrumpida"
    assert interrupted["finished_at"] and "reinici" in (interrupted["error"] or "")
    assert ps.get_run("p1", "terminada", db_path=db)["status"] == "done"
    # Reconciliar de nuevo: idempotente.
    assert ps.reconcile_interrupted(db_path=db) == 0


def test_mark_unknown_run_registers_it(tmp_path):
    """mark_run sobre una corrida no registrada la crea (sin huecos)."""
    db = _db(tmp_path)
    ps.init_db(db)
    ps.mark_run("pX", "nunca_registrada", ps.STATUS_DONE, db_path=db)
    run = ps.get_run("pX", "nunca_registrada", db_path=db)
    assert run is not None and run["status"] == "done"


def test_store_never_raises_on_bad_path():
    """Contrato nunca-crashea: un path imposible degrada a warning, no excepción."""
    bad = os.path.join("Z:\\", "no_existe", "imposible.db") if os.name == "nt" else "/proc/imposible/x.db"
    ps.record_run("p", "r", db_path=bad)          # no debe lanzar
    assert ps.get_run("p", "r", db_path=bad) is None
    assert ps.list_runs(db_path=bad) == []
    assert ps.reconcile_interrupted(db_path=bad) == 0


def test_history_endpoint_lists_runs(tmp_path, monkeypatch):
    """GET /v2/history/runs sirve el historial (smoke HTTP)."""
    db = _db(tmp_path)
    monkeypatch.setattr(ps, "DB_PATH", db)
    ps.init_db()
    ps.record_run("p_http", "r_http", route="gravity_only")
    ps.mark_run("p_http", "r_http", ps.STATUS_DONE)

    from fastapi.testclient import TestClient
    from main import app

    r = TestClient(app).get("/v2/history/runs", params={"project_id": "p_http"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["runs"][0]["run_id"] == "r_http"
    assert body["runs"][0]["status"] == "done"
