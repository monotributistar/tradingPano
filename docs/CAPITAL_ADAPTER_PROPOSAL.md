# Capital.com CFD Adapter — Implementation Proposal

**Status:** Approved for development  
**Date:** 2026-04-23  
**Target files:** `crypto_bot/engine/capital.py`, `crypto_bot/engine/capital_paper.py`

---

## 1. Summary

Add a `CapitalEngine` adapter so every existing strategy can trade forex and
CFD instruments through the Capital.com REST API, using the same `BaseEngine`
contract that already powers Bybit (ccxt) and OANDA.

---

## 2. Capital.com API — Key Facts

### Authentication (session-based, NOT header-key)

Capital.com uses a **two-step session model** — fundamentally different from
OANDA (where the API key goes in every request header).

```
Step 1 — POST /session
  Headers:  X-CAP-API-KEY: <api_key>
  Body:     {"identifier": "<email>", "password": "<password>", "encryptedPassword": false}

  Response headers (read these, not the body):
    CST: <authorization_token>          ← changes every session
    X-SECURITY-TOKEN: <account_token>   ← changes every session

Step 2 — every subsequent request
  Headers:  CST: <token>
            X-SECURITY-TOKEN: <account_token>
```

**Session lifetime:** 10 minutes of inactivity — auto-expires.  
**Strategy:** re-authenticate lazily on HTTP 401, or proactively every 9 minutes.

### Base URLs

| Environment | Base URL |
|---|---|
| Demo | `https://demo-api-capital.backend-capital.com/api/v1` |
| Live | `https://api-capital.backend-capital.com/api/v1` |

### Instrument format (EPIC)

Capital.com uses **concatenated uppercase** — no separators:

```
EUR/USD  →  EURUSD
GBP/USD  →  GBPUSD
XAU/USD  →  XAUUSD   (gold)
US30     →  US30      (Dow Jones)
BTC/USD  →  BTCUSD
```

### Order sizing

Capital.com orders use **`size`** (quantity in contract lots).  
Conversion from USDT amount:

```
size = max(0.01, round(usdt_amount * leverage / (price * contract_size), 2))
```

Default contract sizes:
- FX majors (EURUSD, GBPUSD, …): 10 000 units of base currency
- Gold (XAUUSD): 100 troy oz
- Indices (US30): 1 point per unit

The engine will use a **configurable default** `contract_size: 10000` and allow
per-instrument overrides in config.

### Short selling

Open short → `POST /positions` with `"direction": "SELL"`  
Close short → `DELETE /positions/<dealId>` (same as closing a long)

Both sides use the same endpoint; direction is explicit in the body.

### Rate limits

| Scope | Limit |
|---|---|
| Session creation | 1 req/s |
| General requests | 10 req/s |
| Order creation | 1 per 100 ms |
| Demo trading ops | 1 000/hour |

---

## 3. Architecture

```
create_engine(config, mode)
        │
        ├── exchange == "capital", mode == "live"  →  CapitalEngine
        └── exchange == "capital", mode == "paper" →  CapitalPaperEngine
```

```
CapitalEngine
┌──────────────────────────────────────────────────────────┐
│  Session layer                                           │
│  ├── _create_session()  POST /session → store CST+XST   │
│  ├── _headers()         returns {"CST":…,"X-SECURITY-TOKEN":…}
│  └── _request()         auto-retry on 401 (re-auth)     │
│                                                          │
│  BaseEngine methods                                      │
│  ├── get_price(pair)    POST /prices → (bid+offer)/2     │
│  ├── get_balance()      GET /accounts → balance dict     │
│  ├── market_buy()       POST /positions dir=BUY          │
│  ├── market_sell()      DELETE /positions/<dealId>       │
│  ├── short_open()       POST /positions dir=SELL         │
│  ├── short_cover()      DELETE /positions/<dealId>       │
│  └── fetch_ohlcv()      GET /prices/ohlc                 │
│                                                          │
│  CFD extensions                                          │
│  ├── get_margin_info()  derived from GET /accounts       │
│  └── get_financing_cost() accumulated from activity log  │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Files to Create / Modify

```
crypto_bot/
├── engine/
│   ├── capital.py          ← NEW  CapitalEngine
│   ├── capital_paper.py    ← NEW  CapitalPaperEngine
│   └── __init__.py         ← MODIFY  add "capital" routing
├── config.yaml             ← MODIFY  add capital: block
└── requirements.txt        ← no new dep (uses requests, already installed)

tests/unit/
├── test_capital_engine.py  ← NEW  ~55 unit tests
└── test_engine_factory.py  ← MODIFY  add capital routing tests

docs/
└── CAPITAL.md              ← NEW  operational doc (after implementation)

.env.example                ← already updated
```

---

## 5. `CapitalEngine` — Full Design

### 5.1 Constructor

```python
class CapitalEngine(BaseEngine):
    def __init__(self, config: dict) -> None:
        capital_cfg  = config.get("capital", {})
        risk_cfg     = config.get("risk", {})

        api_key      = os.environ.get("CAPITAL_API_KEY")     or capital_cfg.get("api_key", "")
        password     = os.environ.get("CAPITAL_PASSWORD")    or capital_cfg.get("password", "")
        environment  = os.environ.get("CAPITAL_ENVIRONMENT") or capital_cfg.get("environment", "demo")

        if not api_key or not password:
            raise ValueError("CAPITAL_API_KEY and CAPITAL_PASSWORD required.")

        self._api_key      = api_key
        self._password     = password
        self.leverage      = float(risk_cfg.get("leverage", 10.0))
        self.contract_size = float(capital_cfg.get("contract_size", 10_000))

        self._base_url = (
            "https://api-capital.backend-capital.com/api/v1"
            if environment == "live"
            else "https://demo-api-capital.backend-capital.com/api/v1"
        )

        # Session tokens — refreshed automatically
        self._cst: str   = ""
        self._xst: str   = ""          # X-SECURITY-TOKEN
        self._session_at: float = 0.0  # epoch time of last auth

        # dealId tracker: pair → dealId (needed to close positions)
        self._deal_ids: dict[str, str] = {}

        # Swap accumulator
        self._swap_accrual: dict[str, float] = {}

        self._create_session()
```

### 5.2 Session Management

```python
_SESSION_TTL = 540  # 9 minutes (server expires at 10)

def _create_session(self) -> None:
    """POST /session — store CST and X-SECURITY-TOKEN from response headers."""
    resp = requests.post(
        f"{self._base_url}/session",
        headers={"X-CAP-API-KEY": self._api_key, "Content-Type": "application/json"},
        json={"identifier": self._api_key, "password": self._password,
              "encryptedPassword": False},
    )
    resp.raise_for_status()
    self._cst      = resp.headers["CST"]
    self._xst      = resp.headers["X-SECURITY-TOKEN"]
    self._session_at = time.time()
    logger.info("[CapitalEngine] Session created.")

def _ensure_session(self) -> None:
    """Refresh session if older than TTL."""
    if time.time() - self._session_at > _SESSION_TTL:
        logger.debug("[CapitalEngine] Session TTL exceeded — refreshing.")
        self._create_session()

def _headers(self) -> dict:
    return {
        "CST":               self._cst,
        "X-SECURITY-TOKEN":  self._xst,
        "Content-Type":      "application/json",
    }

def _request(self, method: str, path: str, **kwargs) -> dict:
    """HTTP wrapper with auto-reauth on 401."""
    self._ensure_session()
    url = f"{self._base_url}{path}"
    resp = requests.request(method, url, headers=self._headers(), **kwargs)
    if resp.status_code == 401:
        logger.warning("[CapitalEngine] 401 — re-authenticating.")
        self._create_session()
        resp = requests.request(method, url, headers=self._headers(), **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else {}
```

### 5.3 Pair ↔ EPIC conversion

```python
@staticmethod
def _to_epic(pair: str) -> str:
    """'EUR/USD' → 'EURUSD'"""
    return pair.replace("/", "").upper()

@staticmethod
def _to_pair(epic: str) -> str:
    """Best-effort: 'EURUSD' → 'EUR/USD' (3+3 split)"""
    if len(epic) == 6:
        return f"{epic[:3]}/{epic[3:]}"
    return epic   # non-standard epics returned as-is
```

### 5.4 Price & Balance

```python
def get_price(self, pair: str) -> float:
    """Return mid price (bid + offer) / 2."""
    epic = self._to_epic(pair)
    data = self._request("GET", f"/markets/{epic}")
    bid  = float(data["snapshot"]["bid"])
    offer = float(data["snapshot"]["offer"])
    return (bid + offer) / 2.0

def get_balance(self) -> dict:
    data     = self._request("GET", "/accounts")
    account  = data["accounts"][0]   # first (active) account
    balance  = float(account["balance"]["balance"])
    deposit  = float(account["balance"]["deposit"])
    pnl      = float(account["balance"]["pnl"])
    available = float(account["balance"]["available"])
    return {
        "USDT":          balance,
        "deposit":       deposit,
        "unrealizedPL":  pnl,
        "margin_avail":  available,
        "margin_level":  (balance / max(deposit - available, 1)) * 100
            if (deposit - available) > 0 else 9999.0,
    }
```

### 5.5 Order methods

```python
def market_buy(self, pair: str, usdt_amount: float) -> dict:
    """Open or add to a long position (direction=BUY)."""
    epic = self._to_epic(pair)
    size = self._usdt_to_size(epic, usdt_amount)
    return self._open_position(epic, "BUY", size, pair)

def market_sell(self, pair: str, qty: float) -> dict:
    """Close a long position by dealId."""
    return self._close_position(pair)

def short_open(self, pair: str, usdt_amount: float) -> dict:
    """Open a short position (direction=SELL)."""
    epic = self._to_epic(pair)
    size = self._usdt_to_size(epic, usdt_amount)
    return self._open_position(epic, "SELL", size, pair)

def short_cover(self, pair: str, qty: float) -> dict:
    """Close a short position by dealId."""
    return self._close_position(pair)

def _open_position(self, epic: str, direction: str,
                   size: float, pair: str) -> dict:
    try:
        resp = self._request("POST", "/positions", json={
            "epic":      epic,
            "direction": direction,
            "size":      size,
            "orderType": "MARKET",
            "guaranteedStop": False,
        })
        deal_id = resp.get("dealId", "")
        self._deal_ids[pair] = deal_id
        logger.info("[CapitalEngine] %s %s size=%.2f dealId=%s",
                    direction, pair, size, deal_id)
        return {
            "status":   "filled",
            "price":    self.get_price(pair),
            "qty":      size,
            "fee":      0.0,
            "order_id": deal_id,
        }
    except Exception as exc:
        logger.error("[CapitalEngine] Open %s %s failed: %s", direction, pair, exc)
        return {"status": "error", "reason": str(exc)}

def _close_position(self, pair: str) -> dict:
    deal_id = self._deal_ids.pop(pair, None)
    if not deal_id:
        logger.warning("[CapitalEngine] No dealId for %s — cannot close", pair)
        return {"status": "error", "reason": f"no dealId for {pair}"}
    try:
        self._request("DELETE", f"/positions/{deal_id}")
        logger.info("[CapitalEngine] Closed %s dealId=%s", pair, deal_id)
        return {"status": "filled", "price": self.get_price(pair),
                "qty": 0, "fee": 0.0, "order_id": deal_id}
    except Exception as exc:
        logger.error("[CapitalEngine] Close %s failed: %s", pair, exc)
        return {"status": "error", "reason": str(exc)}
```

### 5.6 OHLCV

```python
_TF_MAP = {
    "1m":  "MINUTE",    "5m":  "MINUTE_5",   "15m": "MINUTE_15",
    "30m": "MINUTE_30", "1h":  "HOUR",        "2h":  "HOUR_2",
    "4h":  "HOUR_4",    "1d":  "DAY",         "1w":  "WEEK",
}
_MAX_CANDLES = 1000

def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
    epic        = self._to_epic(pair)
    resolution  = _TF_MAP.get(timeframe, "HOUR")
    data = self._request("GET", f"/prices/{epic}", params={
        "resolution": resolution,
        "max":        min(limit, _MAX_CANDLES),
    })
    rows = []
    for c in data.get("prices", []):
        rows.append({
            "timestamp": pd.Timestamp(c["snapshotTimeUTC"]),
            "open":   (float(c["openPrice"]["bid"])  + float(c["openPrice"]["ask"])) / 2,
            "high":   (float(c["highPrice"]["bid"])  + float(c["highPrice"]["ask"])) / 2,
            "low":    (float(c["lowPrice"]["bid"])   + float(c["lowPrice"]["ask"])) / 2,
            "close":  (float(c["closePrice"]["bid"]) + float(c["closePrice"]["ask"])) / 2,
            "volume": int(c.get("lastTradedVolume", 0)),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.set_index("timestamp", inplace=True)
    return df

def _usdt_to_size(self, epic: str, usdt_amount: float) -> float:
    price = self.get_price(self._to_pair(epic))
    size  = (usdt_amount * self.leverage) / (price * self.contract_size)
    return max(0.01, round(size, 2))
```

---

## 6. `CapitalPaperEngine` — Design

Follows the same pattern as `OandaPaperEngine`: extends `PaperEngine` for
virtual balance/trade simulation, overrides `get_price()` and `fetch_ohlcv()`
to use real Capital.com prices.

```python
class CapitalPaperEngine(PaperEngine):
    def __init__(self, config: dict) -> None:
        _init_cfg = {**config, "exchange": "bybit"}  # bypass ccxt init
        super().__init__(_init_cfg)
        self._capital = CapitalEngine(config)   # real price feed only

    def get_price(self, pair: str) -> float:
        return self._capital.get_price(pair)

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 100):
        return self._capital.fetch_ohlcv(pair, timeframe, limit)
```

---

## 7. Engine Factory Update

```python
# engine/__init__.py  — add after oanda block

if exchange == "capital":
    from engine.capital import CapitalEngine
    logger.info("[factory] CapitalEngine selected")
    return CapitalEngine(config)

# paper:
if exchange == "capital":
    from engine.capital_paper import CapitalPaperEngine
    logger.info("[factory] CapitalPaperEngine selected")
    return CapitalPaperEngine(config)
```

---

## 8. Config Block

```yaml
# config.yaml
exchange: capital

capital:
  environment: demo          # "demo" | "live"
  contract_size: 10000       # default lot size (FX majors)
  # api_key and password read from CAPITAL_API_KEY / CAPITAL_PASSWORD env vars

pairs:
  - EUR/USD
  - GBP/USD
  - XAU/USD

timeframe: 1h

risk:
  leverage: 10.0
  use_futures: true
  max_concurrent_positions: 3
  daily_loss_stop_pct: 2.0
```

---

## 9. Key Differences from OANDA Adapter

| Aspect | OANDA | Capital.com |
|---|---|---|
| Auth | API key in every header | Session (CST + X-SECURITY-TOKEN) |
| Token refresh | Never expires | Every 10 min inactivity |
| Order sizing | Integer units | Float lots (min 0.01) |
| Short selling | Negative units | `direction: "SELL"` |
| Close position | Negative/reduce-only order | `DELETE /positions/{dealId}` |
| DealId tracking | Not needed | **Required** — stored in `_deal_ids` |
| Library | oandapyV20 | `requests` (no wrapper needed) |
| Pair format | EUR_USD | EURUSD |
| OHLCV endpoint | InstrumentsCandles | `GET /prices/{epic}?resolution=…` |

---

## 10. Critical Implementation Detail — dealId tracking

Capital.com does not support reduce-only orders by size. To close a position
you **must** send the `dealId` returned when the position was opened.

The engine tracks this in `_deal_ids: dict[str, str]` (pair → dealId).

**Risk:** If the engine restarts, `_deal_ids` is lost.
**Mitigation:** `_restore_deal_ids()` calls `GET /positions` on startup and
populates `_deal_ids` from open positions.

```python
def _restore_deal_ids(self) -> None:
    """Populate _deal_ids from currently open positions (called on __init__)."""
    try:
        resp = self._request("GET", "/positions")
        for pos in resp.get("positions", []):
            pair = self._to_pair(pos["position"]["epic"])
            self._deal_ids[pair] = pos["position"]["dealId"]
        if self._deal_ids:
            logger.info("[CapitalEngine] Restored %d open positions: %s",
                        len(self._deal_ids), list(self._deal_ids.keys()))
    except Exception as exc:
        logger.warning("[CapitalEngine] Could not restore dealIds: %s", exc)
```

---

## 11. Test Plan (TDD)

### `tests/unit/test_capital_engine.py` — ~55 tests

All HTTP calls mocked via `unittest.mock.patch("requests.request")`.

**Session tests (8)**
- Constructor calls POST /session
- CST and X-SECURITY-TOKEN stored from response headers
- Missing credentials raise ValueError
- Session auto-refreshes after TTL
- 401 response triggers re-auth and retry
- Session headers included in all requests
- Demo vs live base URL selected correctly
- `_restore_deal_ids()` populates from GET /positions on startup

**Pair conversion tests (4)**
- `EUR/USD` → `EURUSD`
- `XAU/USD` → `XAUUSD`
- `EURUSD` → `EUR/USD` (6-char reverse)
- Non-standard epic returned as-is

**`get_price` tests (3)**
- Returns `(bid + offer) / 2`
- Calls `GET /markets/{epic}`
- Network error → propagates exception

**`get_balance` tests (4)**
- Returns correct USDT, unrealizedPL, margin_avail
- No open positions → margin_level = 9999.0
- Maps first account from accounts list
- Fields present even with zero values

**`market_buy` tests (6)**
- Sends POST /positions with direction=BUY
- size computed correctly from usdt_amount × leverage / (price × contract_size)
- Stores dealId in `_deal_ids[pair]`
- Returns `{"status": "filled", "order_id": dealId}`
- Exception returns `{"status": "error"}`
- min size clamped to 0.01

**`market_sell` tests (4)**
- Sends DELETE /positions/{dealId}
- dealId read from `_deal_ids`
- Missing dealId returns error (no crash)
- Removes pair from `_deal_ids` after close

**`short_open` tests (5)**
- Sends POST /positions with direction=SELL
- Negative units / direction test
- Stores dealId under correct pair
- Returns filled status
- Exception returns error

**`short_cover` tests (4)**
- Sends DELETE /positions/{dealId}
- Correct dealId used
- Missing dealId returns error
- Removes pair from `_deal_ids`

**`fetch_ohlcv` tests (7)**
- Calls GET /prices/{epic} with correct resolution param
- Returns DataFrame with correct columns and UTC index
- Mid-price used `(bid+ask)/2` for all OHLC fields
- In-progress candle filtering (if applicable)
- Timeframe mapping: 1h → HOUR, 4h → HOUR_4, 1d → DAY
- Empty response → empty DataFrame
- limit capped at _MAX_CANDLES

**`get_margin_info` tests (3)**
- Returns margin_level, margin_avail, nav
- No positions → margin_level = 9999.0
- Maps correctly from accounts response

**`_restore_deal_ids` tests (4)**
- Populates _deal_ids from open positions on init
- Empty positions list → empty dict
- GET /positions error → logs warning, no crash
- Correct pair format stored

**Factory routing tests (3)** (added to `test_engine_factory.py`)
- `exchange=capital, mode=live` → CapitalEngine
- `exchange=capital, mode=paper` → CapitalPaperEngine
- `exchange=bybit` still → LiveEngine (no regression)

---

## 12. Implementation Phases

### Phase 1 — Core Adapter (this sprint)
1. Write 55 failing tests
2. `engine/capital.py` — CapitalEngine full implementation
3. `engine/capital_paper.py` — CapitalPaperEngine
4. `engine/__init__.py` — add capital routing
5. `config.yaml` — add capital block
6. All tests green

### Phase 2 — Risk Extensions
1. `MarginMonitor` already works — wire CapitalEngine into it
2. `get_financing_cost()` from `GET /history/activity` (type=DEBIT)
3. Swap cost in backtester already done

### Phase 3 — Docs
1. `docs/CAPITAL.md` — operational reference
2. `docs/architecture.md` — update engine diagram
3. `docs/CONTRACTS.md` — CapitalEngine return shapes

---

## 13. Dependencies

No new Python packages required.

`requests` is already installed (used by FastAPI dependencies).

```bash
# Verify:
python3 -c "import requests; print(requests.__version__)"
```

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Session expires mid-trade | `_request()` auto-reauth on 401 |
| dealId lost on restart | `_restore_deal_ids()` on `__init__` |
| Multiple positions same pair | `_deal_ids` stores only last — add list support if needed |
| Contract size varies by instrument | Make `contract_size` a per-pair config map |
| Rate limit on order creation (10/s) | Add 100 ms sleep after each order in `_open_position` |
| Demo API stability | Tests mock all HTTP — no flaky network dependency |

---

*Proposal ready. Proceed with Phase 1 TDD on approval.*
