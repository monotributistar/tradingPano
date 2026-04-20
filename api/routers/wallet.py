from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime

from api.db.engine import get_db
from api.db.models import WalletSnapshot

router = APIRouter(prefix="/wallet", tags=["wallet"])


class WalletSnapshotResponse(BaseModel):
    id: int
    source: str
    balance_usdt: float
    positions_value: float
    total_equity: float
    positions: dict
    timestamp: datetime

    class Config:
        from_attributes = True


@router.get("/history", response_model=List[WalletSnapshotResponse])
def wallet_history(
    source: Optional[str] = None,
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
):
    q = db.query(WalletSnapshot)
    if source:
        q = q.filter(WalletSnapshot.source == source)
    return q.order_by(WalletSnapshot.timestamp.asc()).limit(limit).all()


@router.get("/summary")
def wallet_summary(
    source: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(WalletSnapshot)
    if source:
        q = q.filter(WalletSnapshot.source == source)

    latest = q.order_by(WalletSnapshot.timestamp.desc()).first()
    first = q.order_by(WalletSnapshot.timestamp.asc()).first()

    if not latest:
        return {
            "total_equity": None,
            "balance_usdt": None,
            "positions_value": None,
            "positions": {},
            "pnl": None,
            "pnl_pct": None,
            "snapshots_count": 0,
        }

    pnl = round(latest.total_equity - first.total_equity, 4) if first else 0.0
    pnl_pct = round(pnl / first.total_equity * 100, 2) if first and first.total_equity else 0.0

    return {
        "total_equity": latest.total_equity,
        "balance_usdt": latest.balance_usdt,
        "positions_value": latest.positions_value,
        "positions": latest.positions,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "snapshots_count": q.count(),
    }
