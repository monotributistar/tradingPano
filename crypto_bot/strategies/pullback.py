"""
Pullback Trading Strategy (Kraken Futures Strategies)
=======================================================
Concept: Buy dips within an established uptrend; short rallies within a downtrend.
Price must be trending (above/below slow EMA), then pull back toward the fast EMA
zone — when RSI shows oversold/overbought exhaustion at that level, enter in the
direction of the primary trend.

Entry conditions (LONG):
  - Price is above slow EMA (primary uptrend)
  - Price has pulled back to within `pullback_tolerance_pct` % of the fast EMA
  - RSI(rsi_period) < rsi_oversold (exhaustion at support)
  - Volume is above its N-bar average (confirms genuine bounce, not dead cat)

Entry conditions (SHORT):
  - Price is below slow EMA (primary downtrend)
  - Price has rallied to within `pullback_tolerance_pct` % of the fast EMA (from above)
  - RSI > rsi_overbought
  - Volume confirmation

Exit:
  - Trailing stop: peak-price − stop_atr_mult × ATR (long) or trough + stop_atr_mult × ATR (short)
  - Take profit: tp_atr_mult × ATR from entry
  - RSI overshoot exit: RSI > rsi_exit_long (long) or RSI < rsi_exit_short (short)
  - Max bars held safety exit

Edge: systematic dip-buying in the direction of the trend is one of the
      highest-probability patterns in trend-following literature.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class PullbackStrategy(BaseStrategy):
    name = "pullback"
    description = "Compra pullbacks en tendencia — rebote al EMA rápido con RSI agotado"
    ideal_timeframes: list = ["1h", "4h", "1d"]
    min_period: str = "2m"
    market_type: str = "trending"
    trade_frequency: str = "medium"
    min_liquidity: str = "medium"
    suitable_timeframes: list = ["1h", "4h", "1d"]
    suitable_market_conditions: list = ["trending", "pullback"]
    recommended_leverage: float = 2.5
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   5.0,
        "position_size_pct": 5.0,
    }

    # ── Initialization ──────────────────────────────────────────────────────────

    def initialize(self, config: dict) -> None:
        self.fast_ema      = config.get("fast_ema", 21)
        self.slow_ema      = config.get("slow_ema", 50)
        self.rsi_period    = config.get("rsi_period", 14)
        self.rsi_oversold  = config.get("rsi_oversold", 35)
        self.rsi_overbought = config.get("rsi_overbought", 65)
        self.rsi_exit_long = config.get("rsi_exit_long", 70)
        self.rsi_exit_short = config.get("rsi_exit_short", 30)
        # How close price must be to fast EMA to count as "at the pullback zone"
        self.pullback_tol  = config.get("pullback_tolerance_pct", 1.5)
        self.vol_period    = config.get("vol_period", 20)
        self.vol_filter    = config.get("vol_filter", True)
        self.atr_period    = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 2.0)
        self.tp_atr_mult   = config.get("tp_atr_mult", 3.5)
        self.max_bars_held = config.get("max_bars_held", 40)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self.use_shorts    = config.get("use_shorts", True)

        self._stop_price: Optional[float] = None
        self._tp_price:   Optional[float] = None
        self._peak:       Optional[float] = None
        self._bars_held:  int = 0

    def reset(self) -> None:
        self._stop_price = None
        self._tp_price   = None
        self._peak       = None
        self._bars_held  = 0

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _rsi(self, close: pd.Series, period: int) -> float:
        delta  = close.diff().dropna()
        gain   = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss   = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs     = gain / loss.replace(0, np.nan)
        rsi    = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

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

    # ── Signal generation ───────────────────────────────────────────────────────

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:

        needed = max(self.slow_ema, self.rsi_period, self.vol_period) + 10
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close  = candles["close"]
        price  = float(close.iloc[-1])

        fast_ema_val = float(close.ewm(span=self.fast_ema, adjust=False).mean().iloc[-1])
        slow_ema_val = float(close.ewm(span=self.slow_ema, adjust=False).mean().iloc[-1])
        rsi_val      = self._rsi(close, self.rsi_period)
        atr          = self._atr(candles, self.atr_period)

        volume    = candles["volume"]
        avg_vol   = float(volume.rolling(self.vol_period).mean().iloc[-1])
        cur_vol   = float(volume.iloc[-1])
        vol_ok    = (not self.vol_filter) or (cur_vol >= avg_vol * 0.9)

        in_uptrend   = price > slow_ema_val
        in_downtrend = price < slow_ema_val

        # Distance from price to fast EMA as % of price
        dist_pct = abs(price - fast_ema_val) / price * 100

        # ── MANAGE OPEN POSITION ─────────────────────────────────────────────
        if position is not None:
            self._bars_held += 1
            side = position.get("side", "long")

            if side == "long":
                # Update peak for trailing stop
                if self._peak is None:
                    self._peak = price
                self._peak = max(self._peak, price)
                trailing_stop = self._peak - self.stop_atr_mult * atr

                # Hard stop
                if self._stop_price is not None and price <= self._stop_price:
                    s = self._stop_price; self.reset()
                    return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                       f"stop loss {s:.4f}", metadata={"atr": atr})

                # Trailing stop
                if price <= trailing_stop:
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"trailing stop {trailing_stop:.4f}",
                                       metadata={"peak": self._peak, "atr": atr})

                # Take profit
                if self._tp_price is not None and price >= self._tp_price:
                    tp = self._tp_price; self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"take profit {tp:.4f}", metadata={"atr": atr})

                # RSI overshoot exit
                if rsi_val >= self.rsi_exit_long:
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"RSI overbought exit: RSI={rsi_val:.1f}",
                                       metadata={"rsi": rsi_val})

                # Time exit
                if self._bars_held >= self.max_bars_held:
                    self.reset()
                    return TradeSignal(Signal.TIME_EXIT, pair, price, 0,
                                       f"time exit after {self._bars_held} bars")

            else:  # short
                if self._peak is None:
                    self._peak = price
                self._peak = min(self._peak, price)
                trailing_stop = self._peak + self.stop_atr_mult * atr

                if self._stop_price is not None and price >= self._stop_price:
                    s = self._stop_price; self.reset()
                    return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                       f"stop loss {s:.4f}", metadata={"atr": atr})

                if price >= trailing_stop:
                    self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"trailing stop {trailing_stop:.4f}",
                                       metadata={"peak": self._peak, "atr": atr})

                if self._tp_price is not None and price <= self._tp_price:
                    tp = self._tp_price; self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"take profit {tp:.4f}", metadata={"atr": atr})

                if rsi_val <= self.rsi_exit_short:
                    self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"RSI oversold exit: RSI={rsi_val:.1f}",
                                       metadata={"rsi": rsi_val})

                if self._bars_held >= self.max_bars_held:
                    self.reset()
                    return TradeSignal(Signal.TIME_EXIT, pair, price, 0,
                                       f"time exit after {self._bars_held} bars")

        # ── NEW ENTRIES ──────────────────────────────────────────────────────
        else:
            self.reset()

            # LONG — price is in uptrend and has pulled back to fast EMA zone
            if in_uptrend and dist_pct <= self.pullback_tol and rsi_val <= self.rsi_oversold and vol_ok:
                stop = price - self.stop_atr_mult * atr
                tp   = price + self.tp_atr_mult   * atr
                self._stop_price = stop
                self._tp_price   = tp
                self._peak       = price
                self._bars_held  = 0
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"pullback long: price={price:.4f} fast_ema={fast_ema_val:.4f} "
                    f"dist={dist_pct:.1f}% RSI={rsi_val:.1f}",
                    confidence=min(1.0, (self.rsi_oversold - rsi_val) / self.rsi_oversold),
                    metadata={
                        "fast_ema": round(fast_ema_val, 4),
                        "slow_ema": round(slow_ema_val, 4),
                        "rsi": round(rsi_val, 2),
                        "atr": round(atr, 6),
                        "stop": round(stop, 4),
                        "tp":   round(tp,   4),
                        "dist_pct": round(dist_pct, 2),
                    },
                )

            # SHORT — price is in downtrend and has rallied to fast EMA zone
            if self.use_shorts and in_downtrend and dist_pct <= self.pullback_tol \
                    and rsi_val >= self.rsi_overbought and vol_ok:
                stop = price + self.stop_atr_mult * atr
                tp   = price - self.tp_atr_mult   * atr
                self._stop_price = stop
                self._tp_price   = tp
                self._peak       = price
                self._bars_held  = 0
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"pullback short: price={price:.4f} fast_ema={fast_ema_val:.4f} "
                    f"dist={dist_pct:.1f}% RSI={rsi_val:.1f}",
                    confidence=min(1.0, (rsi_val - self.rsi_overbought) / (100 - self.rsi_overbought)),
                    metadata={
                        "fast_ema": round(fast_ema_val, 4),
                        "slow_ema": round(slow_ema_val, 4),
                        "rsi": round(rsi_val, 2),
                        "atr": round(atr, 6),
                        "stop": round(stop, 4),
                        "tp":   round(tp,   4),
                        "dist_pct": round(dist_pct, 2),
                    },
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold: trend={'up' if in_uptrend else 'down'} dist={dist_pct:.1f}% RSI={rsi_val:.1f}",
            metadata={
                "fast_ema": round(fast_ema_val, 4),
                "slow_ema": round(slow_ema_val, 4),
                "rsi": round(rsi_val, 2),
                "dist_pct": round(dist_pct, 2),
            },
        )

    # ── Introspection ────────────────────────────────────────────────────────────

    def get_params(self) -> dict:
        return {
            "fast_ema":            self.fast_ema,
            "slow_ema":            self.slow_ema,
            "rsi_period":          self.rsi_period,
            "rsi_oversold":        self.rsi_oversold,
            "rsi_overbought":      self.rsi_overbought,
            "pullback_tolerance_pct": self.pullback_tol,
            "atr_period":          self.atr_period,
            "stop_atr_mult":       self.stop_atr_mult,
            "tp_atr_mult":         self.tp_atr_mult,
            "amount_per_trade":    self.amount_per_trade,
            "use_shorts":          self.use_shorts,
        }

    def get_param_grid(self) -> dict:
        return {
            "fast_ema":            [13, 21, 34],
            "slow_ema":            [50, 100, 200],
            "rsi_oversold":        [30, 35, 40],
            "rsi_overbought":      [60, 65, 70],
            "pullback_tolerance_pct": [1.0, 1.5, 2.5],
            "stop_atr_mult":       [1.5, 2.0, 2.5],
            "tp_atr_mult":         [2.5, 3.5, 5.0],
        }

    def save_state(self) -> dict:
        return {
            "stop_price": self._stop_price,
            "tp_price":   self._tp_price,
            "peak":       self._peak,
            "bars_held":  self._bars_held,
        }

    def load_state(self, state: dict) -> None:
        self._stop_price = state.get("stop_price")
        self._tp_price   = state.get("tp_price")
        self._peak       = state.get("peak")
        self._bars_held  = state.get("bars_held", 0)
