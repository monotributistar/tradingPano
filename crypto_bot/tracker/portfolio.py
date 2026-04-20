"""
Portfolio Analytics
- Valor actual del portfolio
- PnL realizado e irealizado
- Historial de equity
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class Portfolio:
    def __init__(self, initial_balance: float = 20.0):
        self.initial_balance = initial_balance
        self._snapshots: list = []
        self._positions: dict = {}  # pair -> {qty, avg_cost, entry_time}

    def update_position(self, pair: str, qty: float, avg_cost: float):
        if qty <= 0:
            self._positions.pop(pair, None)
        else:
            self._positions[pair] = {
                "qty": qty, "avg_cost": avg_cost,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    def snapshot(self, usdt_balance: float, prices: dict[str, float]):
        """Registra snapshot del portfolio."""
        pos_value = sum(
            self._positions[p]["qty"] * prices.get(p, 0)
            for p in self._positions
        )
        total = usdt_balance + pos_value
        pnl = total - self.initial_balance
        self._snapshots.append({
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "usdt": usdt_balance,
            "positions_value": pos_value,
            "total": total,
            "pnl": pnl,
            "pnl_pct": pnl / self.initial_balance * 100,
        })
        return self._snapshots[-1]

    def get_equity_curve(self) -> list:
        return [s["total"] for s in self._snapshots]

    def summary(self, usdt_balance: float, prices: dict[str, float]) -> dict:
        pos_value = sum(
            self._positions[p]["qty"] * prices.get(p, 0)
            for p in self._positions
        )
        total = usdt_balance + pos_value
        pnl = total - self.initial_balance

        unrealized = {}
        for pair, pos in self._positions.items():
            price = prices.get(pair, 0)
            cost = pos["qty"] * pos["avg_cost"]
            value = pos["qty"] * price
            unrealized[pair] = {
                "qty": pos["qty"],
                "avg_cost": pos["avg_cost"],
                "current_price": price,
                "value": value,
                "unrealized_pnl": value - cost,
                "unrealized_pnl_pct": (value - cost) / cost * 100 if cost > 0 else 0,
            }

        return {
            "initial_capital": self.initial_balance,
            "usdt_balance": usdt_balance,
            "positions_value": pos_value,
            "total_value": total,
            "pnl": pnl,
            "pnl_pct": pnl / self.initial_balance * 100,
            "positions": unrealized,
        }
