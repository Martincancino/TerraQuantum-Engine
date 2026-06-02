"""
API key management endpoints — all protected by X-TQ-Master-Key header.

POST   /api/keys/         — create a new API key
GET    /api/keys/         — list all keys (hash prefix shown, never plaintext)
DELETE /api/keys/         — revoke a key by hash prefix
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from core.auth import create_api_key, list_api_keys, revoke_api_key
from core.config import TQ_API_KEYS_DB, TQ_MASTER_KEY

router = APIRouter(prefix="/api/keys", tags=["auth"])


# ── Master key guard ──────────────────────────────────────────────────────────

def _require_master(x_tq_master_key: str = Header(...)):
    if not TQ_MASTER_KEY:
        raise HTTPException(
            status_code=503,
            detail="Master key not configured. Set TQ_MASTER_KEY env var.",
        )
    if x_tq_master_key != TQ_MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid master key.")


# ── Request/response schemas ──────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str


class RevokeKeyRequest(BaseModel):
    key_hash_prefix: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", dependencies=[Depends(_require_master)])
def create_key(body: CreateKeyRequest):
    raw = create_api_key(TQ_API_KEYS_DB, body.name)
    return {
        "key": raw,
        "note": "Store this key securely — it will not be shown again.",
    }


@router.get("/", dependencies=[Depends(_require_master)])
def list_keys():
    return list_api_keys(TQ_API_KEYS_DB)


@router.delete("/", dependencies=[Depends(_require_master)])
def revoke_key(body: RevokeKeyRequest):
    ok = revoke_api_key(TQ_API_KEYS_DB, body.key_hash_prefix)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"revoked": True}
