"""
api/schemas/bot.py — Request / response schemas for the bot router
===================================================================
"""

from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


class BotStartRequest(BaseModel):
    """
    Body for ``POST /api/bot/start``.

    Fields
    ------
    mode               'paper' or 'live'
    strategy           Strategy name — must be one of the 19 registered strategies.
                       Ignored when strategy_config_id is set (config overrides it).
    pairs              Trading pairs, e.g. ['BTC/USDT', 'ETH/USDT'].
                       Overridden by the config's pairs if strategy_config_id is set
                       and the config has non-empty pairs.
    restore            If True, resume open positions from the last saved BotState.
                       Pass True when restarting after a VPS reboot or manual stop
                       with live positions open.  Default: False (start fresh).
    strategy_config_id Optional ID of a saved StrategyConfig (from the Strategy
                       Engine).  When provided, the config's execution_strategy,
                       execution_timeframe, pairs (if non-empty), and risk_profile
                       overrides are applied automatically.
    """
    mode:               str            = Field("paper",          description="'paper' or 'live'")
    strategy:           str            = Field("mean_reversion", description="Strategy name (overridden by config)")
    pairs:              List[str]      = Field(["BTC/USDT"],     description="Trading pairs")
    restore:            bool           = Field(False,            description="Resume from last saved state")
    strategy_config_id: Optional[int]  = Field(None,            description="Saved StrategyConfig ID")


class BotStatusResponse(BaseModel):
    """
    Response for ``GET /api/bot/status``.

    Fields
    ------
    running               True when the bot thread is alive
    crashed               True when watchdog detected an unexpected thread death
    mode                  'paper' | 'live' | None
    strategy              Active strategy name, or None
    pairs                 Active trading pairs
    started_at            ISO-8601 UTC timestamp of last start, or None
    uptime_seconds        Seconds since last start (None when not running)
    error                 Last exception message if the thread crashed
    strategy_config_id    ID of the active StrategyConfig (None = quick-start)
    strategy_config_name  Display name of the active StrategyConfig
    """
    running:              bool            = False
    crashed:              bool            = False
    mode:                 Optional[str]   = None
    strategy:             Optional[str]   = None
    pairs:                List[str]       = []
    started_at:           Optional[str]   = None
    uptime_seconds:       Optional[float] = None
    error:                Optional[str]   = None
    strategy_config_id:   Optional[int]   = None
    strategy_config_name: Optional[str]   = None


class BotEventResponse(BaseModel):
    """
    One row from the ``bot_events`` audit table.

    ``event_type``  — 'start' | 'stop' | 'crash' | 'halt' | 'resume' | 'watchdog'
    """
    id:          int
    event_type:  str
    mode:        Optional[str]  = None
    strategy:    Optional[str]  = None
    pairs:       Optional[list] = None
    detail:      Optional[str]  = None
    positions:   Optional[dict] = None
    occurred_at: str
