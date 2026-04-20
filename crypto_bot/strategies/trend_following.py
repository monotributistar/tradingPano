"""
Trend Following con filtro de tendencia
- Solo opera en la dirección de la tendencia principal (EMA 200)
- Entry: precio cruza EMA rápida hacia arriba + ADX confirma tendencia fuerte
- Exit: precio cierra por debajo de EMA lenta O trailing stop
- Stop loss ajustado con ATR para respetar volatilidad

Diferencia clave vs EMA Crossover: no entra en mercados laterales (filtro ADX),
y solo compra cuando la tendencia es alcista (precio > EMA200).
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"
    description = "Sigue la tendencia principal con filtro ADX — evita mercados laterales"
    ideal_timeframes: list = ["4h","1d"]
    min_period: str = "3m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['4h', '8h', '1d']
    suitable_market_conditions: list = ['trending']
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     3.0,
        "take_profit_pct":   7.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.fast_ema = config.get("fast_ema", 21)
        self.slow_ema = config.get("slow_ema", 55)
        self.trend_ema = config.get("trend_ema", 200)   # filtro de tendencia macro
        self.adx_period = config.get("adx_period", 14)
        self.adx_threshold = config.get("adx_threshold", 20.0)  # solo entra si ADX > umbral
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)   # stop = entry - 2*ATR
        self.trailing_atr_mult = config.get("trailing_atr_mult", 3.0)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._peak_price: Optional[float] = None
        self._entry_price: Optional[float] = None
        self._stop_price: Optional[float] = None

    def reset(self):
        self._peak_price = None
        self._entry_price = None
        self._stop_price = None

    def _atr(self, candles: pd.DataFrame, period: int) -> float:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    def _adx(self, candles: pd.DataFrame, period: int) -> float:
        """Average Directional Index — mide fuerza de tendencia (no dirección)."""
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=candles.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=candles.index)

        atr_s = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-10)
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-10)

        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10))
        adx = dx.ewm(span=period, adjust=False).mean()
        return float(adx.iloc[-1])

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = self.trend_ema + self.adx_period + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])

        # Compute indicators
        ema_fast = float(close.ewm(span=self.fast_ema, adjust=False).mean().iloc[-1])
        ema_slow = float(close.ewm(span=self.slow_ema, adjust=False).mean().iloc[-1])
        ema_trend = float(close.ewm(span=self.trend_ema, adjust=False).mean().iloc[-1])
        adx = self._adx(candles, self.adx_period)
        atr = self._atr(candles, self.atr_period)

        if adx is None or atr is None or not (adx == adx) or not (atr == atr):
            return TradeSignal(Signal.HOLD, pair, price, 0, "indicator NaN")

        adx = float(adx)
        atr = float(atr)

        trend_is_up = price > ema_trend
        trend_is_strong = adx >= self.adx_threshold

        # ── EXIT logic ──
        if position is not None:
            avg_cost = position.get("avg_cost", price)

            # Update peak for trailing stop
            if self._peak_price is None:
                self._peak_price = price
            self._peak_price = max(self._peak_price, price)

            # Hard stop: entry - 2*ATR
            if self._stop_price is not None and price <= self._stop_price:
                stop_hit = self._stop_price
                self._peak_price = None
                self._stop_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"ATR stop hit at {stop_hit:.2f}",
                    metadata={"atr": atr, "adx": adx}
                )

            # Trailing stop: peak - 3*ATR
            trailing_stop = self._peak_price - self.trailing_atr_mult * atr
            if price <= trailing_stop:
                peak = self._peak_price
                self._peak_price = None
                self._stop_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"trailing stop {price:.2f} < peak {peak:.2f} - {self.trailing_atr_mult}xATR",
                    metadata={"atr": atr, "trailing_stop": trailing_stop, "peak": peak}
                )

            # Exit when fast EMA crosses below slow EMA OR trend turns down
            if ema_fast < ema_slow or not trend_is_up:
                self._peak_price = None
                self._stop_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"trend exit: fast_ema={ema_fast:.2f} slow_ema={ema_slow:.2f} above_trend={trend_is_up}",
                    metadata={"ema_fast": ema_fast, "ema_slow": ema_slow, "adx": adx}
                )

        # ── ENTRY logic ──
        else:
            self._peak_price = None

            ema_fast_prev = float(close.iloc[:-1].ewm(span=self.fast_ema, adjust=False).mean().iloc[-1])
            ema_slow_prev = float(close.iloc[:-1].ewm(span=self.slow_ema, adjust=False).mean().iloc[-1])

            golden_cross = ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow

            if golden_cross and trend_is_up and trend_is_strong:
                stop_price = price - self.atr_stop_mult * atr
                self._stop_price = stop_price
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"trend entry: golden cross + ADX={adx:.1f} + price above EMA{self.trend_ema}",
                    confidence=min(1.0, adx / 50),
                    metadata={"ema_fast": ema_fast, "ema_slow": ema_slow,
                               "adx": adx, "atr": atr, "stop": stop_price}
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold adx={adx:.1f} trend_up={trend_is_up}",
                           metadata={"ema_fast": ema_fast, "ema_slow": ema_slow,
                                     "adx": adx, "trend_up": trend_is_up})

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
            "entry_price": self._entry_price,
            "stop_price": self._stop_price,
        }

    def load_state(self, state: dict):
        self._peak_price = state.get("peak_price")
        self._entry_price = state.get("entry_price")
        self._stop_price = state.get("stop_price")
