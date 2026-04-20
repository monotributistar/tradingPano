"""
Bollinger Band Squeeze Strategy — opera la explosión tras compresión de volatilidad

Edge: cuando la volatilidad se comprime (BB muy angostas), el mercado está "cargando"
energía para un movimiento brusco. Medimos el squeeze comparando el ancho actual de las BB
contra el percentil 20 de los últimos 50 valores. Cuando el precio rompe la banda con volumen,
se abre posición en dirección del breakout. Opera LONG y SHORT.
Trailing stop de 2×ATR desde el pico/valle, o cruce del precio por la media de BB, o 20 barras.
"""
from typing import Optional

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class BBSqueezeStrategy(BaseStrategy):
    name = "bb_squeeze"
    description = "Bollinger Band squeeze — opera la explosion tras compresion de volatilidad"
    ideal_timeframes: list = ["1h","4h"]
    min_period: str = "1m"
    market_type: str = "both"
    trade_frequency: str = "medium"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h']
    suitable_market_conditions: list = ['ranging', 'high_vol']
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   4.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 2.0)
        self.squeeze_percentile = config.get("squeeze_percentile", 20)
        self.vol_mult = config.get("vol_mult", 1.3)
        self.atr_period = config.get("atr_period", 14)
        self.trailing_atr_mult = config.get("trailing_atr_mult", 2.0)
        self.time_exit_bars = config.get("time_exit_bars", 20)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._squeeze_window = 50  # bars used to compute squeeze percentile

        self._stop_price: Optional[float] = None
        self._peak_price: Optional[float] = None    # trailing peak for LONG
        self._trough_price: Optional[float] = None  # trailing trough for SHORT
        self._direction: Optional[str] = None       # "long" or "short"

    def reset(self):
        self._stop_price = None
        self._peak_price = None
        self._trough_price = None
        self._direction = None

    # ── Indicators ──────────────────────────────────────────────────────────────

    def _bollinger(self, close: pd.Series):
        """Returns Series for (upper, middle, lower, width) over full close series."""
        middle = close.rolling(self.bb_period).mean()
        sigma = close.rolling(self.bb_period).std()
        upper = middle + self.bb_std * sigma
        lower = middle - self.bb_std * sigma
        width = upper - lower
        return upper, middle, lower, width

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

    def _in_squeeze(self, width_series: pd.Series) -> bool:
        """True if current BB width is below squeeze_percentile of recent window."""
        window = width_series.iloc[-(self._squeeze_window + 1):-1]  # exclude current
        if len(window) < self._squeeze_window // 2:
            return False
        current_width = float(width_series.iloc[-1])
        if current_width != current_width:
            return False
        threshold = float(np.percentile(window.dropna(), self.squeeze_percentile))
        return current_width < threshold

    # ── Main ────────────────────────────────────────────────────────────────────

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        vol_period = 20
        needed = max(self.bb_period, self.atr_period, self._squeeze_window, vol_period) + 10
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        volume = candles["volume"]
        price = float(close.iloc[-1])

        bb_upper_s, bb_mid_s, bb_lower_s, bb_width_s = self._bollinger(close)
        bb_upper = float(bb_upper_s.iloc[-1])
        bb_mid = float(bb_mid_s.iloc[-1])
        bb_lower = float(bb_lower_s.iloc[-1])
        bb_upper = bb_upper if bb_upper == bb_upper else price
        bb_mid = bb_mid if bb_mid == bb_mid else price
        bb_lower = bb_lower if bb_lower == bb_lower else price

        atr = self._atr(candles, self.atr_period)

        avg_vol = float(volume.rolling(vol_period).mean().iloc[-2])
        avg_vol = avg_vol if avg_vol == avg_vol and avg_vol > 0 else 1.0
        current_vol = float(volume.iloc[-1])
        vol_confirmed = current_vol >= avg_vol * self.vol_mult

        squeeze = self._in_squeeze(bb_width_s)

        # ── EXIT LONG ───────────────────────────────────────────────────────────
        if position is not None and self._direction == "long":
            bars_held = position.get("bars_held", 0)

            # Update trailing peak & trailing stop
            if self._peak_price is None or price > self._peak_price:
                self._peak_price = price
            trailing_stop = self._peak_price - self.trailing_atr_mult * atr
            if self._stop_price is None or trailing_stop > self._stop_price:
                self._stop_price = trailing_stop

            # Hit trailing/hard stop
            if self._stop_price is not None and price <= self._stop_price:
                sp = self._stop_price
                self._reset_state()
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"long stop at {sp:.4f}",
                    metadata={"stop": sp, "atr": atr}
                )

            # Price crosses back below middle band
            if price < bb_mid:
                self._reset_state()
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"long: price {price:.4f} crossed below bb_mid {bb_mid:.4f}",
                    metadata={"bb_mid": bb_mid, "atr": atr}
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

            # Update trailing trough & trailing stop
            if self._trough_price is None or price < self._trough_price:
                self._trough_price = price
            trailing_stop = self._trough_price + self.trailing_atr_mult * atr
            if self._stop_price is None or trailing_stop < self._stop_price:
                self._stop_price = trailing_stop

            # Hit trailing/hard stop
            if self._stop_price is not None and price >= self._stop_price:
                sp = self._stop_price
                self._reset_state()
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"short stop at {sp:.4f}",
                    metadata={"stop": sp, "atr": atr}
                )

            # Price crosses back above middle band
            if price > bb_mid:
                self._reset_state()
                return TradeSignal(
                    Signal.COVER, pair, price, 0,
                    f"short: price {price:.4f} crossed above bb_mid {bb_mid:.4f}",
                    metadata={"bb_mid": bb_mid, "atr": atr}
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

            if squeeze and vol_confirmed:
                if price > bb_upper:
                    # Breakout to the upside → LONG
                    self._direction = "long"
                    self._peak_price = price
                    self._stop_price = price - self.trailing_atr_mult * atr
                    return TradeSignal(
                        Signal.BUY, pair, price, self.amount_per_trade,
                        f"squeeze breakout LONG: price {price:.4f} > upper {bb_upper:.4f}",
                        confidence=min(1.0, (current_vol / avg_vol - 1) / 2),
                        metadata={
                            "bb_upper": bb_upper, "bb_lower": bb_lower,
                            "vol_ratio": round(current_vol / avg_vol, 2),
                            "atr": atr, "stop": self._stop_price,
                        }
                    )
                elif price < bb_lower:
                    # Breakout to the downside → SHORT
                    self._direction = "short"
                    self._trough_price = price
                    self._stop_price = price + self.trailing_atr_mult * atr
                    return TradeSignal(
                        Signal.SHORT, pair, price, self.amount_per_trade,
                        f"squeeze breakout SHORT: price {price:.4f} < lower {bb_lower:.4f}",
                        confidence=min(1.0, (current_vol / avg_vol - 1) / 2),
                        metadata={
                            "bb_upper": bb_upper, "bb_lower": bb_lower,
                            "vol_ratio": round(current_vol / avg_vol, 2),
                            "atr": atr, "stop": self._stop_price,
                        }
                    )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold: squeeze={squeeze} vol_ok={vol_confirmed} bb=[{bb_lower:.4f},{bb_upper:.4f}]",
            metadata={
                "squeeze": squeeze, "vol_confirmed": vol_confirmed,
                "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_mid": bb_mid,
            }
        )

    def _reset_state(self):
        self._stop_price = None
        self._peak_price = None
        self._trough_price = None
        self._direction = None

    def get_params(self) -> dict:
        return {
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "squeeze_percentile": self.squeeze_percentile,
            "vol_mult": self.vol_mult,
            "atr_period": self.atr_period,
            "trailing_atr_mult": self.trailing_atr_mult,
            "time_exit_bars": self.time_exit_bars,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "bb_period": [14, 20, 30],
            "bb_std": [1.5, 2.0, 2.5],
            "squeeze_percentile": [10, 20, 30],
            "vol_mult": [1.2, 1.3, 1.5, 2.0],
            "trailing_atr_mult": [1.5, 2.0, 2.5],
            "time_exit_bars": [15, 20, 30],
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
