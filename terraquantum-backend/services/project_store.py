"""F3 — Historial persistente de proyectos y corridas (SQLite, local-first).

Un solo archivo en el directorio de datos (`data/terraquantum.db`), cero
configuración, respaldable copiando la carpeta — LA elección local-first.

Qué guarda: cada corrida (project_id, run_id) con su estado, ruta de física,
config, timestamps y artefactos. La UI lista corridas y re-abre modelos SIN
re-invertir (los parquet/JSON viven en el run_dir de siempre; aquí solo se
registra el índice + estado).

Concurrencia: escriben el proceso del servidor Y los workers de inversión
(procesos separados) → WAL + una conexión POR OPERACIÓN con timeout. SQLite
maneja esto de fábrica para el volumen local-first (decenas de corridas).

Reconciliación al arrancar: una corrida que quedó `queued`/`running` cuando el
backend murió NO puede seguir viva (los workers mueren con el padre) → se marca
`interrumpida` (gate F3: matar el backend a mitad de corrida → al reiniciar
figura interrumpida, no colgada).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import DATA_DIR
from core.logging import get_logger

_log = get_logger(__name__)

DB_PATH: Path = DATA_DIR / "terraquantum.db"

# Estados canónicos de una corrida en el historial.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrumpida"

_ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    project_id   TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    status       TEXT NOT NULL,
    source       TEXT,
    route        TEXT,
    config_json  TEXT,
    artifacts_json TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    PRIMARY KEY (project_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: "Path | None" = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: "Path | None" = None) -> None:
    """Crea el esquema si no existe. Idempotente; se llama al arrancar."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def record_run(
    project_id: str,
    run_id: str,
    status: str = STATUS_QUEUED,
    source: str = "package",
    route: Optional[str] = None,
    config: Optional[dict] = None,
    db_path: "Path | None" = None,
) -> None:
    """Registra (o re-registra) una corrida. Nunca lanza hacia el caller."""
    try:
        with _connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                """INSERT INTO runs (project_id, run_id, status, source, route,
                                     config_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, run_id) DO UPDATE SET
                     status=excluded.status, source=excluded.source,
                     route=excluded.route, config_json=excluded.config_json""",
                (
                    project_id, run_id, status, source, route,
                    json.dumps(config, ensure_ascii=False, default=str) if config else None,
                    _now(),
                ),
            )
    except Exception as exc:  # noqa: BLE001 — el historial jamás rompe el flujo
        _log.warning("project_store_record_failed", project_id=project_id,
                     run_id=run_id, error=str(exc))


def mark_run(
    project_id: str,
    run_id: str,
    status: str,
    error: Optional[str] = None,
    route: Optional[str] = None,
    artifacts: Optional[dict] = None,
    db_path: "Path | None" = None,
) -> None:
    """Actualiza el estado; fija started_at/finished_at según corresponda."""
    sets = ["status = ?"]
    args: List[Any] = [status]
    if status == STATUS_RUNNING:
        sets.append("started_at = COALESCE(started_at, ?)")
        args.append(_now())
    if status in (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED, STATUS_INTERRUPTED):
        sets.append("finished_at = COALESCE(finished_at, ?)")
        args.append(_now())
    if error is not None:
        sets.append("error = ?")
        args.append(str(error)[:1000])
    if route is not None:
        sets.append("route = ?")
        args.append(route)
    if artifacts is not None:
        sets.append("artifacts_json = ?")
        args.append(json.dumps(artifacts, ensure_ascii=False, default=str))
    args.extend([project_id, run_id])
    try:
        with _connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            cur = conn.execute(
                f"UPDATE runs SET {', '.join(sets)} WHERE project_id = ? AND run_id = ?",
                args,
            )
            if cur.rowcount == 0:
                # Corrida no registrada (p.ej. flujo directo antiguo): registrar
                # sobre la marcha para que el historial no tenga huecos.
                conn.execute(
                    """INSERT OR IGNORE INTO runs
                       (project_id, run_id, status, source, created_at, error, route)
                       VALUES (?, ?, ?, 'unknown', ?, ?, ?)""",
                    (project_id, run_id, status, _now(), error, route),
                )
    except Exception as exc:  # noqa: BLE001
        _log.warning("project_store_mark_failed", project_id=project_id,
                     run_id=run_id, status=status, error=str(exc))


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for key in ("config_json", "artifacts_json"):
        raw = d.pop(key, None)
        clean = key.replace("_json", "")
        try:
            d[clean] = json.loads(raw) if raw else None
        except Exception:
            d[clean] = None
    return d


def get_run(project_id: str, run_id: str, db_path: "Path | None" = None) -> Optional[Dict[str, Any]]:
    try:
        with _connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            row = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? AND run_id = ?",
                (project_id, run_id),
            ).fetchone()
            return _row_to_dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        _log.warning("project_store_get_failed", error=str(exc))
        return None


def list_runs(
    project_id: Optional[str] = None,
    limit: int = 200,
    db_path: "Path | None" = None,
) -> List[Dict[str, Any]]:
    try:
        with _connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _log.warning("project_store_list_failed", error=str(exc))
        return []


def reconcile_interrupted(db_path: "Path | None" = None) -> int:
    """Al ARRANCAR el backend: toda corrida `queued`/`running` quedó huérfana
    (los workers murieron con el proceso padre) → `interrumpida`.

    Devuelve cuántas se reconciliaron. Gate F3: matar el backend a mitad de
    corrida → al reiniciar figura interrumpida, no colgada para siempre.
    """
    try:
        with _connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            cur = conn.execute(
                f"""UPDATE runs SET status = ?, finished_at = COALESCE(finished_at, ?),
                       error = COALESCE(error, 'El backend se reinició con la corrida en curso.')
                    WHERE status IN ({','.join('?' * len(_ACTIVE_STATUSES))})""",
                (STATUS_INTERRUPTED, _now(), *_ACTIVE_STATUSES),
            )
            n = cur.rowcount
            if n:
                _log.warning("project_store_reconciled_interrupted", count=n)
            return n
    except Exception as exc:  # noqa: BLE001
        _log.warning("project_store_reconcile_failed", error=str(exc))
        return 0
