"""
API key authentication middleware.

Validates the X-TQ-API-Key header on every request except:
  - OPTIONS preflight (CORS)
  - Public paths: /health, /, /docs, /openapi.json, /redoc
  - Static files prefix: /models/
  - Key management prefix: /api/keys/ (has its own master-key auth)

Set TQ_AUTH_ENABLED=false to disable globally (dev only).
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.auth import validate_api_key
from core.config import TQ_API_KEYS_DB, TQ_AUTH_ENABLED

_PUBLIC_PATHS = frozenset({"/health", "/", "/docs", "/openapi.json", "/redoc"})
_PUBLIC_PREFIXES = ("/models/",)
# Key-management route uses its own X-TQ-Master-Key auth.
_KEY_MGMT_PREFIX = "/api/keys"


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not TQ_AUTH_ENABLED:
            return await call_next(request)

        # CORS preflight — always pass through.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        if path in _PUBLIC_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)
        if path.startswith(_KEY_MGMT_PREFIX):
            return await call_next(request)

        api_key = request.headers.get("X-TQ-API-Key", "")
        if not validate_api_key(TQ_API_KEYS_DB, api_key):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid or missing API key.",
                    "hint": "Include the X-TQ-API-Key header.",
                },
            )

        return await call_next(request)
