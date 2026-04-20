"""
tests/api/test_portfolio_endpoints.py
=======================================

Integration tests for the multi-strategy portfolio management endpoints.

GET  /api/portfolio/status
POST /api/portfolio/start
POST /api/portfolio/stop

The portfolio slots are never actually started — we verify the API contract
(request validation, response schema, auth, error codes) without running
any trading logic.

Note on ``/start``: the endpoint calls ``load_bot_config()`` which reads
``crypto_bot/config.yaml``.  Most CI environments won't have a
``portfolio.strategies`` section, so the test that exercises a well-formed
start request patches ``load_bot_config`` to inject a minimal portfolio
config.  All other tests rely on the missing-config 422 path, which always
works without patching.
"""

import pytest
from unittest.mock import patch


# ── Minimal portfolio config used by the "happy path" start test ──────────────

_MINIMAL_PORTFOLIO_CONFIG = {
    "exchange": "binance",
    "risk": {
        "daily_loss_stop_pct":     10.0,
        "max_drawdown_pct":         0.0,
        "max_daily_trades":          0,
        "max_consecutive_losses":    0,
        "blackout_hours":           "",
        "max_concurrent_positions":  3,
        "leverage":                1.0,
    },
    "portfolio": {
        "initial_capital": 1000.0,
        "strategies": [
            {
                "name":        "mean_reversion",
                "pairs":       ["BTC/USDT"],
                "capital_pct": 100.0,
                "timeframe":   "1h",
            }
        ],
    },
}


# ── GET /api/portfolio/status ─────────────────────────────────────────────────

@pytest.mark.api
class TestPortfolioStatus:
    def test_status_no_auth_blocked(self, client):
        assert client.get("/api/portfolio/status").status_code == 403

    def test_status_returns_200(self, client, auth_headers):
        resp = client.get("/api/portfolio/status", headers=auth_headers)
        assert resp.status_code == 200

    def test_status_has_required_fields(self, client, auth_headers):
        data = client.get("/api/portfolio/status", headers=auth_headers).json()
        required = {"running", "alive_slots", "total_slots", "crashed_slots", "total_trades", "slots"}
        assert required.issubset(data.keys())

    def test_status_idle_when_not_running(self, client, auth_headers):
        # Ensure portfolio is not running
        client.post("/api/portfolio/stop", headers=auth_headers)  # ignore 409
        data = client.get("/api/portfolio/status", headers=auth_headers).json()
        assert data["running"] is False

    def test_status_slots_is_list(self, client, auth_headers):
        data = client.get("/api/portfolio/status", headers=auth_headers).json()
        assert isinstance(data["slots"], list)

    def test_status_alive_slots_is_int(self, client, auth_headers):
        data = client.get("/api/portfolio/status", headers=auth_headers).json()
        assert isinstance(data["alive_slots"], int)
        assert data["alive_slots"] >= 0

    def test_status_crashed_slots_is_int(self, client, auth_headers):
        data = client.get("/api/portfolio/status", headers=auth_headers).json()
        assert isinstance(data["crashed_slots"], int)
        assert data["crashed_slots"] >= 0


# ── POST /api/portfolio/start ─────────────────────────────────────────────────

@pytest.mark.api
class TestPortfolioStart:
    def test_start_no_auth_blocked(self, client):
        assert client.post("/api/portfolio/start", json={"mode": "paper"}).status_code == 403

    def test_start_missing_portfolio_config_returns_422(self, client, auth_headers):
        """
        When config.yaml has no ``portfolio.strategies``, the endpoint must
        return HTTP 422 with a descriptive message.
        """
        # The router imports load_bot_config inside the function from api.main,
        # so we patch it at the source.
        with patch("api.main.load_bot_config", return_value={}):
            resp = client.post("/api/portfolio/start", headers=auth_headers, json={"mode": "paper"})
        assert resp.status_code == 422
        detail = resp.json().get("detail", "")
        assert "portfolio" in detail.lower() or "strategies" in detail.lower()

    def test_start_empty_strategies_list_returns_422(self, client, auth_headers):
        """An explicit empty strategies list is also invalid."""
        empty_cfg = {"portfolio": {"strategies": [], "initial_capital": 1000.0}}
        with patch("api.main.load_bot_config", return_value=empty_cfg):
            resp = client.post("/api/portfolio/start", headers=auth_headers, json={"mode": "paper"})
        assert resp.status_code == 422

    def test_start_invalid_mode_returns_400(self, client, auth_headers):
        """
        The portfolio_manager should raise RuntimeError for unknown modes,
        which the router converts to HTTP 400.
        """
        with patch("api.main.load_bot_config", return_value=_MINIMAL_PORTFOLIO_CONFIG), \
             patch("api.portfolio_manager.start_portfolio",
                   side_effect=RuntimeError("unknown mode: turbo")):
            resp = client.post(
                "/api/portfolio/start",
                headers=auth_headers,
                json={"mode": "turbo"},
            )
        # Either 400 (explicit check) or 422 (Pydantic enum validation)
        assert resp.status_code in (400, 422)

    def test_start_while_running_returns_409(self, client, auth_headers):
        """Starting twice must return 409 Conflict."""
        # The router imports is_running inside the function from api.portfolio_manager
        with patch("api.portfolio_manager.is_running", return_value=True):
            resp = client.post(
                "/api/portfolio/start",
                headers=auth_headers,
                json={"mode": "paper"},
            )
        assert resp.status_code == 409

    def test_start_response_has_portfolio_shape(self, client, auth_headers):
        """
        A successful start returns a PortfolioStatusResponse.
        We mock both ``load_bot_config`` and ``start_portfolio`` so no real
        threads are created.
        """
        fake_status = {
            "running":       True,
            "alive_slots":   1,
            "total_slots":   1,
            "crashed_slots": 0,
            "total_trades":  0,
            "started_at":    "2026-04-17T12:00:00",
            "uptime_s":      0.1,
            "slots":         [
                {
                    "index":       0,
                    "name":        "mean_reversion",
                    "pairs":       ["BTC/USDT"],
                    "capital_pct": 100.0,
                    "mode":        "paper",
                    "running":     True,
                    "crashed":     False,
                    "trade_count": 0,
                }
            ],
        }

        with patch("api.main.load_bot_config",            return_value=_MINIMAL_PORTFOLIO_CONFIG), \
             patch("api.portfolio_manager.is_running",     return_value=False), \
             patch("api.portfolio_manager.start_portfolio", return_value=fake_status):
            resp = client.post(
                "/api/portfolio/start",
                headers=auth_headers,
                json={"mode": "paper"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["alive_slots"] == 1
        assert isinstance(data["slots"], list)


# ── POST /api/portfolio/stop ──────────────────────────────────────────────────

@pytest.mark.api
class TestPortfolioStop:
    def test_stop_no_auth_blocked(self, client):
        assert client.post("/api/portfolio/stop").status_code == 403

    def test_stop_when_not_running_returns_409(self, client, auth_headers):
        with patch("api.portfolio_manager.is_running", return_value=False):
            resp = client.post("/api/portfolio/stop", headers=auth_headers)
        assert resp.status_code == 409

    def test_stop_returns_portfolio_status_shape(self, client, auth_headers):
        """A successful stop echoes back the final portfolio status."""
        fake_status = {
            "running":       False,
            "alive_slots":   0,
            "total_slots":   1,
            "crashed_slots": 0,
            "total_trades":  5,
            "slots":         [],
        }
        with patch("api.portfolio_manager.is_running",     return_value=True), \
             patch("api.portfolio_manager.stop_portfolio", return_value=fake_status):
            resp = client.post("/api/portfolio/stop", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["total_trades"] == 5
