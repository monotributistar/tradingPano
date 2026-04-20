"""
VWAP Bounce Strategy (Mean Reversion)
- VWAP = sum(typical_price * volume) / sum(volume) over rolling window
- Upper/lower bands: VWAP ± std_mult × std(typical_price)
- BUY: price crosses below lower band AND RSI < 45 AND close > open (bounce candle)
- SELL: price crosses above VWAP midline OR RSI > 65 OR time_exit_bars exceeded
- SHORT: price crosses above upper band AND RSI > 55 AND close < open (rejection candle)
- COVER: price crosses below VWAP midline OR RSI < 35 OR time_exit_bars exceeded
- Hard stop: 1.5 × ATR from entry

Edge: mean reversion against extreme VWAP deviations — price tends to snap back.
Requires bounce/rejection candle confirmation to avoid catching falling knives.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class VWAPBounceStrategy(BaseStrategy):
    name = "vwap_bounce"
    description = "VWAP mean reversion — rebote desde bandas VWAP"
    ideal_timeframes: list = ["15m","30m","1h"]
    min_period: str = "1m"
    market_type: str = "ranging"
    trade_frequency: str = "high"
    min_liquidity: str = "high"
    suitable_timeframes: list = ['15m', '30m', '1h']
    suitable_market_conditions: list = ['ranging', 'high_vol']
    recommended_leverage: float = 3.0
    max_leverage: float = 10.0
    risk_profile: dict = {
        "stop_loss_pct":     1.5,
        "take_profit_pct":   3.0,
        "position_size_pct": 7.0,
    }


    def initialize(self, config: dict):
        self.vwap_period = config.get("vwap_period", 20)
        self.std_mult = config.get("std_mult", 2.0)
        self.rsi_period = config.get("rsi_period", 14)
        self.atr_period = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 1.5)
        self.time_exit_bars = config.get("time_exit_bars", 16)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._stop_price: Optional[float] = None
        self._bars_in_trade: int = 0

    def reset(self):
        self._stop_price = None
        self._bars_in_trade = 0

    def _atr(self, candles: pd.DataFrame) -> float:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        val = float(tr.ewm(span=self.atr_period, adjust=False).mean().iloc[-1])
        return val if val == val else 0.0

    def _rsi(self, close: pd.Series) -> float:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(span=self.rsi_period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(span=self.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi_series = 100 - (100 / (1 + rs))
        val = float(rsi_series.iloc[-1])
        return val if val == val else 50.0

    def _vwap_bands(self, candles: pd.DataFrame) -> tuple[float, float, float]:
        """Returns (vwap, upper_band, lower_band)."""
        typical = (candles["high"] + candles["low"] + candles["close"]) / 3
        volume = candles["volume"]

        tp_vol = typical * volume
        vwap_series = tp_vol.rolling(self.vwap_period).sum() / volume.rolling(self.vwap_period).sum()
        std_series = typical.rolling(self.vwap_period).std()

        vwap = float(vwap_series.iloc[-1])
        std = float(std_series.iloc[-1])

        vwap = vwap if vwap == vwap else float(typical.iloc[-1])
        std = std if std == std else 0.0

        upper = vwap + self.std_mult * std
        lower = vwap - self.std_mult * std
        return vwap, upper, lower

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = max(self.vwap_period, self.rsi_period, self.atr_period) + 10
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        open_ = candles["open"]
        price = float(close.iloc[-1])
        open_price = float(open_.iloc[-1])

        vwap, upper_band, lower_band = self._vwap_bands(candles)
        rsi = self._rsi(close)
        atr = self._atr(candles)

        # Previous bar close for cross detection
        prev_close = float(close.iloc[-2])
        prev_typical = (float(candles["high"].iloc[-2]) + float(candles["low"].iloc[-2]) + prev_close) / 3

        # Cross detection: price crossed below lower band
        crossed_below_lower = prev_close >= lower_band and price < lower_band
        # Price crossed above upper band
        crossed_above_upper = prev_close <= upper_band and price > upper_band
        # Price crossed above VWAP (for exit long)
        crossed_above_vwap = prev_close <= vwap and price > vwap
        # Price crossed below VWAP (for exit short)
        crossed_below_vwap = prev_close >= vwap and price < vwap

        bouncing = price > open_price      # green candle = bounce
        rejecting = price < open_price     # red candle = rejection

        current_side = position.get("side") if position else None

        # ── MANAGE LONG ────────────────────────────────────────────────────────
        if current_side == "long":
            self._bars_in_trade += 1

            # Hard stop
            if self._stop_price is not None and price <= self._stop_price:
                s = self._stop_price
                self._stop_price = None
                self._bars_in_trade = 0
                return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                   f"long stop hit {s:.4f}",
                                   metadata={"stop": s, "vwap": vwap, "rsi": rsi})

            # Exit: crossed above VWAP OR RSI overbought OR time exit
            time_exit = self._bars_in_trade >= self.time_exit_bars
            if crossed_above_vwap or rsi > 65 or time_exit:
                reason = ("vwap cross" if crossed_above_vwap
                          else "rsi overbought" if rsi > 65
                          else f"time exit bar {self._bars_in_trade}")
                self._stop_price = None
                self._bars_in_trade = 0
                return TradeSignal(Signal.SELL, pair, price, 0,
                                   f"long exit: {reason} RSI={rsi:.1f} VWAP={vwap:.4f}",
                                   metadata={"vwap": vwap, "rsi": rsi, "reason": reason})

        # ── MANAGE SHORT ───────────────────────────────────────────────────────
        elif current_side == "short":
            self._bars_in_trade += 1

            # Hard stop (above entry)
            if self._stop_price is not None and price >= self._stop_price:
                s = self._stop_price
                self._stop_price = None
                self._bars_in_trade = 0
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short stop hit {s:.4f}",
                                   metadata={"stop": s, "vwap": vwap, "rsi": rsi})

            # Cover: crossed below VWAP OR RSI oversold OR time exit
            time_exit = self._bars_in_trade >= self.time_exit_bars
            if crossed_below_vwap or rsi < 35 or time_exit:
                reason = ("vwap cross" if crossed_below_vwap
                          else "rsi oversold" if rsi < 35
                          else f"time exit bar {self._bars_in_trade}")
                self._stop_price = None
                self._bars_in_trade = 0
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short exit: {reason} RSI={rsi:.1f} VWAP={vwap:.4f}",
                                   metadata={"vwap": vwap, "rsi": rsi, "reason": reason})

        # ── NO POSITION: look for entry ────────────────────────────────────────
        else:
            self._stop_price = None
            self._bars_in_trade = 0

            # LONG: price crosses below lower band + RSI < 45 + bounce candle
            if crossed_below_lower and rsi < 45 and bouncing:
                stop = price - self.stop_atr_mult * atr
                self._stop_price = stop
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"VWAP bounce BUY: price={price:.4f} lower={lower_band:.4f} RSI={rsi:.1f}",
                    confidence=min(1.0, (lower_band - price) / (atr + 1e-10)),
                    metadata={"vwap": vwap, "lower_band": lower_band, "upper_band": upper_band,
                               "rsi": rsi, "atr": atr, "stop": stop}
                )

            # SHORT: price crosses above upper band + RSI > 55 + rejection candle
            if crossed_above_upper and rsi > 55 and rejecting:
                stop = price + self.stop_atr_mult * atr
                self._stop_price = stop
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"VWAP bounce SHORT: price={price:.4f} upper={upper_band:.4f} RSI={rsi:.1f}",
                    confidence=min(1.0, (price - upper_band) / (atr + 1e-10)),
                    metadata={"vwap": vwap, "lower_band": lower_band, "upper_band": upper_band,
                               "rsi": rsi, "atr": atr, "stop": stop}
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold VWAP={vwap:.4f} RSI={rsi:.1f} upper={upper_band:.4f} lower={lower_band:.4f}",
                           metadata={"vwap": vwap, "upper_band": upper_band,
                                     "lower_band": lower_band, "rsi": rsi})

    def get_params(self) -> dict:
        return {
            "vwap_period": self.vwap_period,
            "std_mult": self.std_mult,
            "rsi_period": self.rsi_period,
            "atr_period": self.atr_period,
            "stop_atr_mult": self.stop_atr_mult,
            "time_exit_bars": self.time_exit_bars,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "vwap_period": [14, 20, 30],
            "std_mult": [1.5, 2.0, 2.5],
            "stop_atr_mult": [1.0, 1.5, 2.0],
            "time_exit_bars": [10, 16, 24],
        }

    def save_state(self) -> dict:
        return {
            "stop_price": self._stop_price,
            "bars_in_trade": self._bars_in_trade,
        }

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
        self._bars_in_trade = state.get("bars_in_trade", 0)
