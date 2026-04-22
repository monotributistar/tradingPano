"""
crypto_bot/margin_monitor.py — CFD Margin Level Monitor
=========================================================

Polls the engine's ``get_margin_info()`` method on a background daemon thread
and takes protective action when margin level drops below configured thresholds.

Thresholds
----------
WARN_LEVEL  (200%) — log a warning; no external alert
ALERT_LEVEL (150%) — send a Telegram / notifier alert
STOP_LEVEL  (110%) — alert + call ``bot_manager.stop()`` to halt trading

OANDA force-closes positions at 100% margin level, so stopping at 110%
gives the system a safety buffer.

Usage
-----
::

    monitor = MarginMonitor(engine, bot_manager, notifier=telegram_notifier)
    monitor.start()   # starts daemon thread
    ...
    monitor.stop()    # signals thread to exit on next iteration
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class MarginMonitor:
    """
    Background thread that watches the account margin level.

    Parameters
    ----------
    engine :
        Any engine with a ``get_margin_info() -> dict`` method.
    bot_manager :
        Object with a ``stop()`` method — called when STOP_LEVEL is hit.
    notifier : optional
        Object with a ``send(text: str)`` method for Telegram alerts.
    interval_s : int
        Seconds between each margin check (default: 30).
    """

    WARN_LEVEL  = 200.0  # % — log warning, no notification
    ALERT_LEVEL = 150.0  # % — send Telegram alert
    STOP_LEVEL  = 110.0  # % — alert + stop bot (OANDA closes at 100%)

    def __init__(
        self,
        engine,
        bot_manager,
        notifier=None,
        interval_s: int = 30,
    ) -> None:
        self._engine      = engine
        self._bot_manager = bot_manager
        self._notifier    = notifier
        self._interval    = interval_s
        self._running     = False
        self._thread: Optional[threading.Thread] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background monitoring thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="margin-monitor")
        self._thread.start()
        logger.info(
            "[MarginMonitor] Started — polling every %ds "
            "(warn=%.0f%% alert=%.0f%% stop=%.0f%%)",
            self._interval, self.WARN_LEVEL, self.ALERT_LEVEL, self.STOP_LEVEL,
        )

    def stop(self) -> None:
        """Signal the background thread to stop after its current sleep."""
        self._running = False
        logger.info("[MarginMonitor] Stop requested.")

    def check_once(self) -> dict:
        """
        Perform a single margin check synchronously.

        Returns a dict with at least:
            ``level``  — float margin level (or 0.0 on error)
            ``action`` — one of "ok" | "warn" | "alert" | "stop" | "error"
        """
        try:
            info  = self._engine.get_margin_info()
            level = float(info.get("margin_level", 9999.0))
        except Exception as exc:
            logger.error("[MarginMonitor] get_margin_info() failed: %s", exc)
            return {"level": 0.0, "action": "error", "error": str(exc)}

        if level <= self.STOP_LEVEL:
            msg = (
                f"⛔ MARGIN STOP — level {level:.1f}% hit the stop threshold "
                f"({self.STOP_LEVEL:.0f}%).  Halting bot."
            )
            logger.critical("[MarginMonitor] %s", msg)
            self._notify(msg)
            self._bot_manager.stop()
            return {"level": level, "action": "stop"}

        if level <= self.ALERT_LEVEL:
            msg = (
                f"🚨 MARGIN ALERT — level {level:.1f}% is near the stop threshold "
                f"({self.STOP_LEVEL:.0f}%).  Check positions."
            )
            logger.error("[MarginMonitor] %s", msg)
            self._notify(msg)
            return {"level": level, "action": "alert"}

        if level <= self.WARN_LEVEL:
            logger.warning("[MarginMonitor] Margin level LOW: %.1f%%", level)
            return {"level": level, "action": "warn"}

        logger.debug("[MarginMonitor] Margin OK: %.1f%%", level)
        return {"level": level, "action": "ok"}

    # ── Internal ───────────────────────────────────────────────────────────────

    def _notify(self, text: str) -> None:
        if self._notifier is not None:
            try:
                self._notifier.send(text)
            except Exception as exc:
                logger.warning("[MarginMonitor] Notifier failed: %s", exc)

    def _loop(self) -> None:
        """Main loop — runs in the daemon thread."""
        while self._running:
            self.check_once()
            time.sleep(self._interval)
