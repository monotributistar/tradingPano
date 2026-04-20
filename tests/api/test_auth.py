"""
tests/api/test_auth.py
======================

Tests for the authentication layer — both the public ``POST /api/auth/login``
endpoint and the ``X-API-Key`` middleware that guards every protected route.

Coverage
--------
POST /api/auth/login
  - correct key → 200 + {"authenticated": true}
  - wrong key → 401 + "Invalid API key"
  - empty string key → 422 (Pydantic min_length=1 rejects it before the handler)
  - missing api_key field → 422
  - completely empty body → 422
  - extra fields in body are silently ignored (Pydantic default)
  - response never echoes the key back

X-API-Key middleware (require_api_key)
  - missing header → 403
  - wrong key → 403
  - correct key → 200
  - empty string header → 403
  - header with extra whitespace → 403 (must be exact)
  - case-sensitive: wrong capitalisation → 403

Error response shapes
  - 401 from /login has {"detail": "Invalid API key"}
  - 403 from protected endpoint has {"detail": "Invalid or missing API key"}
"""

import pytest

from tests.conftest import TEST_API_SECRET

# ── Helpers ────────────────────────────────────────────────────────────────────

WRONG_KEY   = "definitely-not-the-right-key"
EMPTY_KEY   = ""
PADDED_KEY  = f" {TEST_API_SECRET} "   # leading/trailing whitespace


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/login
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.api
class TestLoginEndpoint:

    def test_correct_key_returns_200(self, client):
        resp = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET})
        assert resp.status_code == 200

    def test_correct_key_returns_authenticated_true(self, client):
        data = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET}).json()
        assert data == {"authenticated": True}

    def test_wrong_key_returns_401(self, client):
        resp = client.post("/api/auth/login", json={"api_key": WRONG_KEY})
        assert resp.status_code == 401

    def test_wrong_key_detail_message(self, client):
        data = client.post("/api/auth/login", json={"api_key": WRONG_KEY}).json()
        assert data["detail"] == "Invalid API key"

    def test_empty_string_key_returns_422(self, client):
        """Pydantic rejects empty string before the handler runs (min_length=1)."""
        resp = client.post("/api/auth/login", json={"api_key": ""})
        assert resp.status_code == 422

    def test_missing_api_key_field_returns_422(self, client):
        resp = client.post("/api/auth/login", json={"something_else": "x"})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422

    def test_no_body_returns_422(self, client):
        resp = client.post("/api/auth/login")
        assert resp.status_code == 422

    def test_extra_fields_ignored(self, client):
        """Unknown fields in the body should not cause an error."""
        resp = client.post(
            "/api/auth/login",
            json={"api_key": TEST_API_SECRET, "extra": "ignored"},
        )
        assert resp.status_code == 200

    def test_response_does_not_echo_key(self, client):
        """The server must never return the secret in any response field."""
        data = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET}).json()
        assert TEST_API_SECRET not in str(data)

    def test_whitespace_padded_key_rejected(self, client):
        """Key comparison is exact — padded string must not match."""
        resp = client.post("/api/auth/login", json={"api_key": PADDED_KEY})
        assert resp.status_code == 401

    def test_key_with_different_case_rejected(self, client):
        """Key comparison is case-sensitive."""
        resp = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET.upper()})
        assert resp.status_code == 401

    def test_partial_key_rejected(self, client):
        """A prefix of the correct key must not authenticate."""
        resp = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET[:10]})
        assert resp.status_code == 401

    def test_login_does_not_require_x_api_key_header(self, client):
        """The login endpoint is public — no X-API-Key header needed."""
        resp = client.post(
            "/api/auth/login",
            json={"api_key": TEST_API_SECRET},
            headers={},   # explicitly no auth header
        )
        assert resp.status_code == 200

    def test_login_content_type_is_json(self, client):
        resp = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET})
        assert "application/json" in resp.headers.get("content-type", "")


# ══════════════════════════════════════════════════════════════════════════════
# X-API-Key middleware — guards every protected route
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.api
class TestApiKeyMiddleware:

    # ── Missing / wrong key ───────────────────────────────────────────────────

    def test_no_header_returns_403(self, client):
        resp = client.get("/api/bot/status")
        assert resp.status_code == 403

    def test_wrong_key_returns_403(self, client):
        resp = client.get("/api/bot/status", headers={"X-API-Key": WRONG_KEY})
        assert resp.status_code == 403

    def test_empty_header_returns_403(self, client):
        resp = client.get("/api/bot/status", headers={"X-API-Key": ""})
        assert resp.status_code == 403

    def test_whitespace_only_header_returns_403(self, client):
        resp = client.get("/api/bot/status", headers={"X-API-Key": "   "})
        assert resp.status_code == 403

    def test_padded_key_returns_403(self, client):
        """Exact match only — leading/trailing spaces must fail."""
        resp = client.get("/api/bot/status", headers={"X-API-Key": PADDED_KEY})
        assert resp.status_code == 403

    def test_uppercase_key_returns_403(self, client):
        resp = client.get(
            "/api/bot/status",
            headers={"X-API-Key": TEST_API_SECRET.upper()},
        )
        assert resp.status_code == 403

    def test_partial_key_returns_403(self, client):
        resp = client.get(
            "/api/bot/status",
            headers={"X-API-Key": TEST_API_SECRET[:8]},
        )
        assert resp.status_code == 403

    # ── Correct key ───────────────────────────────────────────────────────────

    def test_correct_key_returns_200(self, client, auth_headers):
        resp = client.get("/api/bot/status", headers=auth_headers)
        assert resp.status_code == 200

    def test_correct_key_on_strategies_endpoint(self, client, auth_headers):
        """Verify auth works on a second protected route (no DB side-effects)."""
        resp = client.get("/api/strategies", headers=auth_headers)
        assert resp.status_code == 200

    def test_correct_key_on_settings_endpoint(self, client, auth_headers):
        resp = client.get("/api/config/settings", headers=auth_headers)
        assert resp.status_code == 200

    # ── 403 response shape ────────────────────────────────────────────────────

    def test_403_detail_message(self, client):
        data = client.get("/api/bot/status").json()
        assert data["detail"] == "Invalid or missing API key"

    def test_403_is_json(self, client):
        resp = client.get("/api/bot/status")
        assert "application/json" in resp.headers.get("content-type", "")

    # ── Public routes are unaffected ──────────────────────────────────────────

    def test_health_endpoint_needs_no_key(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_login_endpoint_needs_no_key(self, client):
        resp = client.post("/api/auth/login", json={"api_key": TEST_API_SECRET})
        assert resp.status_code == 200
