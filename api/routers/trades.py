from __future__ import annotations
from collections import defaultdict
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db.engine import get_db
from api.db.models import Trade
from api.schemas.trade import TradeResponse

router = APIRouter(prefix="/trades", tags=["trades"])


# ── Strategy performance response model ───────────────────────────────────────

class StrategyPerf(BaseModel):
    strategy:       str
    sources:        List[str]        # e.g. ["paper"] or ["paper","live"]
    total_trades:   int
    wins:           int
    losses:         int
    win_rate_pct:   float
    total_pnl:      float
    avg_pnl:        float
    avg_win:        float            # average winning trade (positive)
    avg_loss:       float            # average losing trade (negative)
    best_trade:     float
    worst_trade:    float
    profit_factor:  float            # gross_wins / |gross_losses|; 0 if no losses
    last_trade_at:  Optional[str] = None


@router.get("", response_model=List[TradeResponse])
def list_trades(
    pair: Optional[str] = None,
    strategy: Optional[str] = None,
    source: Optional[str] = None,
    trade_type: Optional[str] = Query(None, alias="type"),
    backtest_job_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Trade)
    if pair:
        q = q.filter(Trade.pair == pair)
    if strategy:
        q = q.filter(Trade.strategy == strategy)
    if source:
        q = q.filter(Trade.source == source)
    if trade_type:
        q = q.filter(Trade.type == trade_type)
    if backtest_job_id is not None:
        q = q.filter(Trade.backtest_job_id == backtest_job_id)
    return q.order_by(Trade.logged_at.desc()).offset(offset).limit(limit).all()


@router.get("/stats")
def trade_stats(
    source: Optional[str] = None,
    strategy: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Trade).filter(Trade.type.in_(["sell", "sell_eod"]), Trade.pnl.isnot(None))
    if source:
        q = q.filter(Trade.source == source)
    if strategy:
        q = q.filter(Trade.strategy == strategy)
    sells = q.all()

    if not sells:
        return {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        }

    winners = [t for t in sells if (t.pnl or 0) > 0]
    total_pnl = sum(t.pnl or 0 for t in sells)
    return {
        "total_trades": len(sells),
        "win_rate_pct": round(len(winners) / len(sells) * 100, 1),
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": round(total_pnl / len(sells), 4),
        "best_trade": round(max(t.pnl or 0 for t in sells), 4),
        "worst_trade": round(min(t.pnl or 0 for t in sells), 4),
    }


@router.get("/strategy-performance", response_model=List[StrategyPerf],
            summary="Per-strategy P&L breakdown")
def strategy_performance(
    source: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Aggregate closed trades (sell / sell_eod / cover / cover_eod) grouped by
    strategy name.

    Returns one row per strategy, sorted by ``total_pnl`` descending.
    Trades with a NULL strategy name are grouped under ``"(unknown)"``.

    Optional ``source`` filter: ``paper`` | ``live``
    """
    # Fetch all exit trades that have a realised PnL
    CLOSE_TYPES = ("sell", "sell_eod", "cover", "cover_eod")
    q = db.query(Trade).filter(
        Trade.type.in_(CLOSE_TYPES),
        Trade.pnl.isnot(None),
    )
    if source:
        q = q.filter(Trade.source == source)

    rows = q.order_by(Trade.logged_at.asc()).all()

    # Group by strategy
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in rows:
        key = t.strategy or "(unknown)"
        groups[key].append(t)

    results: list[StrategyPerf] = []
    for strat, trades in groups.items():
        pnls      = [t.pnl for t in trades]            # all non-null
        wins      = [p for p in pnls if p > 0]
        losses    = [p for p in pnls if p <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))

        profit_factor = round(gross_win / gross_loss, 3) if gross_loss > 0 else 0.0

        sources_set = sorted({t.source for t in trades})

        last = trades[-1]  # already sorted by logged_at asc
        last_at = None
        if last.logged_at:
            last_at = last.logged_at.isoformat()

        results.append(StrategyPerf(
            strategy      = strat,
            sources       = sources_set,
            total_trades  = len(trades),
            wins          = len(wins),
            losses        = len(losses),
            win_rate_pct  = round(len(wins) / len(trades) * 100, 1),
            total_pnl     = round(sum(pnls), 4),
            avg_pnl       = round(sum(pnls) / len(pnls), 4),
            avg_win       = round(sum(wins) / len(wins), 4) if wins else 0.0,
            avg_loss      = round(sum(losses) / len(losses), 4) if losses else 0.0,
            best_trade    = round(max(pnls), 4),
            worst_trade   = round(min(pnls), 4),
            profit_factor = profit_factor,
            last_trade_at = last_at,
        ))

    # Sort by total_pnl descending
    results.sort(key=lambda r: r.total_pnl, reverse=True)
    return results
