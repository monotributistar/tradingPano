"""
RSI Mean Reversion
- BUY cuando RSI < oversold por N barras consecutivas
- SELL cuando RSI > overbought
- Stop loss porcentual desde entry
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    # When avg_loss is 0, all candles are gains → RSI = 100
    rsi[avg_loss == 0] = 100
    return rsi


class RSIMeanRevertStrategy(BaseStrategy):
    name = "rsi_mean_revert"
    description = "Compra en RSI oversold, vende en RSI overbought"
    ideal_timeframes: list = ["1h","4h"]
    min_period: str = "1m"
    market_type: str = "ranging"
    trade_frequency: str = "medium"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h']
    suitable_market_conditions: list = ['ranging']
    recommended_leverage: float = 1.5
    max_leverage: float = 5.0
    risk_profile: dict = {
        "stop_loss_pct":     2.5,
        "take_profit_pct":   4.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_oversold = config.get("rsi_oversold", 25)
        self.rsi_overbought = config.get("rsi_overbought", 75)
        self.amount_per_trade = config.get("amount_per_trade", 5)
        self.confirmation_bars = config.get("confirmation_bars", 2)
        self.max_loss_pct = config.get("max_loss_pct", 4.0)
        self._oversold_bars = 0

    def reset(self):
        self._oversold_bars = 0

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        if len(candles) < self.rsi_period + 5:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])
        rsi_series = _compute_rsi(close, self.rsi_period)
        rsi = float(rsi_series.iloc[-1])

        if position is not None:
            avg_cost = position.get("avg_cost", price)
            loss_pct = (price - avg_cost) / avg_cost * 100

            if loss_pct <= -self.max_loss_pct:
                self._oversold_bars = 0
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"stop loss {loss_pct:.1f}%",
                    metadata={"rsi": rsi, "loss_pct": loss_pct}
                )

            if rsi >= self.rsi_overbought:
                self._oversold_bars = 0
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"RSI overbought {rsi:.1f} >= {self.rsi_overbought}",
                    confidence=min(1.0, (rsi - self.rsi_overbought) / 25),
                    metadata={"rsi": rsi}
                )

        else:
            # Contar barras consecutivas en oversold
            if rsi <= self.rsi_oversold:
                self._oversold_bars += 1
            else:
                self._oversold_bars = 0

            if self._oversold_bars >= self.confirmation_bars:
                self._oversold_bars = 0
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"RSI oversold {rsi:.1f} <= {self.rsi_oversold} ({self.confirmation_bars} bars)",
                    confidence=min(1.0, (self.rsi_oversold - rsi) / 25 + 0.5),
                    metadata={"rsi": rsi, "confirmation_bars": self.confirmation_bars}
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold RSI={rsi:.1f}",
            metadata={"rsi": rsi}
        )

    def get_params(self) -> dict:
        return {
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "amount_per_trade": self.amount_per_trade,
            "confirmation_bars": self.confirmation_bars,
            "max_loss_pct": self.max_loss_pct,
        }

    def get_param_grid(self) -> dict:
        return {
            "rsi_period": [9, 14, 21],
            "rsi_oversold": [20, 25, 30],
            "rsi_overbought": [70, 75, 80],
            "confirmation_bars": [1, 2, 3],
        }
