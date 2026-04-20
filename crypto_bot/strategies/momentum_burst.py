"""
Momentum Burst Strategy — captura explosiones de precio con volumen

Edge: cuando una vela cierra con un movimiento brusco >1.5% Y el volumen duplica
la media, hay alta probabilidad de continuación en esa dirección (al menos 1-2 velas).
Opera LONG en explosiones alcistas y SHORT en explosiones bajistas.
Trailing stop de 1×ATR desde el pico/valle, o cierre por tiempo (12 barras).
RSI como filtro de sobrecompra/sobreventa para salidas adelantadas.
"""
from typing import Optional

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class MomentumBurstStrategy(BaseStrategy):
    name = "momentum_burst"
    description = "Captura explosiones de precio — long/short en ambas direcciones"
    ideal_timeframes: list = ["15m","30m","1h"]
    min_period: str = "2w"
    market_type: str = "trending"
    trade_frequency: str = "high"
    min_liquidity: str = "medium"
    suitable_timeframes: list = ['15m', '30m', '1h']
    suitable_market_conditions: list = ['trending', 'high_vol']
    recommended_leverage: float = 4.0
    max_leverage: float = 12.0
    risk_profile: dict = {
        "stop_loss_pct":     1.5,
        "take_profit_pct":   4.5,
        "position_size_pct": 6.0,
    }


    def initialize(self, config: dict):
        self.surge_pct = config.get("surge_pct", 1.5)          # % mínimo de movimiento en 1 vela
        self.vol_mult = config.get("vol_mult", 2.0)             # volumen debe ser > avg * mult
        self.rsi_period = config.get("rsi_period", 14)
        self.atr_period = config.get("atr_period", 14)
        self.trailing_atr_mult = config.get("trailing_atr_mult", 1.0)
        self.stop_atr_mult = config.get("stop_atr_mult", 2.0)
        self.time_exit_bars = config.get("time_exit_bars", 12)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)

        self._stop_price: Optional[float] = None    # hard stop from entry
        self._peak_price: Optional[float] = None    # trailing peak for LONG
        self._trough_price: Optional[float] = None  # trailing trough for SHORT
        self._direction: Optional[str] = None       # "long" or "short"

    def reset(self):
        self._stop_price = None
        self._peak_price = None
        self._trough_price = None
        self._direction = None

    # ── Indicators ──────────────────────────────────────────────────────────────

    def _rsi(self, close: pd.Series, period: int) -> float:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        val = float(rsi.iloc[-1])
        return val if val == val else 50.0

    def _atr(self, candles: pd.DataFrame, period: int) -> float:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        val = float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
        return val if val == val else 0.0

    # ── Main ────────────────────────────────────────────────────────────────────

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        vol_period = 20
        needed = max(self.rsi_period, self.atr_period, vol_period) + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        high = candles["high"]
        low = candles["low"]
        volume = candles["volume"]

        price = float(close.iloc[-1])
        open_price = float(candles["open"].iloc[-1])
        atr = self._atr(candles, self.atr_period)
        rsi = self._rsi(close, self.rsi_period)

        avg_vol = float(volume.rolling(vol_period).mean().iloc[-2])  # exclude current bar
        avg_vol = avg_vol if avg_vol == avg_vol and avg_vol > 0 else 1.0
        current_vol = float(volume.iloc[-1])
        vol_burst = current_vol >= avg_vol * self.vol_mult

        candle_change_pct = (price - open_price) / open_price * 100 if open_price != 0 else 0.0

        # ── EXIT LONG ───────────────────────────────────────────────────────────
        if position is not None and self._direction == "long":
            bars_held = position.get("bars_held", 0)

            # Update trailing peak
            if self._peak_price is None or price > self._peak_price:
                self._peak_price = price
                # Update trailing stop
                trailing_stop = self._peak_price - self.trailing_atr_mult * atr
                # Don't lower the trailing stop
                if self._stop_price is None or trailing_stop > self._stop_price:
                    self._stop_price = trailing_stop

            # Hard/trailing stop
            if self._stop_price is not None and price <= self._stop_price:
                sp = self._stop_price
                self._reset_state()
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"long stop at {sp:.4f} (trailing from peak {self._peak_price})",
                    metadata={"stop": sp, "atr": atr, "rsi": rsi}
                )

            # RSI overbought exit
            if rsi > 75:
                self._reset_state()
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"long RSI overbought: rsi={rsi:.1f}",
                    metadata={"rsi": rsi}
                )

            # Time exit
            if bars_held >= self.time_exit_bars:
                self._reset_state()
                return TradeSignal(
                    Signal.TIME_EXIT, pair, price, 0,
                    f"long time exit after {bars_held} bars",
                    metadata={"bars_held": bars_held}
                )

        # ── EXIT SHORT ──────────────────────────────────────────────────────────
        elif position is not None and self._direction == "short":
            bars_held = position.get("bars_held", 0)

            # Update trailing trough
            if self._trough_price is None or price < self._trough_price:
                self._trough_price = price
                trailing_stop = self._trough_price + self.trailing_atr_mult * atr
                if self._stop_price is None or trailing_stop < self._stop_price:
                    self._stop_price = trailing_stop

            # Hard/trailing stop
            if self._stop_price is not None and price >= self._stop_price:
                sp = self._stop_price
                self._reset_state()
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"short stop at {sp:.4f}",
                    metadata={"stop": sp, "atr": atr, "rsi": rsi}
                )

            # RSI oversold exit (cover)
            if rsi < 25:
                self._reset_state()
                return TradeSignal(
                    Signal.COVER, pair, price, 0,
                    f"short RSI oversold: rsi={rsi:.1f}",
                    metadata={"rsi": rsi}
                )

            # Time exit
            if bars_held >= self.time_exit_bars:
                self._reset_state()
                return TradeSignal(
                    Signal.TIME_EXIT, pair, price, 0,
                    f"short time exit after {bars_held} bars",
                    metadata={"bars_held": bars_held}
                )

        # ── ENTRY ───────────────────────────────────────────────────────────────
        elif position is None:
            self._reset_state()

            if vol_burst and abs(candle_change_pct) >= self.surge_pct:
                if candle_change_pct > 0:
                    # Bullish burst → LONG
                    self._direction = "long"
                    self._peak_price = price
                    self._stop_price = price - self.stop_atr_mult * atr
                    return TradeSignal(
                        Signal.BUY, pair, price, self.amount_per_trade,
                        f"momentum burst LONG: +{candle_change_pct:.2f}% vol={current_vol:.0f}/{avg_vol:.0f}",
                        confidence=min(1.0, abs(candle_change_pct) / (self.surge_pct * 2)),
                        metadata={
                            "candle_pct": round(candle_change_pct, 3),
                            "vol_ratio": round(current_vol / avg_vol, 2),
                            "atr": atr, "stop": self._stop_price,
                        }
                    )
                else:
                    # Bearish burst → SHORT
                    self._direction = "short"
                    self._trough_price = price
                    self._stop_price = price + self.stop_atr_mult * atr
                    return TradeSignal(
                        Signal.SHORT, pair, price, self.amount_per_trade,
                        f"momentum burst SHORT: {candle_change_pct:.2f}% vol={current_vol:.0f}/{avg_vol:.0f}",
                        confidence=min(1.0, abs(candle_change_pct) / (self.surge_pct * 2)),
                        metadata={
                            "candle_pct": round(candle_change_pct, 3),
                            "vol_ratio": round(current_vol / avg_vol, 2),
                            "atr": atr, "stop": self._stop_price,
                        }
                    )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold: change={candle_change_pct:.2f}% vol_burst={vol_burst} rsi={rsi:.1f}",
            metadata={"candle_pct": round(candle_change_pct, 3), "vol_burst": vol_burst, "rsi": rsi}
        )

    def _reset_state(self):
        self._stop_price = None
        self._peak_price = None
        self._trough_price = None
        self._direction = None

    def get_params(self) -> dict:
        return {
            "surge_pct": self.surge_pct,
            "vol_mult": self.vol_mult,
            "rsi_period": self.rsi_period,
            "atr_period": self.atr_period,
            "trailing_atr_mult": self.trailing_atr_mult,
            "stop_atr_mult": self.stop_atr_mult,
            "time_exit_bars": self.time_exit_bars,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "surge_pct": [1.0, 1.5, 2.0, 2.5],
            "vol_mult": [1.5, 2.0, 2.5, 3.0],
            "trailing_atr_mult": [0.5, 1.0, 1.5],
            "stop_atr_mult": [1.5, 2.0, 2.5],
            "time_exit_bars": [8, 12, 16],
        }

    def save_state(self) -> dict:
        return {
            "stop_price": self._stop_price,
            "peak_price": self._peak_price,
            "trough_price": self._trough_price,
            "direction": self._direction,
        }

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
        self._peak_price = state.get("peak_price")
        self._trough_price = state.get("trough_price")
        self._direction = state.get("direction")
