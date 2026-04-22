"""
tests/unit/test_oanda_swap.py
==============================

Unit tests for swap / overnight-financing accrual on OandaEngine.

Tests the new `accrue_swap(instrument)` method that reads the `financing`
field from OANDA's PositionDetails endpoint and accumulates it in
`_swap_accrual`.

All tests use the same sys.modules stub pattern as test_oanda_engine.py.
The oandapyV20 library is fully mocked — no network calls.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

# ── Stub oandapyV20 before importing the engine ────────────────────────────────

_oanda_stub       = sys.modules.get("oandapyV20",                        MagicMock())
_orders_stub      = sys.modules.get("oandapyV20.endpoints.orders",       MagicMock())
_pricing_stub     = sys.modules.get("oandapyV20.endpoints.pricing",      MagicMock())
_accounts_stub    = sys.modules.get("oandapyV20.endpoints.accounts",     MagicMock())
_instruments_stub = sys.modules.get("oandapyV20.endpoints.instruments",  MagicMock())
_positions_stub   = sys.modules.get("oandapyV20.endpoints.positions",    MagicMock())
_exceptions_stub  = sys.modules.get("oandapyV20.exceptions",             MagicMock())

class _FakeV20Error(Exception):
    pass

_exceptions_stub.V20Error = _FakeV20Error

sys.modules.setdefault("oandapyV20",                       _oanda_stub)
sys.modules.setdefault("oandapyV20.endpoints.orders",      _orders_stub)
sys.modules.setdefault("oandapyV20.endpoints.pricing",     _pricing_stub)
sys.modules.setdefault("oandapyV20.endpoints.accounts",    _accounts_stub)
sys.modules.setdefault("oandapyV20.endpoints.instruments", _instruments_stub)
sys.modules.setdefault("oandapyV20.endpoints.positions",   _positions_stub)
sys.modules.setdefault("oandapyV20.exceptions",            _exceptions_stub)

# ── Helpers ───────────────────────────────────────────────────────────────────

_CFG = {
    "oanda": {"environment": "practice", "account_id": "test-acct", "api_key": "tok"},
    "risk":  {"leverage": 20.0},
}


def _make_engine():
    import engine.oanda as _m
    _m.v20_pricing.PricingInfo.reset_mock()
    _m.v20_accounts.AccountSummary.reset_mock()
    _m.v20_orders.OrderCreate.reset_mock()
    _m.v20_instruments.InstrumentsCandles.reset_mock()

    _oanda_stub.API.return_value = MagicMock()
    return _m.OandaEngine(_CFG)


def _set_price(engine, price: float) -> None:
    """Configure the mocked OANDA pricing response for get_price() calls."""
    import engine.oanda as _m
    _m.v20_pricing.PricingInfo.return_value = MagicMock()
    engine.client.request.return_value = {
        "prices": [{"bids": [{"price": str(price)}],
                    "asks": [{"price": str(price)}]}]
    }


# ── accrue_swap method presence ───────────────────────────────────────────────

@pytest.mark.unit
def test_accrue_swap_method_exists():
    e = _make_engine()
    assert hasattr(e, "accrue_swap")
    assert callable(e.accrue_swap)


# ── accrue_swap fetches from positions endpoint ────────────────────────────────

@pytest.mark.unit
def test_accrue_swap_calls_position_details():
    import engine.oanda as _m
    e = _make_engine()
    # Simulate OANDA positions response
    e.client.request.return_value = {
        "position": {"financing": "-1.25", "unrealizedPL": "0"}
    }
    e.accrue_swap("EUR_USD")
    _m.v20_positions.PositionDetails.assert_called_once()


@pytest.mark.unit
def test_accrue_swap_uses_correct_instrument():
    import engine.oanda as _m
    e = _make_engine()
    e.client.request.return_value = {
        "position": {"financing": "-0.50", "unrealizedPL": "0"}
    }
    e.accrue_swap("EUR_USD")
    call_args = _m.v20_positions.PositionDetails.call_args
    # First positional arg should be the instrument or account_id; instrument passed
    args = call_args[0]
    assert "EUR_USD" in args


@pytest.mark.unit
def test_accrue_swap_accumulates_financing():
    import engine.oanda as _m
    e = _make_engine()
    e.client.request.return_value = {
        "position": {"financing": "-1.00", "unrealizedPL": "0"}
    }
    e.accrue_swap("EUR_USD")
    e.accrue_swap("EUR_USD")
    assert e._swap_accrual.get("EUR_USD", 0.0) == pytest.approx(-2.00, abs=0.001)


@pytest.mark.unit
def test_accrue_swap_tracks_per_instrument():
    import engine.oanda as _m
    e = _make_engine()

    def _pos_response(r):
        inst = r.data if hasattr(r, "data") else None
        return {"position": {"financing": "-1.00", "unrealizedPL": "0"}}

    e.client.request.side_effect = _pos_response
    e.accrue_swap("EUR_USD")
    e.accrue_swap("GBP_USD")
    # Both instruments tracked independently
    assert "EUR_USD" in e._swap_accrual
    assert "GBP_USD" in e._swap_accrual


@pytest.mark.unit
def test_get_financing_cost_sums_all_instruments():
    import engine.oanda as _m
    e = _make_engine()
    # Manually inject accruals
    e._swap_accrual["EUR_USD"] = -1.50
    e._swap_accrual["GBP_USD"] = -0.75
    assert e.get_financing_cost() == pytest.approx(-2.25, abs=0.001)


@pytest.mark.unit
def test_get_financing_cost_initially_zero():
    e = _make_engine()
    assert e.get_financing_cost() == 0.0


# ── accrue_swap with zero financing ──────────────────────────────────────────

@pytest.mark.unit
def test_accrue_swap_zero_financing_does_not_change_total():
    import engine.oanda as _m
    e = _make_engine()
    e._swap_accrual["EUR_USD"] = -5.00
    e.client.request.return_value = {
        "position": {"financing": "0", "unrealizedPL": "0"}
    }
    e.accrue_swap("EUR_USD")
    assert e._swap_accrual["EUR_USD"] == pytest.approx(-5.00, abs=0.001)


# ── accrue_swap error handling ────────────────────────────────────────────────

@pytest.mark.unit
def test_accrue_swap_engine_error_does_not_crash():
    """If positions endpoint fails, accrual is skipped but engine keeps running."""
    import engine.oanda as _m
    e = _make_engine()
    e.client.request.side_effect = RuntimeError("Connection reset")
    # should not raise
    e.accrue_swap("EUR_USD")
    # accrual should remain at 0 (unchanged)
    assert e._swap_accrual.get("EUR_USD", 0.0) == 0.0


@pytest.mark.unit
def test_accrue_swap_missing_financing_field_treated_as_zero():
    """Positions response without 'financing' field → treat as 0, don't crash."""
    import engine.oanda as _m
    e = _make_engine()
    e.client.request.return_value = {
        "position": {"unrealizedPL": "0"}  # no financing field
    }
    e._swap_accrual["EUR_USD"] = -3.00
    e.accrue_swap("EUR_USD")
    # No change — financing defaults to 0.0
    assert e._swap_accrual["EUR_USD"] == pytest.approx(-3.00, abs=0.001)
