"""
Scalping Strategy — RSI(7) + Bollinger Bands(14) + EMA direction filter

Edge: compra rebotes en oversold dentro de una tendencia alcista.
RSI muy corto (7) para ser sensible a movimientos rápidos.
BB de 14 barras para detectar extremos de precio a corto plazo.
EMA50 como filtro de tendencia: solo compra si el precio está por encima.
Salida rápida: máximo 8 velas o cuando RSI llega a 70 / precio cruza BB media.
Stop loss dinámico basado en ATR.
"""
from typing import Optional

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class ScalpingStrategy(BaseStrategy):
    name = "scalping"
    description = "Scalping con RSI + Bollinger Bands — muchas operaciones rapidas"
    ideal_timeframes: list = ["15m","30m","1h"]
    min_period: str = "2w"
    market_type: str = "both"
    trade_frequency: str = "high"
    min_liquidity: str = "medium"
    suitable_timeframes: list = ['15m', '30m', '1h']
    suitable_market_conditions: list = ['both', 'high_vol']
    recommended_leverage: float = 3.0
    max_leverage: float = 10.0
    risk_profile: dict = {
        "stop_loss_pct":     1.0,
        "take_profit_pct":   2.0,
        "position_size_pct": 8.0,
    }


    def initialize(self, config: dict):
        self.rsi_period = config.get("rsi_period", 7)
        self.bb_period = config.get("bb_period", 14)
        self.bb_std = config.get("bb_std", 2.0)
        self.ema_period = config.get("ema_period", 50)
        self.atr_period = config.get("atr_period", 7)
        self.stop_atr_mult = config.get("stop_atr_mult", 1.5)
        self.time_exit_bars = config.get("time_exit_bars", 8)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._stop_price: Optional[float] = None

    def reset(self):
        self._stop_price = None

    # ── Indicators ──────────────────────────────────────────────────────────────

    def _rsi(self, close: pd.Series, period: int) -> float:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        val = float(rsi.iloc[-1])
        return val if val == val else 50.0

    def _bollinger(self, close: pd.Series, period: int, std: float):
        """Returns (upper, middle, lower) as floats."""
        middle = close.rolling(period).mean()
        sigma = close.rolling(period).std()
        upper = middle + std * sigma
        lower = middle - std * sigma
        m = float(middle.iloc[-1])
        u = float(upper.iloc[-1])
        lo = float(lower.iloc[-1])
        m = m if m == m else float(close.iloc[-1])
        u = u if u == u else m
        lo = lo if lo == lo else m
        return u, m, lo

    def _ema(self, close: pd.Series, period: int) -> float:
        val = float(close.ewm(span=period, adjust=False).mean().iloc[-1])
        return val if val == val else float(close.iloc[-1])

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
        needed = max(self.bb_period, self.ema_period, self.atr_period, self.rsi_period) + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])
        rsi = self._rsi(close, self.rsi_period)
        bb_upper, bb_mid, bb_lower = self._bollinger(close, self.bb_period, self.bb_std)
        ema50 = self._ema(close, self.ema_period)
        atr = self._atr(candles, self.atr_period)

        # ── EXIT ────────────────────────────────────────────────────────────────
        if position is not None:
            bars_held = position.get("bars_held", 0)

            # Hard stop
            if self._stop_price is not None and price <= self._stop_price:
                sp = self._stop_price
                self._stop_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"stop loss at {sp:.4f}",
                    metadata={"stop": sp, "atr": atr}
                )

            # Time exit
            if bars_held >= self.time_exit_bars:
                self._stop_price = None
                return TradeSignal(
                    Signal.TIME_EXIT, pair, price, 0,
                    f"time exit after {bars_held} bars",
                    metadata={"bars_held": bars_held}
                )

            # RSI overbought or price crosses above middle BB
            if rsi > 70 or price >= bb_mid:
                self._stop_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"exit: rsi={rsi:.1f} price={price:.4f} bb_mid={bb_mid:.4f}",
                    metadata={"rsi": rsi, "bb_mid": bb_mid}
                )

        # ── ENTRY ───────────────────────────────────────────────────────────────
        else:
            self._stop_price = None
            in_uptrend = price > ema50
            rsi_oversold = rsi < 30
            touches_lower_bb = price <= bb_lower

            if rsi_oversold and touches_lower_bb and in_uptrend:
                stop = price - self.stop_atr_mult * atr
                self._stop_price = stop
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"scalp entry: rsi={rsi:.1f} price={price:.4f} <= bb_lower={bb_lower:.4f}",
                    confidence=min(1.0, (30 - rsi) / 15),
                    metadata={
                        "rsi": rsi, "bb_lower": bb_lower, "bb_mid": bb_mid,
                        "ema50": ema50, "atr": atr, "stop": stop,
                    }
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold: rsi={rsi:.1f} price={price:.4f} bb=[{bb_lower:.4f},{bb_upper:.4f}] ema50={ema50:.4f}",
            metadata={"rsi": rsi, "bb_lower": bb_lower, "bb_mid": bb_mid, "ema50": ema50}
        )

    def get_params(self) -> dict:
        return {
            "rsi_period": self.rsi_period,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "ema_period": self.ema_period,
            "atr_period": self.atr_period,
            "stop_atr_mult": self.stop_atr_mult,
            "time_exit_bars": self.time_exit_bars,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "rsi_period": [5, 7, 9],
            "bb_period": [10, 14, 20],
            "bb_std": [1.5, 2.0, 2.5],
            "ema_period": [20, 50, 100],
            "stop_atr_mult": [1.0, 1.5, 2.0],
            "time_exit_bars": [5, 8, 12],
        }

    def save_state(self) -> dict:
        return {"stop_price": self._stop_price}

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
