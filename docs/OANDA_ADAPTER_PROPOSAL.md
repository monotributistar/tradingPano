# OANDA CFD Adapter — Implementation Proposal

**Status:** Draft  
**Author:** Trading Engine Team  
**Date:** 2026-04-21  
**Target:** `crypto_bot/engine/oanda.py`

---

## 1. Summary

Add a first-class OANDA v20 engine adapter so the existing strategy engine can trade
**forex and CFD instruments** (EUR/USD, indices, commodities) through OANDA's REST API,
using the same `BaseEngine` contract that already powers Bybit/Binance live trading and
the paper engine.

Every existing strategy (`pullback`, `keltner_breakout`, `dual_thrust`, `trend_following`,
`momentum_burst`, …) runs unchanged — only the exchange layer is swapped.

---

## 2. Architecture Overview

```
                         ┌──────────────────────────────────┐
  Strategy               │         engine/__init__.py        │
  on_candle() ──signal──►│    create_engine(config, mode)    │
                         │                                   │
                         │  exchange == "oanda" ─────────────┼──► OandaEngine
                         │  exchange == "bybit" ─────────────┼──► LiveEngine (ccxt)
                         │  mode     == "paper" ─────────────┼──► OandaPaperEngine
                         └──────────────────────────────────┘

  OandaEngine
  ┌─────────────────────────────────────────────────────┐
  │  REST client (oandapyV20)                           │
  │  ├── get_price()      → GET /v3/accounts/{id}/pricing
  │  ├── get_balance()    → GET /v3/accounts/{id}/summary
  │  ├── market_buy()     → POST /v3/accounts/{id}/orders  (units > 0)
  │  ├── market_sell()    → POST /v3/accounts/{id}/orders  (units < 0, close)
  │  ├── short_open()     → POST /v3/accounts/{id}/orders  (units < 0, new)
  │  ├── short_cover()    → POST /v3/accounts/{id}/orders  (units > 0, close)
  │  └── fetch_ohlcv()    → GET /v3/instruments/{inst}/candles
  │                                                     │
  │  SwapTracker — accrues daily financing per position │
  │  MarginMonitor — polls margin level every N seconds │
  └─────────────────────────────────────────────────────┘
```

### What does NOT change

| Layer | Change? |
|-------|---------|
| `BaseStrategy` + all 22 strategies | ✅ None |
| `RiskManager` | ✅ None (leverage, position sizing reused) |
| `main.py` signal handler | Minimal — engine factory call |
| `api/routers/bot.py` | ✅ None |
| `PaperEngine` | ✅ None (reused for paper/OANDA mode) |
| `TradeLogger` / DB | ✅ None |

---

## 3. Files Changed or Created

```
crypto_bot/
├── engine/
│   ├── base.py              ← minor: add short_open / short_cover defaults
│   ├── oanda.py             ← NEW: OandaEngine
│   ├── oanda_paper.py       ← NEW: OandaPaperEngine (OANDA prices + virtual balance)
│   └── __init__.py          ← update factory
├── config.yaml              ← new `oanda:` section
└── risk_manager.py          ← add swap_accrual tracking (optional Phase 2)

api/
└── main.py                  ← load OANDA env vars

.env.example                 ← add OANDA_* vars
docs/
└── OANDA_ADAPTER_PROPOSAL.md  ← this file
```

---

## 4. Contract: `BaseEngine` Extension

Add two optional methods with default no-op implementations so existing engines
(LiveEngine, PaperEngine) don't break, and OANDA can override them:

```python
# engine/base.py  — additions only

class BaseEngine(ABC):
    # ... existing abstract methods unchanged ...

    def short_open(self, pair: str, usdt_amount: float) -> dict:
        """Open a short position. Default: no-op (spot-only engines)."""
        logger.warning(f"short_open not supported by {type(self).__name__}")
        return {"status": "unsupported"}

    def short_cover(self, pair: str, qty: float) -> dict:
        """Close a short position. Default: no-op."""
        logger.warning(f"short_cover not supported by {type(self).__name__}")
        return {"status": "unsupported"}

    def get_margin_info(self) -> dict:
        """Return margin level, used margin, available margin. CFD-only."""
        return {}

    def get_financing_cost(self) -> float:
        """Return total accrued overnight financing cost (USDT). CFD-only."""
        return 0.0
```

---

## 5. `OandaEngine` — Full Design

### 5.1 Pair Normalization

OANDA uses underscores, not slashes or hyphens:

```
EUR/USD  →  EUR_USD
GBP/JPY  →  GBP_JPY
XAU/USD  →  XAU_USD   (gold CFD)
US30/USD →  US30_USD  (Dow Jones CFD)
```

```python
@staticmethod
def _pair_to_instrument(pair: str) -> str:
    return pair.replace("/", "_").upper()

@staticmethod
def _instrument_to_pair(instrument: str) -> str:
    return instrument.replace("_", "/", 1)
```

### 5.2 Unit Calculation

OANDA is units-based, not USDT-based. We convert:

```python
def _usdt_to_units(self, instrument: str, usdt_amount: float) -> int:
    """Convert a USDT trade amount to OANDA units using current mid price."""
    price = self.get_price(self._instrument_to_pair(instrument))
    raw_units = (usdt_amount * self.leverage) / price
    return int(raw_units)   # OANDA requires integer units
```

### 5.3 Full Class Sketch

```python
# crypto_bot/engine/oanda.py

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import oandapyV20
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments

from engine.base import BaseEngine

logger = logging.getLogger(__name__)

# OANDA granularity map  (our timeframe → OANDA granularity)
_TF_MAP = {
    "1m":  "M1",  "5m":  "M5",  "15m": "M15",
    "30m": "M30", "1h":  "H1",  "2h":  "H2",
    "4h":  "H4",  "6h":  "H6",  "12h": "H12",
    "1d":  "D",   "1w":  "W",
}


class OandaEngine(BaseEngine):
    """
    OANDA v20 REST adapter.

    Env vars (set in .env):
        OANDA_API_KEY       — personal access token
        OANDA_ACCOUNT_ID    — e.g. 001-001-1234567-001
        OANDA_ENVIRONMENT   — "practice" | "live"  (default: "practice")
    """

    def __init__(self, config: dict):
        self.config      = config
        oanda_cfg        = config.get("oanda", {})
        risk_cfg         = config.get("risk",  {})

        api_key     = os.environ.get("OANDA_API_KEY")    or oanda_cfg.get("api_key")
        account_id  = os.environ.get("OANDA_ACCOUNT_ID") or oanda_cfg.get("account_id")
        environment = os.environ.get("OANDA_ENVIRONMENT", oanda_cfg.get("environment", "practice"))

        if not api_key or not account_id:
            raise ValueError(
                "OANDA credentials missing. "
                "Set OANDA_API_KEY and OANDA_ACCOUNT_ID as env vars."
            )

        self.account_id  = account_id
        self.leverage    = float(risk_cfg.get("leverage", 20.0))
        self.fee_pct     = float(oanda_cfg.get("fee_pct", 0.0))   # OANDA charges spread, no fee
        self.slippage_pct = float(oanda_cfg.get("slippage_pct", 0.0005))

        self.client = oandapyV20.API(
            access_token=api_key,
            environment=environment,
        )

        # Swap (overnight financing) accumulator: {instrument: float_usdt}
        self._swap_accrual: dict[str, float] = {}
        self._last_swap_check: float = 0.0

        logger.info(
            f"[OANDA] Engine ready — account={account_id} "
            f"env={environment} leverage={self.leverage}x"
        )

    # ── Pair helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _to_instrument(pair: str) -> str:
        return pair.replace("/", "_").upper()

    @staticmethod
    def _to_pair(instrument: str) -> str:
        return instrument.replace("_", "/", 1)

    def _usdt_to_units(self, instrument: str, usdt_amount: float) -> int:
        price = self.get_price(self._to_pair(instrument))
        return max(1, int((usdt_amount * self.leverage) / price))

    # ── BaseEngine interface ─────────────────────────────────────────────────────

    def get_price(self, pair: str) -> float:
        instrument = self._to_instrument(pair)
        r = pricing.PricingInfo(
            accountID=self.account_id,
            params={"instruments": instrument},
        )
        resp = self.client.request(r)
        price_data = resp["prices"][0]
        bid = float(price_data["bids"][0]["price"])
        ask = float(price_data["asks"][0]["price"])
        return (bid + ask) / 2  # mid price

    def get_balance(self) -> dict:
        r = accounts.AccountSummary(self.account_id)
        resp = self.client.request(r)
        summary = resp["account"]
        return {
            "USDT":          float(summary["balance"]),
            "nav":           float(summary["NAV"]),
            "unrealizedPL":  float(summary["unrealizedPL"]),
            "margin_used":   float(summary["marginUsed"]),
            "margin_avail":  float(summary["marginAvailable"]),
            "margin_level":  self._margin_level(summary),
        }

    def market_buy(self, pair: str, usdt_amount: float) -> dict:
        """Open or add to a long position."""
        instrument = self._to_instrument(pair)
        units = self._usdt_to_units(instrument, usdt_amount)

        data = {
            "order": {
                "type":        "MARKET",
                "instrument":  instrument,
                "units":       str(units),      # positive = long
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        return self._place_order(data, "BUY", pair, units)

    def market_sell(self, pair: str, qty: float) -> dict:
        """Close an existing long position by qty units."""
        instrument = self._to_instrument(pair)
        # Close long: sell the units (negative to close)
        data = {
            "order": {
                "type":        "MARKET",
                "instrument":  instrument,
                "units":       str(-abs(int(qty))),
                "timeInForce": "FOK",
                "positionFill": "REDUCE_ONLY",
            }
        }
        return self._place_order(data, "SELL", pair, qty)

    def short_open(self, pair: str, usdt_amount: float) -> dict:
        """Open a short position (negative units)."""
        instrument = self._to_instrument(pair)
        units = self._usdt_to_units(instrument, usdt_amount)

        data = {
            "order": {
                "type":        "MARKET",
                "instrument":  instrument,
                "units":       str(-units),     # negative = short
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        return self._place_order(data, "SHORT", pair, units)

    def short_cover(self, pair: str, qty: float) -> dict:
        """Close an existing short position."""
        instrument = self._to_instrument(pair)
        data = {
            "order": {
                "type":        "MARKET",
                "instrument":  instrument,
                "units":       str(abs(int(qty))),  # positive to close short
                "timeInForce": "FOK",
                "positionFill": "REDUCE_ONLY",
            }
        }
        return self._place_order(data, "COVER", pair, qty)

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        instrument  = self._to_instrument(pair)
        granularity = _TF_MAP.get(timeframe, "H1")

        r = instruments.InstrumentsCandles(
            instrument,
            params={
                "count":       min(limit, 5000),
                "granularity": granularity,
                "price":       "M",   # midpoint candles
            },
        )
        resp = self.client.request(r)

        rows = []
        for c in resp["candles"]:
            if not c["complete"]:
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

    # ── CFD-specific methods ─────────────────────────────────────────────────────

    def get_margin_info(self) -> dict:
        bal = self.get_balance()
        return {
            "margin_level":    bal.get("margin_level", 0.0),
            "margin_used":     bal.get("margin_used",  0.0),
            "margin_available": bal.get("margin_avail", 0.0),
            "nav":             bal.get("nav",           0.0),
        }

    def get_financing_cost(self) -> float:
        return sum(self._swap_accrual.values())

    # ── Internals ────────────────────────────────────────────────────────────────

    def _place_order(self, data: dict, side: str, pair: str, units) -> dict:
        r = orders.OrderCreate(self.account_id, data=data)
        try:
            resp = self.client.request(r)
            fill = resp.get("orderFillTransaction", {})
            fill_price = float(fill.get("price", 0))
            logger.info(
                f"[OANDA] {side} {pair} units={units} "
                f"fill={fill_price:.5f} id={fill.get('id')}"
            )
            return {
                "status":     "filled",
                "price":      fill_price,
                "qty":        abs(units),
                "fee":        float(fill.get("financing", 0)),
                "order_id":   fill.get("id"),
            }
        except oandapyV20.exceptions.V20Error as e:
            logger.error(f"[OANDA] Order failed {side} {pair}: {e}")
            return {"status": "error", "reason": str(e)}

    @staticmethod
    def _margin_level(summary: dict) -> float:
        margin_used = float(summary.get("marginUsed", 0))
        nav         = float(summary.get("NAV", 1))
        if margin_used == 0:
            return 9999.0
        return (nav / margin_used) * 100
```

---

## 6. `OandaPaperEngine` — Virtual Trading with OANDA Prices

Reuses the existing `PaperEngine` balance/fee logic but replaces the CCXT price feed
with OANDA's pricing endpoint:

```python
# crypto_bot/engine/oanda_paper.py

from engine.paper import PaperEngine
from engine.oanda import OandaEngine
import oandapyV20
import os


class OandaPaperEngine(PaperEngine):
    """
    Paper engine with real OANDA prices.
    Balance/trade simulation is fully virtual — no real orders placed.
    """

    def __init__(self, config: dict):
        super().__init__(config)   # sets up virtual balance, fee, slippage
        # Override the CCXT exchange with an OANDA REST client for prices only
        oanda_cfg   = config.get("oanda", {})
        api_key     = os.environ.get("OANDA_API_KEY") or oanda_cfg.get("api_key", "")
        environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
        self._oanda_account = os.environ.get("OANDA_ACCOUNT_ID") or oanda_cfg.get("account_id")
        self._oanda_client  = oandapyV20.API(access_token=api_key, environment=environment)

    def get_price(self, pair: str) -> float:
        """Fetch real OANDA mid price instead of CCXT."""
        import oandapyV20.endpoints.pricing as pricing_ep
        instrument = OandaEngine._to_instrument(pair)
        r = pricing_ep.PricingInfo(
            accountID=self._oanda_account,
            params={"instruments": instrument},
        )
        resp  = self._oanda_client.request(r)
        data  = resp["prices"][0]
        bid   = float(data["bids"][0]["price"])
        ask   = float(data["asks"][0]["price"])
        return (bid + ask) / 2

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Fetch OANDA candles for strategy warmup."""
        _tmp = OandaEngine.__new__(OandaEngine)
        _tmp.client     = self._oanda_client
        _tmp.account_id = self._oanda_account
        return _tmp.fetch_ohlcv(pair, timeframe, limit)
```

---

## 7. `engine/__init__.py` — Engine Factory

```python
# crypto_bot/engine/__init__.py

def create_engine(config: dict, mode: str = "live"):
    """
    Factory function.

    mode    exchange     → engine
    ─────────────────────────────────────────────
    paper   any          → PaperEngine (ccxt prices)
    paper   oanda        → OandaPaperEngine
    live    bybit/binance → LiveEngine (ccxt)
    live    oanda        → OandaEngine
    """
    exchange = config.get("exchange", "bybit").lower()

    if mode == "paper":
        if exchange == "oanda":
            from engine.oanda_paper import OandaPaperEngine
            return OandaPaperEngine(config)
        from engine.paper import PaperEngine
        return PaperEngine(config)

    # live
    if exchange == "oanda":
        from engine.oanda import OandaEngine
        return OandaEngine(config)

    from engine.live import LiveEngine
    return LiveEngine(config)
```

> **Integration point in `main.py`:** Replace direct `PaperEngine(config)` / `LiveEngine(config)`
> instantiation with `create_engine(config, mode)`.

---

## 8. Config Changes

```yaml
# config.yaml — new section

exchange: oanda          # switch from "bybit" to "oanda"

oanda:
  environment: practice  # "practice" | "live"
  account_id: ""         # override via OANDA_ACCOUNT_ID env var
  api_key: ""            # override via OANDA_API_KEY env var
  fee_pct: 0.0           # spread is the cost, no explicit fee
  slippage_pct: 0.0005

pairs:
  - EUR/USD
  - GBP/USD
  - XAU/USD              # gold CFD
  - US30/USD             # Dow Jones CFD

timeframe: 1h

risk:
  leverage: 20.0         # ESMA retail cap: 30x FX, 20x indices
  max_concurrent_positions: 3
  daily_loss_stop_pct: 2.0
  use_futures: true      # enables short_open / short_cover signal handling
  position_sizing: fixed
  atr_stop_enabled: true
  atr_stop_mult: 1.5
  max_drawdown_pct: 4.0
```

---

## 9. Environment Variables

Add to `.env.example`:

```bash
# OANDA CFD Broker
OANDA_API_KEY=your-personal-access-token
OANDA_ACCOUNT_ID=001-001-1234567-001
OANDA_ENVIRONMENT=practice   # "practice" for demo, "live" for real money
```

---

## 10. Margin Monitor (Phase 2)

A lightweight background thread that polls the account every 30 seconds and
fires a `BotEvent` + Telegram alert if margin level drops below thresholds:

```python
# crypto_bot/margin_monitor.py

import threading, time, logging
logger = logging.getLogger(__name__)

WARN_LEVEL  = 200.0   # % — log warning
ALERT_LEVEL = 150.0   # % — Telegram alert
STOP_LEVEL  = 110.0   # % — stop bot (before broker stops at 100%)

class MarginMonitor:
    def __init__(self, engine, bot_manager, interval_s: int = 30):
        self._engine  = engine
        self._bot_mgr = bot_manager
        self._interval = interval_s
        self._thread   = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._running = True
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                info  = self._engine.get_margin_info()
                level = info.get("margin_level", 9999.0)

                if level <= STOP_LEVEL:
                    logger.critical(f"[MARGIN] STOP level hit: {level:.1f}% — halting bot")
                    self._bot_mgr.stop()
                elif level <= ALERT_LEVEL:
                    logger.error(f"[MARGIN] ALERT: margin level {level:.1f}%")
                    # TODO: push Telegram alert
                elif level <= WARN_LEVEL:
                    logger.warning(f"[MARGIN] LOW: margin level {level:.1f}%")
                else:
                    logger.debug(f"[MARGIN] OK: {level:.1f}%")

            except Exception as e:
                logger.error(f"[MARGIN] Monitor error: {e}")

            time.sleep(self._interval)
```

---

## 11. Swap Rate Tracker (Phase 2)

OANDA charges overnight financing on open positions. To track real P&L:

```python
# Applied in OandaEngine after each candle at market close (17:00 NY time):

def _accrue_swap(self, instrument: str, units: int, direction: str):
    """
    Approximate daily swap accrual.
    Real swap rates are fetched from OANDA's /v3/accounts/{id}/positions.
    """
    import oandapyV20.endpoints.positions as pos_ep
    r   = pos_ep.PositionDetails(self.account_id, instrument)
    pos = self.client.request(r)["position"]
    financing = float(pos.get("financing", 0.0))  # already accrued by OANDA
    self._swap_accrual[instrument] = self._swap_accrual.get(instrument, 0.0) + financing
    if financing != 0:
        logger.info(f"[SWAP] {instrument} financing accrued: {financing:.4f} USD")
```

---

## 12. `strategyIndicators.ts` — Frontend Update

The 3 new strategies also need indicator chips. Add to `frontend/src/lib/strategyIndicators.ts`:

```typescript
// pullback
pullback: [
  { id: "fast_ema", label: "EMA 21", type: "ema",  params: { period: 21 }, panel: "price", color: "#60a5fa" },
  { id: "slow_ema", label: "EMA 50", type: "ema",  params: { period: 50 }, panel: "price", color: "#f59e0b" },
  { id: "rsi",      label: "RSI 14", type: "rsi",  params: { period: 14 }, panel: "osc",   color: "#a78bfa",
    levels: [{ value: 35, color: "#22c55e" }, { value: 65, color: "#ef4444" }] },
],

// dual_thrust
dual_thrust: [
  { id: "atr", label: "ATR 14", type: "atr", params: { period: 14 }, panel: "price", color: "#f97316" },
],

// keltner_breakout
keltner_breakout: [
  { id: "kc_ema",   label: "EMA 20",    type: "ema",      params: { period: 20 },            panel: "price", color: "#60a5fa" },
  { id: "kc_bands", label: "Keltner 2×", type: "bollinger", params: { period: 20, mult: 2.0 }, panel: "price", color: "#f59e0b" },
  { id: "rsi",      label: "RSI 14",    type: "rsi",      params: { period: 14 },            panel: "osc",   color: "#a78bfa",
    levels: [{ value: 20, color: "#22c55e" }, { value: 80, color: "#ef4444" }] },
],
```

> Note: Keltner bands share the same shape as Bollinger Bands in the chart — use ATR-based
> mult for visual accuracy once a `keltner` indicator type is added to `indicators.ts`.

---

## 13. Implementation Phases

### Phase 1 — Core Adapter (1–2 days)

| Task | File | Effort |
|------|------|--------|
| Add `short_open`, `short_cover`, `get_margin_info` defaults to BaseEngine | `engine/base.py` | 30 min |
| Implement `OandaEngine` | `engine/oanda.py` | 4–6 h |
| Implement `OandaPaperEngine` | `engine/oanda_paper.py` | 2 h |
| Add `create_engine()` factory | `engine/__init__.py` | 30 min |
| Wire factory into `main.py` | `main.py` | 1 h |
| Config + env var updates | `config.yaml`, `.env.example` | 30 min |

### Phase 2 — CFD Risk (1 day)

| Task | File | Effort |
|------|------|--------|
| `MarginMonitor` thread | `margin_monitor.py` | 3 h |
| Swap accrual tracking | `engine/oanda.py` | 2 h |
| Swap cost in backtest | `backtester/` | 3 h |

### Phase 3 — UI & Testing (1 day)

| Task | File | Effort |
|------|------|--------|
| `strategyIndicators.ts` updates | frontend | 1 h |
| Add `OANDA_*` fields to Settings UI | frontend | 2 h |
| Unit tests for OandaEngine | `tests/test_oanda_engine.py` | 3 h |
| Integration test (OANDA practice) | `tests/test_oanda_live.py` | 2 h |

---

## 14. Testing Plan

### Unit Tests (mock oandapyV20)

```python
# tests/test_oanda_engine.py

from unittest.mock import patch, MagicMock
from engine.oanda import OandaEngine

MOCK_CONFIG = {
    "oanda": {"environment": "practice", "account_id": "test", "api_key": "tok"},
    "risk":  {"leverage": 20.0},
}

def test_pair_normalization():
    assert OandaEngine._to_instrument("EUR/USD") == "EUR_USD"
    assert OandaEngine._to_pair("GBP_JPY")       == "GBP/JPY"

@patch("oandapyV20.API")
def test_market_buy_places_positive_units(mock_api):
    mock_api.return_value.request.return_value = {
        "orderFillTransaction": {"price": "1.08500", "id": "1", "financing": "0"}
    }
    engine = OandaEngine(MOCK_CONFIG)
    # price fetch also mocked — set up accordingly
    with patch.object(engine, "get_price", return_value=1.085):
        result = engine.market_buy("EUR/USD", 100)
    assert result["status"] == "filled"
    # units should be positive (long)
    call_data = mock_api.return_value.request.call_args[0][0].data
    assert int(call_data["order"]["units"]) > 0

@patch("oandapyV20.API")
def test_short_open_places_negative_units(mock_api):
    mock_api.return_value.request.return_value = {
        "orderFillTransaction": {"price": "1.08500", "id": "2", "financing": "0"}
    }
    engine = OandaEngine(MOCK_CONFIG)
    with patch.object(engine, "get_price", return_value=1.085):
        result = engine.short_open("EUR/USD", 100)
    assert result["status"] == "filled"
    call_data = mock_api.return_value.request.call_args[0][0].data
    assert int(call_data["order"]["units"]) < 0   # short = negative
```

### Integration Test (OANDA Practice Account)

```python
# tests/test_oanda_live.py  — runs against OANDA practice, requires env vars

import os, pytest
from engine.oanda import OandaEngine

@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("OANDA_API_KEY"), reason="No OANDA creds")
def test_get_price():
    cfg    = {"oanda": {"environment": "practice"}, "risk": {"leverage": 20}}
    engine = OandaEngine(cfg)
    price  = engine.get_price("EUR/USD")
    assert 0.5 < price < 3.0, f"Unexpected EUR/USD price: {price}"

@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("OANDA_API_KEY"), reason="No OANDA creds")
def test_fetch_ohlcv_returns_dataframe():
    cfg    = {"oanda": {"environment": "practice"}, "risk": {"leverage": 20}}
    engine = OandaEngine(cfg)
    df     = engine.fetch_ohlcv("EUR/USD", "1h", limit=50)
    assert len(df) == 50
    assert set(df.columns) >= {"open", "high", "low", "close", "volume"}
```

---

## 15. Dependencies

Add to `requirements.txt`:

```
oandapyV20>=0.6.6
```

Install:
```bash
pip install oandapyV20
```

---

## 16. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OANDA rate limits (120 req/30s) | Orders throttled | Add retry + backoff in `_place_order()` |
| Weekend gap risk (market closed) | Strategy fires on stale data | Check `tradeable` flag in pricing response |
| Margin stop-out during news events | Positions auto-closed by broker | MarginMonitor + guaranteed stops (Phase 2) |
| Overnight swap erodes P&L | Strategy looks profitable but isn't | Track swap in `get_financing_cost()` |
| OANDA returns incomplete candles | Strategy uses noisy last bar | Filter `complete: false` candles (already done in `fetch_ohlcv`) |
| Env-var missing in production | Engine fails to start | Validate at `__init__` time with clear error message |

---

## 17. Quick Start (after implementation)

```bash
# 1. Install
pip install oandapyV20

# 2. Set credentials
echo "OANDA_API_KEY=your-token"        >> .env
echo "OANDA_ACCOUNT_ID=001-001-xxx-001" >> .env
echo "OANDA_ENVIRONMENT=practice"       >> .env

# 3. Update config
# Set exchange: oanda in config.yaml
# Set pairs: [EUR/USD, GBP/USD, XAU/USD]

# 4. Run paper trading
python crypto_bot/main.py --mode paper --strategy pullback

# 5. Run live (practice account)
python crypto_bot/main.py --mode live --strategy keltner_breakout
```

---

*Proposal ready for review. Phase 1 can start immediately with the OANDA practice account.*
