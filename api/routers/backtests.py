"""
Backtests router — job lifecycle, results, and statistical validation.

Endpoints
---------
POST   /api/backtests                    Submit a new backtest job (async)
GET    /api/backtests                    List jobs (filterable by strategy/pair)
GET    /api/backtests/{id}               Get single job with full results
DELETE /api/backtests/{id}               Delete job and all its trades
POST   /api/backtests/{id}/walk-forward  Walk-forward out-of-sample validation
POST   /api/backtests/{id}/monte-carlo   Monte Carlo trade-shuffle simulation
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db.engine import get_db
from api.db.models import BacktestJob, Trade
from api.schemas.backtest import (
    BacktestCreate, BacktestJobResponse, SUPPORTED_TIMEFRAMES,
)
from api.main import get_strategy_registry, load_bot_config

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _json_safe(value: Any) -> Any:
    """Recursively convert numpy scalars / NaN / Inf into JSON-friendly types."""
    try:
        import numpy as _np
    except Exception:  # pragma: no cover
        _np = None

    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if _np is not None:
        if isinstance(value, _np.integer):
            return int(value)
        if isinstance(value, _np.floating):
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        if isinstance(value, _np.ndarray):
            return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    return value


def _run_backtest_worker(
    job_id: int,
    strategy_name: str,
    pair: str,
    period: str,
    timeframe: str = "1h",
) -> None:
    """Execute a backtest in a background thread (called via FastAPI BackgroundTasks).

    Args:
        job_id:        Database ID of the BacktestJob row to update.
        strategy_name: Registry key for the strategy to instantiate.
        pair:          Trading pair, e.g. ``"BTC/USDT"``.
        period:        History window, e.g. ``"6m"``.
        timeframe:     Candle size, e.g. ``"4h"``.  Overrides the config default.
    """
    from api.db.engine import SessionLocal
    db = SessionLocal()

    try:
        job = db.get(BacktestJob, job_id)
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(tz=timezone.utc)
        db.commit()

        # Import bot code (path already set up by main.py)
        config = load_bot_config()
        registry = get_strategy_registry()

        if strategy_name not in registry:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        strategy = registry[strategy_name]()
        strategy.initialize(config.get("strategies", {}).get(strategy_name, {}))

        from backtester.runner import BacktestRunner
        runner = BacktestRunner(config)
        result = runner.run(strategy, pair, period, timeframe=timeframe)

        # Persist trades
        for t in result.get("trades", []):
            ts = t.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    ts = None
            trade_row = Trade(
                source="backtest",
                backtest_job_id=job_id,
                type=t.get("type", ""),
                pair=pair,
                strategy=strategy_name,
                price=float(t.get("price", 0)),
                qty=float(t.get("qty", 0)),
                fee=float(t.get("fee", 0)),
                pnl=t.get("pnl"),
                pnl_pct=t.get("pnl_pct"),
                reason=t.get("reason"),
                duration_bars=t.get("duration_bars"),
                avg_cost=t.get("avg_cost"),
                timestamp=ts,
            )
            db.add(trade_row)

        job.status = "done"
        job.metrics = result["metrics"]
        job.equity_curve = result["equity_curve"]
        job.equity_timestamps = result["equity_timestamps"]
        job.params = result["params"]
        job.finished_at = datetime.now(tz=timezone.utc)
        db.commit()

    except Exception as exc:
        try:
            job = db.get(BacktestJob, job_id)
            if job:
                job.status = "error"
                job.error_msg = str(exc)
                job.finished_at = datetime.now(tz=timezone.utc)
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


@router.post(
    "",
    response_model=BacktestJobResponse,
    status_code=202,
    summary="Submit a backtest job",
    response_description="Accepted — poll GET /backtests/{id} for results",
)
def create_backtest(
    body: BacktestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Submit a new backtest job and return immediately.

    The job runs asynchronously in a background thread. Use
    ``GET /backtests/{id}`` to poll for ``status='done'``.

    Args:
        body: Strategy, pair, period, and timeframe to simulate.

    Returns:
        BacktestJobResponse with ``status='pending'`` and the assigned ``id``.

    Raises:
        400: Unknown strategy name or unsupported timeframe.
    """
    # Validate strategy exists
    registry = get_strategy_registry()
    if body.strategy not in registry:
        raise HTTPException(
            400,
            f"Unknown strategy '{body.strategy}'. "
            f"Valid strategies: {sorted(registry.keys())}",
        )

    # Validate timeframe
    if body.timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            400,
            f"Invalid timeframe '{body.timeframe}'. "
            f"Valid: {sorted(SUPPORTED_TIMEFRAMES)}",
        )

    job = BacktestJob(
        strategy=body.strategy,
        pair=body.pair,
        period=body.period,
        timeframe=body.timeframe,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        _run_backtest_worker,
        job.id, body.strategy, body.pair, body.period, body.timeframe,
    )
    return job


@router.get(
    "",
    response_model=List[BacktestJobResponse],
    summary="List backtest jobs",
)
def list_backtests(
    strategy: Optional[str] = None,
    pair: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Return a list of backtest jobs, newest first.

    Args:
        strategy: Filter by strategy name (exact match).
        pair:     Filter by trading pair, e.g. ``"BTC/USDT"``.
        limit:    Maximum number of results to return (default 50).
    """
    q = db.query(BacktestJob)
    if strategy:
        q = q.filter(BacktestJob.strategy == strategy)
    if pair:
        q = q.filter(BacktestJob.pair == pair)
    return q.order_by(BacktestJob.created_at.desc()).limit(limit).all()


@router.get("/{job_id}", response_model=BacktestJobResponse, summary="Get backtest job")
def get_backtest(job_id: int, db: Session = Depends(get_db)):
    """Return a single backtest job by ID, including metrics and equity curve.

    Raises:
        404: Job not found.
    """
    job = db.get(BacktestJob, job_id)
    if not job:
        raise HTTPException(404, "Backtest job not found")
    return job


@router.delete("/{job_id}", status_code=204, summary="Delete backtest job")
def delete_backtest(job_id: int, db: Session = Depends(get_db)):
    """Permanently delete a backtest job and all its associated trades.

    Raises:
        404: Job not found.
    """
    job = db.get(BacktestJob, job_id)
    if not job:
        raise HTTPException(404, "Not found")
    db.query(Trade).filter(Trade.backtest_job_id == job_id).delete()
    db.delete(job)
    db.commit()


# ── Validation endpoints: walk-forward & monte carlo ─────────────────────────

@router.post("/{job_id}/walk-forward")
def run_walk_forward_for_job(
    job_id: int,
    n_segments: int = 5,
    period: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Re-run walk-forward validation against the same strategy / pair / period
    that was used to create the original backtest job.

    Query params:
      - n_segments (default 5): how many OOS slices to evaluate
      - period (default: inherit from the job): override data window
    """
    job = db.get(BacktestJob, job_id)
    if not job:
        raise HTTPException(404, "Backtest job not found")

    if n_segments < 2:
        raise HTTPException(400, "n_segments must be at least 2")
    if n_segments > 20:
        raise HTTPException(400, "n_segments capped at 20")

    try:
        config = load_bot_config()
        registry = get_strategy_registry()
        if job.strategy not in registry:
            raise HTTPException(400, f"Unknown strategy: {job.strategy}")

        strategy = registry[job.strategy]()
        strategy.initialize(config.get("strategies", {}).get(job.strategy, {}))

        from backtester.walk_forward import run_walk_forward

        wf_period = period or job.period or "1y"
        result = run_walk_forward(
            strategy=strategy,
            pair=job.pair,
            config=config,
            period=wf_period,
            n_segments=n_segments,
        )
        return _json_safe(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Walk-forward failed: {exc}") from exc


@router.post("/{job_id}/monte-carlo")
def run_monte_carlo_for_job(
    job_id: int,
    n_runs: int = 1000,
    seed: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Run Monte Carlo trade-order analysis over the already-recorded trades
    for this backtest job.  The shuffle operates on the pnl distribution
    only — no new market simulation is required.
    """
    job = db.get(BacktestJob, job_id)
    if not job:
        raise HTTPException(404, "Backtest job not found")

    if n_runs < 1:
        raise HTTPException(400, "n_runs must be at least 1")
    if n_runs > 100_000:
        raise HTTPException(400, "n_runs capped at 100000")

    try:
        initial_capital = 0.0
        if job.metrics and isinstance(job.metrics, dict):
            initial_capital = float(job.metrics.get("initial_capital") or 0.0)
        if initial_capital <= 0:
            config = load_bot_config()
            initial_capital = float(
                config.get("backtest", {}).get("initial_capital", 20.0)
            )

        # Fetch trades from DB (only closed ones with a pnl are useful).
        rows = (
            db.query(Trade)
            .filter(Trade.backtest_job_id == job_id, Trade.pnl.isnot(None))
            .all()
        )
        trades = [
            {
                "pnl": float(r.pnl) if r.pnl is not None else None,
                "status": "closed",
                "type": r.type,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ]

        from backtester.monte_carlo import run_monte_carlo

        result = run_monte_carlo(
            trades=trades,
            initial_capital=initial_capital,
            n_runs=n_runs,
            seed=seed,
        )
        result["job_id"] = job_id
        result["strategy"] = job.strategy
        result["pair"] = job.pair
        return _json_safe(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Monte Carlo failed: {exc}") from exc
