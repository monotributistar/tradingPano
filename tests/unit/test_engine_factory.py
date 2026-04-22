"""
tests/unit/test_engine_factory.py
===================================

Unit tests for the engine factory function  create_engine(config, mode).

The factory decides which engine class to instantiate based on:
  - config["exchange"]  :  "bybit" | "oanda" | ...
  - mode                :  "paper" | "live"

All engine constructors are patched so no real connections are made.

TDD contract:
  - Written before the factory implementation (red phase).
  - The factory in engine/__init__.py must satisfy all assertions.
"""

import sys
from unittest.mock import MagicMock, patch

# Ensure oandapyV20 stubs are present (in case this module loads before
# test_oanda_engine.py registers them).
for _mod in (
    "oandapyV20",
    "oandapyV20.endpoints",
    "oandapyV20.endpoints.orders",
    "oandapyV20.endpoints.pricing",
    "oandapyV20.endpoints.accounts",
    "oandapyV20.endpoints.instruments",
    "oandapyV20.endpoints.positions",
    "oandapyV20.exceptions",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest


# ── Shared minimal configs ─────────────────────────────────────────────────────

_BYBIT_CFG = {
    "exchange": "bybit",
    "testnet":  True,
    "paper": {"initial_balance": 20, "fee_pct": 0.1},
    "risk":  {"leverage": 1.0, "use_futures": False},
}

_OANDA_CFG = {
    "exchange": "oanda",
    "oanda": {
        "environment": "practice",
        "account_id":  "test-account",
        "api_key":     "test-token",
    },
    "paper": {"initial_balance": 20, "fee_pct": 0.0},
    "risk":  {"leverage": 20.0},
}


# ─────────────────────────────────────────────────────────────────────────────
# Factory routing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEngineFactory:

    def test_paper_bybit_returns_paper_engine(self):
        """mode=paper + exchange=bybit → PaperEngine."""
        from engine import create_engine
        from engine.paper import PaperEngine
        with patch("ccxt.bybit") as mock_ccxt:
            mock_ccxt.return_value = MagicMock()
            engine = create_engine(_BYBIT_CFG, mode="paper")
        assert isinstance(engine, PaperEngine)

    def test_live_bybit_returns_live_engine(self):
        """mode=live + exchange=bybit → LiveEngine."""
        from engine import create_engine
        from engine.live import LiveEngine
        cfg = {**_BYBIT_CFG,
               "api_key": "key", "secret": "sec"}
        with patch("ccxt.bybit") as mock_ccxt:
            mock_ccxt.return_value = MagicMock()
            engine = create_engine(cfg, mode="live")
        assert isinstance(engine, LiveEngine)

    def test_paper_oanda_returns_oanda_paper_engine(self):
        """mode=paper + exchange=oanda → OandaPaperEngine."""
        from engine import create_engine
        from engine.oanda_paper import OandaPaperEngine
        with patch("ccxt.bybit") as mock_ccxt:
            mock_ccxt.return_value = MagicMock()
            engine = create_engine(_OANDA_CFG, mode="paper")
        assert isinstance(engine, OandaPaperEngine)

    def test_live_oanda_returns_oanda_engine(self):
        """mode=live + exchange=oanda → OandaEngine."""
        from engine import create_engine
        from engine.oanda import OandaEngine
        engine = create_engine(_OANDA_CFG, mode="live")
        assert isinstance(engine, OandaEngine)

    def test_default_mode_is_live(self):
        """create_engine(config) with no mode → live engine for bybit."""
        from engine import create_engine
        from engine.live import LiveEngine
        cfg = {**_BYBIT_CFG, "api_key": "k", "secret": "s"}
        with patch("ccxt.bybit") as mock_ccxt:
            mock_ccxt.return_value = MagicMock()
            engine = create_engine(cfg)
        assert isinstance(engine, LiveEngine)

    def test_exchange_name_case_insensitive(self):
        """'OANDA' should work the same as 'oanda'."""
        from engine import create_engine
        from engine.oanda import OandaEngine
        cfg = {**_OANDA_CFG, "exchange": "OANDA"}
        engine = create_engine(cfg, mode="live")
        assert isinstance(engine, OandaEngine)


# ─────────────────────────────────────────────────────────────────────────────
# Smoke: returned engines satisfy BaseEngine interface
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEngineInterface:

    def test_oanda_engine_has_market_buy(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "market_buy")

    def test_oanda_engine_has_market_sell(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "market_sell")

    def test_oanda_engine_has_short_open(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "short_open")

    def test_oanda_engine_has_short_cover(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "short_cover")

    def test_oanda_engine_has_fetch_ohlcv(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "fetch_ohlcv")

    def test_oanda_engine_has_get_price(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "get_price")

    def test_oanda_engine_has_get_balance(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "get_balance")

    def test_oanda_engine_has_get_margin_info(self):
        from engine.oanda import OandaEngine
        assert hasattr(OandaEngine, "get_margin_info")

    def test_oanda_paper_engine_has_market_buy(self):
        from engine.oanda_paper import OandaPaperEngine
        assert hasattr(OandaPaperEngine, "market_buy")

    def test_oanda_paper_engine_has_get_price(self):
        from engine.oanda_paper import OandaPaperEngine
        assert hasattr(OandaPaperEngine, "get_price")
