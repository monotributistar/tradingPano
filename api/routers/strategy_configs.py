"""
api/routers/strategy_configs.py — Strategy Engine CRUD
=======================================================

Stores composable strategy configurations: an execution strategy + optional
higher-timeframe trend filter + per-strategy risk profile overrides.

Endpoints
---------
GET    /api/strategy-configs              List all saved configs
POST   /api/strategy-configs             Create a new config
GET    /api/strategy-configs/{id}        Get a single config
PUT    /api/strategy-configs/{id}        Replace a config (full update)
DELETE /api/strategy-configs/{id}        Delete a config
POST   /api/strategy-configs/{id}/activate  Write to config.yaml as active

Validation rules
----------------
- trend_filter_timeframe MUST be a higher timeframe than execution_timeframe
  when trend_filter_strategy is set.
- risk_profile.leverage is capped at min(strategy.max_leverage, 15.0) at
  activate time (enforced by RiskManager; stored value is as-entered).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from api.db.engine import get_db
from api.db.models import StrategyConfig as StrategyConfigORM

router = APIRouter(prefix="/strategy-configs", tags=["strategy-engine"])

# ── Timeframe ordering (used to validate HTF filter is actually higher) ────────

_TF_ORDER = ["15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"]

def _tf_rank(tf: str) -> int:
    try:
        return _TF_ORDER.index(tf)
    except ValueError:
        return -1


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class RiskProfileSchema(BaseModel):
    stop_loss_pct:      Optional[float] = Field(None, ge=0.1, le=50.0)
    take_profit_pct:    Optional[float] = Field(None, ge=0.1, le=200.0)
    position_size_pct:  Optional[float] = Field(None, ge=0.1, le=100.0)
    leverage:           Optional[float] = Field(None, ge=1.0, le=15.0)
    max_daily_loss_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    max_drawdown_pct:   Optional[float] = Field(None, ge=0.0, le=100.0)


class StrategyConfigCreate(BaseModel):
    name:                   str            = Field(..., min_length=1, max_length=80)
    execution_strategy:     str            = Field(..., min_length=1, max_length=40)
    execution_timeframe:    str            = Field("1h", min_length=2, max_length=5)
    trend_filter_strategy:  Optional[str]  = Field(None, max_length=40)
    trend_filter_timeframe: Optional[str]  = Field(None, max_length=5)
    risk_profile:           RiskProfileSchema = Field(default_factory=RiskProfileSchema)
    pairs:                  List[str]      = Field(default_factory=list)
    notes:                  Optional[str]  = None

    @model_validator(mode="after")
    def validate_trend_filter(self) -> "StrategyConfigCreate":
        has_strat = bool(self.trend_filter_strategy)
        has_tf    = bool(self.trend_filter_timeframe)

        if has_strat and not has_tf:
            raise ValueError(
                "trend_filter_timeframe is required when trend_filter_strategy is set"
            )
        if has_tf and not has_strat:
            raise ValueError(
                "trend_filter_strategy is required when trend_filter_timeframe is set"
            )
        if has_strat and has_tf:
            exec_rank   = _tf_rank(self.execution_timeframe)
            filter_rank = _tf_rank(self.trend_filter_timeframe)  # type: ignore[arg-type]
            if filter_rank <= exec_rank:
                raise ValueError(
                    f"trend_filter_timeframe ({self.trend_filter_timeframe}) must be "
                    f"higher than execution_timeframe ({self.execution_timeframe})"
                )
        return self


class StrategyConfigResponse(BaseModel):
    id:                     int
    name:                   str
    execution_strategy:     str
    execution_timeframe:    str
    trend_filter_strategy:  Optional[str]
    trend_filter_timeframe: Optional[str]
    risk_profile:           dict
    pairs:                  list
    notes:                  Optional[str]
    created_at:             datetime
    updated_at:             datetime

    model_config = {"from_attributes": True}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(id: int, db: Session) -> StrategyConfigORM:
    obj = db.query(StrategyConfigORM).filter(StrategyConfigORM.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"StrategyConfig {id} not found")
    return obj


def _orm_from_schema(body: StrategyConfigCreate) -> dict:
    return {
        "name":                   body.name,
        "execution_strategy":     body.execution_strategy,
        "execution_timeframe":    body.execution_timeframe,
        "trend_filter_strategy":  body.trend_filter_strategy,
        "trend_filter_timeframe": body.trend_filter_timeframe,
        "risk_profile":           body.risk_profile.model_dump(exclude_none=False),
        "pairs":                  body.pairs,
        "notes":                  body.notes,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=List[StrategyConfigResponse])
def list_configs(db: Session = Depends(get_db)) -> List[StrategyConfigORM]:
    """List all saved strategy configurations, newest first."""
    return (
        db.query(StrategyConfigORM)
        .order_by(StrategyConfigORM.created_at.desc())
        .all()
    )


@router.post("", response_model=StrategyConfigResponse, status_code=status.HTTP_201_CREATED)
def create_config(body: StrategyConfigCreate, db: Session = Depends(get_db)) -> StrategyConfigORM:
    """Create and persist a new strategy configuration."""
    now = _now()
    obj = StrategyConfigORM(**_orm_from_schema(body), created_at=now, updated_at=now)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{id}", response_model=StrategyConfigResponse)
def get_config(id: int, db: Session = Depends(get_db)) -> StrategyConfigORM:
    """Fetch a single strategy configuration by ID."""
    return _get_or_404(id, db)


@router.put("/{id}", response_model=StrategyConfigResponse)
def update_config(id: int, body: StrategyConfigCreate, db: Session = Depends(get_db)) -> StrategyConfigORM:
    """Replace all fields of an existing strategy configuration."""
    obj = _get_or_404(id, db)
    for k, v in _orm_from_schema(body).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(id: int, db: Session = Depends(get_db)) -> None:
    """Permanently delete a strategy configuration."""
    obj = _get_or_404(id, db)
    db.delete(obj)
    db.commit()


@router.post("/{id}/activate")
def activate_config(id: int, db: Session = Depends(get_db)) -> dict:
    """
    Write this strategy configuration into config.yaml as the active strategy.

    Updates:
    - active_strategy → execution_strategy
    - timeframe → execution_timeframe
    - pairs → config.pairs (if non-empty)
    - risk_profile fields → config.risk overrides
    - trend_filter section → written when a trend filter is set
    """
    from api.routers.settings import _load_raw, _save_raw

    obj = _get_or_404(id, db)
    cfg = _load_raw()

    # ── Execution strategy ───────────────────────────────��────────────────────
    cfg["active_strategy"] = obj.execution_strategy
    cfg["timeframe"]       = obj.execution_timeframe

    # ── Pairs ─────────────────────────────────────────────────────────────────
    if obj.pairs:
        cfg["pairs"] = obj.pairs

    # ── Risk profile overrides ────────────────────────────────────────────────
    risk = cfg.setdefault("risk", {})
    rp: dict = obj.risk_profile or {}
    if rp.get("leverage") is not None:
        risk["leverage"] = rp["leverage"]
    if rp.get("max_drawdown_pct") is not None:
        risk["max_drawdown_pct"] = rp["max_drawdown_pct"]
    if rp.get("max_daily_loss_pct") is not None:
        risk["daily_loss_stop_pct"] = rp["max_daily_loss_pct"]

    # ── Trend filter ──────────────────────────────────────────────────────────
    if obj.trend_filter_strategy:
        cfg["trend_filter"] = {
            "enabled":   True,
            "strategy":  obj.trend_filter_strategy,
            "timeframe": obj.trend_filter_timeframe,
        }
    else:
        cfg.pop("trend_filter", None)

    _save_raw(cfg)

    return {
        "ok":              True,
        "active_strategy": obj.execution_strategy,
        "config_id":       obj.id,
        "name":            obj.name,
    }
