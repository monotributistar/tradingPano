"""
engine/oanda_paper.py — OANDA Paper Engine
============================================

Combines the virtual balance / trade-simulation logic from PaperEngine with
real price feeds from the OANDA v20 REST API.

Why this exists
---------------
``PaperEngine`` fetches prices via CCXT (Bybit / KuCoin).  When trading forex
or CFD pairs (EUR/USD, XAU/USD) those instruments aren't available on crypto
exchanges.  ``OandaPaperEngine`` swaps only the price-feed layer while keeping
the virtual balance, slippage, and fee simulation intact.

Credentials
-----------
Requires ``OANDA_API_KEY`` and ``OANDA_ACCOUNT_ID`` env vars (same as
``OandaEngine``).  The paper engine never submits real orders — it only
reads prices from the OANDA pricing endpoint.
"""

import logging
import os

import pandas as pd

from engine.paper import PaperEngine
from engine.oanda import OandaEngine, _TF_MAP, _MAX_CANDLES

import oandapyV20
import oandapyV20.endpoints.pricing as v20_pricing
import oandapyV20.endpoints.instruments as v20_instruments

logger = logging.getLogger(__name__)


class OandaPaperEngine(PaperEngine):
    """
    Paper trading with real OANDA prices and a virtual balance.

    ``market_buy``, ``market_sell``, ``short_open``, ``short_cover`` are
    fully simulated — no real orders are ever placed.

    ``get_price`` and ``fetch_ohlcv`` hit the OANDA practice REST API.
    """

    def __init__(self, config: dict) -> None:
        # PaperEngine.__init__ uses config["exchange"] to load a CCXT
        # exchange for price feeds.  OANDA is not a CCXT exchange, so
        # we pass a modified config with a known-good fallback exchange.
        # The CCXT exchange is never used in OandaPaperEngine because
        # get_price() and fetch_ohlcv() are overridden below.
        _init_cfg = {**config, "exchange": "bybit"}
        super().__init__(_init_cfg)

        oanda_cfg   = config.get("oanda", {})
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

        self._oanda_account = account_id
        self._oanda_client  = oandapyV20.API(
            access_token=api_key,
            environment=environment,
        )

        logger.info(
            "[OandaPaperEngine] Ready — OANDA prices, virtual balance=%.2f",
            self.balance.get("USDT", 0),
        )

    # ── Price feed override ─────────────────────────────────────────────────────

    def get_price(self, pair: str) -> float:
        """Fetch real OANDA mid price instead of CCXT."""
        instrument = OandaEngine._to_instrument(pair)
        r = v20_pricing.PricingInfo(
            accountID=self._oanda_account,
            params={"instruments": instrument},
        )
        resp = self._oanda_client.request(r)
        data = resp["prices"][0]
        bid  = float(data["bids"][0]["price"])
        ask  = float(data["asks"][0]["price"])
        return (bid + ask) / 2.0

    def fetch_ohlcv(self, pair: str, timeframe: str,
                    limit: int = 100) -> pd.DataFrame:
        """Fetch OANDA candles for strategy warmup (mid-price, complete only)."""
        instrument  = OandaEngine._to_instrument(pair)
        granularity = _TF_MAP.get(timeframe, "H1")

        r = v20_instruments.InstrumentsCandles(
            instrument,
            params={
                "count":       min(limit, _MAX_CANDLES),
                "granularity": granularity,
                "price":       "M",
            },
        )
        resp = self._oanda_client.request(r)

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
