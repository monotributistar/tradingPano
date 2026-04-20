"""
Trend Following Long/Short (Futuros)
- LONG cuando la tendencia es alcista (EMA cruce + ADX fuerte + precio > EMA200)
- SHORT cuando la tendencia es bajista (EMA cruce hacia abajo + ADX fuerte + precio < EMA200)
- Stops con ATR en ambas direcciones
- Sin posición en mercados laterales (ADX bajo)

Esta es la versión long/short de trend_following.py que ganó +4.3% en spot.
Con shorts habilitados puede ganar también cuando el mercado baja.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class TrendFollowingLSStrategy(BaseStrategy):
    name = "trend_following_ls"
    description = "Trend following long/short con futuros — opera en ambas direcciones"
    ideal_timeframes: list = ["4h","1d","1w"]
    min_period: str = "6m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "high"
    suitable_timeframes: list = ['4h', '8h', '1d', '1w']
    suitable_market_conditions: list = ['trending']
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     3.0,
        "take_profit_pct":   8.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.fast_ema = config.get("fast_ema", 21)
        self.slow_ema = config.get("slow_ema", 55)
        self.trend_ema = config.get("trend_ema", 200)
        self.adx_period = config.get("adx_period", 14)
        self.adx_threshold = config.get("adx_threshold", 20.0)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)
        self.trailing_atr_mult = config.get("trailing_atr_mult", 3.0)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._peak_price: Optional[float] = None    # for long trailing stop
        self._trough_price: Optional[float] = None  # for short trailing stop
        self._stop_price: Optional[float] = None

    def reset(self):
        self._peak_price = None
        self._trough_price = None
        self._stop_price = None

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
        return val if val == val else 0.0  # NaN guard

    def _adx(self, candles: pd.DataFrame) -> float:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        period = self.adx_period

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=candles.index)
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=candles.index)

        atr_s = tr.ewm(span=period, adjust=False).mean().replace(0, 1e-10)
        plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
        adx = float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
        return adx if adx == adx else 0.0

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = self.trend_ema + self.adx_period + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])

        ema_fast = float(close.ewm(span=self.fast_ema, adjust=False).mean().iloc[-1])
        ema_slow = float(close.ewm(span=self.slow_ema, adjust=False).mean().iloc[-1])
        ema_fast_prev = float(close.iloc[:-1].ewm(span=self.fast_ema, adjust=False).mean().iloc[-1])
        ema_slow_prev = float(close.iloc[:-1].ewm(span=self.slow_ema, adjust=False).mean().iloc[-1])
        ema_trend = float(close.ewm(span=self.trend_ema, adjust=False).mean().iloc[-1])

        adx = self._adx(candles)
        atr = self._atr(candles)

        trend_up = price > ema_trend
        trend_down = price < ema_trend
        trend_strong = adx >= self.adx_threshold

        golden_cross = ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow
        death_cross = ema_fast_prev >= ema_slow_prev and ema_fast < ema_slow

        current_side = position.get("side") if position else None

        # ── MANAGE LONG ────────────────────────────────────────────────────────
        if current_side == "long":
            if self._peak_price is None:
                self._peak_price = price
            self._peak_price = max(self._peak_price, price)

            # Hard stop
            if self._stop_price is not None and price <= self._stop_price:
                stop_hit = self._stop_price
                self._peak_price = None
                self._stop_price = None
                return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                   f"long stop {stop_hit:.2f}",
                                   metadata={"adx": adx, "atr": atr})

            # Trailing stop
            trailing = self._peak_price - self.trailing_atr_mult * atr
            if price <= trailing:
                peak = self._peak_price
                self._peak_price = None
                self._stop_price = None
                return TradeSignal(Signal.SELL, pair, price, 0,
                                   f"long trailing stop (peak={peak:.2f})",
                                   metadata={"adx": adx, "trailing": trailing})

            # Death cross or trend reversal → close long
            if death_cross or not trend_up:
                self._peak_price = None
                self._stop_price = None
                return TradeSignal(Signal.SELL, pair, price, 0,
                                   f"long exit: death_cross={death_cross} trend_up={trend_up}",
                                   metadata={"ema_fast": ema_fast, "ema_slow": ema_slow, "adx": adx})

        # ── MANAGE SHORT ───────────────────────────────────────────────────────
        elif current_side == "short":
            if self._trough_price is None:
                self._trough_price = price
            self._trough_price = min(self._trough_price, price)

            # Hard stop (for short: stop is ABOVE entry)
            if self._stop_price is not None and price >= self._stop_price:
                stop_hit = self._stop_price
                self._trough_price = None
                self._stop_price = None
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short stop {stop_hit:.2f}",
                                   metadata={"adx": adx, "atr": atr})

            # Trailing stop for short: trough + mult*ATR
            trailing = self._trough_price + self.trailing_atr_mult * atr
            if price >= trailing:
                trough = self._trough_price
                self._trough_price = None
                self._stop_price = None
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short trailing stop (trough={trough:.2f})",
                                   metadata={"adx": adx, "trailing": trailing})

            # Golden cross or trend reversal → close short
            if golden_cross or not trend_down:
                self._trough_price = None
                self._stop_price = None
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short exit: golden_cross={golden_cross} trend_down={trend_down}",
                                   metadata={"ema_fast": ema_fast, "ema_slow": ema_slow, "adx": adx})

        # ── NO POSITION: look for entry ────────────────────────────────────────
        else:
            self._peak_price = None
            self._trough_price = None

            # LONG entry
            if golden_cross and trend_up and trend_strong:
                stop_price = price - self.atr_stop_mult * atr
                self._stop_price = stop_price
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"LONG entry: golden cross ADX={adx:.1f} > EMA{self.trend_ema}",
                    confidence=min(1.0, adx / 50),
                    metadata={"ema_fast": ema_fast, "ema_slow": ema_slow,
                               "adx": adx, "atr": atr, "stop": stop_price}
                )

            # SHORT entry
            if death_cross and trend_down and trend_strong:
                stop_price = price + self.atr_stop_mult * atr
                self._stop_price = stop_price
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"SHORT entry: death cross ADX={adx:.1f} < EMA{self.trend_ema}",
                    confidence=min(1.0, adx / 50),
                    metadata={"ema_fast": ema_fast, "ema_slow": ema_slow,
                               "adx": adx, "atr": atr, "stop": stop_price}
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold adx={adx:.1f} trend_up={trend_up}",
                           metadata={"ema_fast": ema_fast, "ema_slow": ema_slow,
                                     "adx": adx, "trend_up": trend_up})

    def get_params(self) -> dict:
        return {
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "trend_ema": self.trend_ema,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "atr_period": self.atr_period,
            "atr_stop_mult": self.atr_stop_mult,
            "trailing_atr_mult": self.trailing_atr_mult,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "fast_ema": [13, 21, 34],
            "slow_ema": [34, 55, 89],
            "adx_threshold": [15.0, 20.0, 25.0],
            "atr_stop_mult": [1.5, 2.0, 2.5],
            "trailing_atr_mult": [2.5, 3.0, 4.0],
        }

    def save_state(self) -> dict:
        return {
            "peak_price": self._peak_price,
            "trough_price": self._trough_price,
            "stop_price": self._stop_price,
        }

    def load_state(self, state: dict):
        self._peak_price = state.get("peak_price")
        self._trough_price = state.get("trough_price")
        self._stop_price = state.get("stop_price")
