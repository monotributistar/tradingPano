"""
Strategies router — strategy catalog with parameters and metadata.

Endpoints
---------
GET /api/strategies    List all 19 registered strategies with full metadata
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from api.main import get_strategy_registry, load_bot_config

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get(
    "",
    summary="List all strategies",
    response_description="Array of strategy descriptors with metadata and params",
)
def list_strategies() -> List[Dict[str, Any]]:
    """Return all registered strategies with metadata and current parameters.

    Each entry includes:

    - **name** — snake_case identifier used when submitting backtests
    - **description** — one-line summary of the strategy edge
    - **ideal_timeframes** — candle sizes the strategy is optimised for
    - **min_period** — minimum recommended backtest window (e.g. ``"3m"``)
    - **market_type** — ``trending`` | ``ranging`` | ``both``
    - **trade_frequency** — ``high`` (scalping) | ``medium`` | ``low`` (swing)
    - **min_liquidity** — ``high`` (BTC/ETH only) | ``medium`` | ``any``
    - **params** — current parameter values loaded from config.yaml
    - **param_grid** — parameter search space for the optimizer (Phase 5)
    """
    registry = get_strategy_registry()
    config = load_bot_config()
    result = []

    for name, cls in registry.items():
        instance = cls()
        cfg = config.get("strategies", {}).get(name, {})
        instance.initialize(cfg)

        result.append({
            "name": name,
            "description": cls.description,
            # ── Timeframe / regime metadata ───────────────────────────────
            "ideal_timeframes": getattr(cls, "ideal_timeframes", []),
            "min_period":       getattr(cls, "min_period", "1m"),
            "market_type":      getattr(cls, "market_type", "both"),
            "trade_frequency":  getattr(cls, "trade_frequency", "medium"),
            "min_liquidity":    getattr(cls, "min_liquidity", "any"),
            # ── Strategy Engine metadata ──────────────────────────────────
            "suitable_timeframes":        getattr(cls, "suitable_timeframes", []),
            "suitable_market_conditions": getattr(cls, "suitable_market_conditions", []),
            "recommended_leverage":       getattr(cls, "recommended_leverage", 1.0),
            "max_leverage":               getattr(cls, "max_leverage", 5.0),
            "risk_profile":               getattr(cls, "risk_profile", {
                "stop_loss_pct": 2.0, "take_profit_pct": 4.0, "position_size_pct": 5.0,
            }),
            # ── Parameters ───────────────────────────────────────────────
            "params":           instance.get_params(),
            "param_grid":       instance.get_param_grid(),
        })

    return result
