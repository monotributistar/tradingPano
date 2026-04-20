"""
Investment profile presets — apply one-click configurations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.main import load_bot_config, _BOT_CONFIG_PATH

router = APIRouter(prefix="/presets", tags=["presets"])

_PRESETS_PATH = Path(__file__).parent.parent.parent / "crypto_bot" / "presets.yaml"


def _load_presets() -> Dict[str, Any]:
    if not _PRESETS_PATH.exists():
        raise HTTPException(500, f"Presets file not found: {_PRESETS_PATH}")
    with open(_PRESETS_PATH) as f:
        return yaml.safe_load(f)


@router.get("")
def list_presets():
    """List all investment profile presets."""
    data = _load_presets()
    presets = data.get("presets", {})
    return [
        {
            "id": key,
            "label": p.get("label", key),
            "description": p.get("description", ""),
            "target_apy": p.get("target_apy"),
            "max_drawdown_target": p.get("max_drawdown_target"),
            "recommended_capital_usd": p.get("recommended_capital_usd"),
            "strategy": p.get("strategy"),
            "pairs": p.get("pairs", []),
            "timeframe": p.get("timeframe"),
            "period": p.get("period"),
            "leverage": p.get("leverage", 1.0),
            "amount_per_trade": p.get("amount_per_trade"),
            "max_concurrent_positions": p.get("max_concurrent_positions"),
            "daily_loss_stop_pct": p.get("daily_loss_stop_pct"),
            "use_futures": p.get("use_futures", False),
            "risk": p.get("risk", {}),
        }
        for key, p in presets.items()
    ]


@router.get("/{preset_id}")
def get_preset(preset_id: str):
    data = _load_presets()
    presets = data.get("presets", {})
    if preset_id not in presets:
        raise HTTPException(404, f"Preset not found: {preset_id}")
    return {"id": preset_id, **presets[preset_id]}


class ApplyResult(BaseModel):
    ok: bool
    preset_id: str
    changes: Dict[str, Any]


@router.post("/{preset_id}/apply", response_model=ApplyResult)
def apply_preset(preset_id: str):
    """
    Apply a preset to config.yaml — updates active_strategy, pairs, timeframe,
    and strategy params. Safe to call repeatedly.
    """
    data = _load_presets()
    presets = data.get("presets", {})
    if preset_id not in presets:
        raise HTTPException(404, f"Preset not found: {preset_id}")

    preset = presets[preset_id]
    config_path = str(_BOT_CONFIG_PATH)
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    changes: Dict[str, Any] = {}
    # Core config
    if preset.get("strategy"):
        cfg["active_strategy"] = preset["strategy"]
        changes["active_strategy"] = preset["strategy"]
    if preset.get("pairs"):
        cfg["pairs"] = preset["pairs"]
        changes["pairs"] = preset["pairs"]
    if preset.get("timeframe"):
        cfg.setdefault("backtest", {})["timeframe"] = preset["timeframe"]
        changes["timeframe"] = preset["timeframe"]

    # Risk controls (top-level)
    risk_block = {
        "leverage": preset.get("leverage", 1.0),
        "max_concurrent_positions": preset.get("max_concurrent_positions", 3),
        "daily_loss_stop_pct": preset.get("daily_loss_stop_pct", 5.0),
        "use_futures": preset.get("use_futures", False),
        "position_sizing": preset.get("risk", {}).get("position_sizing", "fixed"),
        "atr_stop_enabled": preset.get("risk", {}).get("atr_stop_enabled", True),
        "atr_stop_mult": preset.get("risk", {}).get("atr_stop_mult", 2.0),
        "preset_id": preset_id,
    }
    cfg["risk"] = risk_block
    changes["risk"] = risk_block

    # Strategy-specific: update amount_per_trade in the strategy config
    strategy_name = preset.get("strategy")
    if strategy_name and "strategies" in cfg and strategy_name in cfg["strategies"]:
        if "amount_per_trade" in preset:
            cfg["strategies"][strategy_name]["amount_per_trade"] = preset["amount_per_trade"]
            changes["amount_per_trade"] = preset["amount_per_trade"]

    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    return ApplyResult(ok=True, preset_id=preset_id, changes=changes)


@router.get("/active/current")
def get_active_preset():
    """Return which preset was last applied (read from config.risk.preset_id)."""
    cfg = load_bot_config()
    risk = cfg.get("risk", {})
    preset_id = risk.get("preset_id")
    if not preset_id:
        return {"preset_id": None, "risk": risk}
    data = _load_presets()
    preset = data.get("presets", {}).get(preset_id)
    return {"preset_id": preset_id, "preset": preset, "risk": risk}
