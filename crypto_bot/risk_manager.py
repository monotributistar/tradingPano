"""
crypto_bot/risk_manager.py — Risk management
=============================================

Controls enforced on every trade signal:
  - ATR-based or fixed position sizing
  - Leverage multiplier (hard-capped at 3×)
  - Daily loss auto-stop
  - Max concurrent open positions
  - Max drawdown from equity peak  (NEW)
  - Max trades per day             (NEW)
  - Max consecutive losses         (NEW)
  - Blackout hours (UTC)           (NEW)

Configuration (config.yaml → risk section)
------------------------------------------
    risk:
      leverage: 1.0
      position_sizing: fixed          # fixed | atr_volatility
      max_concurrent_positions: 3
      daily_loss_stop_pct: 5.0

      # Phase 2 circuit breakers
      max_drawdown_pct: 20.0          # halt if equity drops > X% from peak ever
      max_daily_trades: 20            # halt after N trades in one UTC day
      max_consecutive_losses: 5       # pause after N losses in a row
      blackout_hours: "22:00-06:00"   # skip new entries during these UTC hours
                                      # format: "HH:MM-HH:MM", leave blank to disable

All ``check_*`` methods return ``(halted: bool, reason: str)``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

MAX_LEVERAGE_CAP = 15.0
"""Global hard cap on leverage — no strategy or config can exceed this."""


class RiskManager:
    """
    Enforces configurable risk rules for both paper and live trading.
    Used by the backtester (per-bar) and the live bot (per-signal).

    Per-strategy risk overrides
    ---------------------------
    Pass ``strategy_risk_profile`` (from ``BaseStrategy.risk_profile`` plus the
    strategy's ``max_leverage`` / ``recommended_leverage`` class attrs) to let
    individual strategies adjust their own leverage and loss limits.

    Rules:
    - Strategy ``leverage`` may exceed the global config value up to its own
      ``max_leverage``, but never beyond ``MAX_LEVERAGE_CAP`` (15×).
    - Strategy ``max_drawdown_pct`` / ``max_daily_loss_pct`` can only *tighten*
      global limits (lower value wins), not loosen them.
    """

    def __init__(
        self,
        config: dict,
        initial_capital: float,
        strategy_risk_profile: dict | None = None,
    ):
        risk_cfg = config.get("risk", {})
        srp = strategy_risk_profile or {}

        # ── Basic controls ─────────────────────────────────────────────────────
        # Strategy can override leverage up to its own max_leverage, but the
        # global MAX_LEVERAGE_CAP is the absolute ceiling.
        global_leverage   = float(risk_cfg.get("leverage", 1.0))
        strategy_leverage = float(srp.get("leverage", global_leverage))
        strat_max         = float(srp.get("max_leverage", MAX_LEVERAGE_CAP))
        self.leverage = min(MAX_LEVERAGE_CAP, strat_max, max(global_leverage, strategy_leverage))
        self.position_sizing       = risk_cfg.get("position_sizing", "fixed")
        self.risk_per_trade_pct    = float(
            config.get("position_sizing", {})
            .get("atr_volatility", {})
            .get("risk_per_trade_pct", 1.0)
        )
        # Strategy can tighten (lower) daily_loss_stop; cannot loosen it.
        global_daily_loss = float(risk_cfg.get("daily_loss_stop_pct", 5.0))
        strat_daily_loss  = float(srp.get("max_daily_loss_pct", global_daily_loss))
        self.daily_loss_stop_pct = (
            min(global_daily_loss, strat_daily_loss)
            if global_daily_loss > 0 else strat_daily_loss
        )

        self.max_concurrent_positions = int(
            risk_cfg.get("max_concurrent_positions", 3)
        )

        # ── Phase 2 circuit breakers ──────────────────────────────────────────
        global_dd   = float(risk_cfg.get("max_drawdown_pct", 0))
        strat_dd    = float(srp.get("max_drawdown_pct", global_dd))
        self.max_drawdown_pct = (
            min(global_dd, strat_dd) if global_dd > 0 else strat_dd
        )
        self.max_daily_trades      = int(risk_cfg.get("max_daily_trades", 0))
        self.max_consecutive_losses = int(risk_cfg.get("max_consecutive_losses", 0))

        # "HH:MM-HH:MM" UTC — empty string = disabled
        _bh = str(risk_cfg.get("blackout_hours", "")).strip()
        self._blackout_start, self._blackout_end = _parse_blackout(_bh)

        # ── Internal state ────────────────────────────────────────────────────
        self.initial_capital      = initial_capital
        self._peak_equity: float  = initial_capital
        self._day_start_equity: Optional[float] = None
        self._current_day: Optional[str]        = None
        self._halted              = False
        self._halt_reason: Optional[str]        = None

        # Day-scoped counters
        self._daily_trades: int   = 0
        self._consecutive_losses: int = 0

    # ── POSITION SIZING ────────────────────────────────────────────────────────

    def compute_position_size(
        self,
        base_amount_usd: float,
        current_equity: float,
        atr: Optional[float] = None,
        price: Optional[float] = None,
    ) -> float:
        """
        Return the USD amount to risk on this trade.

        Applies leverage, ATR-volatility sizing, and a 50 % safety cap.
        """
        if self.position_sizing == "atr_volatility" and atr and price and atr > 0:
            atr_stop_mult = 2.0
            risk_usd = current_equity * (self.risk_per_trade_pct / 100.0)
            qty      = risk_usd / (atr_stop_mult * atr)
            amount   = qty * price
        else:
            amount = base_amount_usd

        amount *= self.leverage
        max_allowed = current_equity * 0.5 * self.leverage
        amount = min(amount, max_allowed)
        amount = max(1.0, amount)
        return round(amount, 2)

    # ── CIRCUIT BREAKERS ───────────────────────────────────────────────────────

    def check_all(
        self,
        current_equity: float,
        timestamp,
        trade_type: Optional[str] = None,
        trade_pnl: Optional[float] = None,
    ) -> tuple[bool, str]:
        """
        Run all risk checks in order.  Returns ``(halted, reason)`` on the
        **first** failing rule.  Updates internal counters on every call.

        Call this once per candle (or per signal).

        Parameters
        ----------
        current_equity  Current portfolio equity in USDT
        timestamp       Bar timestamp (str, pd.Timestamp, or datetime)
        trade_type      'win' | 'loss' | None — updates consecutive-loss counter
        trade_pnl       Trade P&L for logging (optional)
        """
        dt = _to_datetime(timestamp)
        self._maybe_reset_day(current_equity, dt)

        # Update peak
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # Update consecutive loss counter
        if trade_type == "loss":
            self._consecutive_losses += 1
        elif trade_type == "win":
            self._consecutive_losses = 0

        # Count trade
        if trade_type is not None:
            self._daily_trades += 1

        # ── 1. Already halted ──────────────────────────────────────────────
        if self._halted:
            return True, self._halt_reason or "halted"

        # ── 2. Daily loss stop ─────────────────────────────────────────────
        if self._day_start_equity and self._day_start_equity > 0:
            loss_pct = (
                (self._day_start_equity - current_equity) / self._day_start_equity * 100
            )
            if loss_pct >= self.daily_loss_stop_pct:
                reason = (
                    f"daily loss stop: -{loss_pct:.2f}% ≥ -{self.daily_loss_stop_pct}%"
                )
                return self._halt(reason)

        # ── 3. Max drawdown from peak ──────────────────────────────────────
        if self.max_drawdown_pct > 0 and self._peak_equity > 0:
            dd_pct = (self._peak_equity - current_equity) / self._peak_equity * 100
            if dd_pct >= self.max_drawdown_pct:
                reason = (
                    f"max drawdown: -{dd_pct:.2f}% ≥ -{self.max_drawdown_pct}% "
                    f"(peak={self._peak_equity:.2f})"
                )
                return self._halt(reason)

        # ── 4. Max daily trades ────────────────────────────────────────────
        if self.max_daily_trades > 0 and self._daily_trades >= self.max_daily_trades:
            reason = (
                f"max daily trades: {self._daily_trades}/{self.max_daily_trades}"
            )
            return self._halt(reason)

        # ── 5. Max consecutive losses ──────────────────────────────────────
        if (
            self.max_consecutive_losses > 0
            and self._consecutive_losses >= self.max_consecutive_losses
        ):
            reason = (
                f"max consecutive losses: "
                f"{self._consecutive_losses}/{self.max_consecutive_losses}"
            )
            return self._halt(reason)

        # ── 6. Blackout hours ──────────────────────────────────────────────
        if self._in_blackout(dt):
            # Not a hard halt — just skip this signal
            return True, f"blackout hours ({self._blackout_start}–{self._blackout_end} UTC)"

        return False, ""

    # Legacy method — kept for backtester compatibility
    def check_daily_loss(
        self, current_equity: float, timestamp
    ) -> tuple[bool, str]:
        """Backwards-compatible wrapper; use check_all() for full suite."""
        return self.check_all(current_equity, timestamp)

    # ── MAX CONCURRENT POSITIONS ───────────────────────────────────────────────

    def can_open_new_position(
        self, current_positions_count: int
    ) -> tuple[bool, str]:
        if current_positions_count >= self.max_concurrent_positions:
            return False, (
                f"max positions reached "
                f"({current_positions_count}/{self.max_concurrent_positions})"
            )
        return True, ""

    # ── INFO ───────────────────────────────────────────────────────────────────

    def info(self) -> dict:
        return {
            "leverage":                self.leverage,
            "position_sizing":         self.position_sizing,
            "daily_loss_stop_pct":     self.daily_loss_stop_pct,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_drawdown_pct":        self.max_drawdown_pct,
            "max_daily_trades":        self.max_daily_trades,
            "max_consecutive_losses":  self.max_consecutive_losses,
            "blackout_hours":          (
                f"{self._blackout_start}–{self._blackout_end}"
                if self._blackout_start else "disabled"
            ),
            "halted":                  self._halted,
            "halt_reason":             self._halt_reason,
            "day_start_equity":        self._day_start_equity,
            "peak_equity":             self._peak_equity,
            "daily_trades_today":      self._daily_trades,
            "consecutive_losses":      self._consecutive_losses,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _halt(self, reason: str) -> tuple[bool, str]:
        self._halted      = True
        self._halt_reason = reason
        logger.warning(f"[RiskManager] HALT: {reason}")
        return True, reason

    def _maybe_reset_day(self, current_equity: float, dt: datetime) -> None:
        day = dt.strftime("%Y-%m-%d")
        if self._current_day != day:
            self._current_day      = day
            self._day_start_equity = current_equity
            self._daily_trades     = 0
            # consecutive losses persist across days intentionally
            # (reset manually with reset_consecutive_losses() if desired)
            if self._halted and self._halt_reason and (
                "daily loss" in self._halt_reason
                or "daily trades" in self._halt_reason
            ):
                # Day-scoped halts reset at midnight
                self._halted      = False
                self._halt_reason = None
                logger.info("[RiskManager] Day-scoped halt reset at midnight UTC")

    def _in_blackout(self, dt: datetime) -> bool:
        if not self._blackout_start:
            return False
        current_hm = dt.strftime("%H:%M")
        if self._blackout_start <= self._blackout_end:
            # e.g. 01:00-06:00
            return self._blackout_start <= current_hm < self._blackout_end
        else:
            # Wraps midnight e.g. 22:00-06:00
            return current_hm >= self._blackout_start or current_hm < self._blackout_end

    def reset_consecutive_losses(self) -> None:
        """Manually reset the consecutive-loss counter (e.g. after a winning trade)."""
        self._consecutive_losses = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_datetime(timestamp) -> datetime:
    if isinstance(timestamp, str):
        try:
            return pd.Timestamp(timestamp).to_pydatetime().replace(tzinfo=timezone.utc)
        except Exception:
            pass
    if isinstance(timestamp, pd.Timestamp):
        return timestamp.to_pydatetime().replace(tzinfo=timezone.utc)
    if isinstance(timestamp, datetime):
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    return datetime.now(tz=timezone.utc)


def _parse_blackout(raw: str) -> tuple[str, str]:
    """
    Parse "HH:MM-HH:MM" → (start_str, end_str).
    Returns ("", "") on invalid / empty input.
    """
    raw = raw.strip()
    if not raw or "-" not in raw:
        return "", ""
    parts = raw.split("-", 1)
    if len(parts) != 2:
        return "", ""
    start, end = parts[0].strip(), parts[1].strip()
    # Basic validation
    try:
        datetime.strptime(start, "%H:%M")
        datetime.strptime(end, "%H:%M")
        return start, end
    except ValueError:
        logger.warning(f"[RiskManager] Invalid blackout_hours format: '{raw}'")
        return "", ""
