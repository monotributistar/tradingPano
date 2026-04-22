"""
Live Trading Engine via ccxt.
==============================

Supports Bybit and Binance in both spot and perpetual futures (swap) modes.

Spot mode (default, ``use_futures: false``)
-------------------------------------------
- market_buy / market_sell for long-only strategies
- short_open / short_cover are no-ops with a warning

Perpetuals mode (``use_futures: true``)
----------------------------------------
- Uses ccxt ``defaultType: "swap"`` on Bybit
- short_open  → create market sell order (open short position)
- short_cover → create market buy order  (close short position)
- Leverage set via exchange.set_leverage()

All orders use retry + exponential backoff on rate-limit / network errors.
"""

import logging
import os
import time
from typing import Optional

import ccxt
import pandas as pd

from engine.base import BaseEngine

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0  # seconds


class LiveEngine(BaseEngine):
    def __init__(self, config: dict):
        self.config = config
        exchange_id = config.get("exchange", "bybit")
        testnet = config.get("testnet", True)
        self.use_futures = config.get("risk", {}).get("use_futures", False)
        self.leverage = float(config.get("risk", {}).get("leverage", 1.0))

        api_key = config.get("api_key") or os.environ.get("EXCHANGE_API_KEY", "")
        secret = config.get("secret") or os.environ.get("EXCHANGE_SECRET", "")

        if not api_key or not secret:
            raise ValueError(
                "API key/secret required for live trading. "
                "Set EXCHANGE_API_KEY and EXCHANGE_API_SECRET as env vars."
            )

        # Choose market type based on config
        market_type = "swap" if self.use_futures else "spot"

        ex_cls = getattr(ccxt, exchange_id)
        self.exchange = ex_cls({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": market_type,
                "defaultSubType": "linear",  # USDT-margined (Bybit / Binance)
            },
        })

        if testnet:
            self._setup_testnet(exchange_id)

        if self.use_futures:
            logger.info(
                f"[LIVE] Perpetuals mode — {exchange_id} {market_type} "
                f"(testnet={testnet}, leverage={self.leverage}x)"
            )
        else:
            logger.info(f"[LIVE] Spot mode — {exchange_id} (testnet={testnet})")

    # ── Testnet setup ──────────────────────────────────────────────────────────

    def _setup_testnet(self, exchange_id: str) -> None:
        if exchange_id == "bybit":
            self.exchange.set_sandbox_mode(True)
            logger.info("Bybit testnet activated")
        elif exchange_id == "binance":
            if self.use_futures:
                self.exchange.urls["api"] = {
                    "public":  "https://testnet.binancefuture.com",
                    "private": "https://testnet.binancefuture.com",
                }
            else:
                self.exchange.urls["api"] = "https://testnet.binance.vision"
            logger.info(f"Binance testnet activated ({'futures' if self.use_futures else 'spot'})")
        else:
            logger.warning(f"Testnet not configured for {exchange_id}")

    # ── Retry wrapper ──────────────────────────────────────────────────────────

    def _retry(self, fn, *args, **kwargs):
        """Execute fn with retry + exponential backoff on transient errors."""
        for attempt in range(MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except ccxt.RateLimitExceeded:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Rate limit, retrying in {delay:.1f}s...")
                time.sleep(delay)
            except ccxt.NetworkError as e:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Network error: {e}, retrying in {delay:.1f}s...")
                time.sleep(delay)
            except ccxt.ExchangeError as e:
                logger.error(f"Exchange error (not retryable): {e}")
                raise
        raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")

    # ── Leverage helper ────────────────────────────────────────────────────────

    def _set_leverage(self, pair: str) -> None:
        """Set leverage for a futures pair (best-effort — logs on failure)."""
        if not self.use_futures or self.leverage <= 1.0:
            return
        try:
            self.exchange.set_leverage(int(self.leverage), pair)
            logger.debug(f"[LIVE] Leverage set to {int(self.leverage)}x for {pair}")
        except Exception as exc:
            logger.warning(f"[LIVE] Could not set leverage for {pair}: {exc}")

    # ── Price & balance ────────────────────────────────────────────────────────

    def get_price(self, pair: str) -> float:
        ticker = self._retry(self.exchange.fetch_ticker, pair)
        return float(ticker["last"])

    def get_balance(self) -> dict:
        balance = self._retry(self.exchange.fetch_balance)
        return {k: v for k, v in balance["total"].items() if v > 0}

    def fetch_balance(self) -> dict:
        """Return full balance dict (alias used by bot_manager reconciliation)."""
        return self.get_balance()

    # ── Spot / long operations ─────────────────────────────────────────────────

    def market_buy(self, pair: str, usdt_amount: float) -> dict:
        """Open a long position (spot buy or futures long)."""
        self._set_leverage(pair)
        price = self.get_price(pair)
        qty = usdt_amount / price
        qty = self.exchange.amount_to_precision(pair, qty)
        logger.info(f"[LIVE BUY] {qty} {pair} ~{usdt_amount:.2f} USDT")
        order = self._retry(self.exchange.create_market_buy_order, pair, float(qty))
        logger.info(
            f"[LIVE BUY FILLED] {order.get('filled', qty)} @ "
            f"{order.get('average', price):.4f}"
        )
        return order

    def market_sell(self, pair: str, qty: float) -> dict:
        """Close a long position (spot sell or futures close-long)."""
        qty_str = self.exchange.amount_to_precision(pair, qty)
        logger.info(f"[LIVE SELL] {qty_str} {pair}")

        params = {}
        if self.use_futures:
            # On Bybit perpetuals, reduceOnly=True ensures we close the position
            params = {"reduceOnly": True}

        order = self._retry(
            self.exchange.create_market_sell_order, pair, float(qty_str), params=params
        )
        logger.info(
            f"[LIVE SELL FILLED] {order.get('filled', qty)} @ "
            f"{order.get('average', 0):.4f}"
        )
        return order

    # ── Short operations (perpetuals only) ────────────────────────────────────

    def short_open(self, pair: str, usdt_amount: float) -> dict:
        """
        Open a short position via perpetual futures.

        On Bybit:  Creates a SELL order on the linear swap market.
        On Binance: Creates a SELL order with positionSide=SHORT (hedge mode).

        Falls back to a warning log if running in spot mode.
        """
        if not self.use_futures:
            logger.warning(
                f"[LIVE SHORT_OPEN] Skipped — use_futures=false.  "
                f"Enable perpetuals in config to trade shorts."
            )
            return {}

        self._set_leverage(pair)
        price = self.get_price(pair)
        qty = usdt_amount / price
        qty = self.exchange.amount_to_precision(pair, qty)

        params = {}
        # Bybit unified: no extra params needed in one-way mode (the default)
        # Binance hedge mode needs positionSide=SHORT — detect by exchange id
        if "binance" in str(self.exchange.id).lower():
            params["positionSide"] = "SHORT"

        logger.info(f"[LIVE SHORT_OPEN] SELL {qty} {pair} ~{usdt_amount:.2f} USDT @ ~{price:.4f}")
        order = self._retry(
            self.exchange.create_market_sell_order, pair, float(qty), params=params
        )
        logger.info(
            f"[LIVE SHORT_OPEN FILLED] {order.get('filled', qty)} @ "
            f"{order.get('average', price):.4f}"
        )
        return order

    def short_cover(self, pair: str, qty: float) -> dict:
        """
        Close a short position via perpetual futures (buy to cover).

        Falls back to a warning log if running in spot mode.
        """
        if not self.use_futures:
            logger.warning(
                f"[LIVE SHORT_COVER] Skipped — use_futures=false."
            )
            return {}

        qty_str = self.exchange.amount_to_precision(pair, qty)

        params: dict = {"reduceOnly": True}
        if "binance" in str(self.exchange.id).lower():
            params["positionSide"] = "SHORT"

        logger.info(f"[LIVE SHORT_COVER] BUY {qty_str} {pair} (cover short)")
        order = self._retry(
            self.exchange.create_market_buy_order, pair, float(qty_str), params=params
        )
        logger.info(
            f"[LIVE SHORT_COVER FILLED] {order.get('filled', qty)} @ "
            f"{order.get('average', 0):.4f}"
        )
        return order

    # ── OHLCV ──────────────────────────────────────────────────────────────────

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        raw = self._retry(
            self.exchange.fetch_ohlcv, pair, timeframe=timeframe, limit=limit
        )
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df.astype(float)

    # ── Positions (futures) ────────────────────────────────────────────────────

    def fetch_positions(self, pair: Optional[str] = None) -> list:
        """
        Fetch open positions from the exchange (futures only).

        Returns a list of position dicts.  In spot mode returns an empty list.
        """
        if not self.use_futures:
            return []
        try:
            positions = self._retry(self.exchange.fetch_positions, [pair] if pair else None)
            return [p for p in positions if float(p.get("contracts", 0) or 0) != 0]
        except Exception as exc:
            logger.warning(f"fetch_positions failed: {exc}")
            return []
