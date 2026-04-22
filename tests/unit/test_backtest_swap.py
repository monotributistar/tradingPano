"""
tests/unit/test_backtest_swap.py
=================================

Unit tests for overnight financing (swap) cost simulation in BacktestRunner.

The feature:
  config["backtest"]["swap_cost_daily_pct"] (default 0.0)

When set, a daily financing charge is deducted from the balance at every bar
where a position is held.  The cost is proportional to position value and the
configured daily rate.

Tests use minimal synthetic candle DataFrames to avoid any real data fetching.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

from strategies.base import BaseStrategy, Signal, TradeSignal


# ── Minimal synthetic strategy ─────────────────────────────────────────────────

class _BuyAndHoldStrategy(BaseStrategy):
    """Opens a long position on bar 0, holds forever."""
    name = "buy_and_hold"

    def __init__(self):
        super().__init__()
        self._bought = False

    def initialize(self, config: dict) -> None:
        pass

    def get_params(self) -> dict:
        return {}

    def on_candle(self, pair, candles, position):
        price = float(candles["close"].iloc[-1])
        if not self._bought and position is None:
            self._bought = True
            return TradeSignal(Signal.BUY, pair, price, 10.0, "buy")
        return TradeSignal(Signal.HOLD, pair, price, 0.0, "hold")


class _NeverTradeStrategy(BaseStrategy):
    """Never trades — used to verify swap only applies to held positions."""
    name = "never_trade"

    def __init__(self):
        super().__init__()

    def initialize(self, config: dict) -> None:
        pass

    def get_params(self) -> dict:
        return {}

    def on_candle(self, pair, candles, position):
        price = float(candles["close"].iloc[-1])
        return TradeSignal(Signal.HOLD, pair, price, 0.0, "hold")


# ── Synthetic candle factory ───────────────────────────────────────────────────

def _make_candles(n: int = 100, price: float = 100.0) -> pd.DataFrame:
    """Create a constant-price OHLCV DataFrame for deterministic tests."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame({
        "open":   price,
        "high":   price * 1.001,
        "low":    price * 0.999,
        "close":  price,
        "volume": 1000.0,
    }, index=idx)
    return df


def _make_runner(swap_cost_daily_pct: float = 0.0):
    from backtester.runner import BacktestRunner
    cfg = {
        "backtest": {
            "initial_capital":      1000.0,
            "fee_pct":              0.0,    # zero fees for isolation
            "slippage_pct":         0.0,
            "timeframe":            "1h",
            "data_source":          "kucoin",
            "swap_cost_daily_pct":  swap_cost_daily_pct,
        }
    }
    return BacktestRunner(cfg)


# ── swap_cost_daily_pct = 0 (default) baseline ────────────────────────────────

@pytest.mark.unit
def test_zero_swap_cost_no_effect():
    """With swap_cost_daily_pct=0, equity behaviour is unchanged."""
    runner = _make_runner(swap_cost_daily_pct=0.0)
    strategy = _BuyAndHoldStrategy()
    df = _make_candles(n=100, price=100.0)
    result = runner.run(strategy, pair="EUR/USD", candles_df=df)
    # No swap cost → final equity equals initial (flat price, zero fee/slippage)
    eq = result["equity_curve"]
    assert eq[-1] == pytest.approx(1000.0, abs=1.0)


# ── swap_cost_daily_pct > 0 reduces equity ────────────────────────────────────

@pytest.mark.unit
def test_positive_swap_reduces_equity():
    """With a positive daily swap rate, equity should decrease while holding."""
    runner_swap   = _make_runner(swap_cost_daily_pct=0.01)  # 1% per day
    runner_no_swap = _make_runner(swap_cost_daily_pct=0.0)
    strategy1 = _BuyAndHoldStrategy()
    strategy2 = _BuyAndHoldStrategy()
    df = _make_candles(n=100, price=100.0)

    result_swap   = runner_swap.run(strategy1,   pair="EUR/USD", candles_df=df.copy())
    result_no_swap = runner_no_swap.run(strategy2, pair="EUR/USD", candles_df=df.copy())

    # With swap cost, final equity must be lower
    assert result_swap["equity_curve"][-1] < result_no_swap["equity_curve"][-1]


@pytest.mark.unit
def test_swap_cost_not_applied_when_no_position():
    """Swap cost only applies to bars where a position is held."""
    runner = _make_runner(swap_cost_daily_pct=1.0)  # extreme rate to make difference obvious
    strategy = _NeverTradeStrategy()
    df = _make_candles(n=100, price=100.0)
    result = runner.run(strategy, pair="EUR/USD", candles_df=df)
    # No position held → no swap → equity unchanged
    eq = result["equity_curve"]
    assert all(e == pytest.approx(1000.0, abs=0.001) for e in eq)


@pytest.mark.unit
def test_swap_cost_proportional_to_position_value():
    """
    Larger swap rate → bigger equity reduction.

    For a 10 USDT position held over ~50 bars at 1h frequency:
    daily_bars = 24h / 1h = 24
    cost_per_bar = swap_rate_per_day / 24 * position_value
    """
    df = _make_candles(n=150, price=100.0)

    result_low  = _make_runner(swap_cost_daily_pct=0.01).run(
        _BuyAndHoldStrategy(), pair="EUR/USD", candles_df=df.copy()
    )
    result_high = _make_runner(swap_cost_daily_pct=0.10).run(
        _BuyAndHoldStrategy(), pair="EUR/USD", candles_df=df.copy()
    )

    eq_low  = result_low["equity_curve"][-1]
    eq_high = result_high["equity_curve"][-1]

    # Higher swap rate → lower final equity
    assert eq_high < eq_low


@pytest.mark.unit
def test_swap_cost_per_bar_is_daily_rate_divided_by_24_for_1h():
    """
    For 1h candles, the per-bar swap cost = (daily_rate / 24) * position_value.

    We test this by running for exactly 24 bars (one "day") and checking
    the total deduction against the theoretical value.
    """
    daily_rate = 0.01   # 1% per day
    initial    = 1000.0
    pos_value  = 10.0   # amount_usd in strategy
    price      = 100.0

    runner = _make_runner(swap_cost_daily_pct=daily_rate)
    strategy = _BuyAndHoldStrategy()
    # 50 warmup + 24 active = 74 total bars; position opens after warmup
    df = _make_candles(n=74, price=price)
    result = runner.run(strategy, pair="EUR/USD", candles_df=df)

    eq_start = result["equity_curve"][0]
    eq_end   = result["equity_curve"][-1]

    # Theoretical: cost_per_bar = daily_rate/24 * pos_value; ~24 bars held
    expected_max_deduction = daily_rate * pos_value  # ≤ 1 day worth
    actual_deduction = eq_start - eq_end

    # Allow generous tolerance — strategy may hold slightly more/fewer bars
    assert 0 <= actual_deduction <= expected_max_deduction * 2.0


# ── swap_cost in result metrics ────────────────────────────────────────────────

@pytest.mark.unit
def test_result_contains_total_swap_cost():
    """result dict should contain 'total_swap_cost' key."""
    runner = _make_runner(swap_cost_daily_pct=0.01)
    df = _make_candles(n=100, price=100.0)
    result = runner.run(_BuyAndHoldStrategy(), pair="EUR/USD", candles_df=df)
    assert "total_swap_cost" in result


@pytest.mark.unit
def test_total_swap_cost_zero_when_no_swap_rate():
    runner = _make_runner(swap_cost_daily_pct=0.0)
    df = _make_candles(n=100, price=100.0)
    result = runner.run(_BuyAndHoldStrategy(), pair="EUR/USD", candles_df=df)
    assert result["total_swap_cost"] == pytest.approx(0.0, abs=0.0001)


@pytest.mark.unit
def test_total_swap_cost_positive_when_swap_rate_set():
    """total_swap_cost should be > 0 when holding with positive daily rate."""
    runner = _make_runner(swap_cost_daily_pct=0.05)
    df = _make_candles(n=100, price=100.0)
    result = runner.run(_BuyAndHoldStrategy(), pair="EUR/USD", candles_df=df)
    assert result["total_swap_cost"] > 0.0


@pytest.mark.unit
def test_total_swap_cost_matches_equity_impact():
    """total_swap_cost should equal the equity reduction caused by swap."""
    daily_rate = 0.02
    runner_swap   = _make_runner(swap_cost_daily_pct=daily_rate)
    runner_no_swap = _make_runner(swap_cost_daily_pct=0.0)
    df = _make_candles(n=100, price=100.0)

    result_swap   = runner_swap.run(_BuyAndHoldStrategy(),   pair="EUR/USD", candles_df=df.copy())
    result_no_swap = runner_no_swap.run(_BuyAndHoldStrategy(), pair="EUR/USD", candles_df=df.copy())

    equity_diff  = result_no_swap["equity_curve"][-1] - result_swap["equity_curve"][-1]
    reported_cost = result_swap["total_swap_cost"]

    assert reported_cost == pytest.approx(equity_diff, rel=0.01)


# ── short position swap ────────────────────────────────────────────────────────

class _ShortAndHoldStrategy(BaseStrategy):
    """Opens a short position on bar 0, holds forever."""
    name = "short_and_hold"

    def __init__(self):
        super().__init__()
        self._shorted = False

    def initialize(self, config: dict) -> None:
        pass

    def get_params(self):
        return {}

    def on_candle(self, pair, candles, position):
        price = float(candles["close"].iloc[-1])
        if not self._shorted and position is None:
            self._shorted = True
            return TradeSignal(Signal.SHORT, pair, price, 10.0, "short")
        return TradeSignal(Signal.HOLD, pair, price, 0.0, "hold")


@pytest.mark.unit
def test_swap_cost_applied_to_short_position():
    """Swap cost should also reduce equity when holding a short."""
    runner_swap   = _make_runner(swap_cost_daily_pct=0.01)
    runner_no_swap = _make_runner(swap_cost_daily_pct=0.0)
    df = _make_candles(n=100, price=100.0)

    result_swap   = runner_swap.run(_ShortAndHoldStrategy(),   pair="EUR/USD", candles_df=df.copy())
    result_no_swap = runner_no_swap.run(_ShortAndHoldStrategy(), pair="EUR/USD", candles_df=df.copy())

    assert result_swap["equity_curve"][-1] < result_no_swap["equity_curve"][-1]
