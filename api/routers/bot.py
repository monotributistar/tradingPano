"""
api/routers/bot.py — Bot control endpoints
==========================================

All endpoints require ``X-API-Key`` authentication (enforced at app level
in ``api/main.py``).

Endpoints
---------
POST /api/bot/start     Start paper or live trading
POST /api/bot/stop      Gracefully stop the bot
GET  /api/bot/status    Current bot state (running, crashed, uptime, …)
GET  /api/bot/history   Last N BotState DB snapshots
GET  /api/bot/events    Audit log of lifecycle events (start/stop/crash/…)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db.engine import get_db
from api.db.models import BotState, BotEvent
from api.schemas.bot import BotStartRequest, BotStatusResponse, BotEventResponse
import api.bot_manager as bot_manager
from api.main import load_bot_config

router = APIRouter(prefix="/bot", tags=["bot"])


@router.post("/start", summary="Start the trading bot")
def start_bot(body: BotStartRequest, db: Session = Depends(get_db)):
    """
    Start the bot in paper or live mode.

    Pass ``"restore": true`` to resume open positions from the last saved
    state — use this after a VPS reboot or manual stop with live positions.

    Pass ``strategy_config_id`` to load a saved StrategyConfig from the
    Strategy Engine.  The config's execution_strategy, execution_timeframe,
    pairs, and risk_profile overrides are applied automatically.
    """
    if body.mode not in ("paper", "live"):
        raise HTTPException(400, "mode must be 'paper' or 'live'")

    config      = load_bot_config()
    strategy    = body.strategy
    pairs       = list(body.pairs)
    config_id   = None
    config_name = None

    # ── Resolve StrategyConfig ────────────────────────────────────────────────
    if body.strategy_config_id is not None:
        from api.db.models import StrategyConfig as StrategyConfigORM

        sc = (
            db.query(StrategyConfigORM)
            .filter(StrategyConfigORM.id == body.strategy_config_id)
            .first()
        )
        if not sc:
            raise HTTPException(404, f"StrategyConfig {body.strategy_config_id} not found")

        strategy    = sc.execution_strategy
        config_id   = sc.id
        config_name = sc.name

        # Override pairs if the config specifies them
        if sc.pairs:
            pairs = list(sc.pairs)

        # Override timeframe (stored inside the backtest section of config)
        config.setdefault("backtest", {})["timeframe"] = sc.execution_timeframe

        # Apply risk profile overrides
        rp: dict  = sc.risk_profile or {}
        risk_cfg  = config.setdefault("risk", {})
        strat_cfg = config.setdefault("strategies", {}).setdefault(strategy, {})

        if rp.get("leverage")           is not None: risk_cfg["leverage"]            = rp["leverage"]
        if rp.get("max_drawdown_pct")   is not None: risk_cfg["max_drawdown_pct"]    = rp["max_drawdown_pct"]
        if rp.get("max_daily_loss_pct") is not None: risk_cfg["daily_loss_stop_pct"] = rp["max_daily_loss_pct"]
        if rp.get("stop_loss_pct")      is not None: strat_cfg["stop_loss_pct"]      = rp["stop_loss_pct"]
        if rp.get("take_profit_pct")    is not None: strat_cfg["take_profit_pct"]    = rp["take_profit_pct"]
        if rp.get("position_size_pct")  is not None: strat_cfg["position_size_pct"]  = rp["position_size_pct"]

        # Apply trend filter (or remove if not set)
        if sc.trend_filter_strategy:
            config["trend_filter"] = {
                "enabled":   True,
                "strategy":  sc.trend_filter_strategy,
                "timeframe": sc.trend_filter_timeframe,
            }
        else:
            config.pop("trend_filter", None)

    result = bot_manager.start(
        body.mode, strategy, pairs, config,
        restore=body.restore,
        config_id=config_id,
        config_name=config_name,
    )
    if not result["ok"]:
        raise HTTPException(409, result["detail"])
    return result


@router.post("/stop", summary="Stop the trading bot")
def stop_bot():
    """Gracefully stop the bot.  Waits up to 10 s for the thread to exit."""
    result = bot_manager.stop()
    if not result["ok"]:
        raise HTTPException(409, result["detail"])
    return result


@router.get("/status", response_model=BotStatusResponse, summary="Bot status")
def bot_status():
    """
    Return the current bot state.

    ``crashed`` is True when the watchdog detected an unexpected thread death.
    ``uptime_seconds`` is None when the bot is not running.
    """
    return bot_manager.get_status()


@router.get("/history", summary="BotState snapshots")
def bot_state_history(limit: int = 20, db: Session = Depends(get_db)):
    """
    Return the last ``limit`` BotState rows ordered by most recent first.

    These are raw DB snapshots persisted after every candle — useful for
    debugging position drift or verifying resume behaviour.
    """
    rows = (
        db.query(BotState)
        .order_by(BotState.saved_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id":         r.id,
            "mode":       r.mode,
            "strategy":   r.strategy,
            "pairs":      r.pairs,
            "positions":  r.positions,
            "is_active":  r.is_active,
            "saved_at":   r.saved_at.isoformat() if r.saved_at else None,
        }
        for r in rows
    ]


@router.get("/events", response_model=list[BotEventResponse],
            summary="Bot lifecycle audit log")
def bot_events(limit: int = 50, db: Session = Depends(get_db)):
    """
    Return the last ``limit`` BotEvent rows ordered by most recent first.

    Event types: ``start`` · ``stop`` · ``crash`` · ``halt`` · ``resume`` · ``watchdog``

    This is the primary feed for Telegram alerts (Phase 2).
    """
    rows = (
        db.query(BotEvent)
        .order_by(BotEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        BotEventResponse(
            id=r.id,
            event_type=r.event_type,
            mode=r.mode,
            strategy=r.strategy,
            pairs=r.pairs,
            detail=r.detail,
            positions=r.positions,
            occurred_at=r.occurred_at.isoformat() if r.occurred_at else "",
        )
        for r in rows
    ]
