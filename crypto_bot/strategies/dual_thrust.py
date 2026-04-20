"""
Dual Thrust Intraday Strategy (Kraken Futures — Day Trading)
=============================================================
Classic algorithmic day-trading breakout system by Michael Chambers / Tudor Jones.

Mechanism:
  - Use the prior N bars to define a price range:
      HH = highest high over last N bars
      HC = highest close over last N bars
      LC = lowest close over last N bars
      LL = lowest low over last N bars
      Range = max(HH - LC, HC - LL)     # captures both intraday + close momentum
  - Upper trigger = open_of_period + k_upper × Range
  - Lower trigger = open_of_period − k_lower × Range

  - BUY  when price crosses above the upper trigger (momentum breakout upward)
  - SHORT when price crosses below the lower trigger (momentum breakdown)
  - EXIT at opposite trigger, ATR-based stop, or time_exit_bars safety net

Why this works for day-trading:
  The Range metric combines daily breadth (HH - LL) with close momentum (HC - LC).
  A tight prior range → a tight trigger → enters early on new moves.
  A wide prior range → trigger needs a strong breakout to be worth taking.

Parameters:
  - lookback (N)     : bars to compute Range (default 4 — typically 4 daily bars)
  - k_upper          : upper-trigger coefficient (default 0.7)
  - k_lower          : lower-trigger coefficient (default 0.7)
  - atr_period       : ATR period for stop sizing
  - stop_atr_mult    : stop = trigger ± stop_atr_mult × ATR
  - time_exit_bars   : hard exit after N bars (e.g. 8 on 1h = 8-hour max hold)
  - amount_per_trade : position size in USDT
  - use_shorts       : enable short side
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class DualThrustStrategy(BaseStrategy):
    name = "dual_thrust"
    description = "Dual Thrust intraday — breakout de rango previo (day trading)"
    ideal_timeframes: list = ["15m", "30m", "1h"]
    min_period: str = "1m"
    market_type: str = "both"
    trade_frequency: str = "high"
    min_liquidity: str = "high"
    suitable_timeframes: list = ["15m", "30m", "1h"]
    suitable_market_conditions: list = ["trending", "high_vol", "breakout"]
    recommended_leverage: float = 3.0
    max_leverage: float = 12.0
    risk_profile: dict = {
        "stop_loss_pct":     1.5,
        "take_profit_pct":   3.0,
        "position_size_pct": 6.0,
    }

    # ── Initialization ──────────────────────────────────────────────────────────

    def initialize(self, config: dict) -> None:
        self.lookback       = config.get("lookback", 4)
        self.k_upper        = config.get("k_upper", 0.7)
        self.k_lower        = config.get("k_lower", 0.7)
        self.atr_period     = config.get("atr_period", 14)
        self.stop_atr_mult  = config.get("stop_atr_mult", 1.5)
        self.time_exit_bars = config.get("time_exit_bars", 12)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self.use_shorts     = config.get("use_shorts", True)
        # Minimum range as pct of price — avoids tiny triggers in low-vol markets
        self.min_range_pct  = config.get("min_range_pct", 0.5)

        self._upper_trigger: Optional[float] = None
        self._lower_trigger: Optional[float] = None
        self._stop_price:    Optional[float] = None
        self._bars_held:     int = 0

    def reset(self) -> None:
        self._upper_trigger = None
        self._lower_trigger = None
        self._stop_price    = None
        self._bars_held     = 0

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _atr(self, candles: pd.DataFrame, period: int) -> float:
        high  = candles["high"]
        low   = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    def _compute_triggers(self, candles: pd.DataFrame) -> tuple[float, float, float]:
        """Returns (upper_trigger, lower_trigger, range_val)."""
        n = self.lookback

        # Use prior N bars (exclude current bar)
        window = candles.iloc[-(n + 1):-1]
        hh = float(window["high"].max())
        ll = float(window["low"].min())
        hc = float(window["close"].max())
        lc = float(window["close"].min())

        range_val = max(hh - lc, hc - ll)

        # Current bar's open as the session reference price
        open_price = float(candles["open"].iloc[-1])

        upper = open_price + self.k_upper * range_val
        lower = open_price - self.k_lower * range_val
        return upper, lower, range_val

    # ── Signal generation ───────────────────────────────────────────────────────

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:

        needed = max(self.lookback, self.atr_period) + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])
        atr   = self._atr(candles, self.atr_period)

        upper, lower, range_val = self._compute_triggers(candles)
        self._upper_trigger = upper
        self._lower_trigger = lower

        # Minimum range filter — skip if range is too small
        range_pct = range_val / price * 100
        if range_pct < self.min_range_pct:
            return TradeSignal(
                Signal.HOLD, pair, price, 0,
                f"range too small: {range_pct:.2f}% < {self.min_range_pct}%",
                metadata={"upper": round(upper, 4), "lower": round(lower, 4),
                          "range_pct": round(range_pct, 2)},
            )

        # ── MANAGE OPEN POSITION ─────────────────────────────────────────────
        if position is not None:
            self._bars_held += 1
            side = position.get("side", "long")

            # Hard stop
            if self._stop_price is not None:
                stop_hit = (side == "long"  and price <= self._stop_price) or \
                           (side == "short" and price >= self._stop_price)
                if stop_hit:
                    s = self._stop_price; self.reset()
                    return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                       f"stop loss {s:.4f}", metadata={"atr": atr})

            # Reverse — hit opposite trigger
            if side == "long" and price <= lower:
                self.reset()
                return TradeSignal(Signal.SELL, pair, price, 0,
                                   f"reverse: price {price:.4f} <= lower trigger {lower:.4f}",
                                   metadata={"upper": round(upper, 4), "lower": round(lower, 4)})

            if side == "short" and price >= upper:
                self.reset()
                return TradeSignal(Signal.COVER, pair, price, 0,
                                   f"reverse: price {price:.4f} >= upper trigger {upper:.4f}",
                                   metadata={"upper": round(upper, 4), "lower": round(lower, 4)})

            # Time exit (day-trading discipline)
            if self._bars_held >= self.time_exit_bars:
                self.reset()
                sig = Signal.SELL if side == "long" else Signal.COVER
                return TradeSignal(sig, pair, price, 0,
                                   f"time exit after {self._bars_held} bars")

        # ── NEW ENTRIES ──────────────────────────────────────────────────────
        else:
            self._bars_held = 0

            # Upper breakout → LONG
            if price >= upper:
                stop = price - self.stop_atr_mult * atr
                self._stop_price = stop
                self._bars_held  = 0
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"dual thrust long: {price:.4f} >= {upper:.4f} range={range_pct:.2f}%",
                    confidence=min(1.0, (price - upper) / (atr + 1e-10)),
                    metadata={
                        "upper_trigger": round(upper, 4),
                        "lower_trigger": round(lower, 4),
                        "range_val":  round(range_val, 4),
                        "range_pct":  round(range_pct, 2),
                        "stop":       round(stop, 4),
                        "atr":        round(atr, 6),
                    },
                )

            # Lower breakdown → SHORT
            if self.use_shorts and price <= lower:
                stop = price + self.stop_atr_mult * atr
                self._stop_price = stop
                self._bars_held  = 0
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"dual thrust short: {price:.4f} <= {lower:.4f} range={range_pct:.2f}%",
                    confidence=min(1.0, (lower - price) / (atr + 1e-10)),
                    metadata={
                        "upper_trigger": round(upper, 4),
                        "lower_trigger": round(lower, 4),
                        "range_val":  round(range_val, 4),
                        "range_pct":  round(range_pct, 2),
                        "stop":       round(stop, 4),
                        "atr":        round(atr, 6),
                    },
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold: {lower:.4f} < {price:.4f} < {upper:.4f} range={range_pct:.2f}%",
            metadata={"upper": round(upper, 4), "lower": round(lower, 4),
                      "range_pct": round(range_pct, 2)},
        )

    # ── Introspection ────────────────────────────────────────────────────────────

    def get_params(self) -> dict:
        return {
            "lookback":         self.lookback,
            "k_upper":          self.k_upper,
            "k_lower":          self.k_lower,
            "atr_period":       self.atr_period,
            "stop_atr_mult":    self.stop_atr_mult,
            "time_exit_bars":   self.time_exit_bars,
            "amount_per_trade": self.amount_per_trade,
            "min_range_pct":    self.min_range_pct,
            "use_shorts":       self.use_shorts,
        }

    def get_param_grid(self) -> dict:
        return {
            "lookback":      [3, 4, 6, 8],
            "k_upper":       [0.5, 0.6, 0.7, 0.8],
            "k_lower":       [0.5, 0.6, 0.7, 0.8],
            "stop_atr_mult": [1.0, 1.5, 2.0],
            "time_exit_bars": [6, 12, 18, 24],
        }

    def save_state(self) -> dict:
        return {
            "stop_price":    self._stop_price,
            "upper_trigger": self._upper_trigger,
            "lower_trigger": self._lower_trigger,
            "bars_held":     self._bars_held,
        }

    def load_state(self, state: dict) -> None:
        self._stop_price    = state.get("stop_price")
        self._upper_trigger = state.get("upper_trigger")
        self._lower_trigger = state.get("lower_trigger")
        self._bars_held     = state.get("bars_held", 0)
