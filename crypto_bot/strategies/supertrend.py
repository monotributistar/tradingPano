"""
Supertrend Strategy
- Supertrend is an ATR-based trend indicator extremely popular in crypto day trading.
- Direction flips when price crosses the active band.
- Upper band = (high+low)/2 + mult*ATR  (active in bearish regime)
- Lower band = (high+low)/2 - mult*ATR  (active in bullish regime)
- BUY when direction flips from -1 to 1 (bearish → bullish)
- SHORT when direction flips from 1 to -1 (bullish → bearish)
- ADX filter: only trade when ADX > adx_threshold (avoids sideways markets)
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class SupertrendStrategy(BaseStrategy):
    name = "supertrend"
    description = "Supertrend ATR-based trend indicator — muy popular en crypto"
    ideal_timeframes: list = ["4h","1d"]
    min_period: str = "2m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['4h', '1d']
    suitable_market_conditions: list = ['trending']
    recommended_leverage: float = 3.0
    max_leverage: float = 10.0
    risk_profile: dict = {
        "stop_loss_pct":     3.0,
        "take_profit_pct":   7.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.atr_period = config.get("atr_period", 10)
        self.multiplier = config.get("multiplier", 3.0)
        self.adx_period = config.get("adx_period", 14)
        self.adx_threshold = config.get("adx_threshold", 20.0)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._prev_direction: Optional[int] = None  # 1=bullish, -1=bearish
        self._stop_price: Optional[float] = None

    def reset(self):
        self._prev_direction = None
        self._stop_price = None

    def _atr(self, candles: pd.DataFrame, period: int) -> pd.Series:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    def _adx(self, candles: pd.DataFrame) -> float:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        period = self.adx_period

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=candles.index)
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=candles.index)

        atr_s = tr.ewm(span=period, adjust=False).mean().replace(0, 1e-10)
        plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
        adx = float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
        return adx if adx == adx else 0.0

    def _compute_supertrend(self, candles: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Returns (supertrend_line, direction_series) where direction=1 bullish, -1 bearish."""
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        atr = self._atr(candles, self.atr_period)
        hl2 = (high + low) / 2

        raw_upper = hl2 + self.multiplier * atr
        raw_lower = hl2 - self.multiplier * atr

        n = len(candles)
        upper = raw_upper.copy()
        lower = raw_lower.copy()
        direction = pd.Series(1, index=candles.index, dtype=int)
        supertrend = pd.Series(np.nan, index=candles.index)

        for i in range(1, n):
            idx = candles.index[i]
            idx_prev = candles.index[i - 1]

            # Final upper band
            upper.iloc[i] = (
                raw_upper.iloc[i]
                if raw_upper.iloc[i] < upper.iloc[i - 1] or close.iloc[i - 1] > upper.iloc[i - 1]
                else upper.iloc[i - 1]
            )
            # Final lower band
            lower.iloc[i] = (
                raw_lower.iloc[i]
                if raw_lower.iloc[i] > lower.iloc[i - 1] or close.iloc[i - 1] < lower.iloc[i - 1]
                else lower.iloc[i - 1]
            )

            # Direction
            if direction.iloc[i - 1] == -1 and close.iloc[i] > upper.iloc[i]:
                direction.iloc[i] = 1
            elif direction.iloc[i - 1] == 1 and close.iloc[i] < lower.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            supertrend.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]

        # First bar
        supertrend.iloc[0] = lower.iloc[0] if direction.iloc[0] == 1 else upper.iloc[0]

        return supertrend, direction

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = max(self.atr_period, self.adx_period) * 3 + 10
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])

        supertrend, direction = self._compute_supertrend(candles)
        adx = self._adx(candles)

        cur_dir = int(direction.iloc[-1])
        prev_dir = int(direction.iloc[-2])
        st_line = float(supertrend.iloc[-1])
        st_line = st_line if st_line == st_line else price

        trend_strong = adx >= self.adx_threshold
        current_side = position.get("side") if position else None

        # ── MANAGE LONG ────────────────────────────────────────────────────────
        if current_side == "long":
            # Exit when direction flips to bearish
            if cur_dir == -1:
                self._prev_direction = cur_dir
                self._stop_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"supertrend flip bearish: ST={st_line:.4f} ADX={adx:.1f}",
                    metadata={"supertrend": st_line, "direction": cur_dir, "adx": adx}
                )
            # Hard stop
            if self._stop_price is not None and price <= self._stop_price:
                s = self._stop_price
                self._stop_price = None
                return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                   f"long stop hit {s:.4f}",
                                   metadata={"stop": s, "adx": adx})

        # ── MANAGE SHORT ───────────────────────────────────────────────────────
        elif current_side == "short":
            # Cover when direction flips to bullish
            if cur_dir == 1:
                self._prev_direction = cur_dir
                self._stop_price = None
                return TradeSignal(
                    Signal.COVER, pair, price, 0,
                    f"supertrend flip bullish: ST={st_line:.4f} ADX={adx:.1f}",
                    metadata={"supertrend": st_line, "direction": cur_dir, "adx": adx}
                )
            # Hard stop (short: stop above entry)
            if self._stop_price is not None and price >= self._stop_price:
                s = self._stop_price
                self._stop_price = None
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"short stop hit {s:.4f}",
                                   metadata={"stop": s, "adx": adx})

        # ── NO POSITION: check for direction flip ──────────────────────────────
        else:
            # Direction flip detected on this bar
            flipped_bullish = (prev_dir == -1 and cur_dir == 1)
            flipped_bearish = (prev_dir == 1 and cur_dir == -1)

            if flipped_bullish and trend_strong:
                self._stop_price = st_line  # stop below the supertrend line
                self._prev_direction = cur_dir
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"supertrend BUY flip: ST={st_line:.4f} ADX={adx:.1f}",
                    confidence=min(1.0, adx / 50),
                    metadata={"supertrend": st_line, "adx": adx, "stop": self._stop_price}
                )

            if flipped_bearish and trend_strong:
                self._stop_price = st_line  # stop above the supertrend line
                self._prev_direction = cur_dir
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"supertrend SHORT flip: ST={st_line:.4f} ADX={adx:.1f}",
                    confidence=min(1.0, adx / 50),
                    metadata={"supertrend": st_line, "adx": adx, "stop": self._stop_price}
                )

            self._prev_direction = cur_dir

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold dir={cur_dir} ADX={adx:.1f} ST={st_line:.4f}",
                           metadata={"direction": cur_dir, "adx": adx, "supertrend": st_line})

    def get_params(self) -> dict:
        return {
            "atr_period": self.atr_period,
            "multiplier": self.multiplier,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "atr_period": [7, 10, 14],
            "multiplier": [2.0, 2.5, 3.0, 3.5],
            "adx_threshold": [15.0, 20.0, 25.0],
        }

    def save_state(self) -> dict:
        return {
            "prev_direction": self._prev_direction,
            "stop_price": self._stop_price,
        }

    def load_state(self, state: dict):
        self._prev_direction = state.get("prev_direction")
        self._stop_price = state.get("stop_price")
