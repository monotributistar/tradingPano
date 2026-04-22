"""
tests/unit/test_oanda_engine.py
================================

Unit tests for crypto_bot/engine/oanda.py (OandaEngine).

All tests are pure — no real network, no real credentials.
oandapyV20 is mocked at the module level so the test suite runs even
without the package installed.

TDD contract:
  - These tests define the expected behaviour of OandaEngine.
  - They are written BEFORE the implementation (red phase).
  - The implementation is expected to make all tests green.
"""

# ── Mock oandapyV20 before any engine import ───────────────────────────────────
import sys
from unittest.mock import MagicMock, patch, call

# Build a complete stub of the oandapyV20 namespace so Python's import
# machinery can resolve every sub-module that OandaEngine uses.
_oanda_stub       = MagicMock()
_endpoints_stub   = MagicMock()
_exceptions_stub  = MagicMock()

# Simulate V20Error as a real exception class so `except V20Error` works.
class _FakeV20Error(Exception):
    pass

_exceptions_stub.V20Error = _FakeV20Error

sys.modules.setdefault("oandapyV20",                     _oanda_stub)
sys.modules.setdefault("oandapyV20.endpoints",           _endpoints_stub)
sys.modules.setdefault("oandapyV20.exceptions",          _exceptions_stub)

# ── Configure endpoint stubs to preserve constructor args ─────────────────────
# The real oandapyV20 endpoint classes store their constructor kwargs so
# callers can inspect them.  We replicate that with side_effect functions
# so tests can assert on data["order"]["units"], params["granularity"] etc.

sys.modules["oandapyV20.endpoints.orders"]      = MagicMock()
sys.modules["oandapyV20.endpoints.pricing"]     = MagicMock()
sys.modules["oandapyV20.endpoints.accounts"]    = MagicMock()
sys.modules["oandapyV20.endpoints.instruments"] = MagicMock()
sys.modules["oandapyV20.endpoints.positions"]   = MagicMock()

# ── Test imports ───────────────────────────────────────────────────────────────
import os
import pytest
import pandas as pd


# Minimal config used across tests — no real credentials needed.
_CONFIG = {
    "oanda": {
        "environment": "practice",
        "account_id":  "001-001-test-001",
        "api_key":     "test-token",
    },
    "risk": {"leverage": 20.0},
}


def _make_engine():
    """Construct an OandaEngine with a fresh mock API client."""
    from engine.oanda import OandaEngine
    engine = OandaEngine(_CONFIG)
    engine.client = MagicMock()   # replace real API client
    return engine


def _last_order_data() -> dict:
    """
    Return the ``data`` dict from the most recent OrderCreate() call.

    We import engine.oanda and read its module-level ``v20_orders`` binding
    directly.  This is the exact object the engine calls, regardless of any
    sys.modules mutations that happened after the module was first imported.
    """
    import engine.oanda as _m
    call = _m.v20_orders.OrderCreate.call_args
    assert call is not None, "OrderCreate was never called"
    return call[1]["data"]


def _last_candles_params() -> dict:
    """
    Return the ``params`` dict from the most recent InstrumentsCandles() call.
    """
    import engine.oanda as _m
    call = _m.v20_instruments.InstrumentsCandles.call_args
    assert call is not None, "InstrumentsCandles was never called"
    return call[1]["params"]


def _fill_response(price: str = "1.08500", units: int = 1000,
                   order_id: str = "42", financing: str = "0") -> dict:
    """Helper: OANDA orderFillTransaction response payload."""
    return {
        "orderFillTransaction": {
            "price":      price,
            "units":      str(units),
            "id":         order_id,
            "financing":  financing,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Static helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPairNormalization:
    def test_slash_to_underscore(self):
        from engine.oanda import OandaEngine
        assert OandaEngine._to_instrument("EUR/USD") == "EUR_USD"

    def test_already_uppercase(self):
        from engine.oanda import OandaEngine
        assert OandaEngine._to_instrument("gbp/jpy") == "GBP_JPY"

    def test_gold_cfd(self):
        from engine.oanda import OandaEngine
        assert OandaEngine._to_instrument("XAU/USD") == "XAU_USD"

    def test_instrument_to_pair(self):
        from engine.oanda import OandaEngine
        assert OandaEngine._to_pair("EUR_USD") == "EUR/USD"

    def test_roundtrip(self):
        from engine.oanda import OandaEngine
        pair = "GBP/JPY"
        assert OandaEngine._to_pair(OandaEngine._to_instrument(pair)) == pair


# ─────────────────────────────────────────────────────────────────────────────
# 2. Constructor / credential validation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestConstructor:
    def test_raises_without_api_key(self):
        from engine.oanda import OandaEngine
        with pytest.raises(ValueError, match="OANDA credentials"):
            OandaEngine({"oanda": {"account_id": "001"}, "risk": {}})

    def test_raises_without_account_id(self):
        from engine.oanda import OandaEngine
        with pytest.raises(ValueError, match="OANDA credentials"):
            OandaEngine({"oanda": {"api_key": "tok"}, "risk": {}})

    def test_accepts_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("OANDA_API_KEY",     "env-token")
        monkeypatch.setenv("OANDA_ACCOUNT_ID",  "env-account")
        monkeypatch.setenv("OANDA_ENVIRONMENT", "practice")
        from engine.oanda import OandaEngine
        engine = OandaEngine({"oanda": {}, "risk": {}})
        assert engine.account_id == "env-account"

    def test_default_leverage_is_20(self):
        engine = _make_engine()
        assert engine.leverage == 20.0

    def test_custom_leverage_respected(self):
        from engine.oanda import OandaEngine
        cfg = {**_CONFIG, "risk": {"leverage": 5.0}}
        engine = OandaEngine(cfg)
        engine.client = MagicMock()
        assert engine.leverage == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Unit calculation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestUnitCalculation:
    def test_usdt_to_units_basic(self):
        engine = _make_engine()
        # $100 at price 1.085, leverage 20x → 100*20/1.085 ≈ 1843 units
        with patch.object(engine, "get_price", return_value=1.085):
            units = engine._usdt_to_units("EUR_USD", 100.0)
        assert units == int(100.0 * 20.0 / 1.085)

    def test_usdt_to_units_minimum_one(self):
        engine = _make_engine()
        with patch.object(engine, "get_price", return_value=100_000.0):
            units = engine._usdt_to_units("BTC_USD", 0.001)
        assert units >= 1

    def test_usdt_to_units_returns_int(self):
        engine = _make_engine()
        with patch.object(engine, "get_price", return_value=1.5):
            units = engine._usdt_to_units("GBP_USD", 50.0)
        assert isinstance(units, int)


# ─────────────────────────────────────────────────────────────────────────────
# 4. get_price
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetPrice:
    def _setup_pricing(self, engine, bid: str, ask: str):
        engine.client.request.return_value = {
            "prices": [{
                "bids": [{"price": bid}],
                "asks": [{"price": ask}],
            }]
        }

    def test_returns_mid_price(self):
        engine = _make_engine()
        self._setup_pricing(engine, bid="1.08400", ask="1.08600")
        price = engine.get_price("EUR/USD")
        assert price == pytest.approx(1.085, abs=1e-5)

    def test_uses_first_bid_ask_level(self):
        engine = _make_engine()
        self._setup_pricing(engine, bid="1.10000", ask="1.10020")
        price = engine.get_price("GBP/USD")
        assert price == pytest.approx(1.1001, abs=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# 5. get_balance
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetBalance:
    def _setup_account(self, engine, balance="500.00", nav="520.00",
                       unrealized="20.00", margin_used="100.00",
                       margin_avail="400.00"):
        engine.client.request.return_value = {
            "account": {
                "balance":            balance,
                "NAV":                nav,
                "unrealizedPL":       unrealized,
                "marginUsed":         margin_used,
                "marginAvailable":    margin_avail,
            }
        }

    def test_returns_usdt_balance(self):
        engine = _make_engine()
        self._setup_account(engine, balance="500.00")
        bal = engine.get_balance()
        assert bal["USDT"] == pytest.approx(500.0)

    def test_returns_nav(self):
        engine = _make_engine()
        self._setup_account(engine, nav="520.00")
        bal = engine.get_balance()
        assert bal["nav"] == pytest.approx(520.0)

    def test_returns_margin_fields(self):
        engine = _make_engine()
        self._setup_account(engine, margin_used="100.00", margin_avail="400.00")
        bal = engine.get_balance()
        assert "margin_used"  in bal
        assert "margin_avail" in bal

    def test_margin_level_calculated(self):
        engine = _make_engine()
        # margin_level = NAV / margin_used * 100 = 500/100*100 = 500%
        self._setup_account(engine, nav="500.00", margin_used="100.00")
        bal = engine.get_balance()
        assert bal["margin_level"] == pytest.approx(500.0)

    def test_margin_level_infinity_when_no_positions(self):
        engine = _make_engine()
        self._setup_account(engine, margin_used="0.00", nav="500.00")
        bal = engine.get_balance()
        assert bal["margin_level"] == 9999.0


# ─────────────────────────────────────────────────────────────────────────────
# 6. market_buy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarketBuy:
    def test_places_positive_units(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(units=1843)
        with patch.object(engine, "get_price", return_value=1.085):
            engine.market_buy("EUR/USD", 100.0)
        assert int(_last_order_data()["order"]["units"]) > 0

    def test_returns_filled_status(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(price="1.08500")
        with patch.object(engine, "get_price", return_value=1.085):
            result = engine.market_buy("EUR/USD", 100.0)
        assert result["status"] == "filled"

    def test_returns_fill_price(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(price="1.09000")
        with patch.object(engine, "get_price", return_value=1.09):
            result = engine.market_buy("EUR/USD", 100.0)
        assert result["price"] == pytest.approx(1.09)

    def test_returns_order_id(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(order_id="777")
        with patch.object(engine, "get_price", return_value=1.085):
            result = engine.market_buy("EUR/USD", 100.0)
        assert result["order_id"] == "777"

    def test_api_error_returns_error_status(self):
        """Any exception from the REST API is caught and returned as an error dict."""
        engine = _make_engine()
        engine.client.request.side_effect = RuntimeError("Insufficient funds")
        with patch.object(engine, "get_price", return_value=1.085):
            result = engine.market_buy("EUR/USD", 100.0)
        assert result["status"] == "error"
        assert "Insufficient funds" in result["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. market_sell
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarketSell:
    def test_places_negative_units(self):
        """market_sell closes a long: must send negative units."""
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(units=-500)
        engine.market_sell("EUR/USD", 500.0)
        assert int(_last_order_data()["order"]["units"]) < 0

    def test_uses_reduce_only_fill(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response()
        engine.market_sell("EUR/USD", 100.0)
        assert _last_order_data()["order"]["positionFill"] == "REDUCE_ONLY"

    def test_returns_filled_status(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response()
        result = engine.market_sell("EUR/USD", 100.0)
        assert result["status"] == "filled"


# ─────────────────────────────────────────────────────────────────────────────
# 8. short_open
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestShortOpen:
    def test_places_negative_units(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(units=-1843)
        with patch.object(engine, "get_price", return_value=1.085):
            engine.short_open("EUR/USD", 100.0)
        assert int(_last_order_data()["order"]["units"]) < 0

    def test_returns_filled_status(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(units=-500)
        with patch.object(engine, "get_price", return_value=1.085):
            result = engine.short_open("EUR/USD", 100.0)
        assert result["status"] == "filled"

    def test_qty_is_positive_in_result(self):
        """qty in the return dict is always the absolute number of units."""
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(units=-1843)
        with patch.object(engine, "get_price", return_value=1.085):
            result = engine.short_open("EUR/USD", 100.0)
        assert result["qty"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 9. short_cover
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestShortCover:
    def test_places_positive_units(self):
        """Covering a short = buying back; units must be positive."""
        engine = _make_engine()
        engine.client.request.return_value = _fill_response(units=500)
        engine.short_cover("EUR/USD", 500.0)
        placed = engine.client.request.call_args[0][0]
        assert int(placed.data["order"]["units"]) > 0

    def test_uses_reduce_only_fill(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response()
        engine.short_cover("EUR/USD", 500.0)
        assert _last_order_data()["order"]["positionFill"] == "REDUCE_ONLY"

    def test_returns_filled_status(self):
        engine = _make_engine()
        engine.client.request.return_value = _fill_response()
        result = engine.short_cover("EUR/USD", 500.0)
        assert result["status"] == "filled"


# ─────────────────────────────────────────────────────────────────────────────
# 10. get_margin_info
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetMarginInfo:
    def test_returns_required_keys(self):
        engine = _make_engine()
        engine.client.request.return_value = {
            "account": {
                "balance": "500", "NAV": "520",
                "unrealizedPL": "20", "marginUsed": "100",
                "marginAvailable": "400",
            }
        }
        info = engine.get_margin_info()
        for key in ("margin_level", "margin_used", "margin_available", "nav"):
            assert key in info, f"Missing key: {key}"

    def test_margin_level_is_numeric(self):
        engine = _make_engine()
        engine.client.request.return_value = {
            "account": {
                "balance": "500", "NAV": "500",
                "unrealizedPL": "0", "marginUsed": "50",
                "marginAvailable": "450",
            }
        }
        info = engine.get_margin_info()
        assert isinstance(info["margin_level"], float)


# ─────────────────────────────────────────────────────────────────────────────
# 11. fetch_ohlcv
# ─────────────────────────────────────────────────────────────────────────────

def _make_candle(time: str, o: str, h: str, lo: str, c: str,
                 vol: int = 1000, complete: bool = True) -> dict:
    return {
        "time":     time,
        "complete": complete,
        "volume":   vol,
        "mid": {"o": o, "h": h, "l": lo, "c": c},
    }


@pytest.mark.unit
class TestFetchOHLCV:
    def _setup_candles(self, engine, candles: list):
        engine.client.request.return_value = {
            "instrument": "EUR_USD",
            "granularity": "H1",
            "candles": candles,
        }

    def test_returns_dataframe(self):
        engine = _make_engine()
        self._setup_candles(engine, [
            _make_candle("2026-01-01T00:00:00Z", "1.08", "1.09", "1.07", "1.085"),
            _make_candle("2026-01-01T01:00:00Z", "1.085","1.09","1.08","1.088"),
        ])
        df = engine.fetch_ohlcv("EUR/USD", "1h", limit=2)
        assert isinstance(df, pd.DataFrame)

    def test_returns_ohlcv_columns(self):
        engine = _make_engine()
        self._setup_candles(engine, [
            _make_candle("2026-01-01T00:00:00Z", "1.08", "1.09", "1.07", "1.085"),
        ])
        df = engine.fetch_ohlcv("EUR/USD", "1h", limit=1)
        for col in ("open", "high", "low", "close", "volume"):
            assert col in df.columns, f"Missing column: {col}"

    def test_filters_incomplete_candles(self):
        engine = _make_engine()
        self._setup_candles(engine, [
            _make_candle("2026-01-01T00:00:00Z", "1.08","1.09","1.07","1.085", complete=True),
            _make_candle("2026-01-01T01:00:00Z", "1.085","1.09","1.08","1.088", complete=False),
        ])
        df = engine.fetch_ohlcv("EUR/USD", "1h", limit=2)
        assert len(df) == 1   # incomplete candle is excluded

    def test_empty_response_returns_empty_dataframe(self):
        engine = _make_engine()
        self._setup_candles(engine, [])
        df = engine.fetch_ohlcv("EUR/USD", "1h", limit=5)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_timeframe_mapping_1h(self):
        engine = _make_engine()
        self._setup_candles(engine, [])
        engine.fetch_ohlcv("EUR/USD", "1h", limit=1)
        assert _last_candles_params()["granularity"] == "H1"

    def test_timeframe_mapping_4h(self):
        engine = _make_engine()
        self._setup_candles(engine, [])
        engine.fetch_ohlcv("EUR/USD", "4h", limit=1)
        assert _last_candles_params()["granularity"] == "H4"

    def test_timeframe_mapping_1d(self):
        engine = _make_engine()
        self._setup_candles(engine, [])
        engine.fetch_ohlcv("EUR/USD", "1d", limit=1)
        assert _last_candles_params()["granularity"] == "D"

    def test_limit_capped_at_5000(self):
        engine = _make_engine()
        self._setup_candles(engine, [])
        engine.fetch_ohlcv("EUR/USD", "1h", limit=99999)
        assert _last_candles_params()["count"] <= 5000


# ─────────────────────────────────────────────────────────────────────────────
# 12. Financing / swap accumulation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFinancingCost:
    def test_starts_at_zero(self):
        engine = _make_engine()
        assert engine.get_financing_cost() == 0.0

    def test_accumulates_financing_from_orders(self):
        """Each fill response includes a financing field that should accumulate."""
        engine = _make_engine()
        # Two BUY orders with -0.50 financing each
        engine.client.request.return_value = _fill_response(financing="-0.50")
        with patch.object(engine, "get_price", return_value=1.085):
            engine.market_buy("EUR/USD", 100.0)
            engine.market_buy("EUR/USD", 100.0)
        # Financing is tracked internally — 2 × (-0.50) = -1.00
        assert engine.get_financing_cost() == pytest.approx(-1.0, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 13. BaseEngine default implementations
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestBaseEngineDefaults:
    """
    Verify the default (no-op) implementations added to BaseEngine.
    These ensure existing engines (PaperEngine, LiveEngine) don't break.
    """

    def _concrete_engine(self):
        """Minimal concrete subclass — only implements the abstract methods."""
        from engine.base import BaseEngine
        import pandas as pd

        class _MinimalEngine(BaseEngine):
            def get_price(self, pair):           return 1.0
            def get_balance(self):               return {"USDT": 100.0}
            def market_buy(self, pair, amount):  return {"status": "ok"}
            def market_sell(self, pair, qty):    return {"status": "ok"}
            def fetch_ohlcv(self, pair, tf, limit=100): return pd.DataFrame()

        return _MinimalEngine()

    def test_default_short_open_returns_unsupported(self):
        eng = self._concrete_engine()
        result = eng.short_open("EUR/USD", 100.0)
        assert result.get("status") == "unsupported"

    def test_default_short_cover_returns_unsupported(self):
        eng = self._concrete_engine()
        result = eng.short_cover("EUR/USD", 500.0)
        assert result.get("status") == "unsupported"

    def test_default_get_margin_info_returns_dict(self):
        eng = self._concrete_engine()
        info = eng.get_margin_info()
        assert isinstance(info, dict)

    def test_default_get_financing_cost_returns_zero(self):
        eng = self._concrete_engine()
        assert eng.get_financing_cost() == 0.0
