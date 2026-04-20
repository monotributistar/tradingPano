"""
Breakout Strategy (Donchian Channel)
- Compra cuando el precio rompe el máximo de N barras (canal superior de Donchian)
- Solo entra si el volumen confirma el breakout (> promedio * multiplicador)
- Stop loss en el mínimo de N/2 barras
- Take profit en % fijo O trailing stop ATR

Edge: los breakouts con volumen alto tienen continuación. Evita entrar en
rangos laterales porque exige que el precio supere un máximo previo real.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class BreakoutStrategy(BaseStrategy):
    name = "breakout"
    description = "Breakout de canal Donchian con confirmación de volumen"
    ideal_timeframes: list = ["1h","4h","1d"]
    min_period: str = "2m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "medium"
    suitable_timeframes: list = ['1h', '4h', '1d']
    suitable_market_conditions: list = ['trending', 'high_vol']
    recommended_leverage: float = 3.0
    max_leverage: float = 10.0
    risk_profile: dict = {
        "stop_loss_pct":     2.5,
        "take_profit_pct":   7.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.channel_period = config.get("channel_period", 20)   # barras para máximo/mínimo
        self.vol_mult = config.get("vol_mult", 1.5)              # volumen debe ser > avg * mult
        self.vol_period = config.get("vol_period", 20)
        self.atr_period = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 2.0)
        self.take_profit_pct = config.get("take_profit_pct", 4.0)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self.trend_filter = config.get("trend_filter", True)  # solo compra en uptrend
        self.trend_ema = config.get("trend_ema", 100)
        self._stop_price: Optional[float] = None
        self._tp_price: Optional[float] = None

    def reset(self):
        self._stop_price = None
        self._tp_price = None

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

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = max(self.channel_period, self.vol_period, self.trend_ema) + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        high = candles["high"]
        low = candles["low"]
        volume = candles["volume"]
        price = float(close.iloc[-1])
        current_high = float(high.iloc[-1])

        # Donchian channel from previous bars (exclude current)
        prev_high = float(high.iloc[-(self.channel_period + 1):-1].max())
        prev_low = float(low.iloc[-(self.channel_period // 2 + 1):-1].min())

        # Volume confirmation
        avg_vol = float(volume.rolling(self.vol_period).mean().iloc[-1])
        current_vol = float(volume.iloc[-1])
        vol_confirmed = current_vol >= avg_vol * self.vol_mult

        atr = self._atr(candles, self.atr_period)

        # Trend filter
        in_uptrend = True
        if self.trend_filter:
            trend_ema = float(close.ewm(span=self.trend_ema, adjust=False).mean().iloc[-1])
            in_uptrend = price > trend_ema

        # ── EXIT logic ──
        if position is not None:
            avg_cost = position.get("avg_cost", price)

            # Hit stop loss
            if self._stop_price is not None and price <= self._stop_price:
                stop_hit = self._stop_price
                self._stop_price = None
                self._tp_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"stop loss hit at {stop_hit:.2f}",
                    metadata={"atr": atr, "stop": stop_hit}
                )

            # Hit take profit
            if self._tp_price is not None and price >= self._tp_price:
                tp_hit = self._tp_price
                self._stop_price = None
                self._tp_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"take profit hit at {tp_hit:.2f}",
                    metadata={"atr": atr, "tp": tp_hit}
                )

            # Trend reversal — exit if price drops back into channel
            if price < prev_low:
                self._stop_price = None
                self._tp_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"channel breakdown: price {price:.2f} < low {prev_low:.2f}",
                    metadata={"prev_low": prev_low, "atr": atr}
                )

        # ── ENTRY logic ──
        else:
            self._stop_price = None
            self._tp_price = None

            breakout = current_high > prev_high

            if breakout and vol_confirmed and in_uptrend:
                stop = price - self.stop_atr_mult * atr
                tp = price * (1 + self.take_profit_pct / 100)
                self._stop_price = stop
                self._tp_price = tp
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"breakout: {current_high:.2f} > {prev_high:.2f} vol={current_vol:.0f}/{avg_vol:.0f}",
                    confidence=min(1.0, (current_vol / avg_vol - 1) / 2),
                    metadata={
                        "prev_high": prev_high, "atr": atr,
                        "stop": stop, "tp": tp,
                        "vol_ratio": round(current_vol / avg_vol, 2),
                    }
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold: high={current_high:.2f} channel={prev_high:.2f} vol_ok={vol_confirmed}",
                           metadata={"prev_high": prev_high, "vol_confirmed": vol_confirmed,
                                     "in_uptrend": in_uptrend})

    def get_params(self) -> dict:
        return {
            "channel_period": self.channel_period,
            "vol_mult": self.vol_mult,
            "vol_period": self.vol_period,
            "atr_period": self.atr_period,
            "stop_atr_mult": self.stop_atr_mult,
            "take_profit_pct": self.take_profit_pct,
            "amount_per_trade": self.amount_per_trade,
            "trend_filter": self.trend_filter,
            "trend_ema": self.trend_ema,
        }

    def get_param_grid(self) -> dict:
        return {
            "channel_period": [10, 20, 30, 55],
            "vol_mult": [1.2, 1.5, 2.0],
            "stop_atr_mult": [1.5, 2.0, 2.5],
            "take_profit_pct": [3.0, 4.0, 6.0, 8.0],
            "trend_ema": [50, 100, 200],
        }

    def save_state(self) -> dict:
        return {"stop_price": self._stop_price, "tp_price": self._tp_price}

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
        self._tp_price = state.get("tp_price")
