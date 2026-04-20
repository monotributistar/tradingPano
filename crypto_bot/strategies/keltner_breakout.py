"""
Keltner Channel Breakout Strategy (Kraken Futures — Directional / Momentum)
============================================================================
Keltner Channels place upper/lower bands around an EMA using ATR multiples
(rather than std-dev like Bollinger Bands). Because ATR is smoothed and
non-volatile, Keltner bands define a steadier trend envelope.

Mechanism:
  - Middle band : EMA(ema_period)
  - Upper band  : EMA + kc_mult × ATR(atr_period)
  - Lower band  : EMA − kc_mult × ATR(atr_period)

  - LONG  : candle CLOSES above the upper band (momentum breakout confirmed)
            AND EMA is sloping upward (slope > 0 over slope_bars bars)
            AND volume ≥ vol_mult × average volume
  - SHORT : candle CLOSES below the lower band
            AND EMA is sloping downward
            AND volume confirmation
  - EXIT  : price reverts back inside the channel mid-line (EMA)
            OR ATR-based trailing stop is hit
            OR RSI hits overbought/oversold reversal threshold (optional filter)

Why this differs from bb_squeeze / breakout:
  - bb_squeeze: trades the volatility EXPANSION after a compression phase.
  - breakout (Donchian): uses prior highs/lows as the trigger.
  - keltner_breakout: uses a smoothed ATR envelope — more stable than BB
    in trending markets, fires fewer false positives because the bands
    expand with real volatility (ATR) rather than recent price swings.

Key references: Chester Keltner (1960), Linda Bradford Raschke modernisation.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class KeltnerBreakoutStrategy(BaseStrategy):
    name = "keltner_breakout"
    description = "Keltner Channel breakout — rompimiento de banda ATR con confirmación de volumen"
    ideal_timeframes: list = ["1h", "4h", "1d"]
    min_period: str = "2m"
    market_type: str = "trending"
    trade_frequency: str = "medium"
    min_liquidity: str = "medium"
    suitable_timeframes: list = ["1h", "4h", "1d"]
    suitable_market_conditions: list = ["trending", "breakout", "high_vol"]
    recommended_leverage: float = 3.0
    max_leverage: float = 10.0
    risk_profile: dict = {
        "stop_loss_pct":     2.5,
        "take_profit_pct":   6.0,
        "position_size_pct": 5.0,
    }

    # ── Initialization ──────────────────────────────────────────────────────────

    def initialize(self, config: dict) -> None:
        self.ema_period     = config.get("ema_period", 20)
        self.atr_period     = config.get("atr_period", 10)
        self.kc_mult        = config.get("kc_mult", 2.0)
        self.slope_bars     = config.get("slope_bars", 5)
        self.vol_period     = config.get("vol_period", 20)
        self.vol_mult       = config.get("vol_mult", 1.3)
        self.vol_filter     = config.get("vol_filter", True)
        self.rsi_period     = config.get("rsi_period", 14)
        self.rsi_exit_long  = config.get("rsi_exit_long", 80)
        self.rsi_exit_short = config.get("rsi_exit_short", 20)
        self.rsi_filter     = config.get("rsi_filter", True)  # Don't enter if RSI already extreme
        self.stop_atr_mult  = config.get("stop_atr_mult", 2.0)
        self.tp_atr_mult    = config.get("tp_atr_mult", 4.0)
        self.max_bars_held  = config.get("max_bars_held", 50)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self.use_shorts     = config.get("use_shorts", True)

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

    def _rsi(self, close: pd.Series, period: int) -> float:
        delta = close.diff().dropna()
        gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    def _keltner(self, close: pd.Series, candles: pd.DataFrame) -> tuple[float, float, float]:
        """Returns (middle, upper, lower)."""
        ema_series = close.ewm(span=self.ema_period, adjust=False).mean()
        mid    = float(ema_series.iloc[-1])
        atr    = self._atr(candles, self.atr_period)
        upper  = mid + self.kc_mult * atr
        lower  = mid - self.kc_mult * atr
        return mid, upper, lower, float(ema_series.iloc[-self.slope_bars - 1]), atr

    # ── Signal generation ───────────────────────────────────────────────────────

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:

        needed = max(self.ema_period, self.atr_period, self.rsi_period, self.vol_period) + 10
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])

        mid, upper, lower, ema_prev, atr = self._keltner(close, candles)
        rsi_val = self._rsi(close, self.rsi_period)

        volume  = candles["volume"]
        avg_vol = float(volume.rolling(self.vol_period).mean().iloc[-1])
        cur_vol = float(volume.iloc[-1])
        vol_ok  = (not self.vol_filter) or (cur_vol >= avg_vol * self.vol_mult)

        ema_slope_up   = mid > ema_prev
        ema_slope_down = mid < ema_prev

        # ── MANAGE OPEN POSITION ─────────────────────────────────────────────
        if position is not None:
            self._bars_held += 1
            side = position.get("side", "long")

            if side == "long":
                if self._peak is None:
                    self._peak = price
                self._peak = max(self._peak, price)
                trailing_stop = self._peak - self.stop_atr_mult * atr

                if self._stop_price is not None and price <= self._stop_price:
                    s = self._stop_price; self.reset()
                    return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                       f"stop loss {s:.4f}", metadata={"atr": atr})

                if price <= trailing_stop:
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"trailing stop {trailing_stop:.4f}",
                                       metadata={"peak": self._peak, "atr": atr})

                if self._tp_price is not None and price >= self._tp_price:
                    tp = self._tp_price; self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"take profit {tp:.4f}", metadata={"atr": atr})

                # Reversion to mid-band
                if price <= mid:
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"reversion to EMA mid {mid:.4f}",
                                       metadata={"mid": round(mid, 4), "rsi": round(rsi_val, 2)})

                if self.rsi_filter and rsi_val >= self.rsi_exit_long:
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"RSI extreme exit: {rsi_val:.1f} >= {self.rsi_exit_long}",
                                       metadata={"rsi": round(rsi_val, 2)})

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

                if price >= mid:
                    self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"reversion to EMA mid {mid:.4f}",
                                       metadata={"mid": round(mid, 4), "rsi": round(rsi_val, 2)})

                if self.rsi_filter and rsi_val <= self.rsi_exit_short:
                    self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"RSI extreme exit: {rsi_val:.1f} <= {self.rsi_exit_short}",
                                       metadata={"rsi": round(rsi_val, 2)})

                if self._bars_held >= self.max_bars_held:
                    self.reset()
                    return TradeSignal(Signal.TIME_EXIT, pair, price, 0,
                                       f"time exit after {self._bars_held} bars")

        # ── NEW ENTRIES ──────────────────────────────────────────────────────
        else:
            self.reset()

            # LONG: close above upper band, slope up, volume confirmed
            not_rsi_overbought = (not self.rsi_filter) or rsi_val < self.rsi_exit_long
            if price > upper and ema_slope_up and vol_ok and not_rsi_overbought:
                stop = price - self.stop_atr_mult * atr
                tp   = price + self.tp_atr_mult   * atr
                self._stop_price = stop
                self._tp_price   = tp
                self._peak       = price
                self._bars_held  = 0
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"keltner long: {price:.4f} > upper {upper:.4f} RSI={rsi_val:.1f}",
                    confidence=min(1.0, (price - upper) / (atr + 1e-10) * 0.5),
                    metadata={
                        "kc_upper": round(upper, 4),
                        "kc_mid":   round(mid,   4),
                        "kc_lower": round(lower, 4),
                        "rsi":      round(rsi_val, 2),
                        "atr":      round(atr, 6),
                        "stop":     round(stop, 4),
                        "tp":       round(tp,   4),
                        "vol_ratio": round(cur_vol / (avg_vol + 1e-10), 2),
                    },
                )

            # SHORT: close below lower band, slope down, volume confirmed
            not_rsi_oversold = (not self.rsi_filter) or rsi_val > self.rsi_exit_short
            if self.use_shorts and price < lower and ema_slope_down and vol_ok and not_rsi_oversold:
                stop = price + self.stop_atr_mult * atr
                tp   = price - self.tp_atr_mult   * atr
                self._stop_price = stop
                self._tp_price   = tp
                self._peak       = price
                self._bars_held  = 0
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"keltner short: {price:.4f} < lower {lower:.4f} RSI={rsi_val:.1f}",
                    confidence=min(1.0, (lower - price) / (atr + 1e-10) * 0.5),
                    metadata={
                        "kc_upper": round(upper, 4),
                        "kc_mid":   round(mid,   4),
                        "kc_lower": round(lower, 4),
                        "rsi":      round(rsi_val, 2),
                        "atr":      round(atr, 6),
                        "stop":     round(stop, 4),
                        "tp":       round(tp,   4),
                        "vol_ratio": round(cur_vol / (avg_vol + 1e-10), 2),
                    },
                )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"hold: {lower:.4f} < {price:.4f} < {upper:.4f} RSI={rsi_val:.1f}",
            metadata={
                "kc_upper": round(upper, 4),
                "kc_mid":   round(mid,   4),
                "kc_lower": round(lower, 4),
                "rsi":      round(rsi_val, 2),
            },
        )

    # ── Introspection ────────────────────────────────────────────────────────────

    def get_params(self) -> dict:
        return {
            "ema_period":      self.ema_period,
            "atr_period":      self.atr_period,
            "kc_mult":         self.kc_mult,
            "slope_bars":      self.slope_bars,
            "vol_period":      self.vol_period,
            "vol_mult":        self.vol_mult,
            "rsi_period":      self.rsi_period,
            "rsi_exit_long":   self.rsi_exit_long,
            "rsi_exit_short":  self.rsi_exit_short,
            "stop_atr_mult":   self.stop_atr_mult,
            "tp_atr_mult":     self.tp_atr_mult,
            "amount_per_trade": self.amount_per_trade,
            "use_shorts":      self.use_shorts,
        }

    def get_param_grid(self) -> dict:
        return {
            "ema_period":    [14, 20, 30],
            "atr_period":    [7, 10, 14],
            "kc_mult":       [1.5, 2.0, 2.5],
            "vol_mult":      [1.1, 1.3, 1.5],
            "stop_atr_mult": [1.5, 2.0, 2.5],
            "tp_atr_mult":   [3.0, 4.0, 5.0],
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
