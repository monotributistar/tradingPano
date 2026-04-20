"""
api/telegram_bot.py — Telegram integration
============================================

Two responsibilities:
  1. **TelegramNotifier** — sends alert messages to a Telegram chat via the
     Bot API (plain HTTP, no external library needed beyond ``requests``).
     Called by ``bot_manager.py`` on every trade, halt, crash, start, stop.

  2. **TelegramCommandHandler** — long-polls the Bot API for incoming messages
     and dispatches ``/commands`` to the bot manager.  Runs in a daemon thread.

Configuration
-------------
Set in ``.env``:

    TELEGRAM_BOT_TOKEN=123456:ABCdef...    # from @BotFather
    TELEGRAM_CHAT_ID=987654321            # from @userinfobot

Leave blank to disable Telegram entirely (no error, just a warning).

Supported commands (sent to the bot in Telegram)
-------------------------------------------------
  /help              Show command list
  /status            Bot status (running, strategy, uptime)
  /balance           Current equity + open positions
  /pnl               Today's and total P&L from DB
  /trades [n]        Last N closed trades (default 5)
  /stop              Stop the trading bot
  /start [strategy]  Start with specified strategy (paper mode)

Security
--------
Only messages from ``TELEGRAM_CHAT_ID`` are processed — all other senders
receive a "not authorised" reply.

Usage
-----
    from api.telegram_bot import get_notifier, start_command_handler, stop_command_handler

    # In api/main.py on_startup:
    start_command_handler()

    # In bot_manager.py after a trade:
    get_notifier().alert_trade_closed(pair, side, price, qty, pnl, pnl_pct, strategy, mode)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── Module-level singleton ────────────────────────────────────────────────────

_notifier: Optional["TelegramNotifier"] = None
_handler: Optional["TelegramCommandHandler"] = None


def get_notifier() -> "TelegramNotifier":
    """Return the singleton notifier (no-op if token/chat_id not configured)."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier(
            token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )
    return _notifier


def start_command_handler() -> None:
    """Start the command polling thread.  Safe to call multiple times."""
    global _handler
    n = get_notifier()
    if not n.enabled:
        logger.info("Telegram disabled — BOT_TOKEN or CHAT_ID not set")
        return
    if _handler and _handler.is_running():
        return
    _handler = TelegramCommandHandler(n)
    _handler.start()
    logger.info("Telegram command handler started")


def stop_command_handler() -> None:
    """Stop the polling thread gracefully."""
    global _handler
    if _handler:
        _handler.stop()
        _handler = None


# ── Notifier ──────────────────────────────────────────────────────────────────

class TelegramNotifier:
    """
    Sends messages to a Telegram chat via direct HTTP calls to the Bot API.

    All ``alert_*`` methods are fire-and-forget — failures are logged but
    never raised.  Thread-safe.
    """

    def __init__(self, token: str, chat_id: str):
        self._token   = token.strip()
        self._chat_id = chat_id.strip()
        self._base    = f"https://api.telegram.org/bot{self._token}"
        self._lock    = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    # ── Core send ──────────────────────────────────────────────────────────

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a plain text message.  Returns True on success."""
        if not self.enabled:
            return False
        try:
            import urllib.request, urllib.parse, json
            payload = json.dumps({
                "chat_id":    self._chat_id,
                "text":       text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self._base}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.warning(f"Telegram send failed: {exc}")
            return False

    # ── Alert helpers ──────────────────────────────────────────────────────

    def alert_started(self, mode: str, strategy: str, pairs: list,
                      restore: bool = False) -> None:
        restore_tag = " <i>(positions restored)</i>" if restore else ""
        pairs_str   = ", ".join(pairs)
        self.send(
            f"▶️ <b>Bot started</b>{restore_tag}\n"
            f"Mode: <code>{mode.upper()}</code>\n"
            f"Strategy: <code>{strategy}</code>\n"
            f"Pairs: {pairs_str}"
        )

    def alert_stopped(self, mode: str, strategy: str) -> None:
        self.send(
            f"⏹ <b>Bot stopped</b>\n"
            f"Mode: <code>{mode.upper()}</code>  Strategy: <code>{strategy}</code>"
        )

    def alert_trade_opened(self, pair: str, side: str, price: float,
                           qty: float, strategy: str, mode: str) -> None:
        emoji = "🟢" if side.lower() in ("buy", "long") else "🔴"
        self.send(
            f"{emoji} <b>TRADE OPENED</b> [{mode.upper()}]\n"
            f"<code>{side.upper()} {pair}</code>\n"
            f"Price: <b>{price:,.4f}</b>  Qty: {qty:.6f}\n"
            f"Strategy: {strategy}"
        )

    def alert_trade_closed(self, pair: str, side: str, price: float,
                           qty: float, pnl: float, pnl_pct: float,
                           strategy: str, mode: str) -> None:
        sign  = "+" if pnl >= 0 else ""
        emoji = "💚" if pnl >= 0 else "🔴"
        self.send(
            f"{emoji} <b>TRADE CLOSED</b> [{mode.upper()}]\n"
            f"<code>{side.upper()} {pair}</code>\n"
            f"Price: <b>{price:,.4f}</b>  Qty: {qty:.6f}\n"
            f"P&L: <b>{sign}{pnl:.2f} USDT ({sign}{pnl_pct:.2f}%)</b>\n"
            f"Strategy: {strategy}"
        )

    def alert_risk_halt(self, reason: str, mode: str) -> None:
        self.send(
            f"⚠️ <b>RISK HALT</b> [{mode.upper()}]\n"
            f"{reason}\n"
            f"<i>No new trades will open until tomorrow UTC.</i>"
        )

    def alert_crash(self, error: str, mode: str, strategy: str) -> None:
        self.send(
            f"❌ <b>BOT CRASHED</b>\n"
            f"Mode: <code>{mode}</code>  Strategy: <code>{strategy}</code>\n"
            f"Error: <code>{error[:400]}</code>\n"
            f"<i>Restart with POST /api/bot/start</i>"
        )

    def alert_watchdog(self, mode: str, strategy: str) -> None:
        self.send(
            f"🔄 <b>WATCHDOG ALERT</b>\n"
            f"Bot thread died unexpectedly.\n"
            f"Mode: <code>{mode}</code>  Strategy: <code>{strategy}</code>\n"
            f"<i>Restart with POST /api/bot/start or /start {strategy}</i>"
        )

    def alert_resume(self, mode: str, strategy: str, n_positions: int) -> None:
        self.send(
            f"🔄 <b>Bot resumed</b>\n"
            f"Mode: <code>{mode.upper()}</code>  Strategy: <code>{strategy}</code>\n"
            f"Restored {n_positions} open position(s)"
        )

    def alert_circuit_breaker(self, rule: str, detail: str, mode: str) -> None:
        self.send(
            f"🛑 <b>CIRCUIT BREAKER</b> [{mode.upper()}]\n"
            f"Rule: <b>{rule}</b>\n"
            f"{detail}"
        )


# ── Command handler ───────────────────────────────────────────────────────────

class TelegramCommandHandler:
    """
    Long-polls the Telegram Bot API for commands and dispatches them.

    Runs in a background daemon thread.  Only processes messages from
    the configured ``TELEGRAM_CHAT_ID``.
    """

    POLL_TIMEOUT = 30       # seconds for long polling
    RETRY_DELAY  = 5        # seconds between retries on error

    def __init__(self, notifier: TelegramNotifier):
        self._notifier   = notifier
        self._offset     = 0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="telegram-poller",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    # ── Internal ───────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        logger.info("Telegram command polling started")
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates()
                for upd in updates:
                    self._dispatch(upd)
            except Exception as exc:
                logger.warning(f"Telegram poll error: {exc}")
                self._stop_event.wait(self.RETRY_DELAY)
        logger.info("Telegram command polling stopped")

    def _get_updates(self) -> list:
        import urllib.request, urllib.parse, json
        params = urllib.parse.urlencode({
            "offset":          self._offset,
            "timeout":         self.POLL_TIMEOUT,
            "allowed_updates": '["message"]',
        })
        url = f"{self._notifier._base}/getUpdates?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.POLL_TIMEOUT + 5) as resp:
                data = json.loads(resp.read())
                if data.get("ok"):
                    results = data.get("result", [])
                    if results:
                        self._offset = results[-1]["update_id"] + 1
                    return results
        except Exception:
            pass
        return []

    def _reply(self, chat_id: int, text: str) -> None:
        """Reply to a specific chat (not necessarily the configured one)."""
        if not self._notifier.enabled:
            return
        try:
            import urllib.request, json
            payload = json.dumps({
                "chat_id":    str(chat_id),
                "text":       text,
                "parse_mode": "HTML",
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self._notifier._base}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:
            logger.warning(f"Telegram reply failed: {exc}")

    def _dispatch(self, update: dict) -> None:
        msg     = update.get("message", {})
        text    = msg.get("text", "").strip()
        chat_id = msg.get("chat", {}).get("id")

        if not text or not chat_id:
            return

        # Security: only accept commands from authorised chat
        if str(chat_id) != self._notifier._chat_id:
            self._reply(chat_id, "⛔ Not authorised.")
            return

        cmd = text.split()[0].lower().lstrip("/")

        if cmd == "help":
            self._cmd_help(chat_id)
        elif cmd == "status":
            self._cmd_status(chat_id)
        elif cmd == "balance":
            self._cmd_balance(chat_id)
        elif cmd == "pnl":
            self._cmd_pnl(chat_id)
        elif cmd == "trades":
            n = _parse_int(text, 5)
            self._cmd_trades(chat_id, n)
        elif cmd == "stop":
            self._cmd_stop(chat_id)
        elif cmd == "start":
            parts    = text.split()
            strategy = parts[1] if len(parts) > 1 else None
            self._cmd_start(chat_id, strategy)
        else:
            self._reply(chat_id, f"Unknown command: <code>{cmd}</code>\nSend /help")

    # ── Commands ───────────────────────────────────────────────────────────

    def _cmd_help(self, chat_id: int) -> None:
        self._reply(chat_id,
            "⚡ <b>CryptoBot commands</b>\n\n"
            "/status — current bot state\n"
            "/balance — equity + positions\n"
            "/pnl — today's and all-time P&L\n"
            "/trades [n] — last N closed trades\n"
            "/stop — stop the bot\n"
            "/start [strategy] — start in paper mode\n"
            "/help — this message"
        )

    def _cmd_status(self, chat_id: int) -> None:
        import api.bot_manager as bm
        s = bm.get_status()
        if s["running"]:
            uptime = ""
            if s.get("uptime_seconds"):
                h = int(s["uptime_seconds"]) // 3600
                m = (int(s["uptime_seconds"]) % 3600) // 60
                uptime = f"\nUptime: {h}h {m}m"
            text = (
                f"✅ <b>Bot running</b>\n"
                f"Mode: <code>{s['mode'].upper()}</code>\n"
                f"Strategy: <code>{s['strategy']}</code>\n"
                f"Pairs: {', '.join(s['pairs'])}"
                f"{uptime}"
            )
        elif s.get("crashed"):
            text = f"❌ <b>Bot CRASHED</b>\n{s.get('error','unknown error')}"
        else:
            text = "⏸ <b>Bot is IDLE</b>"
        self._reply(chat_id, text)

    def _cmd_balance(self, chat_id: int) -> None:
        try:
            from api.db.engine import SessionLocal
            from api.db.models import WalletSnapshot
            db = SessionLocal()
            snap = db.query(WalletSnapshot).order_by(
                WalletSnapshot.timestamp.desc()
            ).first()
            db.close()
            if snap:
                self._reply(chat_id,
                    f"💰 <b>Balance</b>\n"
                    f"Total equity: <b>{snap.total_equity:.2f} USDT</b>\n"
                    f"Free USDT: {snap.balance_usdt:.2f}\n"
                    f"Positions: {snap.positions_value:.2f} USDT\n"
                    f"<i>as of {snap.timestamp.strftime('%Y-%m-%d %H:%M UTC')}</i>"
                )
            else:
                self._reply(chat_id, "No wallet snapshots yet.")
        except Exception as exc:
            self._reply(chat_id, f"Error: {exc}")

    def _cmd_pnl(self, chat_id: int) -> None:
        try:
            from datetime import datetime, timezone
            from api.db.engine import SessionLocal
            from api.db.models import Trade
            from sqlalchemy import func
            db    = SessionLocal()
            today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

            today_pnl = db.query(func.sum(Trade.pnl)).filter(
                Trade.pnl.isnot(None),
                Trade.logged_at >= today,
            ).scalar() or 0.0

            total_pnl = db.query(func.sum(Trade.pnl)).filter(
                Trade.pnl.isnot(None)
            ).scalar() or 0.0

            trades_today = db.query(func.count(Trade.id)).filter(
                Trade.logged_at >= today,
                Trade.pnl.isnot(None),
            ).scalar() or 0

            db.close()

            sign_t  = "+" if today_pnl >= 0 else ""
            sign_a  = "+" if total_pnl >= 0 else ""
            emoji_t = "💚" if today_pnl >= 0 else "🔴"
            emoji_a = "💚" if total_pnl >= 0 else "🔴"

            self._reply(chat_id,
                f"📊 <b>P&L Summary</b>\n"
                f"{emoji_t} Today: <b>{sign_t}{today_pnl:.2f} USDT</b> ({trades_today} trades)\n"
                f"{emoji_a} All-time: <b>{sign_a}{total_pnl:.2f} USDT</b>"
            )
        except Exception as exc:
            self._reply(chat_id, f"Error: {exc}")

    def _cmd_trades(self, chat_id: int, n: int = 5) -> None:
        try:
            from api.db.engine import SessionLocal
            from api.db.models import Trade
            db     = SessionLocal()
            trades = (
                db.query(Trade)
                .filter(Trade.pnl.isnot(None))
                .order_by(Trade.logged_at.desc())
                .limit(min(n, 10))
                .all()
            )
            db.close()
            if not trades:
                self._reply(chat_id, "No closed trades yet.")
                return
            lines = [f"📋 <b>Last {len(trades)} trades</b>\n"]
            for t in trades:
                sign  = "+" if (t.pnl or 0) >= 0 else ""
                emoji = "💚" if (t.pnl or 0) >= 0 else "🔴"
                lines.append(
                    f"{emoji} {t.type.upper()} {t.pair}  "
                    f"<b>{sign}{t.pnl:.2f}$ ({sign}{t.pnl_pct:.1f}%)</b>  "
                    f"<i>{t.logged_at.strftime('%m-%d %H:%M')}</i>"
                )
            self._reply(chat_id, "\n".join(lines))
        except Exception as exc:
            self._reply(chat_id, f"Error: {exc}")

    def _cmd_stop(self, chat_id: int) -> None:
        import api.bot_manager as bm
        if not bm.is_running():
            self._reply(chat_id, "Bot is not running.")
            return
        result = bm.stop()
        if result["ok"]:
            self._reply(chat_id, "⏹ Bot stopped.")
        else:
            self._reply(chat_id, f"Could not stop: {result['detail']}")

    def _cmd_start(self, chat_id: int, strategy: Optional[str]) -> None:
        import api.bot_manager as bm
        from api.main import load_bot_config, get_strategy_registry
        if bm.is_running():
            self._reply(chat_id, "Bot is already running. Send /stop first.")
            return
        cfg      = load_bot_config()
        registry = get_strategy_registry()
        strat    = strategy or cfg.get("active_strategy", "stoch_rsi")
        if strat not in registry:
            self._reply(chat_id,
                f"Unknown strategy: {strat}\n"
                f"Available: {', '.join(list(registry)[:10])}…"
            )
            return
        pairs = cfg.get("pairs", ["BTC/USDT"])
        result = bm.start("paper", strat, pairs, cfg)
        if result["ok"]:
            self._reply(chat_id,
                f"▶️ Started paper bot\nStrategy: <code>{strat}</code>\n"
                f"Pairs: {', '.join(pairs)}"
            )
        else:
            self._reply(chat_id, f"Could not start: {result['detail']}")


# ── Util ──────────────────────────────────────────────────────────────────────

def _parse_int(text: str, default: int) -> int:
    parts = text.split()
    if len(parts) > 1:
        try:
            return max(1, min(int(parts[1]), 20))
        except ValueError:
            pass
    return default
