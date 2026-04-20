"""
api/routers/ws.py — WebSocket endpoint
========================================

Endpoint
--------
  WS /api/ws/bot?api_key=<BOT_API_SECRET>

Authentication
--------------
WebSocket connections cannot easily send custom headers from a browser,
so the API key is passed as a query parameter ``api_key``.

Events pushed to the client
---------------------------
  {"type": "status",  "payload": <BotStatus>}      — on connect + every status change
  {"type": "trade",   "payload": <TradeDict>}       — on every trade execution
  {"type": "equity",  "payload": <EquityDict>}      — on every wallet snapshot
  {"type": "event",   "payload": <BotEventDict>}    — on lifecycle events (start/stop/crash)
  {"type": "ping",    "payload": null}              — every 25 s keepalive

Messages from client
--------------------
  {"type": "ping"}   — client heartbeat (no response needed)

Error codes
-----------
  4003  Forbidden — invalid or missing api_key
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import os
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

import api.bot_manager as bot_manager
from api.ws_manager import get_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

HEARTBEAT_INTERVAL = 25  # seconds


def _valid_key(key: str) -> bool:
    """Constant-time comparison against BOT_API_SECRET."""
    expected = os.environ.get("BOT_API_SECRET", "").strip()
    if not expected or not key:
        return False
    return secrets.compare_digest(key, expected)


@router.websocket("/ws/bot")
async def bot_websocket(
    ws: WebSocket,
    api_key: str = Query("", alias="api_key"),
):
    """
    WebSocket feed for real-time bot events.

    Connect with:
        ws://host/api/ws/bot?api_key=<BOT_API_SECRET>

    On successful connection the server immediately pushes the current bot
    status, then continues to push events as they occur.
    """
    if not _valid_key(api_key):
        await ws.close(code=4003, reason="Invalid API key")
        return

    manager = get_manager()
    if manager is None:
        await ws.close(code=1011, reason="WebSocket manager not initialised")
        return

    await manager.connect(ws)

    try:
        # Push current status immediately on connect
        await manager.send_to(ws, {
            "type":    "status",
            "payload": bot_manager.get_status(),
        })

        # Keep the connection alive and handle client messages
        while True:
            try:
                # Wait for a client message with a timeout for heartbeats
                raw = await asyncio.wait_for(
                    ws.receive_text(),
                    timeout=HEARTBEAT_INTERVAL,
                )
                # Client sent something (e.g. a ping) — ignore it
                _ = raw
            except asyncio.TimeoutError:
                # Send server-side keepalive
                await manager.send_to(ws, {"type": "ping", "payload": None})
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug(f"WebSocket error: {exc}")
    finally:
        manager.disconnect(ws)
