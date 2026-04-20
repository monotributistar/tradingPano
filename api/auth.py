"""
api/auth.py — API key authentication
=====================================

All non-health endpoints are protected with a shared API key delivered via
the ``X-API-Key`` request header.

Setup
-----
Set ``BOT_API_SECRET`` in the environment (via ``.env`` or docker-compose):

    BOT_API_SECRET=<random-string>   # generate with: openssl rand -hex 32

The frontend stores the key in ``localStorage`` and sends it with every
request.  See ``frontend/src/api/client.ts``.

Usage in routers
----------------
    from api.auth import require_api_key
    from fastapi import Depends

    router = APIRouter(dependencies=[Depends(require_api_key)])

    # — or per-endpoint:
    @router.post("/start")
    def start(body: ..., _: None = Depends(require_api_key)):
        ...

Public endpoints (no auth required)
------------------------------------
- ``GET /api/health``     — Docker / nginx healthcheck
- ``GET /docs``           — Swagger UI  (disabled by default in production)
- ``GET /redoc``          — ReDoc

Contract
--------
- Header name: ``X-API-Key``
- On missing / wrong key: HTTP 403 with body ``{"detail": "Invalid or missing API key"}``
- If ``BOT_API_SECRET`` is not set in the environment the server REFUSES TO
  START — running an unprotected bot in production is not allowed.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

# ── Key loading ───────────────────────────────────────────────────────────────

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_BOT_API_SECRET: str | None = None


def _get_secret() -> str:
    """
    Return the configured API secret.

    Loads lazily so unit-tests can set the env var before importing this
    module.  Raises ``RuntimeError`` if the env var is absent — this is
    intentional: we never want to start an unprotected API in production.
    """
    global _BOT_API_SECRET
    if _BOT_API_SECRET is None:
        secret = os.environ.get("BOT_API_SECRET", "").strip()
        if not secret:
            raise RuntimeError(
                "BOT_API_SECRET environment variable is not set.\n"
                "Generate one with:  openssl rand -hex 32\n"
                "Then add it to your .env file."
            )
        _BOT_API_SECRET = secret
    return _BOT_API_SECRET


# ── Dependency ────────────────────────────────────────────────────────────────

async def require_api_key(key: str | None = Security(_API_KEY_HEADER)) -> None:
    """
    FastAPI dependency — validates the ``X-API-Key`` header.

    Raises HTTP 403 if the key is missing or incorrect.
    Uses ``secrets.compare_digest`` to prevent timing attacks.
    """
    try:
        expected = _get_secret()
    except RuntimeError as exc:
        # Server mis-configuration — return 500 so it's visible immediately
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key",
        )
