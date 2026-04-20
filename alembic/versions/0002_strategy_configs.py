"""Add strategy_configs table

Stores composable Strategy Engine configurations — each record pairs an
execution strategy with an optional HTF trend-filter strategy, per-strategy
risk profile overrides, and a list of target pairs.

Revision ID: 0002
Revises:     0001
Create Date: 2026-04-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_configs",
        sa.Column("id",                     sa.Integer(),    nullable=False),
        sa.Column("name",                   sa.String(80),   nullable=False),
        sa.Column("execution_strategy",     sa.String(40),   nullable=False),
        sa.Column("execution_timeframe",    sa.String(5),    nullable=False, server_default="1h"),
        sa.Column("trend_filter_strategy",  sa.String(40),   nullable=True),
        sa.Column("trend_filter_timeframe", sa.String(5),    nullable=True),
        sa.Column("risk_profile",           sa.JSON(),       nullable=False),
        sa.Column("pairs",                  sa.JSON(),       nullable=False),
        sa.Column("notes",                  sa.Text(),       nullable=True),
        sa.Column("created_at",             sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",             sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_configs_created_at", "strategy_configs", ["created_at"])
    op.create_index("ix_strategy_configs_execution_strategy", "strategy_configs", ["execution_strategy"])


def downgrade() -> None:
    op.drop_table("strategy_configs")
