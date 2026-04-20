"""
Mean Reversion con Z-Score
- Calcula EMA y desviación estándar del precio
- Entra cuando Z-Score < z_score_entry (precio muy por debajo de la media)
- Sale cuando Z-Score > z_score_exit (precio volvió a la media)
- Entries escalonados en grid_levels niveles
- Time exit: salir si no revirtió en N barras
- Cooldown después de stop loss
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"
    description = "Compra cuando el precio se aleja de la media, vende al volver"
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
        self.ema_period = config.get("ema_period", 20)
        self.z_score_entry = config.get("z_score_entry", -1.5)
        self.z_score_exit = config.get("z_score_exit", 0.5)
        self.amount_per_trade = config.get("amount_per_trade", 5)
        self.grid_levels = config.get("grid_levels", 3)
        self.max_loss_pct = config.get("max_loss_pct", 5.0)
        self.time_exit_bars = config.get("time_exit_bars", 30)
        self.cooldown_bars = config.get("cooldown_bars", 5)
        self._cooldown_counter = 0
        self._entry_levels_used = 0

    def reset(self):
        self._cooldown_counter = 0
        self._entry_levels_used = 0

    def _compute_zscore(self, close: pd.Series) -> tuple[float, float, float]:
        """Calcula EMA y Z-Score. Retorna (zscore, ema, std)."""
        n = self.ema_period
        if len(close) < n:
            return 0.0, float(close.iloc[-1]), 0.0
        ema = close.ewm(span=n, adjust=False).mean().iloc[-1]
        std = close.rolling(n).std().iloc[-1]
        if std == 0 or np.isnan(std):
            return 0.0, ema, 0.0
        zscore = (close.iloc[-1] - ema) / std
        return float(zscore), float(ema), float(std)

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        close = candles["close"]
        price = float(close.iloc[-1])

        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return TradeSignal(Signal.HOLD, pair, price, 0, "cooldown",
                               metadata={"cooldown_left": self._cooldown_counter})

        zscore, ema, std = self._compute_zscore(close)

        # --- SELL / exit logic ---
        if position is not None:
            bars_held = position.get("bars_held", 0)
            avg_cost = position.get("avg_cost", price)

            # Stop loss
            loss_pct = (price - avg_cost) / avg_cost * 100
            if loss_pct <= -self.max_loss_pct:
                self._cooldown_counter = self.cooldown_bars
                self._entry_levels_used = 0
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"stop loss {loss_pct:.1f}%",
                    confidence=1.0,
                    metadata={"zscore": zscore, "loss_pct": loss_pct}
                )

            # Time exit
            if bars_held >= self.time_exit_bars:
                self._entry_levels_used = 0
                return TradeSignal(
                    Signal.TIME_EXIT, pair, price, 0,
                    f"time exit after {bars_held} bars",
                    confidence=0.8,
                    metadata={"zscore": zscore, "bars_held": bars_held}
                )

            # Z-Score exit (profit)
            if zscore >= self.z_score_exit:
                self._entry_levels_used = 0
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"z-score exit {zscore:.2f} >= {self.z_score_exit}",
                    confidence=min(1.0, zscore / 2),
                    metadata={"zscore": zscore, "ema": ema}
                )

        # --- BUY logic ---
        if zscore <= self.z_score_entry:
            # Calcular nivel de entrada (0-indexed)
            # Cuanto más negativo el zscore, más niveles habilitados
            levels_available = min(
                self.grid_levels,
                int(abs(zscore - self.z_score_entry) / 0.5) + 1
            )
            if self._entry_levels_used < levels_available:
                self._entry_levels_used += 1
                confidence = min(1.0, abs(zscore) / 3)
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"z-score entry {zscore:.2f} (level {self._entry_levels_used}/{self.grid_levels})",
                    confidence=confidence,
                    metadata={"zscore": zscore, "ema": ema, "std": std,
                               "level": self._entry_levels_used}
                )

        # Reset level counter when price normalizes (no position)
        if position is None and abs(zscore) < 0.5:
            self._entry_levels_used = 0

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold z-score={zscore:.2f}",
                           metadata={"zscore": zscore, "ema": ema})

    def get_params(self) -> dict:
        return {
            "ema_period": self.ema_period,
            "z_score_entry": self.z_score_entry,
            "z_score_exit": self.z_score_exit,
            "amount_per_trade": self.amount_per_trade,
            "grid_levels": self.grid_levels,
            "max_loss_pct": self.max_loss_pct,
            "time_exit_bars": self.time_exit_bars,
            "cooldown_bars": self.cooldown_bars,
        }

    def get_param_grid(self) -> dict:
        return {
            "ema_period": [10, 20, 30, 50],
            "z_score_entry": [-1.0, -1.5, -2.0, -2.5],
            "z_score_exit": [0.0, 0.5, 1.0],
            "grid_levels": [1, 2, 3],
            "time_exit_bars": [20, 30, 50],
        }

    def save_state(self) -> dict:
        return {
            "cooldown_counter": self._cooldown_counter,
            "entry_levels_used": self._entry_levels_used,
        }

    def load_state(self, state: dict):
        self._cooldown_counter = state.get("cooldown_counter", 0)
        self._entry_levels_used = state.get("entry_levels_used", 0)
