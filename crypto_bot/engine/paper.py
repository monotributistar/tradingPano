"""
Paper Trading Engine.
- Precios reales via ccxt (public endpoints, no auth needed)
- Balance y trades simulados (long + short/futuros)
- Fees y slippage configurables
"""
import logging
import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

from engine.base import BaseEngine

logger = logging.getLogger(__name__)


class PaperEngine(BaseEngine):
    def __init__(self, config: dict):
        self.config = config
        paper_cfg = config.get("paper", {})
        self.fee_pct = paper_cfg.get("fee_pct", 0.1) / 100
        self.slippage_pct = 0.0005  # 0.05%

        exchange_id = config.get("exchange", "bybit")
        ex_cls = getattr(ccxt, exchange_id)
        self.exchange = ex_cls({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        # Virtual balance
        initial = paper_cfg.get("initial_balance", 20.0)
        self.balance = {"USDT": initial}
        # Short positions: {pair: {"qty", "entry_price", "collateral"}}
        self._shorts: dict = {}
        self._orders = []

    def get_price(self, pair: str) -> float:
        ticker = self.exchange.fetch_ticker(pair)
        return float(ticker["last"])

    def get_balance(self) -> dict:
        return dict(self.balance)

    # ── LONG ──────────────────────────────────────────────────────────────────

    def market_buy(self, pair: str, usdt_amount: float) -> dict:
        price = self.get_price(pair)
        fill_price = price * (1 + self.slippage_pct)
        fee = usdt_amount * self.fee_pct
        cost = usdt_amount + fee

        if self.balance.get("USDT", 0) < cost:
            logger.warning(f"Balance insuficiente: {self.balance.get('USDT', 0):.4f} < {cost:.4f}")
            return {"status": "rejected", "reason": "insufficient_balance"}

        qty = usdt_amount / fill_price
        base = pair.split("/")[0]
        self.balance["USDT"] = self.balance.get("USDT", 0) - cost
        self.balance[base] = self.balance.get(base, 0) + qty

        order = {
            "id": f"paper_{int(time.time()*1000)}", "pair": pair, "side": "buy",
            "price": fill_price, "qty": qty, "cost": cost, "fee": fee,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(), "status": "filled",
        }
        self._orders.append(order)
        logger.info(f"[PAPER BUY] {qty:.6f} {base} @ {fill_price:.2f} | fee={fee:.4f}")
        return order

    def market_sell(self, pair: str, qty: float) -> dict:
        base = pair.split("/")[0]
        if self.balance.get(base, 0) < qty * 0.9999:
            logger.warning(f"Balance insuficiente: {base} {self.balance.get(base, 0):.6f}")
            return {"status": "rejected", "reason": "insufficient_balance"}

        price = self.get_price(pair)
        fill_price = price * (1 - self.slippage_pct)
        gross = qty * fill_price
        fee = gross * self.fee_pct
        net = gross - fee

        self.balance[base] = self.balance.get(base, 0) - qty
        self.balance["USDT"] = self.balance.get("USDT", 0) + net

        order = {
            "id": f"paper_{int(time.time()*1000)}", "pair": pair, "side": "sell",
            "price": fill_price, "qty": qty, "gross": gross, "fee": fee, "net": net,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(), "status": "filled",
        }
        self._orders.append(order)
        logger.info(f"[PAPER SELL] {qty:.6f} {base} @ {fill_price:.2f} | net={net:.4f}")
        return order

    # ── SHORT (futures simulation) ─────────────────────────────────────────────

    def short_open(self, pair: str, usdt_amount: float) -> dict:
        """Open a short: borrow asset, sell at current price, lock collateral."""
        price = self.get_price(pair)
        fill_price = price * (1 - self.slippage_pct)
        fee = usdt_amount * self.fee_pct
        collateral = usdt_amount

        if self.balance.get("USDT", 0) < collateral + fee:
            logger.warning(f"Margen insuficiente para short: {collateral + fee:.4f}")
            return {"status": "rejected", "reason": "insufficient_margin"}

        qty = usdt_amount / fill_price
        self.balance["USDT"] -= fee  # fee upfront; collateral stays in balance but reserved

        self._shorts[pair] = {"qty": qty, "entry_price": fill_price, "collateral": collateral}

        order = {
            "id": f"paper_{int(time.time()*1000)}", "pair": pair, "side": "short",
            "price": fill_price, "qty": qty, "fee": fee, "collateral": collateral,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(), "status": "filled",
        }
        self._orders.append(order)
        logger.info(f"[PAPER SHORT] {qty:.6f} @ {fill_price:.2f} | collateral={collateral:.4f}")
        return order

    def short_cover(self, pair: str) -> dict:
        """Close a short: buy back at current price, return collateral ± PnL."""
        if pair not in self._shorts:
            return {"status": "rejected", "reason": "no_short_position"}

        pos = self._shorts[pair]
        price = self.get_price(pair)
        fill_price = price * (1 + self.slippage_pct)
        qty = pos["qty"]
        fee = qty * fill_price * self.fee_pct

        pnl = (pos["entry_price"] - fill_price) * qty - fee
        self.balance["USDT"] += pos["collateral"] + pnl
        del self._shorts[pair]

        order = {
            "id": f"paper_{int(time.time()*1000)}", "pair": pair, "side": "cover",
            "price": fill_price, "qty": qty, "fee": fee, "pnl": pnl,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(), "status": "filled",
        }
        self._orders.append(order)
        logger.info(f"[PAPER COVER] {qty:.6f} @ {fill_price:.2f} | pnl={pnl:.4f}")
        return order

    def get_short_position(self, pair: str) -> dict:
        return self._shorts.get(pair, {})

    # ── DATA ──────────────────────────────────────────────────────────────────

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        raw = self.exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df.astype(float)

    def get_orders(self) -> list:
        return list(self._orders)
