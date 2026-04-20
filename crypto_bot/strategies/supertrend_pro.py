"""
Supertrend Pro Strategy — Multi-timeframe Supertrend (institutional favorite 2026)

- Two Supertrend lines:
    * Fast (atr=7, mult=2.0)  → entry trigger
    * Slow (atr=21, mult=3.5) → macro trend filter + trailing stop
- BUY only when BOTH supertrends are bullish AND the fast one flipped bullish on this bar
- SHORT only when BOTH supertrends are bearish AND the fast one flipped bearish on this bar
- Exit LONG when fast flips bearish (SELL)
- Exit SHORT when fast flips bullish (COVER)
- ADX(14) > 20 filter to skip sideways markets
- ATR trailing stop anchored to the slow Supertrend line (trails up/down as trend continues)
- Iterative Supertrend with proper band-locking
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class SupertrendProStrategy(BaseStrategy):
    name = "supertrend_pro"
    description = "Multi-timeframe Supertrend con filtro ADX — favorita institucional 2026"
    ideal_timeframes: list = ["4h","1d"]
    min_period: str = "3m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['4h', '1d']
    suitable_market_conditions: list = ['trending']
    recommended_leverage: float = 3.0
    max_leverage: float = 12.0
    risk_profile: dict = {
        "stop_loss_pct":     3.0,
        "take_profit_pct":   8.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.atr_fast = int(config.get("atr_fast", 7))
        self.mult_fast = float(config.get("mult_fast", 2.0))
        self.atr_slow = int(config.get("atr_slow", 21))
        self.mult_slow = float(config.get("mult_slow", 3.5))
        self.adx_period = int(config.get("adx_period", 14))
        self.adx_threshold = float(config.get("adx_threshold", 20.0))
        self.amount_per_trade = float(config.get("amount_per_trade", 10.0))

        # Mutable state
        self._prev_fast_dir: Optional[int] = None
        self._prev_slow_dir: Optional[int] = None
        self._stop_price: Optional[float] = None  # slow-supertrend-based trailing stop

    def reset(self):
        self._prev_fast_dir = None
        self._prev_slow_dir = None
        self._stop_price = None

    # ── Indicators ─────────────────────────────────────────────────────────────
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

    def _compute_supertrend(
        self, candles: pd.DataFrame, period: int, multiplier: float
    ) -> tuple[pd.Series, pd.Series]:
        """Iterative Supertrend with band-locking.

        Returns (supertrend_line, direction_series): direction=1 bullish, -1 bearish.
        """
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        atr = self._atr(candles, period)
        hl2 = (high + low) / 2.0

        raw_upper = hl2 + multiplier * atr
        raw_lower = hl2 - multiplier * atr

        n = len(candles)
        upper = raw_upper.copy()
        lower = raw_lower.copy()
        direction = pd.Series(1, index=candles.index, dtype=int)
        st = pd.Series(np.nan, index=candles.index)

        for i in range(1, n):
            # Lock upper band: cannot rise during downtrend until broken
            if (
                raw_upper.iloc[i] < upper.iloc[i - 1]
                or close.iloc[i - 1] > upper.iloc[i - 1]
            ):
                upper.iloc[i] = raw_upper.iloc[i]
            else:
                upper.iloc[i] = upper.iloc[i - 1]

            # Lock lower band: cannot fall during uptrend until broken
            if (
                raw_lower.iloc[i] > lower.iloc[i - 1]
                or close.iloc[i - 1] < lower.iloc[i - 1]
            ):
                lower.iloc[i] = raw_lower.iloc[i]
            else:
                lower.iloc[i] = lower.iloc[i - 1]

            prev_dir = direction.iloc[i - 1]
            if prev_dir == -1 and close.iloc[i] > upper.iloc[i]:
                direction.iloc[i] = 1
            elif prev_dir == 1 and close.iloc[i] < lower.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = prev_dir

            st.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]

        st.iloc[0] = lower.iloc[0] if direction.iloc[0] == 1 else upper.iloc[0]
        return st, direction

    # ── Core ───────────────────────────────────────────────────────────────────
    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = max(self.atr_fast, self.atr_slow, self.adx_period) * 3 + 10
        if len(candles) < needed:
            return TradeSignal(
                Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup"
            )

        close = candles["close"]
        price = float(close.iloc[-1])
        if price != price:  # NaN guard
            return TradeSignal(Signal.HOLD, pair, 0.0, 0, "nan price")

        st_fast, dir_fast = self._compute_supertrend(candles, self.atr_fast, self.mult_fast)
        st_slow, dir_slow = self._compute_supertrend(candles, self.atr_slow, self.mult_slow)
        adx = self._adx(candles)

        cur_fast = int(dir_fast.iloc[-1])
        prev_fast = int(dir_fast.iloc[-2])
        cur_slow = int(dir_slow.iloc[-1])

        st_fast_val = float(st_fast.iloc[-1])
        st_slow_val = float(st_slow.iloc[-1])
        st_fast_val = st_fast_val if st_fast_val == st_fast_val else price
        st_slow_val = st_slow_val if st_slow_val == st_slow_val else price

        trend_strong = adx >= self.adx_threshold
        current_side = position.get("side") if position else None

        # ── MANAGE LONG ────────────────────────────────────────────────────────
        if current_side == "long":
            # Exit on fast flip bearish
            if cur_fast == -1:
                self._prev_fast_dir = cur_fast
                self._prev_slow_dir = cur_slow
                self._stop_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"fast ST flip bearish: fastST={st_fast_val:.4f} ADX={adx:.1f}",
                    metadata={"st_fast": st_fast_val, "st_slow": st_slow_val,
                              "dir_fast": cur_fast, "dir_slow": cur_slow, "adx": adx}
                )

            # Update trailing stop to max(prev_stop, slow ST) while in uptrend
            if cur_slow == 1:
                if self._stop_price is None or st_slow_val > self._stop_price:
                    self._stop_price = st_slow_val

            if self._stop_price is not None and price <= self._stop_price:
                s = self._stop_price
                self._prev_fast_dir = cur_fast
                self._prev_slow_dir = cur_slow
                self._stop_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"long trailing stop hit {s:.4f}",
                    metadata={"stop": s, "st_slow": st_slow_val, "adx": adx}
                )

        # ── MANAGE SHORT ───────────────────────────────────────────────────────
        elif current_side == "short":
            # Exit on fast flip bullish
            if cur_fast == 1:
                self._prev_fast_dir = cur_fast
                self._prev_slow_dir = cur_slow
                self._stop_price = None
                return TradeSignal(
                    Signal.COVER, pair, price, 0,
                    f"fast ST flip bullish: fastST={st_fast_val:.4f} ADX={adx:.1f}",
                    metadata={"st_fast": st_fast_val, "st_slow": st_slow_val,
                              "dir_fast": cur_fast, "dir_slow": cur_slow, "adx": adx}
                )

            # Trailing stop: min(prev_stop, slow ST) while downtrend
            if cur_slow == -1:
                if self._stop_price is None or st_slow_val < self._stop_price:
                    self._stop_price = st_slow_val

            if self._stop_price is not None and price >= self._stop_price:
                s = self._stop_price
                self._prev_fast_dir = cur_fast
                self._prev_slow_dir = cur_slow
                self._stop_price = None
                return TradeSignal(
                    Signal.COVER, pair, price, 0,
                    f"short trailing stop hit {s:.4f}",
                    metadata={"stop": s, "st_slow": st_slow_val, "adx": adx}
                )

        # ── NO POSITION: look for aligned flip ─────────────────────────────────
        else:
            flipped_bull = (prev_fast == -1 and cur_fast == 1)
            flipped_bear = (prev_fast == 1 and cur_fast == -1)

            if flipped_bull and cur_slow == 1 and trend_strong:
                self._stop_price = st_slow_val
                self._prev_fast_dir = cur_fast
                self._prev_slow_dir = cur_slow
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"ST-Pro BUY: fastST={st_fast_val:.4f} slowST={st_slow_val:.4f} ADX={adx:.1f}",
                    confidence=min(1.0, adx / 50.0),
                    metadata={"st_fast": st_fast_val, "st_slow": st_slow_val,
                              "adx": adx, "stop": self._stop_price}
                )

            if flipped_bear and cur_slow == -1 and trend_strong:
                self._stop_price = st_slow_val
                self._prev_fast_dir = cur_fast
                self._prev_slow_dir = cur_slow
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"ST-Pro SHORT: fastST={st_fast_val:.4f} slowST={st_slow_val:.4f} ADX={adx:.1f}",
                    confidence=min(1.0, adx / 50.0),
                    metadata={"st_fast": st_fast_val, "st_slow": st_slow_val,
                              "adx": adx, "stop": self._stop_price}
                )

            self._prev_fast_dir = cur_fast
            self._prev_slow_dir = cur_slow

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold fast={cur_fast} slow={cur_slow} ADX={adx:.1f}",
            metadata={"st_fast": st_fast_val, "st_slow": st_slow_val,
                      "dir_fast": cur_fast, "dir_slow": cur_slow, "adx": adx}
        )

    def get_params(self) -> dict:
        return {
            "atr_fast": self.atr_fast,
            "mult_fast": self.mult_fast,
            "atr_slow": self.atr_slow,
            "mult_slow": self.mult_slow,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "atr_fast": [5, 7, 10],
            "mult_fast": [1.5, 2.0, 2.5],
            "atr_slow": [14, 21, 28],
            "mult_slow": [3.0, 3.5, 4.0],
            "adx_threshold": [15.0, 20.0, 25.0],
        }

    def save_state(self) -> dict:
        return {
            "prev_fast_dir": self._prev_fast_dir,
            "prev_slow_dir": self._prev_slow_dir,
            "stop_price": self._stop_price,
        }

    def load_state(self, state: dict):
        self._prev_fast_dir = state.get("prev_fast_dir")
        self._prev_slow_dir = state.get("prev_slow_dir")
        self._stop_price = state.get("stop_price")
