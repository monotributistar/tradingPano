"""
api/ws_manager.py — WebSocket connection manager
==================================================

Manages all active WebSocket connections and provides a thread-safe
broadcast method that can be called from any thread (including the
non-async bot-runner thread).

Architecture
------------
                      ┌─────────────────────────────────────┐
  bot-runner thread   │  broadcast_sync(msg)                │
  ──────────────────► │    └─ asyncio.run_coroutine_         │
                      │         threadsafe(_broadcast, loop) │
                      └─────────────────────────────────────┘
                                        │
                               asyncio event loop
                                        │
                      ┌─────────────────▼───────────────────┐
                      │  ConnectionManager._broadcast(msg)  │
                      │    for each WebSocket:               │
                      │      await ws.send_json(msg)         │
                      └─────────────────────────────────────┘

Setup (called from api/main.py on_startup)
------------------------------------------
    from api import ws_manager
    ws_manager.setup(asyncio.get_event_loop())

Message schema
--------------
Every message is a JSON object with ``type`` and ``payload`` fields:

    {"type": "status",  "payload": <BotStatus>}
    {"type": "trade",   "payload": <TradeDict>}
    {"type": "equity",  "payload": {"total_equity": 1234.5, "balance_usdt": 900.0, ...}}
    {"type": "event",   "payload": <BotEventDict>}
    {"type": "ping",    "payload": null}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── Module state ──────────────────────────────────────────────────────────────

_loop:    Optional[asyncio.AbstractEventLoop] = None
_manager: Optional["ConnectionManager"]       = None


def setup(loop: asyncio.AbstractEventLoop) -> None:
    """
    Bind the WebSocket manager to the running asyncio event loop.
    Must be called once during FastAPI startup before any broadcast.
    """
    global _loop, _manager
    _loop    = loop
    _manager = ConnectionManager()
    logger.info("WebSocket manager ready")


def get_manager() -> Optional["ConnectionManager"]:
    return _manager


def broadcast_sync(message: dict) -> None:
    """
    Thread-safe broadcast from non-async code (e.g. bot-runner thread).

    Schedules ``_manager.broadcast(message)`` on the FastAPI event loop and
    returns immediately.  No-op if the manager is not yet initialised or if
    there are no connected clients.
    """
    if _loop is None or _manager is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(_manager.broadcast(message), _loop)
    except Exception as exc:
        logger.debug(f"WebSocket broadcast_sync failed: {exc}")


# ── Connection manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Tracks active WebSocket connections and fans out broadcast messages.

    Dead connections are removed silently.
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info(
            f"WebSocket client connected — "
            f"total={len(self._connections)}"
        )

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info(
            f"WebSocket client disconnected — "
            f"total={len(self._connections)}"
        )

    async def broadcast(self, message: dict) -> None:
        """Send ``message`` to all connected clients.  Dead connections are pruned."""
        if not self._connections:
            return

        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        """Send a message to a single connection."""
        try:
            await ws.send_json(message)
        except Exception as exc:
            logger.debug(f"WebSocket unicast failed: {exc}")
            self.disconnect(ws)
