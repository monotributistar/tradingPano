"""
api/portfolio_manager.py — Multi-strategy portfolio manager
============================================================

Runs multiple strategies simultaneously, each with:
  - Isolated capital allocation (capital_pct % of the total configured balance)
  - Independent daemon thread + stop event
  - Independent position tracking in DB
  - Aggregate status reported via ``/api/portfolio/*``

Portfolio configuration lives in ``config.yaml``:

    portfolio:
      enabled: true
      initial_balance: 100        # USDT to distribute across strategies
      strategies:
        - name: stoch_rsi
          capital_pct: 40          # 40 % = 40 USDT
          pairs: [BTC/USDT, ETH/USDT]
        - name: trend_following
          capital_pct: 30
          pairs: [SOL/USDT, NEAR/USDT]
        - name: grid_dynamic
          capital_pct: 30
          pairs: [ETH/USDT]

Threading model
---------------
  api-thread          →  FastAPI request handlers
  portfolio-slot-N    →  daemon thread per strategy slot
  portfolio-watchdog  →  daemon thread checking all slots every 60 s

Usage
-----
    from api.portfolio_manager import start_portfolio, stop_portfolio, portfolio_status

    start_portfolio(config, mode="paper")
    status = portfolio_status()   # list of slot statuses
    stop_portfolio()
"""

from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Module-level state ─────────────────────────────────────────────────────────

_lock = threading.Lock()
_slots: list[_Slot]                          = []
_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop: Optional[threading.Event]    = None
_portfolio_start_time: Optional[datetime]    = None


# ── Internal slot class ────────────────────────────────────────────────────────

class _Slot:
    """Represents one strategy running within the portfolio."""

    def __init__(self, index: int, slot_cfg: dict, global_cfg: dict, mode: str):
        self.index      = index
        self.name       = slot_cfg["name"]
        self.pairs      = slot_cfg.get("pairs", global_cfg.get("pairs", ["BTC/USDT"]))
        self.capital_pct = float(slot_cfg.get("capital_pct", 100.0 / max(1, index + 1)))
        self.mode       = mode

        # Build per-slot config — start from global, override strategy & capital
        self.config = deepcopy(global_cfg)
        self.config["strategy"] = self.name
        self.config["pairs"]    = self.pairs
        self.config["mode"]     = mode

        # Adjust initial balance by capital_pct
        base_balance = float(
            global_cfg.get("portfolio", {}).get("initial_balance", None)
            or global_cfg.get("paper", {}).get("initial_balance", 20.0)
        )
        slot_balance = round(base_balance * self.capital_pct / 100.0, 2)
        self.config.setdefault("paper", {})["initial_balance"] = slot_balance

        # Override strategy params with slot-specific params if provided
        strat_overrides = slot_cfg.get("params", {})
        if strat_overrides:
            self.config.setdefault("strategies", {}).setdefault(self.name, {}).update(strat_overrides)

        # Runtime state
        self.thread: Optional[threading.Thread] = None
        self.stop_event: Optional[threading.Event] = None
        self.started_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.crashed: bool = False
        self.trade_count: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        self.stop_event = threading.Event()
        self.started_at = datetime.now(tz=timezone.utc)
        self.error      = None
        self.crashed    = False

        self.thread = threading.Thread(
            target=self._run,
            name=f"portfolio-slot-{self.index}-{self.name}",
            daemon=True,
        )
        self.thread.start()
        logger.info(
            f"[Portfolio] Slot {self.index} started — strategy={self.name}, "
            f"pairs={self.pairs}, capital={self.capital_pct}%"
        )

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        logger.info(f"[Portfolio] Slot {self.index} ({self.name}) stop requested")

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ── Main loop ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """
        Trading loop for this slot.

        Uses the same ``on_candle / Signal`` API as bot_manager._load_and_run.
        Each slot manages its own ``positions`` dict independently.
        """
        import time as _time
        try:
            from api.main import get_strategy_registry
            from strategies.base import Signal
            from api.adapters.db_trade_logger import DBTradeLogger
            from api.anomaly_detector import AnomalyDetector
            from api.telegram_bot import get_notifier

            # Engine
            if self.mode == "live":
                from engine.live import LiveEngine
                engine = LiveEngine(self.config)
            else:
                from engine.paper import PaperEngine
                engine = PaperEngine(self.config)

            # Strategy
            registry = get_strategy_registry()
            if self.name not in registry:
                raise ValueError(f"Unknown strategy: {self.name}")
            strategy = registry[self.name]()
            strategy.initialize(self.config.get("strategies", {}).get(self.name, {}))

            # Trade logger
            trade_logger = DBTradeLogger(source=self.mode)

            # Anomaly detector
            detector = AnomalyDetector(self.config)
            try:
                detector.set_notifier(get_notifier())
            except Exception:
                pass

            timeframe       = self.config.get("backtest", {}).get("timeframe", "1h")
            tf_seconds      = _candle_seconds(timeframe)
            initial_balance = float(
                self.config.get("paper", {}).get("initial_balance", 20.0)
            )

            # Risk manager — each slot enforces its own circuit breakers
            from risk_manager import RiskManager
            from datetime import datetime, timezone as _tz
            risk = RiskManager(self.config, initial_balance)
            _last_halt_reason: Optional[str] = None

            positions: dict      = {}
            current_prices: dict = {}

            assert self.stop_event is not None
            logger.info(
                f"[Slot-{self.index}] Loop starting — strategy={self.name}, "
                f"pairs={self.pairs}, balance={initial_balance} USDT"
            )

            while not self.stop_event.is_set():

                # Per-cycle risk check
                now_dt = datetime.now(tz=_tz.utc)
                equity = _slot_equity(positions, current_prices, initial_balance)
                halted, halt_reason = risk.check_all(equity, now_dt)

                if halted:
                    is_blackout = "blackout" in halt_reason
                    if halt_reason != _last_halt_reason:
                        _last_halt_reason = halt_reason
                        logger.warning(f"[Slot-{self.index}] Risk halt: {halt_reason}")
                        if not is_blackout:
                            self._broadcast_event("halt", halt_reason)
                    if not is_blackout:
                        break  # hard halt — stop this slot
                    self.stop_event.wait(timeout=300)
                    _last_halt_reason = None
                    continue
                else:
                    _last_halt_reason = None

                for pair in self.pairs:
                    if self.stop_event.is_set():
                        break
                    try:
                        candles = engine.fetch_ohlcv(pair, timeframe, limit=200)
                        if not candles:
                            continue

                        last_price = candles[-1][4]
                        current_prices[pair] = last_price

                        if not detector.check_price_freshness(pair, last_price):
                            continue  # stale feed — skip signal

                        pos = positions.get(pair)
                        if pos:
                            pos["bars_held"] = pos.get("bars_held", 0) + 1

                        sig_obj = strategy.on_candle(pair, candles, pos)
                        sig     = sig_obj.signal

                        # LONG OPEN
                        if sig == Signal.BUY and sig_obj.amount_usd > 0:
                            can_open, block_reason = risk.can_open_new_position(len(positions))
                            if not can_open:
                                logger.debug(f"[Slot-{self.index}] {pair} BUY blocked: {block_reason}")
                                continue
                            if pos is None or pos.get("side") == "long":
                                order = engine.market_buy(pair, sized_amount)
                                if order.get("status") != "rejected":
                                    fp  = order.get("price", sig_obj.price)
                                    qty = order.get("qty", sized_amount / max(fp, 1))
                                    fee = order.get("fee", 0)
                                    detector.check_slippage(pair, sig_obj.price, fp, "buy")
                                    if pair in positions:
                                        p  = positions[pair]
                                        tq = p["qty"] + qty
                                        p["avg_cost"] = (p["avg_cost"]*p["qty"] + fp*qty) / tq
                                        p["qty"] = tq
                                    else:
                                        positions[pair] = {
                                            "side": "long", "qty": qty, "avg_cost": fp,
                                            "bars_held": 0,
                                        }
                                    trade_logger.log_buy(
                                        pair, fp, qty, fee, self.name, sig_obj.reason, self.mode
                                    )
                                    self.trade_count += 1
                                    self._broadcast_trade("buy", pair, order)

                        # LONG CLOSE
                        elif sig.name in ("SELL", "STOP_LOSS", "TIME_EXIT"):
                            pos2 = positions.get(pair)
                            if pos2 and pos2.get("side", "long") == "long":
                                order = engine.market_sell(pair, pos2["qty"])
                                if order.get("status") != "rejected":
                                    fp      = order.get("price", sig_obj.price)
                                    qty     = order.get("qty", pos2["qty"])
                                    fee     = order.get("fee", 0)
                                    detector.check_slippage(pair, sig_obj.price, fp, "sell")
                                    cost    = pos2["avg_cost"] * qty
                                    pnl     = qty * fp - fee - cost
                                    pnl_pct = pnl / cost * 100 if cost else 0
                                    trade_logger.log_sell(
                                        pair, fp, qty, fee, pnl, pnl_pct,
                                        self.name, sig_obj.reason, self.mode
                                    )
                                    del positions[pair]
                                    self.trade_count += 1
                                    self._broadcast_trade("sell", pair, {
                                        **order, "pnl": round(pnl, 4),
                                        "pnl_pct": round(pnl_pct, 4),
                                    })
                                    new_eq = _slot_equity(positions, current_prices, initial_balance)
                                    risk.check_all(new_eq, now_dt,
                                                   trade_type="win" if pnl >= 0 else "loss",
                                                   trade_pnl=pnl)

                        # SHORT OPEN
                        elif sig == Signal.SHORT and sig_obj.amount_usd > 0:
                            can_open_s, block_s = risk.can_open_new_position(len(positions))
                            if not can_open_s:
                                logger.debug(f"[Slot-{self.index}] {pair} SHORT blocked: {block_s}")
                                continue
                            if pair not in positions and hasattr(engine, "short_open"):
                                sized_short = risk.compute_position_size(sig_obj.amount_usd, equity)
                                order = engine.short_open(pair, sized_short)
                                if order.get("status") != "rejected":
                                    fp  = order.get("price", sig_obj.price)
                                    qty = order.get("qty", sized_short / max(fp, 1))
                                    fee = order.get("fee", 0)
                                    detector.check_slippage(pair, sig_obj.price, fp, "short")
                                    positions[pair] = {
                                        "side": "short", "qty": qty, "avg_cost": fp,
                                        "bars_held": 0,
                                    }
                                    trade_logger.log_buy(
                                        pair, fp, qty, fee, self.name,
                                        f"SHORT: {sig_obj.reason}", self.mode
                                    )
                                    self.trade_count += 1
                                    self._broadcast_trade("short", pair, order)

                        # SHORT CLOSE
                        elif sig.name in ("COVER",) or (
                            sig.name in ("STOP_LOSS", "TIME_EXIT")
                            and positions.get(pair, {}).get("side") == "short"
                        ):
                            pos2 = positions.get(pair)
                            if pos2 and pos2.get("side") == "short" and hasattr(engine, "short_cover"):
                                order = engine.short_cover(pair, pos2["qty"])
                                if order.get("status") != "rejected":
                                    fp      = order.get("price", sig_obj.price)
                                    qty     = order.get("qty", pos2["qty"])
                                    fee     = order.get("fee", 0)
                                    detector.check_slippage(pair, sig_obj.price, fp, "cover")
                                    pnl     = order.get("pnl", 0)
                                    base    = pos2["avg_cost"] * qty
                                    pnl_pct = pnl / base * 100 if base else 0
                                    trade_logger.log_sell(
                                        pair, fp, qty, fee, pnl, pnl_pct,
                                        self.name, f"COVER: {sig_obj.reason}", self.mode
                                    )
                                    del positions[pair]
                                    self.trade_count += 1
                                    self._broadcast_trade("cover", pair, {
                                        **order, "pnl": round(pnl, 4),
                                        "pnl_pct": round(pnl_pct, 4),
                                    })
                                    new_eq = _slot_equity(positions, current_prices, initial_balance)
                                    risk.check_all(new_eq, now_dt,
                                                   trade_type="win" if pnl >= 0 else "loss",
                                                   trade_pnl=pnl)

                    except Exception as pair_exc:
                        logger.warning(
                            f"[Slot-{self.index}] {pair} error: {pair_exc}",
                            exc_info=True,
                        )

                # Sleep until next candle using interruptible 1 s ticks
                for _ in range(int(tf_seconds)):
                    if self.stop_event.is_set():
                        break
                    _time.sleep(1)

            logger.info(f"[Slot-{self.index}] Loop stopped cleanly ({self.name})")

        except Exception as exc:
            self.crashed = True
            self.error   = str(exc)
            logger.exception(f"[Slot-{self.index}] CRASHED: {exc}")

    def _broadcast_event(self, event_type: str, detail: str) -> None:
        """Fire a WebSocket lifecycle event (best-effort)."""
        try:
            from api import ws_manager
            ws_manager.broadcast_sync({
                "type": "event",
                "payload": {
                    "event_type": event_type,
                    "mode":       self.mode,
                    "strategy":   self.name,
                    "detail":     f"[slot-{self.index}] {detail}",
                },
            })
        except Exception:
            pass

    def _broadcast_trade(self, trade_type: str, pair: str, result: dict) -> None:
        """Fire a WebSocket trade event (best-effort)."""
        try:
            from api import ws_manager
            price = float(result.get("average") or result.get("price") or 0)
            ws_manager.broadcast_sync({
                "type": "trade",
                "payload": {
                    "type":     trade_type,
                    "pair":     pair,
                    "price":    price,
                    "qty":      float(result.get("filled") or 0),
                    "strategy": self.name,
                    "mode":     self.mode,
                    "slot":     self.index,
                },
            })
        except Exception:
            pass

    def status_dict(self) -> dict:
        uptime: Optional[float] = None
        if self.started_at and self.is_alive():
            uptime = (datetime.now(tz=timezone.utc) - self.started_at).total_seconds()
        return {
            "index":       self.index,
            "name":        self.name,
            "pairs":       self.pairs,
            "capital_pct": self.capital_pct,
            "mode":        self.mode,
            "running":     self.is_alive(),
            "crashed":     self.crashed,
            "started_at":  self.started_at.isoformat() if self.started_at else None,
            "uptime_s":    round(uptime, 1) if uptime is not None else None,
            "trade_count": self.trade_count,
            "error":       self.error,
        }


# ── Public API ─────────────────────────────────────────────────────────────────

def is_running() -> bool:
    """True if at least one slot is alive."""
    with _lock:
        return any(s.is_alive() for s in _slots)


def portfolio_status() -> dict:
    """Return aggregate portfolio status with per-slot breakdown."""
    with _lock:
        slot_statuses = [s.status_dict() for s in _slots]

    alive_count   = sum(1 for s in slot_statuses if s["running"])
    crashed_count = sum(1 for s in slot_statuses if s["crashed"])
    total_trades  = sum(s["trade_count"] for s in slot_statuses)

    uptime: Optional[float] = None
    if _portfolio_start_time:
        uptime = (datetime.now(tz=timezone.utc) - _portfolio_start_time).total_seconds()

    return {
        "running":       alive_count > 0,
        "alive_slots":   alive_count,
        "total_slots":   len(slot_statuses),
        "crashed_slots": crashed_count,
        "total_trades":  total_trades,
        "started_at":    _portfolio_start_time.isoformat() if _portfolio_start_time else None,
        "uptime_s":      round(uptime, 1) if uptime is not None else None,
        "slots":         slot_statuses,
    }


def start_portfolio(config: dict, mode: str = "paper") -> dict:
    """
    Start all configured portfolio slots.

    Raises ``RuntimeError`` if portfolio is already running or if config
    has no portfolio section or no strategies defined.
    """
    global _slots, _watchdog_thread, _watchdog_stop, _portfolio_start_time

    with _lock:
        if any(s.is_alive() for s in _slots):
            raise RuntimeError("Portfolio already running — stop it first")

        portfolio_cfg = config.get("portfolio", {})
        slot_cfgs: list[dict] = portfolio_cfg.get("strategies", [])

        if not slot_cfgs:
            raise RuntimeError(
                "No strategies defined in config.yaml portfolio.strategies. "
                "Add at least one entry."
            )

        # Validate capital_pct sums to ~100 (warn if not, but don't block)
        total_pct = sum(float(s.get("capital_pct", 0)) for s in slot_cfgs)
        if abs(total_pct - 100.0) > 1.0:
            logger.warning(
                f"Portfolio capital_pct sums to {total_pct:.1f}% (expected 100%). "
                f"Each slot will receive its proportional slice."
            )

        _slots = [_Slot(i, sc, config, mode) for i, sc in enumerate(slot_cfgs)]
        _portfolio_start_time = datetime.now(tz=timezone.utc)

        for slot in _slots:
            slot.start()

        # Watchdog
        _watchdog_stop = threading.Event()
        _watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            name="portfolio-watchdog",
            daemon=True,
        )
        _watchdog_thread.start()

        return portfolio_status()


def stop_portfolio() -> dict:
    """Signal all slots to stop and return final status."""
    global _watchdog_stop

    with _lock:
        if _watchdog_stop:
            _watchdog_stop.set()
        for slot in _slots:
            slot.stop()

    logger.info("[Portfolio] Stop requested for all slots")
    return portfolio_status()


# ── Watchdog ───────────────────────────────────────────────────────────────────

def _watchdog_loop() -> None:
    """Check all slots every 60 s and log crashes."""
    assert _watchdog_stop is not None
    while not _watchdog_stop.is_set():
        _watchdog_stop.wait(timeout=60)
        with _lock:
            for slot in _slots:
                if not slot.is_alive() and slot.started_at and not slot.crashed:
                    # Thread died without being stopped
                    slot.crashed = True
                    slot.error   = slot.error or "Thread died unexpectedly"
                    logger.critical(
                        f"[Portfolio watchdog] Slot {slot.index} ({slot.name}) "
                        f"died unexpectedly! error={slot.error}"
                    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slot_equity(positions: dict, current_prices: dict, initial_balance: float) -> float:
    """Approximate equity for a portfolio slot from its in-memory position dict."""
    positions_value = sum(
        p["qty"] * current_prices.get(pair, p["avg_cost"])
        for pair, p in positions.items()
    )
    cost_basis   = sum(p["qty"] * p["avg_cost"] for p in positions.values())
    balance_usdt = max(0.0, initial_balance - cost_basis)
    return round(balance_usdt + positions_value, 4)


def _candle_seconds(timeframe: str) -> float:
    """Convert a ccxt timeframe string to seconds (approximate)."""
    multipliers = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        unit = timeframe[-1].lower()
        qty  = int(timeframe[:-1])
        return qty * multipliers.get(unit, 3600)
    except (ValueError, IndexError):
        return 3600
