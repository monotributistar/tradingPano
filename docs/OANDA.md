# OANDA CFD Adapter

This document is the operational reference for trading forex and CFD instruments
via the OANDA v20 REST API.  It covers setup, configuration, the engine contract,
risk management extensions, and the backtester swap cost feature.

---

## Table of Contents

- [Overview](#overview)
- [Supported Instruments](#supported-instruments)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Engine Modes](#engine-modes)
  - [OandaEngine (live)](#oandaengine-live)
  - [OandaPaperEngine (paper)](#oandapaperengine-paper)
- [Engine Factory](#engine-factory)
- [OandaEngine API Reference](#oandaengine-api-reference)
- [MarginMonitor](#marginmonitor)
- [Swap Accrual](#swap-accrual)
- [Backtest Swap Cost](#backtest-swap-cost)
- [Differences from Crypto (LiveEngine)](#differences-from-crypto-liveengine)
- [Running Strategies on OANDA](#running-strategies-on-oanda)
- [Troubleshooting](#troubleshooting)

---

## Overview

```
                    create_engine(config, mode)
                           │
              ┌────────────┴────────────┐
              │ exchange == "oanda" ?   │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │  mode == "paper"?       │
     yes ─────┤                         ├───── no
              └────────────┬────────────┘
                           │
         OandaPaperEngine  │  OandaEngine
         (virtual balance  │  (real orders via
          real OANDA prices)│   OANDA v20 REST)
```

All 22 strategies run unchanged — only the exchange layer is swapped.
The engine converts between the project's slash notation (`EUR/USD`) and
OANDA's underscore notation (`EUR_USD`) transparently.

---

## Supported Instruments

| Category | Examples |
|---|---|
| Major FX | EUR/USD · GBP/USD · USD/JPY · AUD/USD |
| Minor FX | EUR/GBP · EUR/JPY · GBP/JPY |
| Commodity CFDs | XAU/USD (gold) · XAG/USD (silver) · BCO/USD (oil) |
| Index CFDs | US30/USD (Dow) · SPX500/USD (S&P) · NAS100/USD (Nasdaq) |

> Crypto spot (BTC/USDT, etc.) is **not** available on OANDA — use `LiveEngine` (Bybit) for crypto.

---

## Prerequisites

1. Open an OANDA practice account at [oanda.com](https://www.oanda.com)
2. Generate a personal access token:
   `My Account → Manage API Access → Generate`
3. Copy your account ID (format: `001-001-1234567-001`)
4. Install the Python client:
   ```bash
   pip install oandapyV20>=0.6.6
   # already in crypto_bot/requirements.txt
   ```

---

## Configuration

### Environment variables (preferred)

```bash
# .env
OANDA_API_KEY=your-personal-access-token
OANDA_ACCOUNT_ID=001-001-1234567-001
OANDA_ENVIRONMENT=practice   # "practice" or "live"
```

### config.yaml

```yaml
exchange: oanda   # switch from "bybit" to "oanda"

oanda:
  environment: practice   # overridden by OANDA_ENVIRONMENT env var
  # api_key and account_id are read from env vars; fallback here if needed:
  # api_key: ""
  # account_id: ""

pairs:
  - EUR/USD
  - GBP/USD
  - XAU/USD    # gold CFD

timeframe: 1h

risk:
  leverage: 20.0             # ESMA retail cap: 30x FX, 20x indices, 5x commodities
  use_futures: true          # enables SHORT / COVER signal handling
  max_concurrent_positions: 3
  daily_loss_stop_pct: 2.0
  position_sizing: fixed
  atr_stop_enabled: true
  atr_stop_mult: 1.5
  max_drawdown_pct: 4.0

backtest:
  initial_capital: 10000
  fee_pct: 0.0               # OANDA charges spread, not explicit fees
  slippage_pct: 0.02
  swap_cost_daily_pct: 0.02  # overnight financing ~2% annual ÷ 365 ≈ 0.0055% daily
```

### Timeframe mapping

| Config value | OANDA granularity |
|---|---|
| `1m` | M1 |
| `5m` | M5 |
| `15m` | M15 |
| `30m` | M30 |
| `1h` | H1 |
| `2h` | H2 |
| `4h` | H4 |
| `6h` | H6 |
| `12h` | H12 |
| `1d` | D |
| `1w` | W |

---

## Engine Modes

### OandaEngine (live)

File: `crypto_bot/engine/oanda.py`

Places real orders on the OANDA practice or live account.  Uses the v20 REST
API via `oandapyV20`.

```python
from engine.oanda import OandaEngine

engine = OandaEngine(config)
price  = engine.get_price("EUR/USD")       # mid price (bid+ask)/2
bal    = engine.get_balance()              # NAV, margin, unrealized PL
order  = engine.market_buy("EUR/USD", 100) # 100 USDT worth, leveraged
```

**Unit sizing** — OANDA orders are unit-based, not USDT-based.  The engine
converts automatically:

```
units = max(1, int(usdt_amount × leverage / mid_price))
```

For example: 100 USDT × 20× leverage ÷ EUR/USD 1.085 ≈ **1843 units**.

### OandaPaperEngine (paper)

File: `crypto_bot/engine/oanda_paper.py`

Virtual balance + trade simulation, but price feed and OHLCV data come from
the real OANDA practice REST API.  No real orders are ever placed.

```python
from engine.oanda_paper import OandaPaperEngine

engine = OandaPaperEngine(config)
# market_buy / market_sell / short_open / short_cover → all simulated
# get_price / fetch_ohlcv → real OANDA data
```

Requires the same OANDA credentials as `OandaEngine` (for the price feed).

---

## Engine Factory

`engine/__init__.py` provides `create_engine()` — the canonical way to instantiate
an engine.  Both `main.py` (CLI) and `api/bot_manager.py` use it.

```python
from engine import create_engine

engine = create_engine(config, mode="paper")  # OandaPaperEngine if exchange==oanda
engine = create_engine(config, mode="live")   # OandaEngine if exchange==oanda
```

Routing table:

| `config["exchange"]` | `mode` | Engine |
|---|---|---|
| `bybit` / `binance` / ... | `paper` | `PaperEngine` (ccxt prices) |
| `bybit` / `binance` / ... | `live` | `LiveEngine` (ccxt) |
| `oanda` | `paper` | `OandaPaperEngine` |
| `oanda` | `live` | `OandaEngine` |

---

## OandaEngine API Reference

All methods implement the `BaseEngine` contract; OANDA-specific extensions are marked ★.

### `get_price(pair) → float`

Returns the mid price `(bid + ask) / 2` from the OANDA pricing endpoint.

```python
price = engine.get_price("EUR/USD")  # e.g. 1.08512
```

### `get_balance() → dict`

```python
{
    "USDT":         10000.0,   # account balance (base currency)
    "nav":          10050.25,  # net asset value
    "unrealizedPL":    50.25,  # open position P&L
    "margin_used":    500.0,   # margin currently in use
    "margin_avail":  9550.0,   # available margin
    "margin_level":  2010.0,   # NAV / margin_used × 100 (%)
}
```

### `market_buy(pair, usdt_amount) → dict`

Opens or adds to a long position.  Sends a positive-unit MARKET FOK order.

```python
order = engine.market_buy("EUR/USD", 100.0)
# → {"status": "filled", "price": 1.085, "qty": 1843, "fee": 0.0, "order_id": "123"}
```

### `market_sell(pair, qty) → dict`

Closes an existing long position.  Sends a negative-unit MARKET REDUCE_ONLY order.

```python
order = engine.market_sell("EUR/USD", 1843)
```

### `short_open(pair, usdt_amount) → dict`

Opens a short position.  Sends a negative-unit MARKET DEFAULT order.

### `short_cover(pair, qty) → dict`

Closes an existing short position.  Sends a positive-unit MARKET REDUCE_ONLY order.

### `fetch_ohlcv(pair, timeframe, limit=100) → pd.DataFrame`

Returns complete (non-in-progress) candles as a DataFrame indexed by UTC timestamp.
Columns: `open · high · low · close · volume`.

```python
df = engine.fetch_ohlcv("EUR/USD", "1h", limit=200)
```

> **Note:** OANDA returns in-progress (incomplete) candles — the engine filters
> them out using `c["complete"] == True` before returning.

### ★ `get_margin_info() → dict`

```python
{
    "margin_level":     2010.0,  # % — 9999.0 when no open positions
    "margin_used":       500.0,
    "margin_available": 9550.0,
    "nav":             10050.0,
}
```

### ★ `get_financing_cost() → float`

Returns the total accumulated overnight financing cost (in account currency) across
all instruments since the engine was instantiated.

```python
cost = engine.get_financing_cost()  # e.g. -4.25 (negative = charge)
```

### ★ `accrue_swap(instrument)`

Fetches the current financing charge for `instrument` from the OANDA
PositionDetails endpoint and adds it to the local accumulator.

```python
engine.accrue_swap("EUR_USD")   # instrument notation, not pair
```

Call this once per candle close (or on a nightly schedule) to keep the
financing accumulator current.  Safe when no position is open.

### `_place_order()` error handling

On any API error, `_place_order()` catches the exception, logs it, and returns:
```python
{"status": "error", "reason": "<exception message>"}
```
The bot never crashes from a failed order — it logs and continues.

---

## MarginMonitor

File: `crypto_bot/margin_monitor.py`

A background daemon thread that polls `engine.get_margin_info()` every N seconds
and protects against margin stop-out.

### Thresholds

| Level | Default | Action |
|---|---|---|
| `WARN_LEVEL` | 200% | Log `WARNING` |
| `ALERT_LEVEL` | 150% | Log `ERROR` + send Telegram alert |
| `STOP_LEVEL` | 110% | Log `CRITICAL` + alert + call `bot_manager.stop()` |

OANDA force-closes positions at 100% margin level.  The 110% stop threshold
gives a 10-point safety buffer.

### Usage

```python
from margin_monitor import MarginMonitor

monitor = MarginMonitor(
    engine      = oanda_engine,
    bot_manager = bot_manager,
    notifier    = telegram_notifier,  # optional — any object with .send(text)
    interval_s  = 30,                 # poll every 30 seconds (default)
)
monitor.start()   # starts daemon thread — non-blocking
# ...
monitor.stop()    # signals thread to stop after current sleep
```

### `check_once() → dict`

Synchronous single check — useful for testing and manual calls.

```python
result = monitor.check_once()
# → {"level": 320.5, "action": "ok"}
# → {"level": 145.0, "action": "alert"}
# → {"level": 108.0, "action": "stop"}
# → {"level": 0.0,   "action": "error", "error": "Connection reset"}
```

### Integration with bot_manager

Wire the `MarginMonitor` into the bot start lifecycle in `api/bot_manager.py`:

```python
from margin_monitor import MarginMonitor

# after engine is created:
if config.get("exchange") == "oanda":
    monitor = MarginMonitor(engine, bot_manager, notifier=telegram_notifier)
    monitor.start()
```

---

## Swap Accrual

OANDA charges overnight financing (swap) on open CFD positions.  The engine
tracks this via `_swap_accrual: dict[str, float]` — keyed by OANDA instrument.

### How it accumulates

Each `_place_order()` call reads `orderFillTransaction.financing` from the fill
response and adds it to `_swap_accrual[instrument]`.

For positions held between orders, call `accrue_swap(instrument)` periodically:

```python
# Once per candle (in your bot loop):
for instrument in open_instruments:
    engine.accrue_swap(instrument)

# Total financing cost:
total_cost = engine.get_financing_cost()   # sum across all instruments
```

### Reading the total

```python
cost = engine.get_financing_cost()
# Negative value means you were charged (normal for long positions in low-rate pairs)
# Positive value means you received financing (short positions in carry trades)
```

---

## Backtest Swap Cost

The backtester can simulate overnight financing charges via the
`swap_cost_daily_pct` parameter.

### How it works

At every bar where a position is held, the runner deducts:

```
cost_per_bar = (swap_cost_daily_pct / bars_per_day) * position_value
```

Where `bars_per_day` is derived from the timeframe (e.g. 24 for `1h`, 6 for `4h`).
For short positions, `position_value = collateral`.

The total deducted is returned in `result["total_swap_cost"]`.

### Configuration

```yaml
backtest:
  swap_cost_daily_pct: 0.0055   # ~2% annual / 365 days ≈ realistic for EUR/USD
```

| Pair / Instrument | Typical daily rate |
|---|---|
| EUR/USD long | ~0.002% (low carry) |
| GBP/JPY long | ~0.008% (high carry) |
| XAU/USD long | ~0.006% (commodity) |
| Short positions | Rate may be positive (you receive financing) |

> These are approximate. Check current rates on the OANDA platform before
> running real capital.

### Result dict

```python
result = runner.run(strategy, pair="EUR/USD", period="6m")

result["total_swap_cost"]   # float — total financing deducted (e.g. -12.40)
result["metrics"]           # equity metrics already reflect the swap cost
result["equity_curve"]      # equity curve already reflects the swap cost
```

### Default is `0.0` (backward-compatible)

Omitting `swap_cost_daily_pct` or setting it to `0.0` disables the feature.
All existing backtests are unaffected.

---

## Differences from Crypto (LiveEngine)

| Feature | LiveEngine (Bybit/ccxt) | OandaEngine (OANDA) |
|---|---|---|
| Order size | USDT amount | Integer units (auto-converted) |
| Price feed | `fetch_ticker` last price | Mid (bid+ask)/2 |
| Shorting | Perpetuals swap market | Negative units, same account |
| Fees | Exchange fee % | Spread only (fee_pct = 0) |
| Market hours | 24/7 | Forex: Mon–Fri; Closed weekends |
| Overnight cost | None (crypto) | Swap / overnight financing |
| Leverage | Exchange default | Config `risk.leverage` (ESMA caps apply) |
| Candle completeness | All candles complete | Engine filters `complete: false` |
| Testnet | Bybit sandbox | OANDA practice account |

---

## Running Strategies on OANDA

### CLI — paper trading

```bash
# Paper trade with real OANDA prices, virtual balance
python3 crypto_bot/main.py --mode paper --strategy keltner_breakout

# Override config inline
OANDA_ENVIRONMENT=practice python3 crypto_bot/main.py --mode paper --strategy pullback
```

### CLI — live trading

```bash
# Live orders on OANDA practice account
OANDA_ENVIRONMENT=practice python3 crypto_bot/main.py --mode live --strategy dual_thrust

# Production (real money — triple check!)
OANDA_ENVIRONMENT=live python3 crypto_bot/main.py --mode live --strategy ema_crossover
```

### Via API (bot_manager)

```bash
curl -X POST http://localhost:8000/api/bot/start \
  -H "X-API-Key: $BOT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "paper",
    "strategy": "keltner_breakout",
    "pairs": ["EUR/USD", "XAU/USD"],
    "timeframe": "1h"
  }'
```

### Recommended strategies for forex/CFD

| Strategy | Why it fits | Key config |
|---|---|---|
| `keltner_breakout` | Designed for trending FX pairs | `atr_mult: 2.0` |
| `pullback` | EMA + RSI mean-reversion, low noise | `fast_ema: 21, rsi_low: 35` |
| `dual_thrust` | Range-breakout, good for Asian session | `k1: 0.7, k2: 0.7` |
| `trend_following` | Supertrend for commodity CFDs | `atr_period: 14, factor: 3.0` |
| `ema_crossover` | Classic FX signal, simple | `fast_ema: 9, slow_ema: 21` |

---

## Troubleshooting

### `ValueError: OANDA credentials missing`

`OANDA_API_KEY` or `OANDA_ACCOUNT_ID` env vars are not set.

```bash
export OANDA_API_KEY=your-token
export OANDA_ACCOUNT_ID=001-001-1234567-001
# or add them to .env
```

### `OandaPaperEngine` fails to import / ccxt error

The paper engine passes `exchange: bybit` to `PaperEngine.__init__` internally
(since OANDA isn't a ccxt exchange).  If ccxt is not installed:

```bash
pip install ccxt
```

### Orders return `{"status": "error"}`

Check the `reason` field and the bot log (`data/bot.log`).  Common causes:
- `ACCOUNT_NOT_TRADEABLE` — practice account, confirm instruments are enabled
- `INSUFFICIENT_MARGIN` — reduce `leverage` in config or close other positions
- `MARKET_ORDER_FILLED` — fill was actually successful (race condition log)

### Weekend gap risk

OANDA's forex market closes Friday ~17:00 NY time and reopens Sunday ~17:00 NY time.
Strategies will not receive new candles during this period.  Set `stale_price_candles`
in the `risk:` config section and enable `AnomalyDetector` to alert on stale prices.

### Incomplete candles in OHLCV

OANDA returns the in-progress (current, incomplete) candle in every response.
`OandaEngine.fetch_ohlcv()` filters these out by checking `c["complete"] == True`.
If your strategy receives a shorter-than-expected DataFrame, this is the reason.

### OANDA rate limit (120 requests / 30 seconds)

If you run multiple pairs simultaneously, you may hit the rate limit.  The engine
does not implement automatic retry for price requests.  Increase the candle interval
or reduce the number of simultaneous pairs.
