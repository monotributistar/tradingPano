"""
Pydantic schemas for the backtests API.

Request/response contracts for:

- ``POST /api/backtests``      → ``BacktestCreate``
- ``GET  /api/backtests``      → ``list[BacktestJobResponse]``
- ``GET  /api/backtests/{id}`` → ``BacktestJobResponse``

All timestamps are ISO 8601 strings in UTC.
All monetary values are denominated in USDT.

Supported timeframes
--------------------
15m · 30m · 1h · 2h · 4h · 6h · 12h · 1d · 1w

Supported periods
-----------------
1w · 2w · 1m · 2m · 3m · 6m · 9m · 1y · 18m · 2y · 3y · 4y · 5y
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_TIMEFRAMES = {
    "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w",
}
"""Candle timeframes accepted by the backtest endpoint."""

SUPPORTED_PERIODS = {
    "1w", "2w", "1m", "2m", "3m", "6m", "9m", "1y", "18m", "2y", "3y", "4y", "5y",
}
"""History window strings accepted by the backtest endpoint."""


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class BacktestCreate(BaseModel):
    """Request body for ``POST /api/backtests``.

    Jobs run asynchronously. Poll ``GET /api/backtests/{id}`` for results.

    Example::

        {
            "strategy": "stoch_rsi",
            "pair": "NEAR/USDT",
            "period": "6m",
            "timeframe": "4h"
        }
    """

    strategy: str = Field(
        ...,
        description="Strategy identifier — see GET /api/strategies for valid names",
        examples=["stoch_rsi", "supertrend_pro", "macd_rsi"],
    )
    pair: str = Field(
        "BTC/USDT",
        description="Trading pair in BASE/QUOTE format",
        examples=["BTC/USDT", "ETH/USDT", "NEAR/USDT"],
    )
    period: str = Field(
        "6m",
        description="Historical data window. Valid: " + " · ".join(sorted(SUPPORTED_PERIODS)),
        examples=["3m", "6m", "1y"],
    )
    timeframe: str = Field(
        "1h",
        description="Candle size. Valid: " + " · ".join(sorted(SUPPORTED_TIMEFRAMES)),
        examples=["1h", "4h", "1d"],
    )


# ---------------------------------------------------------------------------
# Metrics sub-model
# ---------------------------------------------------------------------------

class BacktestMetrics(BaseModel):
    """Performance metrics produced at the end of a completed backtest run.

    Return and drawdown values are percentage points (e.g. 27.3 = +27.3%).
    Monetary values are in USDT.
    """

    total_return_pct: float = Field(..., description="Strategy return %, e.g. 27.3 means +27.3%")
    final_capital: float = Field(..., description="Final portfolio value in USDT")
    initial_capital: float = Field(..., description="Starting capital in USDT")

    sharpe_ratio: float = Field(..., description="Annualised Sharpe ratio (risk-free rate = 0)")
    sortino_ratio: float = Field(..., description="Annualised Sortino ratio")

    max_drawdown_pct: float = Field(..., description="Max peak-to-trough drawdown (positive %)")
    max_drawdown_duration_bars: Optional[int] = Field(
        None, description="Bars from drawdown peak to recovery"
    )

    win_rate_pct: float = Field(..., description="% of closed trades that were profitable")
    profit_factor: float = Field(..., description="Gross profit / gross loss (>1 is profitable)")
    total_trades: int = Field(..., description="Total completed round-trips")
    avg_trade_duration_bars: float = Field(..., description="Mean trade duration in candles")

    expectancy_usd: float = Field(
        ..., description="Expected profit per trade: (win_rate × avg_win) − (loss_rate × avg_loss)"
    )
    capital_utilization_pct: float = Field(
        ..., description="Average fraction of capital deployed per trade"
    )

    avg_win_usd: Optional[float] = Field(None, description="Average winning trade in USDT")
    avg_loss_usd: Optional[float] = Field(None, description="Average losing trade in USDT (negative)")


# ---------------------------------------------------------------------------
# Job response model
# ---------------------------------------------------------------------------

class BacktestJobResponse(BaseModel):
    """Full backtest job record returned by GET /api/backtests/*.

    ``equity_curve`` has one value per simulated bar (post-warmup) representing
    total portfolio value in USDT. ``equity_timestamps`` has matching ISO 8601
    UTC strings.
    """

    id: int = Field(..., description="Unique job ID")
    strategy: str = Field(..., description="Strategy name")
    pair: str = Field(..., description="Trading pair")
    period: str = Field(..., description="History window used")
    timeframe: str = Field(..., description="Candle size used")
    status: str = Field(..., description="pending | running | done | error")

    error_msg: Optional[str] = Field(None, description="Error detail (status=error only)")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Performance metrics (status=done)")
    equity_curve: Optional[List[float]] = Field(None, description="Portfolio value per bar")
    equity_timestamps: Optional[List[str]] = Field(None, description="ISO 8601 UTC per equity bar")
    params: Optional[Dict[str, Any]] = Field(None, description="Strategy params used")

    created_at: datetime = Field(..., description="Job creation time (UTC)")
    started_at: Optional[datetime] = Field(None, description="Execution start (UTC)")
    finished_at: Optional[datetime] = Field(None, description="Execution finish (UTC)")

    model_config = {"from_attributes": True}
