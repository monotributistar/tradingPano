"""
tests/api/test_bot_endpoints.py
================================

Integration tests for the bot management API endpoints.

GET  /api/bot/status
POST /api/bot/start
POST /api/bot/stop
GET  /api/bot/events
GET  /api/bot/history

The bot thread is never actually started — we verify the API contract
(request validation, response schema, auth, error codes) without running
any trading logic.
"""

import pytest


@pytest.mark.api
class TestBotStatus:
    def test_status_idle_when_not_running(self, client, auth_headers):
        resp = client.get("/api/bot/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["crashed"] is False

    def test_status_has_required_fields(self, client, auth_headers):
        data = client.get("/api/bot/status", headers=auth_headers).json()
        required = {"running", "crashed"}
        assert required.issubset(data.keys())

    def test_status_no_auth_blocked(self, client):
        assert client.get("/api/bot/status").status_code == 403


@pytest.mark.api
class TestBotStart:
    def test_start_with_invalid_mode_returns_400(self, client, auth_headers):
        resp = client.post(
            "/api/bot/start",
            headers=auth_headers,
            json={"mode": "turbo", "strategy": "mean_reversion", "pairs": ["BTC/USDT"]},
        )
        assert resp.status_code == 400

    def test_start_with_empty_pairs_returns_422(self, client, auth_headers):
        """Pydantic validation: pairs must be a non-empty list."""
        resp = client.post(
            "/api/bot/start",
            headers=auth_headers,
            json={"mode": "paper", "strategy": "mean_reversion", "pairs": []},
        )
        # Pydantic or our validator should reject this
        assert resp.status_code in (400, 422)

    def test_start_paper_bot_launches(self, client, auth_headers):
        """
        Starts the bot and immediately stops it.
        The thread actually runs but we stop it before it does anything meaningful.
        """
        # Make sure it's stopped first
        client.post("/api/bot/stop", headers=auth_headers)

        resp = client.post(
            "/api/bot/start",
            headers=auth_headers,
            json={
                "mode":     "paper",
                "strategy": "mean_reversion",
                "pairs":    ["BTC/USDT"],
                "restore":  False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True

        # Clean up — stop the bot
        stop_resp = client.post("/api/bot/stop", headers=auth_headers)
        assert stop_resp.status_code == 200

    def test_start_while_running_returns_409(self, client, auth_headers):
        # Start the bot
        client.post("/api/bot/start", headers=auth_headers,
                    json={"mode": "paper", "strategy": "mean_reversion",
                          "pairs": ["BTC/USDT"]})
        # Try to start again
        resp = client.post("/api/bot/start", headers=auth_headers,
                           json={"mode": "paper", "strategy": "mean_reversion",
                                 "pairs": ["ETH/USDT"]})
        assert resp.status_code == 409
        # Clean up
        client.post("/api/bot/stop", headers=auth_headers)

    def test_start_no_auth_blocked(self, client):
        resp = client.post("/api/bot/start",
                           json={"mode": "paper", "strategy": "x", "pairs": ["BTC/USDT"]})
        assert resp.status_code == 403


@pytest.mark.api
class TestBotStop:
    def test_stop_when_not_running_returns_409(self, client, auth_headers):
        # Ensure bot is stopped
        client.post("/api/bot/stop", headers=auth_headers)
        resp = client.post("/api/bot/stop", headers=auth_headers)
        assert resp.status_code == 409

    def test_stop_no_auth_blocked(self, client):
        assert client.post("/api/bot/stop").status_code == 403


@pytest.mark.api
class TestBotEvents:
    def test_events_returns_list(self, client, auth_headers):
        resp = client.get("/api/bot/events", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_events_limit_param_accepted(self, client, auth_headers):
        resp = client.get("/api/bot/events?limit=5", headers=auth_headers)
        assert resp.status_code == 200

    def test_events_no_auth_blocked(self, client):
        assert client.get("/api/bot/events").status_code == 403


@pytest.mark.api
class TestBotHistory:
    def test_history_returns_list(self, client, auth_headers):
        resp = client.get("/api/bot/history", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_history_no_auth_blocked(self, client):
        assert client.get("/api/bot/history").status_code == 403
