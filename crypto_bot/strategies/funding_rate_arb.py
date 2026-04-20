"""
Funding Rate Arbitrage Strategy — Delta-neutral passive income (simulated)

Real-world setup:
    * Long spot + Short perpetual → delta-neutral, collect positive funding.
    * Reverse on negative funding.

Since the backtester feeds us OHLCV only (no funding data), we SIMULATE the
funding rate from trend strength:
    funding_rate_est = clip( (fast_ema - slow_ema) / slow_ema, -0.001, 0.001 )
Interpreted as "funding rate per 8h interval" (0.1% cap per 8h).

Trading logic:
    * Bot opens a LONG (spot leg in a real hedge; perp short isn't simulated
      because the backtester has no perp book). Price exposure is treated as
      "hedged" — we still safety-stop on price drops as a rail.
    * Entry every `entry_check_bars` when abs(funding) >= min_funding and no
      position is open.
    * Exit when:
        - funding flips sign for `exit_flip_bars` consecutive bars
        - accumulated estimated profit ≥ take_profit_usd
        - bars_held ≥ max_hold_bars
        - price drops > emergency_stop_pct from entry (safety rail)

APY estimate reported in reason: funding * 3 * 365.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class FundingRateArbStrategy(BaseStrategy):
    name = "funding_rate_arb"
    description = "Delta-neutral funding rate arbitrage — ingreso pasivo simulado"
    ideal_timeframes: list = ["1d","1w"]
    min_period: str = "6m"
    market_type: str = "both"
    trade_frequency: str = "low"
    min_liquidity: str = "high"
    suitable_timeframes: list = ['4h', '1d']
    suitable_market_conditions: list = ['both']
    recommended_leverage: float = 1.0
    max_leverage: float = 3.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   3.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.fast_ema = int(config.get("fast_ema", 20))
        self.slow_ema = int(config.get("slow_ema", 50))
        self.min_funding = float(config.get("min_funding", 0.00005))
        self.exit_flip_bars = int(config.get("exit_flip_bars", 3))
        self.take_profit_usd = float(config.get("take_profit_usd", 0.5))
        self.max_hold_bars = int(config.get("max_hold_bars", 168))
        self.entry_check_bars = int(config.get("entry_check_bars", 24))
        self.emergency_stop_pct = float(config.get("emergency_stop_pct", 5.0))
        self.amount_per_trade = float(config.get("amount_per_trade", 10.0))

        # Assumed hours per bar — backtester normally runs on 1h, so ratio=1.
        # A funding interval is 8h → bars-per-funding-interval default 8.
        self.bar_hours = float(config.get("bar_hours", 1.0))

        # Mutable state
        self._flip_count: int = 0
        self._prev_funding_sign: int = 0
        self._bars_since_last_check: int = 0
        self._accum_profit: float = 0.0
        self._entry_price: Optional[float] = None
        self._entry_bar_idx: Optional[int] = None
        self._bars_held: int = 0

    def reset(self):
        self._flip_count = 0
        self._prev_funding_sign = 0
        self._bars_since_last_check = 0
        self._accum_profit = 0.0
        self._entry_price = None
        self._entry_bar_idx = None
        self._bars_held = 0

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _funding_rate_estimate(self, candles: pd.DataFrame) -> float:
        """Estimated funding rate per 8h interval, clipped to ±0.001."""
        close = candles["close"]
        fast = self._ema(close, self.fast_ema).iloc[-1]
        slow = self._ema(close, self.slow_ema).iloc[-1]
        if slow == 0 or slow != slow or fast != fast:
            return 0.0
        raw = (fast - slow) / slow
        if raw != raw:  # NaN
            return 0.0
        return float(np.clip(raw, -0.001, 0.001))

    def _bar_fraction(self) -> float:
        """Fraction of a funding interval (8h) represented by one bar."""
        return self.bar_hours / 8.0

    # ── Core ───────────────────────────────────────────────────────────────────
    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = max(self.fast_ema, self.slow_ema) + 5
        if len(candles) < needed:
            return TradeSignal(
                Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup"
            )

        price = float(candles["close"].iloc[-1])
        if price != price:
            return TradeSignal(Signal.HOLD, pair, 0.0, 0, "nan price")

        funding = self._funding_rate_estimate(candles)
        funding_bp = funding * 10000.0  # in basis points for display
        apy = funding * 3 * 365 * 100.0  # 3 intervals/day * 365 days * 100 %
        funding_sign = 1 if funding > 0 else (-1 if funding < 0 else 0)

        current_side = position.get("side") if position else None

        # ── MANAGE OPEN POSITION ───────────────────────────────────────────────
        if current_side == "long" and self._entry_price is not None:
            self._bars_held += 1

            # Accumulate estimated profit this bar
            qty = 0.0
            if position is not None:
                qty = float(position.get("qty", 0.0) or 0.0)
            # Fallback in case qty not provided
            if qty <= 0 and self._entry_price > 0:
                qty = self.amount_per_trade / self._entry_price

            bar_profit = qty * price * funding * self._bar_fraction()
            if bar_profit == bar_profit:  # NaN guard
                self._accum_profit += bar_profit

            # Funding flip counter
            if funding_sign != 0 and funding_sign != self._prev_funding_sign and self._prev_funding_sign != 0:
                self._flip_count += 1
            elif funding_sign == self._prev_funding_sign:
                # still same sign → reset flip run
                self._flip_count = 0
            self._prev_funding_sign = funding_sign if funding_sign != 0 else self._prev_funding_sign

            # Emergency safety stop
            if self._entry_price > 0:
                drawdown_pct = (self._entry_price - price) / self._entry_price * 100.0
                if drawdown_pct >= self.emergency_stop_pct:
                    reason = (f"funding_arb EMERGENCY stop: -{drawdown_pct:.2f}% "
                              f"accum=${self._accum_profit:.4f}")
                    self._reset_position_state()
                    return TradeSignal(
                        Signal.STOP_LOSS, pair, price, 0, reason,
                        metadata={"funding_bp": funding_bp, "apy_pct": apy,
                                  "accum_profit": self._accum_profit,
                                  "drawdown_pct": drawdown_pct}
                    )

            # Take-profit on accumulated funding
            if self._accum_profit >= self.take_profit_usd:
                reason = (f"funding_arb TP: accum=${self._accum_profit:.4f} "
                          f"≥ ${self.take_profit_usd:.2f}")
                accum = self._accum_profit
                self._reset_position_state()
                return TradeSignal(
                    Signal.SELL, pair, price, 0, reason,
                    metadata={"funding_bp": funding_bp, "apy_pct": apy,
                              "accum_profit": accum}
                )

            # Funding sign flipped for N bars
            if self._flip_count >= self.exit_flip_bars:
                reason = (f"funding_arb EXIT: funding flipped {self._flip_count} bars "
                          f"funding={funding_bp:.2f}bp accum=${self._accum_profit:.4f}")
                accum = self._accum_profit
                self._reset_position_state()
                return TradeSignal(
                    Signal.SELL, pair, price, 0, reason,
                    metadata={"funding_bp": funding_bp, "apy_pct": apy,
                              "accum_profit": accum}
                )

            # Max hold exceeded
            if self._bars_held >= self.max_hold_bars:
                reason = (f"funding_arb TIME EXIT: held={self._bars_held} bars "
                          f"accum=${self._accum_profit:.4f}")
                accum = self._accum_profit
                self._reset_position_state()
                return TradeSignal(
                    Signal.TIME_EXIT, pair, price, 0, reason,
                    metadata={"funding_bp": funding_bp, "apy_pct": apy,
                              "accum_profit": accum}
                )

            return TradeSignal(
                Signal.HOLD, pair, price, 0,
                f"funding_arb HOLD: funding={funding_bp:.2f}bp apy≈{apy:.1f}% "
                f"accum=${self._accum_profit:.4f} held={self._bars_held}",
                metadata={"funding_bp": funding_bp, "apy_pct": apy,
                          "accum_profit": self._accum_profit,
                          "bars_held": self._bars_held}
            )

        # ── NO POSITION ────────────────────────────────────────────────────────
        self._bars_since_last_check += 1

        if self._bars_since_last_check < self.entry_check_bars:
            return TradeSignal(
                Signal.HOLD, pair, price, 0,
                f"funding_arb WAIT: check in {self.entry_check_bars - self._bars_since_last_check} bars "
                f"(funding={funding_bp:.2f}bp)",
                metadata={"funding_bp": funding_bp, "apy_pct": apy}
            )

        # Time to check entry
        self._bars_since_last_check = 0

        if abs(funding) >= self.min_funding:
            # Enter LONG (spot leg of the delta-neutral pair)
            self._entry_price = price
            self._entry_bar_idx = len(candles) - 1
            self._bars_held = 0
            self._accum_profit = 0.0
            self._flip_count = 0
            self._prev_funding_sign = funding_sign

            reason = (f"funding_arb: funding_rate={funding_bp:.2f} bp, "
                      f"apy≈{apy:.1f}%")
            return TradeSignal(
                Signal.BUY, pair, price, self.amount_per_trade, reason,
                confidence=min(1.0, abs(funding) / 0.0005),
                metadata={"funding_bp": funding_bp, "apy_pct": apy,
                          "entry_price": price}
            )

        return TradeSignal(
            Signal.HOLD, pair, price, 0,
            f"funding_arb SKIP: |funding|={abs(funding_bp):.2f}bp < "
            f"{self.min_funding * 10000:.2f}bp",
            metadata={"funding_bp": funding_bp, "apy_pct": apy}
        )

    def _reset_position_state(self):
        self._entry_price = None
        self._entry_bar_idx = None
        self._bars_held = 0
        self._accum_profit = 0.0
        self._flip_count = 0
        self._prev_funding_sign = 0
        self._bars_since_last_check = 0

    def get_params(self) -> dict:
        return {
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "min_funding": self.min_funding,
            "exit_flip_bars": self.exit_flip_bars,
            "take_profit_usd": self.take_profit_usd,
            "max_hold_bars": self.max_hold_bars,
            "entry_check_bars": self.entry_check_bars,
            "emergency_stop_pct": self.emergency_stop_pct,
            "amount_per_trade": self.amount_per_trade,
            "bar_hours": self.bar_hours,
        }

    def get_param_grid(self) -> dict:
        return {
            "fast_ema": [10, 20, 30],
            "slow_ema": [40, 50, 80],
            "min_funding": [0.00001, 0.00005, 0.0001],
            "exit_flip_bars": [2, 3, 5],
            "take_profit_usd": [0.25, 0.5, 1.0],
            "max_hold_bars": [72, 168, 336],
            "entry_check_bars": [8, 24, 48],
            "emergency_stop_pct": [3.0, 5.0, 8.0],
        }

    def save_state(self) -> dict:
        return {
            "flip_count": self._flip_count,
            "prev_funding_sign": self._prev_funding_sign,
            "bars_since_last_check": self._bars_since_last_check,
            "accum_profit": self._accum_profit,
            "entry_price": self._entry_price,
            "entry_bar_idx": self._entry_bar_idx,
            "bars_held": self._bars_held,
        }

    def load_state(self, state: dict):
        self._flip_count = state.get("flip_count", 0)
        self._prev_funding_sign = state.get("prev_funding_sign", 0)
        self._bars_since_last_check = state.get("bars_since_last_check", 0)
        self._accum_profit = state.get("accum_profit", 0.0)
        self._entry_price = state.get("entry_price")
        self._entry_bar_idx = state.get("entry_bar_idx")
        self._bars_held = state.get("bars_held", 0)
