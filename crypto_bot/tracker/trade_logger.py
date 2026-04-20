"""
Trade Logger — persiste trades a data/trades.json.
Thread-safe, append-only, con rotación básica.
"""
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class TradeLogger:
    def __init__(self, path: str = "data/trades.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._trades: list = self._load()

    def _load(self) -> list:
        if self.path.exists():
            try:
                with open(self.path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"No se pudo leer {self.path}, empezando limpio")
        return []

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._trades, f, indent=2, default=str)

    def log(self, trade: dict):
        """Agrega un trade al log."""
        trade = dict(trade)
        if "logged_at" not in trade:
            trade["logged_at"] = datetime.now(tz=timezone.utc).isoformat()
        with self._lock:
            self._trades.append(trade)
            self._save()

    def log_buy(self, pair: str, price: float, qty: float, fee: float,
                strategy: str, reason: str, mode: str = "paper", **extra):
        self.log({
            "type": "buy", "pair": pair, "price": price,
            "qty": qty, "fee": fee, "strategy": strategy,
            "reason": reason, "mode": mode,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            **extra
        })

    def log_sell(self, pair: str, price: float, qty: float, fee: float,
                 pnl: float, pnl_pct: float, strategy: str, reason: str,
                 mode: str = "paper", **extra):
        self.log({
            "type": "sell", "pair": pair, "price": price,
            "qty": qty, "fee": fee, "pnl": pnl, "pnl_pct": pnl_pct,
            "strategy": strategy, "reason": reason, "mode": mode,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "status": "closed",
            **extra
        })

    def get_trades(self, pair: str = None, strategy: str = None,
                   mode: str = None) -> list:
        trades = self._trades
        if pair:
            trades = [t for t in trades if t.get("pair") == pair]
        if strategy:
            trades = [t for t in trades if t.get("strategy") == strategy]
        if mode:
            trades = [t for t in trades if t.get("mode") == mode]
        return trades

    def get_stats(self) -> dict:
        sells = [t for t in self._trades if t.get("type") == "sell" and "pnl" in t]
        if not sells:
            return {"total_trades": 0, "win_rate": 0, "total_pnl": 0}
        winners = [t for t in sells if t["pnl"] > 0]
        return {
            "total_trades": len(sells),
            "win_rate": len(winners) / len(sells) * 100,
            "total_pnl": sum(t["pnl"] for t in sells),
            "avg_pnl": sum(t["pnl"] for t in sells) / len(sells),
        }
