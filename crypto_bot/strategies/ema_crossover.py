"""
EMA Crossover Momentum
- BUY en golden cross (EMA_fast cruza arriba de EMA_slow)
- SELL en death cross (EMA_fast cruza abajo de EMA_slow)
- Trailing stop desde el máximo post-entry
- Filtro de volumen opcional
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class EMACrossoverStrategy(BaseStrategy):
    name = "ema_crossover"
    description = "Momentum: compra en golden cross, vende en death cross"
    ideal_timeframes: list = ["1h","4h","1d"]
    min_period: str = "2m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h', '1d']
    suitable_market_conditions: list = ['trending']
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   5.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.fast_ema = config.get("fast_ema", 9)
        self.slow_ema = config.get("slow_ema", 21)
        self.signal_ema = config.get("signal_ema", 5)
        self.amount_per_trade = config.get("amount_per_trade", 5)
        self.trailing_stop_pct = config.get("trailing_stop_pct", 2.0)
        self.min_volume_filter = config.get("min_volume_filter", True)
        self._peak_price = None

    def reset(self):
        self._peak_price = None

    def _compute_emas(self, close: pd.Series, volume: pd.Series) -> tuple:
        fast = close.ewm(span=self.fast_ema, adjust=False).mean()
        slow = close.ewm(span=self.slow_ema, adjust=False).mean()
        diff = fast - slow
        signal = diff.ewm(span=self.signal_ema, adjust=False).mean()

        vol_ok = True
        if self.min_volume_filter and len(volume) >= 20:
            avg_vol = volume.rolling(20).mean().iloc[-1]
            vol_ok = float(volume.iloc[-1]) >= float(avg_vol) * 0.7

        return (
            float(fast.iloc[-1]), float(fast.iloc[-2]),
            float(slow.iloc[-1]), float(slow.iloc[-2]),
            float(diff.iloc[-1]), float(signal.iloc[-1]),
            vol_ok
        )

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        if len(candles) < self.slow_ema + self.signal_ema + 2:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        volume = candles["volume"]
        price = float(close.iloc[-1])

        fast_now, fast_prev, slow_now, slow_prev, diff_now, sig_now, vol_ok = \
            self._compute_emas(close, volume)

        # Actualizar peak para trailing stop
        if position is not None:
            if self._peak_price is None:
                self._peak_price = price
            self._peak_price = max(self._peak_price, price)

            # Trailing stop
            drop = (price - self._peak_price) / self._peak_price * 100
            if drop <= -self.trailing_stop_pct:
                peak = self._peak_price
                self._peak_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"trailing stop {drop:.1f}% from peak {peak:.2f}",
                    confidence=1.0,
                    metadata={"peak": self._peak_price, "drop_pct": drop}
                )

            # Death cross → sell
            cross_down = fast_prev >= slow_prev and fast_now < slow_now
            if cross_down:
                self._peak_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"death cross: fast={fast_now:.4f} < slow={slow_now:.4f}",
                    confidence=min(1.0, abs(diff_now) / price * 200),
                    metadata={"fast_ema": fast_now, "slow_ema": slow_now, "diff": diff_now}
                )

        else:
            self._peak_price = None
            # Golden cross → buy
            cross_up = fast_prev <= slow_prev and fast_now > slow_now
            if cross_up and vol_ok:
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"golden cross: fast={fast_now:.4f} > slow={slow_now:.4f}",
                    confidence=min(1.0, abs(diff_now) / price * 200),
                    metadata={"fast_ema": fast_now, "slow_ema": slow_now,
                               "signal": sig_now, "vol_ok": vol_ok}
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold fast={fast_now:.4f} slow={slow_now:.4f}",
            metadata={"fast_ema": fast_now, "slow_ema": slow_now, "diff": diff_now}
        )

    def get_params(self) -> dict:
        return {
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "signal_ema": self.signal_ema,
            "amount_per_trade": self.amount_per_trade,
            "trailing_stop_pct": self.trailing_stop_pct,
            "min_volume_filter": self.min_volume_filter,
        }

    def get_param_grid(self) -> dict:
        return {
            "fast_ema": [5, 9, 12],
            "slow_ema": [21, 26, 50],
            "trailing_stop_pct": [1.5, 2.0, 3.0],
        }
