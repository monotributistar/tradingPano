"""
api/routers/settings.py — Runtime configuration editor
=======================================================

Allows the frontend to read and write the editable sections of config.yaml
without requiring an SSH session.  Only safe, non-credential fields are
exposed.

Endpoints
---------
GET  /api/config/settings      Current values for all editable sections
PATCH /api/config/risk         Update risk circuit-breaker + anomaly thresholds
PATCH /api/config/bot          Update bot settings (pairs, strategy, paper params)
"""

from __future__ import annotations

from typing import List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.main import _BOT_CONFIG_PATH, load_bot_config

router = APIRouter(prefix="/config", tags=["config"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_raw() -> dict:
    with open(str(_BOT_CONFIG_PATH)) as f:
        return yaml.safe_load(f) or {}


def _save_raw(cfg: dict) -> None:
    with open(str(_BOT_CONFIG_PATH), "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ── Request models ─────────────────────────────────────────────────────────────

class RiskPatch(BaseModel):
    """All fields are optional — only provided keys are written."""

    # Circuit breakers
    daily_loss_stop_pct:   Optional[float] = Field(None, ge=0, le=100)
    max_drawdown_pct:      Optional[float] = Field(None, ge=0, le=100)
    max_daily_trades:      Optional[int]   = Field(None, ge=0)
    max_consecutive_losses: Optional[int]  = Field(None, ge=0)
    max_concurrent_positions: Optional[int] = Field(None, ge=1, le=20)
    leverage:              Optional[float] = Field(None, ge=1.0, le=15.0)

    # Blackout window — "HH:MM-HH:MM" or "" to disable
    blackout_hours: Optional[str] = None

    # Anomaly detection thresholds
    slippage_alert_pct:  Optional[float] = Field(None, ge=0, le=100)
    balance_gap_pct:     Optional[float] = Field(None, ge=0, le=100)
    stale_price_candles: Optional[int]   = Field(None, ge=1)

    @field_validator("blackout_hours")
    @classmethod
    def validate_blackout(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        import re
        if not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", v):
            raise ValueError("blackout_hours must be 'HH:MM-HH:MM' or empty string")
        start, end = v.split("-")
        for part in (start, end):
            hh, mm = map(int, part.split(":"))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError(f"Invalid time component: {part}")
        return v


class PaperSettings(BaseModel):
    initial_balance: Optional[float] = Field(None, gt=0)
    fee_pct:         Optional[float] = Field(None, ge=0, le=5)


class BotPatch(BaseModel):
    """Top-level bot settings and paper trading parameters."""
    active_strategy: Optional[str]       = None
    pairs:           Optional[List[str]] = None
    paper:           Optional[PaperSettings] = None

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if not v:
            raise ValueError("pairs must not be empty")
        for pair in v:
            if "/" not in pair:
                raise ValueError(f"Invalid pair format '{pair}' — expected BASE/QUOTE")
        return v


# ── Response model ─────────────────────────────────────────────────────────────

class SettingsSnapshot(BaseModel):
    """Current editable config values returned by GET /api/config/settings."""

    # Risk / circuit breakers
    daily_loss_stop_pct:      float
    max_drawdown_pct:         float
    max_daily_trades:         int
    max_consecutive_losses:   int
    max_concurrent_positions: int
    leverage:                 float
    blackout_hours:           str

    # Anomaly thresholds
    slippage_alert_pct:  float
    balance_gap_pct:     float
    stale_price_candles: int

    # Bot settings
    active_strategy: str
    pairs: List[str]

    # Paper settings
    paper_initial_balance: float
    paper_fee_pct:         float


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=SettingsSnapshot, summary="Current editable settings")
def get_settings() -> SettingsSnapshot:
    """
    Return all user-editable configuration values as a flat object.
    Secrets (API keys, exchange credentials) are never included.
    """
    cfg = load_bot_config()
    risk = cfg.get("risk", {})
    paper = cfg.get("paper", {})

    return SettingsSnapshot(
        # Risk / circuit breakers
        daily_loss_stop_pct=      float(risk.get("daily_loss_stop_pct",   5.0)),
        max_drawdown_pct=         float(risk.get("max_drawdown_pct",       0.0)),
        max_daily_trades=         int(  risk.get("max_daily_trades",       0)),
        max_consecutive_losses=   int(  risk.get("max_consecutive_losses", 0)),
        max_concurrent_positions= int(  risk.get("max_concurrent_positions", 3)),
        leverage=                 float(risk.get("leverage",               1.0)),
        blackout_hours=           str(  risk.get("blackout_hours",         "")),
        # Anomaly thresholds
        slippage_alert_pct=       float(risk.get("slippage_alert_pct",     0.5)),
        balance_gap_pct=          float(risk.get("balance_gap_pct",        5.0)),
        stale_price_candles=      int(  risk.get("stale_price_candles",    5)),
        # Bot settings
        active_strategy=          str(  cfg.get("active_strategy",         "")),
        pairs=                    list( cfg.get("pairs",                   [])),
        # Paper settings
        paper_initial_balance=    float(paper.get("initial_balance",       100.0)),
        paper_fee_pct=            float(paper.get("fee_pct",               0.1)),
    )


@router.patch("/risk", summary="Update risk circuit breakers and anomaly thresholds")
def patch_risk(patch: RiskPatch):
    """
    Persist changes to the ``risk`` section of config.yaml.

    Only non-null fields in the request body are written.
    Returns the updated risk section after saving.
    """
    updates = patch.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")

    try:
        cfg = _load_raw()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="config.yaml not found")

    risk_section = cfg.setdefault("risk", {})
    risk_section.update(updates)

    try:
        _save_raw(cfg)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    return {"ok": True, "updated": list(updates.keys()), "risk": risk_section}


@router.patch("/bot", summary="Update bot settings and paper trading parameters")
def patch_bot(patch: BotPatch):
    """
    Persist changes to the top-level bot settings and ``paper`` sub-section
    of config.yaml.

    Only non-null fields are written.  Returns the updated top-level fields.
    """
    updates = patch.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")

    try:
        cfg = _load_raw()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="config.yaml not found")

    # Apply top-level fields
    if "active_strategy" in updates:
        cfg["active_strategy"] = updates["active_strategy"]
    if "pairs" in updates:
        cfg["pairs"] = updates["pairs"]

    # Apply paper sub-section
    if "paper" in updates and updates["paper"]:
        paper_section = cfg.setdefault("paper", {})
        paper_section.update(updates["paper"])

    try:
        _save_raw(cfg)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    written: list[str] = []
    if "active_strategy" in updates:
        written.append("active_strategy")
    if "pairs" in updates:
        written.append("pairs")
    if "paper" in updates:
        written += [f"paper.{k}" for k in updates["paper"]]

    return {
        "ok":      True,
        "updated": written,
        "active_strategy": cfg.get("active_strategy"),
        "pairs":           cfg.get("pairs", []),
        "paper":           cfg.get("paper", {}),
    }
