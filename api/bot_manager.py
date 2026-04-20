"""
api/bot_manager.py — Bot lifecycle manager
===========================================

Responsibilities
----------------
- Start / stop the trading bot in a background daemon thread
- Persist state to DB after every candle (BotState table)
- Resume open positions from DB on restart (``restore=True``)
- Watchdog thread: detect silent thread deaths, alert via Telegram
- Write BotEvent audit records for every lifecycle transition
- Broadcast real-time events to WebSocket clients
- Call TelegramNotifier on trades, halts, crashes, starts, stops
- Expose ``get_status()`` for the ``/api/bot/status`` endpoint

Threading model
---------------
  Main thread   →  FastAPI request handlers
  bot-runner    →  daemon thread running the trading loop
  bot-watchdog  →  daemon thread checking bot-runner every 30 s
  telegram-poll →  daemon thread polling Telegram for commands

Notification hooks
------------------
Every trade, lifecycle event and risk halt fires:
  1. WebSocket broadcast  →  real-time UI update
  2. Telegram alert       →  phone notification

Position resume flow
--------------------
When ``start(..., restore=True)`` is called:
  1. Query the latest ``BotState`` where ``is_active=True``
  2. Restore ``positions`` dict and call ``strategy.load_state()``
  3. Continue the loop with the restored state
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional, List

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────

_lock = threading.Lock()
_thread: Optional[threading.Thread]         = None
_stop_event: Optional[threading.Event]      = None
_current_config: dict                       = {}
_start_time: Optional[datetime]             = None
_error: Optional[str]                       = None
_crashed: bool                              = False

_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop:   Optional[threading.Event]  = None


# ── Public API ────────────────────────────────────────────────────────────────

def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def get_status() -> dict:
    uptime_seconds: Optional[float] = None
    if _start_time and is_running():
        uptime_seconds = (datetime.now(tz=timezone.utc) - _start_time).total_seconds()

    return {
        "running":              is_running(),
        "crashed":              _crashed,
        "mode":                 _current_config.get("mode"),
        "strategy":             _current_config.get("strategy"),
        "pairs":                _current_config.get("pairs", []),
        "started_at":           _start_time.isoformat() if _start_time else None,
        "uptime_seconds":       uptime_seconds,
        "error":                _error,
        "risk":                 _current_config.get("risk"),  # live circuit-breaker state
        "strategy_config_id":   _current_config.get("config_id"),
        "strategy_config_name": _current_config.get("config_name"),
    }


def start(mode: str, strategy_name: str, pairs: List[str],
          bot_config: dict, restore: bool = False,
          config_id: Optional[int] = None,
          config_name: Optional[str] = None) -> dict:
    """
    Start the trading bot in a daemon thread.

    Parameters
    ----------
    mode           'paper' | 'live'
    strategy_name  Must exist in the strategy registry
    pairs          List of trading pairs, e.g. ['BTC/USDT', 'ETH/USDT']
    bot_config     Full config dict from ``load_bot_config()``
    restore        If True, resume last persisted positions from DB
    """
    global _thread, _stop_event, _current_config, _start_time, _error, _crashed

    with _lock:
        if is_running():
            return {"ok": False, "detail": "Bot already running"}

        _error   = None
        _crashed = False
        _stop_event = threading.Event()

        def run():
            global _error, _crashed
            try:
                _load_and_run(mode, strategy_name, pairs, bot_config,
                              _stop_event, restore=restore)
            except Exception as exc:
                _error   = str(exc)
                _crashed = True
                logger.error(f"Bot thread crashed: {exc}", exc_info=True)
                _write_event("crash", mode, strategy_name, pairs, detail=str(exc))
                _notify_crash(str(exc), mode, strategy_name)
                _ws_broadcast({"type": "event", "payload": {
                    "event_type": "crash",
                    "mode": mode, "strategy": strategy_name,
                    "detail": str(exc),
                }})

        _thread         = threading.Thread(target=run, daemon=True, name="bot-runner")
        _current_config = {
            "mode":        mode,
            "strategy":    strategy_name,
            "pairs":       pairs,
            "config_id":   config_id,
            "config_name": config_name,
        }
        _start_time     = datetime.now(tz=timezone.utc)
        _thread.start()

        _write_event("start", mode, strategy_name, pairs, detail=f"restore={restore}")
        _notify_started(mode, strategy_name, pairs, restore)
        _ws_broadcast({"type": "status", "payload": get_status()})
        logger.info(f"Bot started: {mode} / {strategy_name} / {pairs} restore={restore}")

        _start_watchdog()
        return {"ok": True, "detail": f"{mode} bot started"}


def stop() -> dict:
    global _stop_event, _thread, _current_config, _start_time, _crashed
    with _lock:
        if not is_running():
            return {"ok": False, "detail": "No bot running"}

        mode     = _current_config.get("mode", "")
        strategy = _current_config.get("strategy", "")
        pairs    = _current_config.get("pairs", [])

        _stop_event.set()
        _thread.join(timeout=10)
        _thread         = None
        _current_config = {}
        _start_time     = None
        _crashed        = False

        _stop_watchdog()
        _write_event("stop", mode, strategy, pairs)
        _notify_stopped(mode, strategy)
        _ws_broadcast({"type": "status", "payload": get_status()})
        logger.info("Bot stopped")
        return {"ok": True, "detail": "Bot stopped"}


# ── Watchdog ──────────────────────────────────────────────────────────────────

def _start_watchdog() -> None:
    global _watchdog_thread, _watchdog_stop
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    _watchdog_stop   = threading.Event()
    _watchdog_thread = threading.Thread(
        target=_watchdog_loop,
        args=(_watchdog_stop,),
        daemon=True,
        name="bot-watchdog",
    )
    _watchdog_thread.start()


def _stop_watchdog() -> None:
    global _watchdog_stop
    if _watchdog_stop:
        _watchdog_stop.set()


def _watchdog_loop(stop_event: threading.Event) -> None:
    global _crashed
    while not stop_event.wait(timeout=30):
        with _lock:
            config_set = bool(_current_config)
            alive      = is_running()

        if config_set and not alive and not _crashed:
            _crashed = True
            mode     = _current_config.get("mode", "")
            strategy = _current_config.get("strategy", "")
            pairs    = _current_config.get("pairs", [])
            logger.critical(
                f"Watchdog: bot thread died unexpectedly "
                f"(mode={mode}, strategy={strategy})"
            )
            _write_event("watchdog", mode, strategy, pairs,
                         detail="Thread died without explicit stop()")
            _notify_watchdog(mode, strategy)
            _ws_broadcast({"type": "event", "payload": {
                "event_type": "watchdog",
                "mode": mode, "strategy": strategy,
                "detail": "Bot thread died unexpectedly",
            }})
            _ws_broadcast({"type": "status", "payload": get_status()})


# ── Notification helpers ──────────────────────────────────────────────────────

def _notify_started(mode: str, strategy: str, pairs: list,
                    restore: bool = False) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_started(mode, strategy, pairs, restore)
    except Exception as exc:
        logger.debug(f"Telegram alert_started failed: {exc}")


def _notify_stopped(mode: str, strategy: str) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_stopped(mode, strategy)
    except Exception as exc:
        logger.debug(f"Telegram alert_stopped failed: {exc}")


def _notify_trade_opened(pair: str, side: str, price: float,
                         qty: float, strategy: str, mode: str) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_trade_opened(pair, side, price, qty, strategy, mode)
    except Exception as exc:
        logger.debug(f"Telegram alert_trade_opened failed: {exc}")


def _notify_trade_closed(pair: str, side: str, price: float, qty: float,
                         pnl: float, pnl_pct: float,
                         strategy: str, mode: str) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_trade_closed(
            pair, side, price, qty, pnl, pnl_pct, strategy, mode
        )
    except Exception as exc:
        logger.debug(f"Telegram alert_trade_closed failed: {exc}")


def _notify_risk_halt(reason: str, mode: str) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_risk_halt(reason, mode)
    except Exception as exc:
        logger.debug(f"Telegram alert_risk_halt failed: {exc}")


def _notify_crash(error: str, mode: str, strategy: str) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_crash(error, mode, strategy)
    except Exception as exc:
        logger.debug(f"Telegram alert_crash failed: {exc}")


def _notify_watchdog(mode: str, strategy: str) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_watchdog(mode, strategy)
    except Exception as exc:
        logger.debug(f"Telegram alert_watchdog failed: {exc}")


def _notify_resume(mode: str, strategy: str, n_positions: int) -> None:
    try:
        from api.telegram_bot import get_notifier
        get_notifier().alert_resume(mode, strategy, n_positions)
    except Exception as exc:
        logger.debug(f"Telegram alert_resume failed: {exc}")


def _ws_broadcast(message: dict) -> None:
    try:
        from api.ws_manager import broadcast_sync
        broadcast_sync(message)
    except Exception as exc:
        logger.debug(f"WS broadcast failed: {exc}")


# ── Audit event helper ────────────────────────────────────────────────────────

def _write_event(event_type: str, mode: Optional[str], strategy: Optional[str],
                 pairs: Optional[list], detail: Optional[str] = None,
                 positions: Optional[dict] = None) -> None:
    try:
        from api.db.engine import SessionLocal
        from api.db.models import BotEvent
        db = SessionLocal()
        try:
            db.add(BotEvent(
                event_type=event_type, mode=mode, strategy=strategy,
                pairs=pairs, detail=detail, positions=positions or {},
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Failed to write BotEvent({event_type}): {e}")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"BotEvent write error: {e}")


# ── DB state helpers ──────────────────────────────────────────────────────────

def _load_last_state() -> Optional[dict]:
    try:
        from api.db.engine import SessionLocal
        from api.db.models import BotState
        db = SessionLocal()
        try:
            row = (
                db.query(BotState)
                .filter_by(is_active=True)
                .order_by(BotState.saved_at.desc())
                .first()
            )
            if row:
                return {
                    "mode":           row.mode,
                    "strategy":       row.strategy,
                    "pairs":          row.pairs,
                    "positions":      dict(row.positions or {}),
                    "strategy_state": dict(row.strategy_state or {}),
                }
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not load last BotState: {e}")
    return None


def _save_state(mode: str, strategy_name: str, pairs: list,
                positions: dict, strategy_state: dict) -> None:
    from api.db.engine import SessionLocal
    from api.db.models import BotState
    db = SessionLocal()
    try:
        db.query(BotState).filter_by(is_active=True).update({"is_active": False})
        db.add(BotState(
            mode=mode, strategy=strategy_name, pairs=pairs,
            positions=positions, strategy_state=strategy_state,
            is_active=True,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to save BotState: {e}")
    finally:
        db.close()


def _save_wallet_snapshot(mode: str, positions: dict, current_prices: dict,
                          initial_balance: float) -> None:
    from api.db.engine import SessionLocal
    from api.db.models import WalletSnapshot
    db = SessionLocal()
    try:
        positions_value = sum(
            p["qty"] * current_prices.get(pair, p["avg_cost"])
            for pair, p in positions.items()
        )
        cost_basis   = sum(p["qty"] * p["avg_cost"] for p in positions.values())
        balance_usdt = max(0.0, initial_balance - cost_basis)
        total_equity = balance_usdt + positions_value

        snap = WalletSnapshot(
            source=mode,
            balance_usdt=round(balance_usdt, 4),
            positions_value=round(positions_value, 4),
            total_equity=round(total_equity, 4),
            positions={k: {"qty": v["qty"], "avg_cost": v["avg_cost"]}
                       for k, v in positions.items()},
        )
        db.add(snap)
        db.commit()

        # Broadcast equity update via WebSocket
        _ws_broadcast({"type": "equity", "payload": {
            "total_equity":    round(total_equity, 4),
            "balance_usdt":    round(balance_usdt, 4),
            "positions_value": round(positions_value, 4),
            "positions":       snap.positions,
        }})
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to save WalletSnapshot: {e}")
    finally:
        db.close()


# ── Core trading loop ─────────────────────────────────────────────────────────

def _load_and_run(mode: str, strategy_name: str, pairs: List[str],
                  config: dict, stop_event: threading.Event,
                  restore: bool = False) -> None:
    # ── Engine ──────────────────────────────────────────────────────────────
    if mode == "paper":
        from engine.paper import PaperEngine as EngineClass
    else:
        from engine.live import LiveEngine as EngineClass

    # ── Strategy ────────────────────────────────────────────────────────────
    from api.main import get_strategy_registry
    registry = get_strategy_registry()
    if strategy_name not in registry:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    strategy = registry[strategy_name]()
    strategy.initialize(config.get("strategies", {}).get(strategy_name, {}))

    engine          = EngineClass(config)
    trade_logger    = _make_trade_logger(mode)
    initial_balance = config.get(mode, {}).get("initial_balance", 20.0)

    # ── Risk manager ─────────────────────────────────────────────────────────
    from risk_manager import RiskManager
    risk = RiskManager(config, initial_balance)
    _last_halt_reason: Optional[str] = None  # track to avoid duplicate alerts

    # ── Anomaly detector ─────────────────────────────────────────────────────
    from api.anomaly_detector import AnomalyDetector
    from api.telegram_bot import get_notifier
    detector = AnomalyDetector(config)
    try:
        detector.set_notifier(get_notifier())
    except Exception:
        pass  # Telegram not configured — anomalies still logged, just no phone alert

    # ── Timeframe ────────────────────────────────────────────────────────────
    timeframe  = config.get("backtest", {}).get("timeframe", "1h")
    tf_seconds = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "4h": 14400, "1d": 86400,
    }.get(timeframe, 3600)

    # ── Position restore ─────────────────────────────────────────────────────
    positions: dict = {}
    if restore:
        saved = _load_last_state()
        if saved:
            positions = saved["positions"]
            try:
                strategy.load_state(saved["strategy_state"])
            except Exception as e:
                logger.warning(f"Could not restore strategy state: {e}")
            n = len(positions)
            logger.info(f"Resumed — {n} open position(s): {list(positions.keys())}")
            _write_event("resume", mode, strategy_name, pairs,
                         detail=f"Restored {n} position(s)", positions=positions)
            _notify_resume(mode, strategy_name, n)
            _ws_broadcast({"type": "event", "payload": {
                "event_type": "resume", "mode": mode, "strategy": strategy_name,
                "detail": f"Restored {n} position(s)", "positions": positions,
            }})
        else:
            logger.info("restore=True but no saved state found — starting fresh")

    from strategies.base import Signal

    current_prices: dict = {}

    # ── Main loop ────────────────────────────────────────────────────────────
    while not stop_event.is_set():

        # ── Per-cycle risk check ─────────────────────────────────────────────
        now_dt = datetime.now(tz=timezone.utc)
        equity = _compute_equity(positions, current_prices, initial_balance)
        halted, halt_reason = risk.check_all(equity, now_dt)

        if halted:
            is_blackout = "blackout" in halt_reason
            if halt_reason != _last_halt_reason:
                # First time hitting this halt — fire notifications
                _last_halt_reason = halt_reason
                logger.warning(f"[RiskManager] {halt_reason}")
                if is_blackout:
                    logger.info(f"[Risk] Blackout window — sleeping 5 min")
                    _ws_broadcast({"type": "event", "payload": {
                        "event_type": "halt", "mode": mode, "strategy": strategy_name,
                        "detail": halt_reason,
                    }})
                else:
                    # Hard halt — stop the bot entirely
                    _write_event("halt", mode, strategy_name, pairs, detail=halt_reason,
                                 positions=positions)
                    _notify_risk_halt(halt_reason, mode)
                    _ws_broadcast({"type": "event", "payload": {
                        "event_type": "halt", "mode": mode, "strategy": strategy_name,
                        "detail": halt_reason,
                    }})
                    _ws_broadcast({"type": "status", "payload": get_status()})

            if not is_blackout:
                break  # exit the loop — hard halt

            # Blackout: sleep 5 min then re-check
            stop_event.wait(timeout=300)
            _last_halt_reason = None  # allow re-notification after blackout ends
            continue
        else:
            _last_halt_reason = None  # clear halt tracking once risk is clear

        for pair in pairs:
            if stop_event.is_set():
                break
            try:
                candles = engine.fetch_ohlcv(pair, timeframe, limit=200)
                if candles:
                    last_price = candles[-1][4]
                    current_prices[pair] = last_price
                    # ── Stale price anomaly check ──────────────────────────
                    if not detector.check_price_freshness(pair, last_price):
                        continue  # skip signal — price feed frozen

                pos = positions.get(pair)
                if pos:
                    pos["bars_held"] = pos.get("bars_held", 0) + 1

                sig_obj = strategy.on_candle(pair, candles, pos)
                sig     = sig_obj.signal

                # ── LONG OPEN ──────────────────────────────────────────────
                if sig == Signal.BUY and sig_obj.amount_usd > 0:
                    # Max concurrent positions gate
                    can_open, block_reason = risk.can_open_new_position(len(positions))
                    if not can_open:
                        logger.debug(f"[Risk] {pair} BUY blocked: {block_reason}")
                        continue
                    if pos is None or pos.get("side") == "long":
                        sized_amount = risk.compute_position_size(
                            sig_obj.amount_usd, equity
                        )
                        order = engine.market_buy(pair, sized_amount)
                        if order.get("status") != "rejected":
                            qty = order.get("qty", sized_amount / max(sig_obj.price, 1))
                            fp  = order.get("price", sig_obj.price)
                            fee = order.get("fee", 0)
                            # ── Slippage check ─────────────────────────────
                            detector.check_slippage(pair, sig_obj.price, fp, "buy")
                            if pair in positions:
                                p  = positions[pair]
                                tq = p["qty"] + qty
                                p["avg_cost"] = (p["avg_cost"]*p["qty"] + fp*qty) / tq
                                p["qty"] = tq
                            else:
                                positions[pair] = {
                                    "side": "long", "qty": qty, "avg_cost": fp,
                                    "bars_held": 0, "entry_time": time.time(),
                                }
                            trade_logger.log_buy(
                                pair, fp, qty, fee, strategy_name, sig_obj.reason, mode
                            )
                            current_prices[pair] = fp
                            _save_wallet_snapshot(mode, positions, current_prices, initial_balance)
                            _notify_trade_opened(pair, "buy", fp, qty, strategy_name, mode)
                            _ws_broadcast({"type": "trade", "payload": {
                                "type": "buy", "pair": pair, "price": fp,
                                "qty": qty, "strategy": strategy_name,
                                "mode": mode, "reason": sig_obj.reason,
                            }})

                # ── LONG CLOSE ─────────────────────────────────────────────
                elif sig.name in ("SELL", "STOP_LOSS", "TIME_EXIT"):
                    pos2 = positions.get(pair)
                    if pos2 and pos2.get("side", "long") == "long":
                        order = engine.market_sell(pair, pos2["qty"])
                        if order.get("status") != "rejected":
                            qty     = order.get("qty", pos2["qty"])
                            fp      = order.get("price", sig_obj.price)
                            fee     = order.get("fee", 0)
                            # ── Slippage check ─────────────────────────────
                            detector.check_slippage(pair, sig_obj.price, fp, "sell")
                            cost    = pos2["avg_cost"] * qty
                            pnl     = qty * fp - fee - cost
                            pnl_pct = pnl / cost * 100 if cost else 0
                            trade_logger.log_sell(
                                pair, fp, qty, fee, pnl, pnl_pct,
                                strategy_name, sig_obj.reason, mode
                            )
                            del positions[pair]
                            current_prices[pair] = fp
                            _save_wallet_snapshot(mode, positions, current_prices, initial_balance)
                            _notify_trade_closed(
                                pair, "sell", fp, qty, pnl, pnl_pct, strategy_name, mode
                            )
                            _ws_broadcast({"type": "trade", "payload": {
                                "type": "sell", "pair": pair, "price": fp,
                                "qty": qty, "pnl": round(pnl, 4),
                                "pnl_pct": round(pnl_pct, 4),
                                "strategy": strategy_name, "mode": mode,
                                "reason": sig_obj.reason,
                            }})
                            # ── Risk: update win/loss counter ──────────────
                            new_equity = _compute_equity(positions, current_prices, initial_balance)
                            risk.check_all(new_equity, now_dt,
                                           trade_type="win" if pnl >= 0 else "loss",
                                           trade_pnl=pnl)

                # ── SHORT OPEN ─────────────────────────────────────────────
                elif sig == Signal.SHORT and sig_obj.amount_usd > 0:
                    can_open, block_reason = risk.can_open_new_position(len(positions))
                    if not can_open:
                        logger.debug(f"[Risk] {pair} SHORT blocked: {block_reason}")
                        continue
                    if pair not in positions and hasattr(engine, "short_open"):
                        sized_amount = risk.compute_position_size(sig_obj.amount_usd, equity)
                        order = engine.short_open(pair, sized_amount)
                        if order.get("status") != "rejected":
                            fp  = order.get("price", sig_obj.price)
                            qty = order.get("qty", sized_amount / max(sig_obj.price, 1))
                            fee = order.get("fee", 0)
                            # ── Slippage check ─────────────────────────────
                            detector.check_slippage(pair, sig_obj.price, fp, "short")
                            positions[pair] = {
                                "side": "short", "qty": qty, "avg_cost": fp,
                                "collateral": order.get("collateral", sig_obj.amount_usd),
                                "bars_held": 0, "entry_time": time.time(),
                            }
                            trade_logger.log_buy(
                                pair, fp, qty, fee, strategy_name,
                                f"SHORT: {sig_obj.reason}", mode
                            )
                            current_prices[pair] = fp
                            _save_wallet_snapshot(mode, positions, current_prices, initial_balance)
                            _notify_trade_opened(pair, "short", fp, qty, strategy_name, mode)
                            _ws_broadcast({"type": "trade", "payload": {
                                "type": "short", "pair": pair, "price": fp,
                                "qty": qty, "strategy": strategy_name,
                                "mode": mode, "reason": sig_obj.reason,
                            }})

                # ── SHORT CLOSE ────────────────────────────────────────────
                elif sig.name in ("COVER",) or (
                    sig.name in ("STOP_LOSS", "TIME_EXIT")
                    and positions.get(pair, {}).get("side") == "short"
                ):
                    pos2 = positions.get(pair)
                    if pos2 and pos2.get("side") == "short" and hasattr(engine, "short_cover"):
                        order = engine.short_cover(pair, pos2["qty"])  # qty fix
                        if order.get("status") != "rejected":
                            fp      = order.get("price", sig_obj.price)
                            qty     = order.get("qty", pos2["qty"])
                            fee     = order.get("fee", 0)
                            # ── Slippage check ─────────────────────────────
                            detector.check_slippage(pair, sig_obj.price, fp, "cover")
                            pnl     = order.get("pnl", 0)
                            base    = pos2["avg_cost"] * qty
                            pnl_pct = pnl / base * 100 if base else 0
                            trade_logger.log_sell(
                                pair, fp, qty, fee, pnl, pnl_pct,
                                strategy_name, f"COVER: {sig_obj.reason}", mode
                            )
                            del positions[pair]
                            current_prices[pair] = fp
                            _save_wallet_snapshot(mode, positions, current_prices, initial_balance)
                            _notify_trade_closed(
                                pair, "cover", fp, qty, pnl, pnl_pct, strategy_name, mode
                            )
                            _ws_broadcast({"type": "trade", "payload": {
                                "type": "cover", "pair": pair, "price": fp,
                                "qty": qty, "pnl": round(pnl, 4),
                                "pnl_pct": round(pnl_pct, 4),
                                "strategy": strategy_name, "mode": mode,
                                "reason": sig_obj.reason,
                            }})
                            # ── Risk: update win/loss counter ──────────────
                            new_equity = _compute_equity(positions, current_prices, initial_balance)
                            risk.check_all(new_equity, now_dt,
                                           trade_type="win" if pnl >= 0 else "loss",
                                           trade_pnl=pnl)

            except Exception as e:
                logger.error(f"Error processing {pair}: {e}", exc_info=True)

        # ── Persist state ────────────────────────────────────────────────────
        _save_state(mode, strategy_name, pairs, positions, strategy.save_state())

        # ── Risk: expose current state in status ─────────────────────────────
        risk_info = risk.info()
        _current_config["risk"] = {
            "halted":            risk_info["halted"],
            "halt_reason":       risk_info["halt_reason"],
            "daily_trades":      risk_info["daily_trades_today"],
            "consecutive_losses": risk_info["consecutive_losses"],
            "peak_equity":       round(risk_info["peak_equity"], 2),
        }

        # ── Balance integrity check (live mode only, every N cycles) ─────────
        if mode == "live" and current_prices:
            try:
                live_bal = engine.fetch_balance()
                live_usdt = float(live_bal.get("USDT", 0))
                if live_usdt > 0:
                    positions_val = sum(
                        p["qty"] * current_prices.get(pair, p["avg_cost"])
                        for pair, p in positions.items()
                    )
                    cost_basis   = sum(p["qty"] * p["avg_cost"] for p in positions.values())
                    db_usdt      = max(0.0, initial_balance - cost_basis)
                    detector.check_balance(db_usdt, live_usdt, "USDT balance")
            except Exception:
                pass  # don't crash the loop on balance check failure

        # Broadcast status on every completed candle cycle
        _ws_broadcast({"type": "status", "payload": get_status()})

        # ── Sleep with interruptible 1-second ticks ──────────────────────────
        for _ in range(tf_seconds):
            if stop_event.is_set():
                break
            time.sleep(1)

    # ── Final save ───────────────────────────────────────────────────────────
    _save_state(mode, strategy_name, pairs, positions, strategy.save_state())
    logger.info("Bot loop exited cleanly")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_equity(positions: dict, current_prices: dict, initial_balance: float) -> float:
    """
    Approximate total equity from the in-memory position dict.

    equity = (initial_balance - cost_basis) + positions_value

    Uses avg_cost as the fallback price when a current market price is missing.
    """
    positions_value = sum(
        p["qty"] * current_prices.get(pair, p["avg_cost"])
        for pair, p in positions.items()
    )
    cost_basis   = sum(p["qty"] * p["avg_cost"] for p in positions.values())
    balance_usdt = max(0.0, initial_balance - cost_basis)
    return round(balance_usdt + positions_value, 4)


def _make_trade_logger(mode: str):
    from api.adapters.db_trade_logger import DBTradeLogger
    return DBTradeLogger(source=mode)
