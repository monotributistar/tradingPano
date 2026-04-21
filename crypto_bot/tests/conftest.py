"""
crypto_bot/tests/conftest.py
============================
Shared fixtures for strategy unit tests.

All fixtures create synthetic OHLCV DataFrames — no network required.

Usage:
    def test_something(uptrend_candles):
        strategy.on_candle("BTC/USDT", uptrend_candles, position=None)
"""

import numpy as np
import pandas as pd
import pytest


# ── Core candle factory ───────────────────────────────────────────────────────

def make_candles(
    n: int = 200,
    start_price: float = 100.0,
    trend: float = 0.0,
    noise: float = 0.5,
    volume: float = 1000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Create a synthetic OHLCV DataFrame for testing.

    Args:
        n:           Number of bars.
        start_price: Initial close price.
        trend:       Price change per bar (positive = uptrend, negative = downtrend).
        noise:       Standard deviation of random noise per bar.
        volume:      Average volume per bar.
        seed:        Random seed for reproducibility.

    Returns:
        pd.DataFrame with columns: open, high, low, close, volume
        Index is a UTC DatetimeIndex at 1h frequency.
    """
    rng = np.random.default_rng(seed)
    prices = [start_price]
    for _ in range(n - 1):
        prices.append(max(0.01, prices[-1] + trend + rng.normal(0, noise)))
    prices = np.array(prices)

    df = pd.DataFrame({
        "open":   prices * (1 - rng.uniform(0, 0.002, n)),
        "high":   prices * (1 + rng.uniform(0.001, 0.006, n)),
        "low":    prices * (1 - rng.uniform(0.001, 0.006, n)),
        "close":  prices,
        "volume": rng.uniform(volume * 0.5, volume * 1.5, n),
    })
    # Ensure OHLC consistency
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"]  = df[["open", "low",  "close"]].min(axis=1)
    return df


# ── Standard fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def flat_candles() -> pd.DataFrame:
    """200 bars: no trend, minimal noise. Good for HOLD / neutral tests."""
    return make_candles(n=200, trend=0.0, noise=0.05, seed=1)


@pytest.fixture
def uptrend_candles() -> pd.DataFrame:
    """200 bars: strong uptrend (+0.3/bar). Good for BUY signal tests."""
    return make_candles(n=200, trend=0.3, noise=0.2, seed=2)


@pytest.fixture
def downtrend_candles() -> pd.DataFrame:
    """200 bars: strong downtrend (-0.3/bar). Good for SHORT signal tests."""
    return make_candles(n=200, trend=-0.3, noise=0.2, seed=3)


@pytest.fixture
def volatile_candles() -> pd.DataFrame:
    """200 bars: no trend, high noise. Good for oscillator / BB tests."""
    return make_candles(n=200, trend=0.0, noise=2.0, seed=4)


@pytest.fixture
def tiny_candles() -> pd.DataFrame:
    """10 bars only. Used to test warmup guard returns HOLD."""
    return make_candles(n=10, trend=0.0, noise=0.1, seed=5)


@pytest.fixture
def pullback_candles() -> pd.DataFrame:
    """
    200 bars: uptrend that dips in the last 10 bars.
    Useful for testing pullback / dip-buying entry conditions.
    """
    df = make_candles(n=200, trend=0.15, noise=0.1, seed=6)
    close = df["close"].values.copy()
    last_peak = close[-11]
    close[-10:] = last_peak * np.linspace(0.98, 0.96, 10)  # -2 to -4% dip
    df["close"] = close
    df["low"]   = df[["low", "close"]].min(axis=1)
    return df


@pytest.fixture
def oversold_candles() -> pd.DataFrame:
    """
    200 bars: long downtrend followed by a sharp drop.
    RSI should be low (< 30) at the end.
    """
    return make_candles(n=200, trend=-0.5, noise=0.3, seed=7)


@pytest.fixture
def overbought_candles() -> pd.DataFrame:
    """
    200 bars: long uptrend followed by a sharp spike.
    RSI should be high (> 70) at the end.
    """
    return make_candles(n=200, trend=0.6, noise=0.2, seed=8)


# ── Open position helpers ─────────────────────────────────────────────────────

@pytest.fixture
def long_position() -> dict:
    """Typical open long position dict (as passed by the engine)."""
    return {
        "side":      "long",
        "qty":       0.1,
        "avg_cost":  100.0,
        "entry_bar": 0,
        "bars_held": 5,
        "entries":   [{"price": 100.0, "qty": 0.1}],
    }


@pytest.fixture
def short_position() -> dict:
    """Typical open short position dict."""
    return {
        "side":       "short",
        "qty":        0.1,
        "avg_cost":   100.0,
        "entry_bar":  0,
        "bars_held":  5,
        "collateral": 10.0,
        "entries":    [{"price": 100.0, "qty": 0.1}],
    }
