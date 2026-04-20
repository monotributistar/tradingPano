"""
api/routers/portfolio.py — Multi-strategy portfolio endpoints
=============================================================

All endpoints require ``X-API-Key`` (injected by main.py at router level).

Endpoints
---------
GET  /api/portfolio/status       Aggregate status + per-slot breakdown
POST /api/portfolio/start        Start all configured portfolio slots
POST /api/portfolio/stop         Stop all running slots
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── Request / Response models ──────────────────────────────────────────────────

class PortfolioStartRequest(BaseModel):
    mode: str = "paper"   # "paper" | "live"


class SlotStatus(BaseModel):
    index:       int
    name:        str
    pairs:       list[str]
    capital_pct: float
    mode:        str
    running:     bool
    crashed:     bool
    started_at:  Optional[str] = None
    uptime_s:    Optional[float] = None
    trade_count: int = 0
    error:       Optional[str] = None


class PortfolioStatusResponse(BaseModel):
    running:       bool
    alive_slots:   int
    total_slots:   int
    crashed_slots: int
    total_trades:  int
    started_at:    Optional[str] = None
    uptime_s:      Optional[float] = None
    slots:         list[SlotStatus] = []


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status", response_model=PortfolioStatusResponse)
def get_portfolio_status():
    """Return aggregate portfolio status and per-slot breakdown."""
    from api.portfolio_manager import portfolio_status
    return portfolio_status()


@router.post("/start", response_model=PortfolioStatusResponse)
def start_portfolio(body: PortfolioStartRequest):
    """
    Start all strategy slots defined in ``config.yaml portfolio.strategies``.

    Requires at least one entry under ``portfolio.strategies``.
    Returns HTTP 409 if the portfolio is already running.
    Returns HTTP 422 if the portfolio section is missing or empty.
    """
    from api.portfolio_manager import start_portfolio as _start, is_running
    from api.main import load_bot_config

    if is_running():
        raise HTTPException(status_code=409, detail="Portfolio already running")

    config = load_bot_config()
    portfolio_cfg = config.get("portfolio", {})

    if not portfolio_cfg or not portfolio_cfg.get("strategies"):
        raise HTTPException(
            status_code=422,
            detail=(
                "No portfolio.strategies found in config.yaml. "
                "Add a portfolio section with at least one strategy entry."
            ),
        )

    try:
        status = _start(config, mode=body.mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return status


@router.post("/stop", response_model=PortfolioStatusResponse)
def stop_portfolio():
    """Signal all running portfolio slots to stop gracefully."""
    from api.portfolio_manager import stop_portfolio as _stop, is_running

    if not is_running():
        raise HTTPException(status_code=409, detail="Portfolio is not running")

    return _stop()
