"""
API key management — SHA-256 hashed keys stored in SQLite (stdlib).
Keys are of the form "tq_<random>" and are NEVER stored in plaintext.
"""
import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key_hash    TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            last_used   TEXT,
            revoked     INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Public API ────────────────────────────────────────────────────────────────

def create_api_key(db_path: Path, name: str) -> str:
    """Creates a new key. Returns plaintext key — shown once, never stored."""
    raw = "tq_" + secrets.token_urlsafe(32)
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT INTO api_keys (key_hash, name, created_at) VALUES (?, ?, ?)",
        (_hash(raw), name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return raw


def validate_api_key(db_path: Path, raw: str) -> bool:
    """Returns True if the key exists and is not revoked. Updates last_used."""
    if not raw:
        return False
    h = _hash(raw)
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT revoked FROM api_keys WHERE key_hash = ?", (h,)
    ).fetchone()
    if row is not None and row[0] == 0:
        conn.execute(
            "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
            (datetime.now(timezone.utc).isoformat(), h),
        )
        conn.commit()
    conn.close()
    return row is not None and row[0] == 0


def revoke_api_key(db_path: Path, key_hash_prefix: str) -> bool:
    """Revokes all keys whose SHA-256 hash starts with `key_hash_prefix`."""
    conn = _get_conn(db_path)
    cur = conn.execute(
        "UPDATE api_keys SET revoked = 1 WHERE key_hash LIKE ?",
        (key_hash_prefix + "%",),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def list_api_keys(db_path: Path) -> list[dict]:
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT key_hash, name, created_at, last_used, revoked "
        "FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "key_hash_prefix": r[0][:12] + "...",
            "name": r[1],
            "created_at": r[2],
            "last_used": r[3],
            "revoked": bool(r[4]),
        }
        for r in rows
    ]
