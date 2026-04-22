"""
engine/oanda.py — OANDA v20 REST Engine
=========================================

Implements BaseEngine for forex and CFD trading via the OANDA v20 REST API.
Drop-in replacement for LiveEngine: all strategies run unchanged.

Authentication
--------------
Set credentials via env vars (preferred) or the ``oanda:`` config block:

    OANDA_API_KEY       personal access token  (required)
    OANDA_ACCOUNT_ID    e.g. 001-001-1234567-001  (required)
    OANDA_ENVIRONMENT   "practice" | "live"  (default: "practice")

Pair convention
---------------
The engine converts between the project's slash notation (``EUR/USD``) and
OANDA's underscore notation (``EUR_USD``) automatically.  Strategies and
the rest of the engine layer always use the slash format.

Unit sizing
-----------
OANDA orders are unit-based, not USDT-based.  ``market_buy(pair, usdt_amount)``
converts the USDT amount to integer units:

    units = int(usdt_amount × leverage / current_price)

Short selling
-------------
Shorts are placed as negative-unit MARKET orders.  ``short_open`` sends
negative units; ``short_cover`` sends positive units with ``REDUCE_ONLY``.

Timeframe mapping
-----------------
Standard timeframes are mapped to OANDA granularities:
    1m→M1, 5m→M5, 15m→M15, 30m→M30,
    1h→H1, 2h→H2, 4h→H4, 6h→H6, 12h→H12,
    1d→D, 1w→W
"""

import logging
import os
from typing import Optional

import pandas as pd

import oandapyV20
import oandapyV20.endpoints.orders as v20_orders
import oandapyV20.endpoints.pricing as v20_pricing
import oandapyV20.endpoints.accounts as v20_accounts
import oandapyV20.endpoints.instruments as v20_instruments
import oandapyV20.endpoints.positions as v20_positions
from oandapyV20.exceptions import V20Error

from engine.base import BaseEngine

logger = logging.getLogger(__name__)

# ── Timeframe → OANDA granularity ─────────────────────────────────────────────
_TF_MAP: dict[str, str] = {
    "1m":  "M1",
    "5m":  "M5",
    "15m": "M15",
    "30m": "M30",
    "1h":  "H1",
    "2h":  "H2",
    "4h":  "H4",
    "6h":  "H6",
    "12h": "H12",
    "1d":  "D",
    "1w":  "W",
}

_MAX_CANDLES = 5000   # OANDA hard limit per request


class OandaEngine(BaseEngine):
    """
    OANDA v20 REST adapter for the trading engine.

    Suitable for: forex pairs, commodity CFDs (XAU/USD), index CFDs (US30/USD).
    Not suitable for: crypto spot (use LiveEngine + Bybit instead).
    """

    def __init__(self, config: dict) -> None:
        self.config   = config
        oanda_cfg     = config.get("oanda", {})
        risk_cfg      = config.get("risk", {})

        api_key     = (os.environ.get("OANDA_API_KEY")
                       or oanda_cfg.get("api_key", ""))
        account_id  = (os.environ.get("OANDA_ACCOUNT_ID")
                       or oanda_cfg.get("account_id", ""))
        environment = (os.environ.get("OANDA_ENVIRONMENT")
                       or oanda_cfg.get("environment", "practice"))

        if not api_key or not account_id:
            raise ValueError(
                "OANDA credentials missing. "
                "Set OANDA_API_KEY and OANDA_ACCOUNT_ID as environment variables."
            )

        self.account_id  = account_id
        self.leverage    = float(risk_cfg.get("leverage", 20.0))

        self.client = oandapyV20.API(
            access_token=api_key,
            environment=environment,
        )

        # Overnight financing accumulator: instrument → float USD
        self._swap_accrual: dict[str, float] = {}

        logger.info(
            "[OandaEngine] Ready — account=%s env=%s leverage=%.1fx",
            account_id, environment, self.leverage,
        )

    # ── Static helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_instrument(pair: str) -> str:
        """'EUR/USD' → 'EUR_USD'"""
        return pair.replace("/", "_").upper()

    @staticmethod
    def _to_pair(instrument: str) -> str:
        """'EUR_USD' → 'EUR/USD'"""
        return instrument.replace("_", "/", 1)

    def _usdt_to_units(self, instrument: str, usdt_amount: float) -> int:
        """Convert a USDT trade amount to OANDA integer units."""
        price = self.get_price(self._to_pair(instrument))
        raw = (usdt_amount * self.leverage) / price
        return max(1, int(raw))

    @staticmethod
    def _margin_level(summary: dict) -> float:
        margin_used = float(summary.get("marginUsed", 0))
        nav         = float(summary.get("NAV", 1))
        if margin_used == 0:
            return 9999.0
        return (nav / margin_used) * 100.0

    # ── BaseEngine interface ────────────────────────────────────────────────────

    def get_price(self, pair: str) -> float:
        """Return the mid price (average of best bid and ask)."""
        instrument = self._to_instrument(pair)
        r = v20_pricing.PricingInfo(
            accountID=self.account_id,
            params={"instruments": instrument},
        )
        resp  = self.client.request(r)
        data  = resp["prices"][0]
        bid   = float(data["bids"][0]["price"])
        ask   = float(data["asks"][0]["price"])
        return (bid + ask) / 2.0

    def get_balance(self) -> dict:
        """Return account balance, NAV, unrealized P&L, and margin info."""
        r    = v20_accounts.AccountSummary(self.account_id)
        resp = self.client.request(r)
        s    = resp["account"]
        return {
            "USDT":          float(s["balance"]),
            "nav":           float(s["NAV"]),
            "unrealizedPL":  float(s["unrealizedPL"]),
            "margin_used":   float(s["marginUsed"]),
            "margin_avail":  float(s["marginAvailable"]),
            "margin_level":  self._margin_level(s),
        }

    def market_buy(self, pair: str, usdt_amount: float) -> dict:
        """Open or add to a long position (positive units)."""
        instrument = self._to_instrument(pair)
        units      = self._usdt_to_units(instrument, usdt_amount)
        data = {
            "order": {
                "type":         "MARKET",
                "instrument":   instrument,
                "units":        str(units),
                "timeInForce":  "FOK",
                "positionFill": "DEFAULT",
            }
        }
        return self._place_order(data, "BUY", pair, units)

    def market_sell(self, pair: str, qty: float) -> dict:
        """Close an existing long position (negative units, REDUCE_ONLY)."""
        instrument = self._to_instrument(pair)
        data = {
            "order": {
                "type":         "MARKET",
                "instrument":   instrument,
                "units":        str(-abs(int(qty))),
                "timeInForce":  "FOK",
                "positionFill": "REDUCE_ONLY",
            }
        }
        return self._place_order(data, "SELL", pair, qty)

    def short_open(self, pair: str, usdt_amount: float) -> dict:
        """Open a short position (negative units)."""
        instrument = self._to_instrument(pair)
        units      = self._usdt_to_units(instrument, usdt_amount)
        data = {
            "order": {
                "type":         "MARKET",
                "instrument":   instrument,
                "units":        str(-units),
                "timeInForce":  "FOK",
                "positionFill": "DEFAULT",
            }
        }
        return self._place_order(data, "SHORT", pair, units)

    def short_cover(self, pair: str, qty: float) -> dict:
        """Close an existing short position (positive units, REDUCE_ONLY)."""
        instrument = self._to_instrument(pair)
        data = {
            "order": {
                "type":         "MARKET",
                "instrument":   instrument,
                "units":        str(abs(int(qty))),
                "timeInForce":  "FOK",
                "positionFill": "REDUCE_ONLY",
            }
        }
        return self._place_order(data, "COVER", pair, qty)

    def fetch_ohlcv(self, pair: str, timeframe: str,
                    limit: int = 100) -> pd.DataFrame:
        """
        Fetch OHLCV candles from OANDA.

        Returns a DataFrame with columns: open, high, low, close, volume.
        Index is a DatetimeIndex (UTC).
        Incomplete (in-progress) candles are excluded.
        """
        instrument  = self._to_instrument(pair)
        granularity = _TF_MAP.get(timeframe, "H1")

        r = v20_instruments.InstrumentsCandles(
            instrument,
            params={
                "count":       min(limit, _MAX_CANDLES),
                "granularity": granularity,
                "price":       "M",   # midpoint candles
            },
        )
        resp = self.client.request(r)

        rows = []
        for c in resp["candles"]:
            if not c.get("complete", False):
                continue
            m = c["mid"]
            rows.append({
                "timestamp": pd.Timestamp(c["time"]),
                "open":      float(m["o"]),
                "high":      float(m["h"]),
                "low":       float(m["l"]),
                "close":     float(m["c"]),
                "volume":    int(c.get("volume", 0)),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
        return df

    # ── CFD-specific extensions ─────────────────────────────────────────────────

    def get_margin_info(self) -> dict:
        """Return current margin level, used margin, and available margin."""
        bal = self.get_balance()
        return {
            "margin_level":     bal.get("margin_level", 0.0),
            "margin_used":      bal.get("margin_used",  0.0),
            "margin_available": bal.get("margin_avail", 0.0),
            "nav":              bal.get("nav", 0.0),
        }

    def get_financing_cost(self) -> float:
        """Return total accumulated overnight financing cost (USD)."""
        return sum(self._swap_accrual.values())

    def accrue_swap(self, instrument: str) -> None:
        """
        Fetch the current financing charge for ``instrument`` from the OANDA
        positions endpoint and add it to the local accumulator.

        Called by the bot runner once per candle close (or on a schedule).
        Safe to call when no position is open — OANDA returns financing=0.

        Parameters
        ----------
        instrument : str
            OANDA instrument notation, e.g. ``"EUR_USD"``.
        """
        try:
            r    = v20_positions.PositionDetails(self.account_id, instrument)
            resp = self.client.request(r)
            pos  = resp.get("position", {})
            financing = float(pos.get("financing", 0.0))
            self._swap_accrual[instrument] = (
                self._swap_accrual.get(instrument, 0.0) + financing
            )
            if financing != 0.0:
                logger.info(
                    "[OandaEngine] Swap accrual %s: %.4f (total %.4f)",
                    instrument, financing,
                    self._swap_accrual[instrument],
                )
        except Exception as exc:
            logger.warning(
                "[OandaEngine] accrue_swap(%s) failed: %s — skipping",
                instrument, exc,
            )

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _place_order(self, data: dict, side: str,
                     pair: str, units) -> dict:
        r = v20_orders.OrderCreate(self.account_id, data=data)
        try:
            resp = self.client.request(r)
            fill  = resp.get("orderFillTransaction", {})
            fill_price  = float(fill.get("price", 0))
            financing   = float(fill.get("financing", 0))
            order_id    = fill.get("id", "")
            qty         = abs(units)

            # Accumulate swap/financing cost per instrument
            instrument = self._to_instrument(pair)
            self._swap_accrual[instrument] = (
                self._swap_accrual.get(instrument, 0.0) + financing
            )

            logger.info(
                "[OandaEngine] %s %s units=%s fill=%.5f id=%s financing=%.4f",
                side, pair, units, fill_price, order_id, financing,
            )
            return {
                "status":    "filled",
                "price":     fill_price,
                "qty":       qty,
                "fee":       financing,
                "order_id":  order_id,
            }
        except Exception as exc:
            logger.error("[OandaEngine] Order failed %s %s: %s", side, pair, exc)
            return {"status": "error", "reason": str(exc)}
