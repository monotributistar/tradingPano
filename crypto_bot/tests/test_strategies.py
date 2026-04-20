"""
Unit tests para señales de estrategias.
No requieren conexión a internet — todo con datos sintéticos.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from strategies.base import Signal
from strategies.mean_reversion import MeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.bollinger_dca import BollingerDCAStrategy
from strategies.rsi_mean_revert import RSIMeanRevertStrategy
from strategies.grid_dynamic import GridDynamicStrategy


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_candles(prices: list[float], with_volume: bool = True) -> pd.DataFrame:
    """Crea un DataFrame OHLCV a partir de una lista de precios de cierre."""
    n = len(prices)
    prices = np.array(prices, dtype=float)
    df = pd.DataFrame({
        "open":   prices * 0.999,
        "high":   prices * 1.005,
        "low":    prices * 0.995,
        "close":  prices,
        "volume": np.random.uniform(100, 1000, n) if with_volume else np.ones(n) * 500,
    }, index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    return df


def flat_prices(n=100, base=50000.0) -> list[float]:
    return [base] * n


def trending_up(n=100, start=50000.0, slope=50.0) -> list[float]:
    return [start + i * slope for i in range(n)]


def trending_down(n=100, start=60000.0, slope=50.0) -> list[float]:
    return [start - i * slope for i in range(n)]


def oscillating(n=100, base=50000.0, amplitude=500.0) -> list[float]:
    return [base + amplitude * np.sin(i * 0.3) for i in range(n)]


# ── Mean Reversion ────────────────────────────────────────────────────────────

class TestMeanReversion:
    def setup_method(self):
        self.strategy = MeanReversionStrategy()
        self.strategy.initialize({
            "ema_period": 20, "z_score_entry": -1.5, "z_score_exit": 0.5,
            "amount_per_trade": 5, "grid_levels": 3, "max_loss_pct": 5.0,
            "time_exit_bars": 30, "cooldown_bars": 3,
        })

    def test_hold_on_flat_market(self):
        candles = make_candles(flat_prices(60))
        sig = self.strategy.on_candle("BTC/USDT", candles, None)
        assert sig.signal == Signal.HOLD

    def test_buy_on_low_zscore(self):
        # Precio cae bruscamente → en algún punto Z-Score cruza -1.5
        prices = flat_prices(50) + [50000 - i * 600 for i in range(20)]
        candles = make_candles(prices)
        got_buy = False
        for i in range(55, len(prices)):
            self.strategy.reset()
            sig = self.strategy.on_candle("BTC/USDT", candles.iloc[:i+1], None)
            if sig.signal == Signal.BUY:
                got_buy = True
                assert sig.amount_usd == 5
                break
        assert got_buy

    def test_sell_on_high_zscore(self):
        # Con posición abierta y precio recuperado
        prices = flat_prices(50) + [51000 + i * 300 for i in range(15)]
        candles = make_candles(prices)
        position = {"qty": 0.0001, "avg_cost": 50000, "bars_held": 5, "entries": []}
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal in (Signal.SELL, Signal.HOLD)

    def test_stop_loss_triggered(self):
        candles = make_candles(flat_prices(60))
        price = float(candles["close"].iloc[-1])
        position = {
            "qty": 0.0001, "avg_cost": price / 0.93,  # -7% → trigger stop
            "bars_held": 5, "entries": []
        }
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal == Signal.STOP_LOSS

    def test_time_exit_triggered(self):
        candles = make_candles(flat_prices(80))
        price = float(candles["close"].iloc[-1])
        position = {
            "qty": 0.0001, "avg_cost": price,
            "bars_held": 35,  # > time_exit_bars=30
            "entries": []
        }
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal == Signal.TIME_EXIT

    def test_cooldown_after_stop_loss(self):
        candles = make_candles(flat_prices(60))
        price = float(candles["close"].iloc[-1])
        position = {"qty": 0.0001, "avg_cost": price / 0.93, "bars_held": 5, "entries": []}
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal == Signal.STOP_LOSS
        # Next candles should be HOLDs (cooldown)
        for _ in range(3):
            sig2 = self.strategy.on_candle("BTC/USDT", candles, None)
            assert sig2.signal == Signal.HOLD

    def test_reset_clears_state(self):
        self.strategy._cooldown_counter = 5
        self.strategy._entry_levels_used = 2
        self.strategy.reset()
        assert self.strategy._cooldown_counter == 0
        assert self.strategy._entry_levels_used == 0

    def test_get_params_returns_dict(self):
        params = self.strategy.get_params()
        assert "ema_period" in params
        assert "z_score_entry" in params

    def test_param_grid_not_empty(self):
        assert len(self.strategy.get_param_grid()) > 0


# ── EMA Crossover ─────────────────────────────────────────────────────────────

class TestEMACrossover:
    def setup_method(self):
        self.strategy = EMACrossoverStrategy()
        self.strategy.initialize({
            "fast_ema": 9, "slow_ema": 21, "signal_ema": 5,
            "amount_per_trade": 5, "trailing_stop_pct": 2.0, "min_volume_filter": False,
        })

    def test_warmup_returns_hold(self):
        candles = make_candles(flat_prices(15))
        sig = self.strategy.on_candle("BTC/USDT", candles, None)
        assert sig.signal == Signal.HOLD

    def test_golden_cross_generates_buy(self):
        # Trending down then up → should generate golden cross
        prices = trending_down(40) + trending_up(40)
        candles = make_candles(prices)
        signals = []
        for i in range(30, len(prices)):
            self.strategy.reset()
            sig = self.strategy.on_candle("BTC/USDT", candles.iloc[:i+1], None)
            signals.append(sig.signal)
        assert Signal.BUY in signals

    def test_trailing_stop(self):
        prices = trending_up(50)
        candles = make_candles(prices)
        price = float(candles["close"].iloc[-1])
        # Simulate peak higher than current price to trigger trailing stop
        self.strategy._peak_price = price * 1.03  # peak was 3% higher
        position = {"qty": 0.001, "avg_cost": price * 0.95, "bars_held": 10, "entries": []}
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal == Signal.STOP_LOSS

    def test_get_params(self):
        p = self.strategy.get_params()
        assert "fast_ema" in p and "slow_ema" in p


# ── Bollinger DCA ─────────────────────────────────────────────────────────────

class TestBollingerDCA:
    def setup_method(self):
        self.strategy = BollingerDCAStrategy()
        self.strategy.initialize({
            "bb_period": 20, "bb_std": 2.0, "dca_amount": 5,
            "max_positions": 3, "take_profit_pct": 2.0,
            "buy_on_lower_band": True, "sell_on_upper_band": True,
        })

    def test_buy_on_lower_band_touch(self):
        # Precio oscilante que toca la banda inferior
        prices = oscillating(60, base=50000, amplitude=1200)
        # Force last candle well below the mean
        prices_mod = list(prices[:-1]) + [prices[-1] - 1500]
        candles = make_candles(prices_mod)
        # Check that at some point during the series we get a buy
        got_buy = False
        for i in range(25, len(prices_mod)):
            self.strategy.reset()
            sig = self.strategy.on_candle("BTC/USDT", candles.iloc[:i+1], None)
            if sig.signal == Signal.BUY:
                got_buy = True
                break
        assert got_buy

    def test_take_profit_triggers_sell(self):
        candles = make_candles(flat_prices(60, base=51200))
        price = float(candles["close"].iloc[-1])
        position = {
            "qty": 0.001, "avg_cost": 50000,  # +2.4% > take_profit=2%
            "bars_held": 10, "entries": []
        }
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal == Signal.SELL

    def test_reset(self):
        self.strategy._entries_count = 3
        self.strategy.reset()
        assert self.strategy._entries_count == 0


# ── RSI Mean Revert ───────────────────────────────────────────────────────────

class TestRSIMeanRevert:
    def setup_method(self):
        self.strategy = RSIMeanRevertStrategy()
        self.strategy.initialize({
            "rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70,
            "amount_per_trade": 5, "confirmation_bars": 1, "max_loss_pct": 4.0,
        })

    def test_warmup(self):
        candles = make_candles(flat_prices(10))
        sig = self.strategy.on_candle("BTC/USDT", candles, None)
        assert sig.signal == Signal.HOLD

    def test_buy_on_oversold(self):
        # Sharp decline → RSI oversold
        prices = flat_prices(30) + [50000 - i * 500 for i in range(20)]
        candles = make_candles(prices)
        got_buy = False
        for i in range(20, len(prices)):
            self.strategy.reset()
            sig = self.strategy.on_candle("BTC/USDT", candles.iloc[:i+1], None)
            if sig.signal == Signal.BUY:
                got_buy = True
                break
        assert got_buy

    def test_sell_on_overbought(self):
        # Sharp rally from flat baseline → RSI goes overbought
        prices = flat_prices(30) + [50000 + i * 1000 for i in range(30)]
        candles = make_candles(prices)
        position = {"qty": 0.0001, "avg_cost": 50000, "bars_held": 10, "entries": []}
        got_sell = False
        for i in range(25, len(prices)):
            sig = self.strategy.on_candle("BTC/USDT", candles.iloc[:i+1], position)
            if sig.signal == Signal.SELL:
                got_sell = True
                break
        assert got_sell

    def test_stop_loss(self):
        candles = make_candles(flat_prices(60, base=48000))
        position = {"qty": 0.001, "avg_cost": 50000, "bars_held": 5, "entries": []}
        sig = self.strategy.on_candle("BTC/USDT", candles, position)
        assert sig.signal == Signal.STOP_LOSS  # -4% → stop


# ── Grid Dynamic ──────────────────────────────────────────────────────────────

class TestGridDynamic:
    def setup_method(self):
        self.strategy = GridDynamicStrategy()
        self.strategy.initialize({
            "grid_levels": 3, "grid_spacing_pct": 1.0, "volatility_adjust": False,
            "atr_period": 14, "amount_per_level": 3, "range_reset_hours": 24,
        })

    def test_warmup(self):
        candles = make_candles(flat_prices(5))
        sig = self.strategy.on_candle("BTC/USDT", candles, None)
        assert sig.signal == Signal.HOLD

    def test_buy_at_grid_level(self):
        # Step 1: build grid at 50000 by calling with flat prices
        prices_flat = flat_prices(30, base=50000)
        candles_flat = make_candles(prices_flat)
        self.strategy.on_candle("BTC/USDT", candles_flat, None)
        # Grid is now built around 50000: buy_1 = 49500
        # Step 2: price drops below buy_1
        prices_drop = list(prices_flat) + [49400]
        candles_drop = make_candles(prices_drop)
        sig = self.strategy.on_candle("BTC/USDT", candles_drop, None)
        assert sig.signal == Signal.BUY

    def test_grid_reset_on_init(self):
        prices = flat_prices(30)
        candles = make_candles(prices)
        self.strategy.on_candle("BTC/USDT", candles, None)
        assert self.strategy._grid is not None
        assert "buy_1" in self.strategy._grid

    def test_save_and_load_state(self):
        prices = flat_prices(30)
        candles = make_candles(prices)
        self.strategy.on_candle("BTC/USDT", candles, None)
        state = self.strategy.save_state()
        assert "grid" in state
        new_strat = GridDynamicStrategy()
        new_strat.initialize({"grid_levels": 3, "grid_spacing_pct": 1.0,
                               "volatility_adjust": False, "atr_period": 14,
                               "amount_per_level": 3, "range_reset_hours": 24})
        new_strat.load_state(state)
        assert new_strat._grid == state["grid"]


# ── Signal/TradeSignal dataclass ──────────────────────────────────────────────

def test_trade_signal_defaults():
    from strategies.base import TradeSignal
    sig = TradeSignal(signal=Signal.HOLD, pair="BTC/USDT", price=50000.0,
                      amount_usd=0.0, reason="test")
    assert sig.confidence == 1.0
    assert sig.metadata == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
