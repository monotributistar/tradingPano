"""
Stochastic RSI + EMA Trend Filter Strategy
- Stochastic RSI: apply Stochastic formula on top of RSI values
- %K = ((RSI - min_RSI) / (max_RSI - min_RSI)) × 100
- %D = SMA(smooth_k) of %K
- BUY:  %K crosses above %D, both < 20 (oversold), price > EMA(ema_trend)
- SELL: %K crosses below %D and both > 80 (overbought) OR time_exit_bars exceeded
- SHORT: %K crosses below %D, both > 80 (overbought), price < EMA(ema_trend)
- COVER: %K crosses above %D and both < 20 (oversold) OR time_exit_bars exceeded
- Stop loss: 2×ATR from entry

Edge: Stochastic RSI is more sensitive than plain RSI, giving earlier overbought/
oversold readings. The EMA trend filter ensures mean-reversion signals align with
the broader trend direction.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class StochRSIStrategy(BaseStrategy):
    name = "stoch_rsi"
    description = "Stochastic RSI con filtro de tendencia EMA"
    ideal_timeframes: list = ["1h","4h"]
    min_period: str = "1m"
    market_type: str = "both"
    trade_frequency: str = "medium"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h']
    suitable_market_conditions: list = ['both']
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   4.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.rsi_period = config.get("rsi_period", 14)
        self.stoch_period = config.get("stoch_period", 14)
        self.smooth_k = config.get("smooth_k", 3)
        self.ema_trend = config.get("ema_trend", 50)
        self.atr_period = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 2.0)
        self.time_exit_bars = config.get("time_exit_bars", 20)
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

    def _rsi_series(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(span=self.rsi_period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(span=self.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def _stoch_rsi(self, candles: pd.DataFrame) -> tuple[float, float, float, float]:
        """Returns (k_curr, d_curr, k_prev, d_prev)."""
        close = candles["close"]
        rsi = self._rsi_series(close)

        rsi_min = rsi.rolling(self.stoch_period).min()
        rsi_max = rsi.rolling(self.stoch_period).max()
        rsi_range = (rsi_max - rsi_min).replace(0, 1e-10)
        stoch = (rsi - rsi_min) / rsi_range
        k = stoch * 100
        d = k.rolling(self.smooth_k).mean()

        k_curr = float(k.iloc[-1])
        d_curr = float(d.iloc[-1])
        k_prev = float(k.iloc[-2])
        d_prev = float(d.iloc[-2])

        k_curr = k_curr if k_curr == k_curr else 50.0
        d_curr = d_curr if d_curr == d_curr else 50.0
        k_prev = k_prev if k_prev == k_prev else 50.0
        d_prev = d_prev if d_prev == d_prev else 50.0

        return k_curr, d_curr, k_prev, d_prev

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = self.rsi_period + self.stoch_period + self.smooth_k + self.ema_trend + 10
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])

        k_curr, d_curr, k_prev, d_prev = self._stoch_rsi(candles)
        atr = self._atr(candles)
        ema = float(close.ewm(span=self.ema_trend, adjust=False).mean().iloc[-1])
        ema = ema if ema == ema else price

        uptrend = price > ema
        downtrend = price < ema

        # Crossover detection
        k_crossed_above_d = k_prev <= d_prev and k_curr > d_curr   # bullish cross
        k_crossed_below_d = k_prev >= d_prev and k_curr < d_curr   # bearish cross

        oversold = k_curr < 20 and d_curr < 20
        overbought = k_curr > 80 and d_curr > 80

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
                                   metadata={"stop": s, "k": k_curr, "d": d_curr})

            # Exit: bearish stoch cross with overbought OR time exit
            time_exit = self._bars_in_trade >= self.time_exit_bars
            if (k_crossed_below_d and overbought) or time_exit:
                reason = "stoch overbought cross" if (k_crossed_below_d and overbought) else f"time exit bar {self._bars_in_trade}"
                self._stop_price = None
                self._bars_in_trade = 0
                return TradeSignal(Signal.SELL, pair, price, 0,
                                   f"long exit: {reason} %K={k_curr:.1f} %D={d_curr:.1f}",
                                   metadata={"k": k_curr, "d": d_curr, "ema": ema})

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
                                   metadata={"stop": s, "k": k_curr, "d": d_curr})

            # Cover: bullish stoch cross with oversold OR time exit
            time_exit = self._bars_in_trade >= self.time_exit_bars
            if (k_crossed_above_d and oversold) or time_exit:
                reason = "stoch oversold cross" if (k_crossed_above_d and oversold) else f"time exit bar {self._bars_in_trade}"
                self._stop_price = None
                self._bars_in_trade = 0
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short exit: {reason} %K={k_curr:.1f} %D={d_curr:.1f}",
                                   metadata={"k": k_curr, "d": d_curr, "ema": ema})

        # ── NO POSITION: look for entry ────────────────────────────────────────
        else:
            self._stop_price = None
            self._bars_in_trade = 0

            # LONG: bullish cross + oversold + uptrend
            if k_crossed_above_d and oversold and uptrend:
                stop = price - self.stop_atr_mult * atr
                self._stop_price = stop
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"StochRSI BUY: %K={k_curr:.1f} cross %D={d_curr:.1f} oversold uptrend EMA={ema:.4f}",
                    confidence=min(1.0, (20 - k_curr) / 20),
                    metadata={"k": k_curr, "d": d_curr, "ema": ema, "atr": atr, "stop": stop}
                )

            # SHORT: bearish cross + overbought + downtrend
            if k_crossed_below_d and overbought and downtrend:
                stop = price + self.stop_atr_mult * atr
                self._stop_price = stop
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"StochRSI SHORT: %K={k_curr:.1f} cross %D={d_curr:.1f} overbought downtrend EMA={ema:.4f}",
                    confidence=min(1.0, (k_curr - 80) / 20),
                    metadata={"k": k_curr, "d": d_curr, "ema": ema, "atr": atr, "stop": stop}
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold %K={k_curr:.1f} %D={d_curr:.1f} EMA={ema:.4f} uptrend={uptrend}",
                           metadata={"k": k_curr, "d": d_curr, "ema": ema,
                                     "uptrend": uptrend, "oversold": oversold, "overbought": overbought})

    def get_params(self) -> dict:
        return {
            "rsi_period": self.rsi_period,
            "stoch_period": self.stoch_period,
            "smooth_k": self.smooth_k,
            "ema_trend": self.ema_trend,
            "atr_period": self.atr_period,
            "stop_atr_mult": self.stop_atr_mult,
            "time_exit_bars": self.time_exit_bars,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "rsi_period": [10, 14, 21],
            "stoch_period": [10, 14, 21],
            "smooth_k": [3, 5],
            "ema_trend": [34, 50, 100],
            "stop_atr_mult": [1.5, 2.0, 2.5],
            "time_exit_bars": [12, 20, 30],
        }

    def save_state(self) -> dict:
        return {
            "stop_price": self._stop_price,
            "bars_in_trade": self._bars_in_trade,
        }

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
        self._bars_in_trade = state.get("bars_in_trade", 0)
