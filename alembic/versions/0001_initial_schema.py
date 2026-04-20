"""Initial schema — all tables

Creates the five core tables that make up the trading bot's data model:

  trades            — individual trade entries (buy/sell/short/cover, paper/live/backtest)
  backtest_jobs     — backtest run parameters, status, metrics and equity curve
  wallet_snapshots  — periodic portfolio snapshots (balance + open positions)
  bot_state         — persisted bot state used to resume after a restart
  bot_events        — immutable audit log of lifecycle events (start/stop/crash/halt)

Revision ID: 0001
Revises:     (none — initial revision)
Create Date: 2026-04-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Upgrade ────────────────────────────────────────────────────────────────────

def upgrade() -> None:

    # ── backtest_jobs ─────────────────────────────────────────────────────────
    # Created first because trades.backtest_job_id has a FK to it.
    op.create_table(
        "backtest_jobs",
        sa.Column("id",                 sa.Integer(),    nullable=False),
        sa.Column("strategy",           sa.String(40),   nullable=False),
        sa.Column("pair",               sa.String(20),   nullable=False),
        sa.Column("period",             sa.String(10),   nullable=False),
        sa.Column("timeframe",          sa.String(5),    nullable=False, server_default="1h"),
        sa.Column("params",             sa.JSON(),       nullable=True),
        sa.Column("status",             sa.String(12),   nullable=False, server_default="pending"),
        sa.Column("error_msg",          sa.Text(),       nullable=True),
        sa.Column("metrics",            sa.JSON(),       nullable=True),
        sa.Column("equity_curve",       sa.JSON(),       nullable=True),
        sa.Column("equity_timestamps",  sa.JSON(),       nullable=True),
        sa.Column("created_at",         sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at",        sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_jobs_status",     "backtest_jobs", ["status"])
    op.create_index("ix_backtest_jobs_created_at", "backtest_jobs", ["created_at"])

    # ── trades ────────────────────────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column("id",               sa.Integer(),    nullable=False),
        sa.Column("source",           sa.String(10),   nullable=False),
        sa.Column("backtest_job_id",  sa.Integer(),    nullable=True),
        sa.Column("type",             sa.String(10),   nullable=False),
        sa.Column("pair",             sa.String(20),   nullable=False),
        sa.Column("strategy",         sa.String(40),   nullable=True),
        sa.Column("price",            sa.Float(),      nullable=False),
        sa.Column("qty",              sa.Float(),      nullable=False),
        sa.Column("fee",              sa.Float(),      nullable=False, server_default="0.0"),
        sa.Column("pnl",              sa.Float(),      nullable=True),
        sa.Column("pnl_pct",          sa.Float(),      nullable=True),
        sa.Column("reason",           sa.Text(),       nullable=True),
        sa.Column("duration_bars",    sa.Integer(),    nullable=True),
        sa.Column("avg_cost",         sa.Float(),      nullable=True),
        sa.Column("timestamp",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("logged_at",        sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["backtest_job_id"], ["backtest_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_backtest_job_id", "trades", ["backtest_job_id"])
    op.create_index("ix_trades_pair",            "trades", ["pair"])
    op.create_index("ix_trades_strategy",        "trades", ["strategy"])
    op.create_index("ix_trades_logged_at",       "trades", ["logged_at"])

    # ── wallet_snapshots ──────────────────────────────────────────────────────
    op.create_table(
        "wallet_snapshots",
        sa.Column("id",               sa.Integer(),  nullable=False),
        sa.Column("source",           sa.String(10), nullable=False),
        sa.Column("balance_usdt",     sa.Float(),    nullable=False),
        sa.Column("positions_value",  sa.Float(),    nullable=False),
        sa.Column("total_equity",     sa.Float(),    nullable=False),
        sa.Column("positions",        sa.JSON(),     nullable=False),
        sa.Column("timestamp",        sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wallet_snapshots_source",    "wallet_snapshots", ["source"])
    op.create_index("ix_wallet_snapshots_timestamp", "wallet_snapshots", ["timestamp"])

    # ── bot_state ─────────────────────────────────────────────────────────────
    op.create_table(
        "bot_state",
        sa.Column("id",             sa.Integer(),   nullable=False),
        sa.Column("mode",           sa.String(10),  nullable=False),
        sa.Column("strategy",       sa.String(40),  nullable=False),
        sa.Column("pairs",          sa.JSON(),      nullable=False),
        sa.Column("positions",      sa.JSON(),      nullable=False),
        sa.Column("strategy_state", sa.JSON(),      nullable=False),
        sa.Column("is_active",      sa.Boolean(),   nullable=False, server_default="0"),
        sa.Column("saved_at",       sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_state_is_active", "bot_state", ["is_active"])
    op.create_index("ix_bot_state_saved_at",  "bot_state", ["saved_at"])

    # ── bot_events ────────────────────────────────────────────────────────────
    op.create_table(
        "bot_events",
        sa.Column("id",          sa.Integer(),   nullable=False),
        sa.Column("event_type",  sa.String(20),  nullable=False),
        sa.Column("mode",        sa.String(10),  nullable=True),
        sa.Column("strategy",    sa.String(40),  nullable=True),
        sa.Column("pairs",       sa.JSON(),      nullable=True),
        sa.Column("detail",      sa.Text(),      nullable=True),
        sa.Column("positions",   sa.JSON(),      nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_events_event_type",  "bot_events", ["event_type"])
    op.create_index("ix_bot_events_occurred_at", "bot_events", ["occurred_at"])


# ── Downgrade ──────────────────────────────────────────────────────────────────

def downgrade() -> None:
    # Drop in reverse FK dependency order
    op.drop_table("bot_events")
    op.drop_table("bot_state")
    op.drop_table("wallet_snapshots")
    op.drop_table("trades")
    op.drop_table("backtest_jobs")
