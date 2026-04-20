"""
Grid Trading Dinámico
- Calcula rango via ATR
- N niveles de compra debajo del precio, N de venta arriba
- Spacing se ajusta con volatilidad si volatility_adjust=True
- Reset del grid cada range_reset_hours
"""
from typing import Optional
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


def _atr(candles: pd.DataFrame, period: int) -> float:
    high = candles["high"]
    low = candles["low"]
    close = candles["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


class GridDynamicStrategy(BaseStrategy):
    name = "grid_dynamic"
    description = "Grid trading con bandas que se ajustan a volatilidad"
    ideal_timeframes: list = ["1h","4h"]
    min_period: str = "1m"
    market_type: str = "ranging"
    trade_frequency: str = "high"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h']
    suitable_market_conditions: list = ['ranging']
    recommended_leverage: float = 1.5
    max_leverage: float = 5.0
    risk_profile: dict = {
        "stop_loss_pct":     5.0,
        "take_profit_pct":   1.0,
        "position_size_pct": 10.0,
    }


    def initialize(self, config: dict):
        self.grid_levels = config.get("grid_levels", 5)
        self.grid_spacing_pct = config.get("grid_spacing_pct", 1.0)
        self.volatility_adjust = config.get("volatility_adjust", True)
        self.atr_period = config.get("atr_period", 14)
        self.amount_per_level = config.get("amount_per_level", 3)
        self.range_reset_hours = config.get("range_reset_hours", 24)
        self._grid = None
        self._last_reset: Optional[datetime] = None
        self._filled_buys: dict = {}  # nivel -> precio de compra

    def reset(self):
        self._grid = None
        self._last_reset = None
        self._filled_buys = {}

    def _build_grid(self, price: float, spacing_pct: float) -> dict:
        """Construye los niveles del grid alrededor del precio actual."""
        levels = {}
        for i in range(1, self.grid_levels + 1):
            levels[f"buy_{i}"] = price * (1 - spacing_pct / 100 * i)
            levels[f"sell_{i}"] = price * (1 + spacing_pct / 100 * i)
        return levels

    def _should_reset(self, now: datetime) -> bool:
        if self._last_reset is None:
            return True
        elapsed = now - self._last_reset
        return elapsed >= timedelta(hours=self.range_reset_hours)

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        if len(candles) < self.atr_period + 2:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        price = float(candles["close"].iloc[-1])
        now = candles.index[-1]
        if hasattr(now, 'to_pydatetime'):
            now = now.to_pydatetime()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Calcular spacing ajustado por volatilidad
        spacing = self.grid_spacing_pct
        if self.volatility_adjust:
            atr = _atr(candles, self.atr_period)
            if atr > 0 and price > 0:
                atr_pct = atr / price * 100
                # Spacing = max(base, ATR%) pero limitado a 3x base
                spacing = max(self.grid_spacing_pct,
                              min(atr_pct * 0.5, self.grid_spacing_pct * 3))

        # Resetear grid si es necesario
        if self._should_reset(now):
            self._grid = self._build_grid(price, spacing)
            self._last_reset = now
            self._filled_buys = {}

        if self._grid is None:
            return TradeSignal(Signal.HOLD, pair, price, 0, "no grid")

        # Verificar si el precio cruzó algún nivel de compra
        if position is None or True:  # siempre verificar DCA entries
            for i in range(1, self.grid_levels + 1):
                buy_level = self._grid.get(f"buy_{i}")
                if buy_level and price <= buy_level and f"buy_{i}" not in self._filled_buys:
                    self._filled_buys[f"buy_{i}"] = price
                    return TradeSignal(
                        Signal.BUY, pair, price, self.amount_per_level,
                        f"grid buy level {i} @ {buy_level:.4f}",
                        confidence=0.7,
                        metadata={"level": i, "grid_price": buy_level, "spacing_pct": spacing}
                    )

        # Verificar si el precio cruzó algún nivel de venta (si hay posición)
        if position is not None:
            avg_cost = position.get("avg_cost", price)
            # Vender en el primer nivel de venta arriba del avg_cost
            for i in range(1, self.grid_levels + 1):
                sell_level = self._grid.get(f"sell_{i}")
                if sell_level and price >= sell_level and sell_level > avg_cost:
                    # Reset nivel de compra correspondiente para re-entrar
                    if f"buy_{i}" in self._filled_buys:
                        del self._filled_buys[f"buy_{i}"]
                    return TradeSignal(
                        Signal.SELL, pair, price, 0,
                        f"grid sell level {i} @ {sell_level:.4f}",
                        confidence=0.8,
                        metadata={"level": i, "grid_price": sell_level}
                    )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold spacing={spacing:.2f}%",
            metadata={"spacing_pct": spacing, "filled_buys": len(self._filled_buys)}
        )

    def get_params(self) -> dict:
        return {
            "grid_levels": self.grid_levels,
            "grid_spacing_pct": self.grid_spacing_pct,
            "volatility_adjust": self.volatility_adjust,
            "atr_period": self.atr_period,
            "amount_per_level": self.amount_per_level,
            "range_reset_hours": self.range_reset_hours,
        }

    def get_param_grid(self) -> dict:
        return {
            "grid_levels": [3, 5, 7],
            "grid_spacing_pct": [0.5, 1.0, 1.5],
            "atr_period": [10, 14, 20],
        }

    def save_state(self) -> dict:
        return {
            "grid": self._grid,
            "last_reset": self._last_reset.isoformat() if self._last_reset else None,
            "filled_buys": self._filled_buys,
        }

    def load_state(self, state: dict):
        self._grid = state.get("grid")
        lr = state.get("last_reset")
        self._last_reset = datetime.fromisoformat(lr) if lr else None
        self._filled_buys = state.get("filled_buys", {})
