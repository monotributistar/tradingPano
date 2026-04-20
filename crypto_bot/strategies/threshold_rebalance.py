"""
Threshold Rebalancing
- Mantiene allocation target por par
- Rebalancea cuando un par se desvía > threshold%
- Check_interval en horas
"""
from typing import Optional
from datetime import datetime, timezone, timedelta
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class ThresholdRebalanceStrategy(BaseStrategy):
    name = "threshold_rebalance"
    description = "Rebalanceo cuando la allocation se desvía del target"
    ideal_timeframes: list = ["1d","1w"]
    min_period: str = "6m"
    market_type: str = "both"
    trade_frequency: str = "low"
    min_liquidity: str = "high"
    suitable_timeframes: list = ['1d']
    suitable_market_conditions: list = ['both']
    recommended_leverage: float = 1.0
    max_leverage: float = 3.0
    risk_profile: dict = {
        "stop_loss_pct":     5.0,
        "take_profit_pct":   10.0,
        "position_size_pct": 10.0,
    }


    def initialize(self, config: dict):
        self.target_allocation = config.get("target_allocation", {"BTC/USDT": 50, "ETH/USDT": 30, "SOL/USDT": 20})
        self.rebalance_threshold = config.get("rebalance_threshold", 8.0)
        check_str = str(config.get("check_interval", "4h"))
        hours = int(check_str.replace("h", "")) if "h" in check_str else 4
        self.check_interval = timedelta(hours=hours)
        self.min_trade_usd = config.get("min_trade_usd", 3)
        self._last_check: Optional[datetime] = None
        self._portfolio_values: dict = {}

    def reset(self):
        self._last_check = None
        self._portfolio_values = {}

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        price = float(candles["close"].iloc[-1])
        now = candles.index[-1]
        if hasattr(now, 'to_pydatetime'):
            now = now.to_pydatetime()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Solo chequear en intervalos definidos
        if self._last_check is not None:
            elapsed = now - self._last_check
            if elapsed < self.check_interval:
                return TradeSignal(Signal.HOLD, pair, price, 0,
                                   f"next check in {(self.check_interval - elapsed).seconds // 3600}h")

        self._last_check = now
        target_pct = self.target_allocation.get(pair, 0)

        if target_pct == 0:
            return TradeSignal(Signal.HOLD, pair, price, 0, "pair not in allocation")

        # Para backtesting, simulamos la desviación basada en el estado de la posición
        # En paper/live se usaría el balance real del engine
        if position is not None:
            current_value = position["qty"] * price
            # Asumimos que total_portfolio ≈ current_value / (target_pct/100)
            estimated_total = current_value / (target_pct / 100)
            current_pct = current_value / estimated_total * 100
            deviation = current_pct - target_pct

            if abs(deviation) >= self.rebalance_threshold:
                if deviation > 0:
                    # Sobre-asignado → vender parte
                    excess_value = current_value - estimated_total * (target_pct / 100)
                    if excess_value >= self.min_trade_usd:
                        return TradeSignal(
                            Signal.SELL, pair, price, 0,
                            f"rebalance sell: {current_pct:.1f}% > {target_pct}% (dev={deviation:.1f}%)",
                            confidence=0.8,
                            metadata={"deviation_pct": deviation, "target_pct": target_pct}
                        )
                else:
                    # Sub-asignado → comprar más
                    deficit_value = estimated_total * (target_pct / 100) - current_value
                    if deficit_value >= self.min_trade_usd:
                        return TradeSignal(
                            Signal.BUY, pair, price, min(deficit_value, 10),
                            f"rebalance buy: {current_pct:.1f}% < {target_pct}% (dev={deviation:.1f}%)",
                            confidence=0.8,
                            metadata={"deviation_pct": deviation, "target_pct": target_pct}
                        )
        else:
            # Sin posición y tenemos target → comprar
            initial_amount = self.min_trade_usd * 2
            return TradeSignal(
                Signal.BUY, pair, price, initial_amount,
                f"initial allocation {target_pct}% of portfolio",
                confidence=0.9,
                metadata={"target_pct": target_pct}
            )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"allocation ok target={target_pct}%")

    def get_params(self) -> dict:
        return {
            "target_allocation": self.target_allocation,
            "rebalance_threshold": self.rebalance_threshold,
            "check_interval": str(self.check_interval),
            "min_trade_usd": self.min_trade_usd,
        }

    def get_param_grid(self) -> dict:
        return {
            "rebalance_threshold": [5.0, 8.0, 12.0],
        }
