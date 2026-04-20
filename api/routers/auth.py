"""
api/routers/auth.py — Login / key-validation endpoint
======================================================

Provides a single public endpoint that lets the frontend (or any client)
verify a ``BOT_API_SECRET`` key before storing it.  This gives immediate
server-side feedback instead of the user discovering a wrong key via a 403
on the first real request.

Endpoint
--------
    POST /api/auth/login
    Content-Type: application/json
    Body: {"api_key": "<BOT_API_SECRET>"}

Responses
---------
    200  {"authenticated": true}          — key is correct
    401  {"detail": "Invalid API key"}    — key is wrong or empty
    422  (FastAPI validation error)       — body is missing / malformed

Design notes
------------
- This endpoint is intentionally **public** (no ``require_api_key`` dependency)
  because its sole purpose is to validate the key.
- Uses ``secrets.compare_digest`` to prevent timing attacks — same constant-time
  comparison as the main ``require_api_key`` dependency.
- The server never echoes the key back; it only returns ``{"authenticated": true}``
  so even a successful response leaks nothing useful.
"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["auth"])


# ── Request / response models ─────────────────────────────────────────────────

class LoginRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="The BOT_API_SECRET value to validate")


class LoginResponse(BaseModel):
    authenticated: bool = True


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="Validate API key",
    description=(
        "Validates the supplied ``api_key`` against the server's "
        "``BOT_API_SECRET``.  Returns ``{authenticated: true}`` on success "
        "or HTTP 401 on failure.  Use this to verify the key before storing "
        "it in the browser."
    ),
)
def login(body: LoginRequest) -> LoginResponse:
    """
    Validate a ``BOT_API_SECRET`` API key.

    - **200** + ``{"authenticated": true}`` — key matches
    - **401** — key is wrong or ``BOT_API_SECRET`` is not configured on the server
    """
    expected = os.environ.get("BOT_API_SECRET", "").strip()

    if not expected:
        # Misconfigured server — don't reveal details, just deny
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Constant-time comparison — prevents timing-oracle attacks
    if not secrets.compare_digest(body.api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return LoginResponse(authenticated=True)
