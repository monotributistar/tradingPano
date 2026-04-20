"""
api/db/models.py — SQLAlchemy ORM models
=========================================

Tables
------
trades            Individual trade entries (buy/sell, backtest or live)
backtest_jobs     Backtest job metadata and results
wallet_snapshots  Periodic portfolio snapshots (balance + open positions)
bot_state         Last known bot state — used to resume after restart
bot_events        Audit log of bot lifecycle events (start/stop/crash/halt)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from api.db.engine import Base


def _now():
    return datetime.now(tz=timezone.utc)


# ── Trades ─────────────────────────────────────────────────────────────────────

class Trade(Base):
    """
    One side of a trade (BUY entry or SELL/COVER exit).

    ``source``        — 'paper' | 'live' | 'backtest'
    ``backtest_job_id`` — FK to BacktestJob when source == 'backtest'
    ``type``          — 'buy' | 'sell' | 'short' | 'cover'
    ``pnl``           — realised P&L in USDT (exit trades only)
    ``reason``        — human-readable signal reason from strategy
    """
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10))
    backtest_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("backtest_jobs.id"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(10))
    pair: Mapped[str] = mapped_column(String(20), index=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_bars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    backtest_job: Mapped[Optional["BacktestJob"]] = relationship(back_populates="trades")


# ── Backtest jobs ──────────────────────────────────────────────────────────────

class BacktestJob(Base):
    """
    A backtest run: stores parameters, status and results (metrics + equity curve).

    ``status``  — 'pending' | 'running' | 'completed' | 'failed'
    ``metrics`` — JSON dict with Sharpe, MaxDD, WinRate, etc.
    ``equity_curve`` / ``equity_timestamps`` — parallel arrays for the chart
    """
    __tablename__ = "backtest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(40))
    pair: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(10))
    timeframe: Mapped[str] = mapped_column(String(5), default="1h")
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    equity_curve: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    equity_timestamps: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    trades: Mapped[List["Trade"]] = relationship(back_populates="backtest_job")


# ── Wallet snapshots ───────────────────────────────────────────────────────────

class WalletSnapshot(Base):
    """
    Point-in-time portfolio snapshot saved after every trade.

    ``source``           — 'paper' | 'live'
    ``balance_usdt``     — free USDT not tied up in positions
    ``positions_value``  — mark-to-market value of all open positions
    ``total_equity``     — balance_usdt + positions_value
    ``positions``        — JSON snapshot: {pair: {qty, avg_cost}}
    """
    __tablename__ = "wallet_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10), index=True)
    balance_usdt: Mapped[float] = mapped_column(Float)
    positions_value: Mapped[float] = mapped_column(Float)
    total_equity: Mapped[float] = mapped_column(Float)
    positions: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ── Bot state (resume) ────────────────────────────────────────────────────────

class BotState(Base):
    """
    Persisted bot state — written after every candle, used to resume after
    a restart.

    Only one row has ``is_active=True`` at any time.

    ``positions``      — {pair: {side, qty, avg_cost, bars_held, entry_time}}
    ``strategy_state`` — opaque dict returned by ``strategy.save_state()``
    """
    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(10))
    strategy: Mapped[str] = mapped_column(String(40))
    pairs: Mapped[list] = mapped_column(JSON)
    positions: Mapped[dict] = mapped_column(JSON, default=dict)
    strategy_state: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ── Bot events (audit log) ────────────────────────────────────────────────────

class BotEvent(Base):
    """
    Immutable audit log of bot lifecycle events.

    Every significant state change (start, stop, crash, risk halt, restart)
    writes a row here.  Used by ``GET /api/bot/events`` and Telegram alerts.

    ``event_type``  — 'start' | 'stop' | 'crash' | 'halt' | 'resume' | 'watchdog'
    ``mode``        — 'paper' | 'live' | None
    ``strategy``    — strategy name at the time of the event
    ``detail``      — free-text description or error message
    ``positions``   — snapshot of open positions at the time of the event
    """
    __tablename__ = "bot_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    pairs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    positions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ── Strategy Engine configs ───────────────────────────────────────────────────

class StrategyConfig(Base):
    """
    A saved, composable strategy configuration.

    execution_strategy + execution_timeframe define entry/exit logic.
    trend_filter_strategy + trend_filter_timeframe add optional HTF gating
    (multi-timeframe analysis).

    risk_profile is a JSON dict with optional overrides:
    {stop_loss_pct, take_profit_pct, position_size_pct, leverage,
     max_daily_loss_pct, max_drawdown_pct}

    Activate via POST /api/strategy-configs/{id}/activate, which writes the
    chosen strategy + risk profile into config.yaml.
    """

    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    execution_strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    execution_timeframe: Mapped[str] = mapped_column(String(5), nullable=False, default="1h")
    trend_filter_strategy: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    trend_filter_timeframe: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    risk_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    pairs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
