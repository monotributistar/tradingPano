from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class TradeResponse(BaseModel):
    id: int
    source: str
    backtest_job_id: Optional[int] = None
    type: str
    pair: str
    strategy: Optional[str] = None
    price: float
    qty: float
    fee: float
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    reason: Optional[str] = None
    duration_bars: Optional[int] = None
    avg_cost: Optional[float] = None
    timestamp: Optional[datetime] = None
    logged_at: datetime

    model_config = {"from_attributes": True}
