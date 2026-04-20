"""
Bollinger Bands + DCA
- BUY cuando precio toca/cruza banda inferior → DCA entry
- Acumula hasta max_positions entradas
- SELL cuando precio toca banda superior O avg_cost + take_profit%
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class BollingerDCAStrategy(BaseStrategy):
    name = "bollinger_dca"
    description = "DCA cuando el precio toca banda inferior de Bollinger"
    ideal_timeframes: list = ["1h","4h","1d"]
    min_period: str = "1m"
    market_type: str = "ranging"
    trade_frequency: str = "low"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h', '1d']
    suitable_market_conditions: list = ['ranging', 'low_vol']
    recommended_leverage: float = 1.5
    max_leverage: float = 5.0
    risk_profile: dict = {
        "stop_loss_pct":     3.0,
        "take_profit_pct":   6.0,
        "position_size_pct": 4.0,
    }


    def initialize(self, config: dict):
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 2.0)
        self.dca_amount = config.get("dca_amount", 5)
        self.max_positions = config.get("max_positions", 5)
        self.take_profit_pct = config.get("take_profit_pct", 2.0)
        self.buy_on_lower_band = config.get("buy_on_lower_band", True)
        self.sell_on_upper_band = config.get("sell_on_upper_band", True)
        self._entries_count = 0

    def reset(self):
        self._entries_count = 0

    def _compute_bb(self, close: pd.Series) -> tuple[float, float, float]:
        if len(close) < self.bb_period:
            p = float(close.iloc[-1])
            return p, p, p
        ma = close.rolling(self.bb_period).mean().iloc[-1]
        std = close.rolling(self.bb_period).std().iloc[-1]
        return float(ma), float(ma + self.bb_std * std), float(ma - self.bb_std * std)

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        close = candles["close"]
        price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2]) if len(close) >= 2 else price

        ma, upper, lower = self._compute_bb(close)

        if position is not None:
            avg_cost = position.get("avg_cost", price)

            # Take profit por precio objetivo
            tp_price = avg_cost * (1 + self.take_profit_pct / 100)
            if price >= tp_price:
                self._entries_count = 0
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"take profit {self.take_profit_pct}% avg={avg_cost:.4f}",
                    confidence=0.9,
                    metadata={"avg_cost": avg_cost, "upper": upper, "ma": ma}
                )

            # Sell en banda superior
            if self.sell_on_upper_band and price >= upper:
                self._entries_count = 0
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"upper band {upper:.4f}",
                    confidence=0.85,
                    metadata={"upper": upper, "ma": ma, "lower": lower}
                )

            # DCA adicional si sigue en banda inferior y no llegamos al máximo
            if (self.buy_on_lower_band and price <= lower and
                    self._entries_count < self.max_positions):
                self._entries_count += 1
                return TradeSignal(
                    Signal.BUY, pair, price, self.dca_amount,
                    f"DCA entry {self._entries_count}/{self.max_positions} lower={lower:.4f}",
                    confidence=0.7,
                    metadata={"lower": lower, "ma": ma, "entry": self._entries_count}
                )

        else:
            self._entries_count = 0
            # Primera entrada en banda inferior
            if self.buy_on_lower_band and prev_price > lower and price <= lower:
                self._entries_count = 1
                return TradeSignal(
                    Signal.BUY, pair, price, self.dca_amount,
                    f"lower band touch {lower:.4f}",
                    confidence=0.8,
                    metadata={"lower": lower, "ma": ma, "upper": upper}
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold ma={ma:.4f} upper={upper:.4f} lower={lower:.4f}",
            metadata={"ma": ma, "upper": upper, "lower": lower}
        )

    def get_params(self) -> dict:
        return {
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "dca_amount": self.dca_amount,
            "max_positions": self.max_positions,
            "take_profit_pct": self.take_profit_pct,
        }

    def get_param_grid(self) -> dict:
        return {
            "bb_period": [15, 20, 25],
            "bb_std": [1.5, 2.0, 2.5],
            "take_profit_pct": [1.5, 2.0, 3.0],
            "max_positions": [3, 5],
        }
