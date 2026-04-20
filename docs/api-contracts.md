# API Contracts

> Interactive docs: **http://localhost:8000/docs** (Swagger UI)  
> Alternative: **http://localhost:8000/redoc** (ReDoc)  
> Base URL: `http://localhost:8000/api`
>
> **Version:** 2.1.0  
> **Last updated:** 2026-04-17

---

## Authentication

All endpoints **except** `GET /api/health` require an API key delivered via the `X-API-Key` header.

```
X-API-Key: <BOT_API_SECRET>
```

### Setup

1. Generate a secret:
   ```bash
   openssl rand -hex 32
   # → e.g. a3f2c1d8e0b4...
   ```
2. Add it to `.env`:
   ```
   BOT_API_SECRET=a3f2c1d8e0b4...
   ```
3. In the browser app — click **🔑** in the header and paste the key. It is stored in `localStorage` and sent automatically with every request.

### Errors

| Code | Meaning |
|------|---------|
| `403 Forbidden` | Key is missing or incorrect |
| `500 Internal Server Error` | `BOT_API_SECRET` env var is not set on the server |

### curl example

```bash
curl -H "X-API-Key: $BOT_API_SECRET" http://localhost:8000/api/bot/status
```

---

## Health (public — no auth)

### `GET /api/health`

Lightweight liveness probe used by Docker and nginx healthchecks.

**Response**
```json
{ "status": "ok", "version": "2.1.0" }
```

---

## Backtests

### `POST /api/backtests` — Submit a backtest job

Jobs run asynchronously. Returns `202 Accepted` immediately; poll `GET /api/backtests/{id}`.

**Request body**
```json
{
  "strategy": "stoch_rsi",
  "pair":     "NEAR/USDT",
  "period":   "6m",
  "timeframe":"4h"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | string | **required** | Strategy key from `GET /strategies` |
| `pair` | string | `"BTC/USDT"` | Trading pair (BASE/QUOTE) |
| `period` | string | `"6m"` | History window — see valid values below |
| `timeframe` | string | `"1h"` | Candle size — see valid values below |

**Valid timeframes:** `15m` · `30m` · `1h` · `2h` · `4h` · `6h` · `12h` · `1d` · `1w`  
**Valid periods:** `1w` · `2w` · `1m` · `2m` · `3m` · `6m` · `9m` · `1y` · `18m` · `2y` · `3y` · `4y` · `5y`

**Response** `202 Accepted` → `BacktestJob` (status = `"pending"`)

---

### `GET /api/backtests` — List jobs

**Query params:** `strategy`, `pair`, `limit` (default 50)  
**Response:** `BacktestJob[]` ordered newest first

---

### `GET /api/backtests/{id}` — Get single job

**Response:** `BacktestJob` with full metrics and equity curve when done  
**Error:** `404` if not found

---

### `DELETE /api/backtests/{id}` — Delete job

Also deletes all trade records for the job.  
**Response:** `204 No Content`

---

### `POST /api/backtests/{id}/walk-forward` — Walk-forward validation

Splits the job's pair/period into N out-of-sample segments and runs the strategy on each.

**Query params:**

| Param | Default | Range | Description |
|-------|---------|-------|-------------|
| `n_segments` | `5` | 2–20 | Number of OOS slices |
| `period` | job's period | — | Override data window |

**Response:** `WalkForwardResult`

---

### `POST /api/backtests/{id}/monte-carlo` — Monte Carlo simulation

Shuffles trade order N times to estimate the probability distribution of outcomes.

**Query params:**

| Param | Default | Range | Description |
|-------|---------|-------|-------------|
| `n_runs` | `1000` | 1–100000 | Number of shuffled simulations |
| `seed` | — | int | Optional random seed for reproducibility |

**Response:** `MonteCarloResult`

---

## Strategies

### `GET /api/strategies` — List all strategies

**Response:** `Strategy[]`

---

## Trades

### `GET /api/trades` — List trades

**Query params:** `backtest_job_id`, `pair`, `strategy`, `source`, `type`, `limit` (default 100)  
**Response:** `Trade[]`

---

## Provider (Market Data)

### `GET /api/provider/ohlcv/{pair}` — OHLCV candles

Uses DataFetcher with multi-exchange fallback and disk cache.

**Query params:**

| Param | Default | Description |
|-------|---------|-------------|
| `timeframe` | `"1h"` | Candle size |
| `period` | `"3m"` | History window |
| `limit` | `200` | Max candles (ignored when `period` is set) |

**Response:** `OHLCVCandle[]`

---

### `GET /api/provider/ticker/{pair}` — Live ticker

**Response:** `Ticker`

---

### `GET /api/provider/balance` — Account balance

Requires API key.  
**Response:** `{ total: Record<string,number>, free: Record<string,number> }`

---

### `GET /api/provider/status` — Exchange config

**Response:** `ProviderStatus`

---

### `POST /api/provider/test` — Test connectivity

**Response:** `ConnectionResult`

---

### `PATCH /api/provider/config` — Update exchange config

Persists to `config.yaml`. Accepts any subset of fields.

---

## Presets

### `GET /api/presets` → `Preset[]`
### `POST /api/presets/{id}/apply` → `ApplyPresetResult`
### `GET /api/presets/active/current` → active preset info

---

## TypeScript Contracts

### `BacktestJob`
```typescript
interface BacktestJob {
  id: number;
  strategy: string;
  pair: string;
  period: string;         // e.g. "6m"
  timeframe: string;      // e.g. "4h"
  status: "pending" | "running" | "done" | "error";
  error_msg?: string;
  metrics?: BacktestMetrics;
  equity_curve?: number[];      // USDT portfolio value per bar
  equity_timestamps?: string[]; // ISO 8601 UTC per bar
  params?: Record<string, unknown>;
  created_at: string;           // ISO 8601 UTC
  started_at?: string;
  finished_at?: string;
}
```

### `BacktestMetrics`
```typescript
interface BacktestMetrics {
  total_return_pct: number;       // e.g. 27.3 means +27.3%
  final_capital: number;          // USDT
  initial_capital: number;        // USDT
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;       // positive value, e.g. 8.2 means -8.2%
  max_drawdown_duration_bars?: number;
  win_rate_pct: number;
  profit_factor: number;          // >1 is profitable
  total_trades: number;
  avg_trade_duration_bars: number;
  expectancy_usd: number;
  capital_utilization_pct: number;
  avg_win_usd?: number;
  avg_loss_usd?: number;          // negative value
}
```

### `Strategy`
```typescript
interface Strategy {
  name: string;
  description: string;
  ideal_timeframes: string[];              // e.g. ["4h","1d"]
  min_period: string;                      // e.g. "3m"
  market_type: "trending"|"ranging"|"both";
  trade_frequency: "high"|"medium"|"low";
  min_liquidity: "high"|"medium"|"any";
  params: Record<string, unknown>;
  param_grid: Record<string, unknown[]>;
}
```

### `OHLCVCandle`
```typescript
interface OHLCVCandle {
  t: number;  // Unix milliseconds (UTC) — use new Date(t) or toISOString()
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;  // volume in base currency
}
```

### `Trade`
```typescript
interface Trade {
  id: number;
  source: "backtest" | "paper" | "live";
  backtest_job_id?: number;
  type: "buy"|"sell"|"short"|"cover"|"sell_eod"|"cover_eod";
  pair: string;
  strategy?: string;
  price: number;
  qty: number;
  fee: number;
  pnl?: number;      // USDT, positive = profit
  pnl_pct?: number;
  reason?: string;
  duration_bars?: number;
  avg_cost?: number;
  timestamp?: string; // ISO 8601 UTC (from the candle, not wall clock)
  logged_at: string;
}
```

### `WalkForwardResult`
```typescript
interface WalkForwardResult {
  pair: string;
  strategy: string;
  n_segments: number;
  segments: WalkForwardSegment[];
  aggregate: {
    avg_return_pct: number;
    std_return_pct: number;
    consistency_score: number; // 0–1, % of profitable segments
    avg_sharpe: number;
    worst_segment_return: number;
    best_segment_return: number;
    avg_max_drawdown_pct?: number;
  };
}
```

### `MonteCarloResult`
```typescript
interface MonteCarloResult {
  n_runs: number;
  original_return_pct: number;
  mean_return_pct: number;
  median_return_pct: number;
  std_return_pct: number;
  percentile_5_pct: number;
  percentile_95_pct: number;
  max_drawdown_distribution: { mean: number; median: number; percentile_95: number };
  probability_profit: number;    // 0–100 (percentage, not fraction)
  histogram: Array<{ bucket_pct: number; count: number }>;
}
```

---

## Bot

### `POST /api/bot/start` — Start trading

**Request body**
```json
{
  "mode":     "paper",
  "strategy": "stoch_rsi",
  "pairs":    ["BTC/USDT", "ETH/USDT"],
  "restore":  false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"paper"` | `"paper"` or `"live"` |
| `strategy` | string | `"mean_reversion"` | Strategy key |
| `pairs` | string[] | `["BTC/USDT"]` | Trading pairs |
| `restore` | bool | `false` | Resume positions from last saved BotState. Pass `true` after a VPS reboot or manual stop with open positions. |

**Response** `200`
```json
{ "ok": true, "detail": "paper bot started" }
```

---

### `POST /api/bot/stop` — Stop trading

**Response** `200`
```json
{ "ok": true, "detail": "Bot stopped" }
```

---

### `GET /api/bot/status` — Current state

**Response**
```json
{
  "running":        true,
  "crashed":        false,
  "mode":           "paper",
  "strategy":       "stoch_rsi",
  "pairs":          ["BTC/USDT"],
  "started_at":     "2026-04-17T10:00:00+00:00",
  "uptime_seconds": 3600.5,
  "error":          null
}
```

| Field | Description |
|-------|-------------|
| `crashed` | `true` when the watchdog detected an unexpected thread death |
| `uptime_seconds` | `null` when not running |
| `error` | Last exception message if the thread crashed |

---

### `GET /api/bot/history` — BotState snapshots

Query: `limit` (default 20)

Returns raw DB snapshots persisted after every candle.

---

### `GET /api/bot/events` — Audit log

Query: `limit` (default 50)

Returns lifecycle events ordered most-recent first.

```json
[
  {
    "id":          1,
    "event_type":  "start",
    "mode":        "paper",
    "strategy":    "stoch_rsi",
    "pairs":       ["BTC/USDT"],
    "detail":      "restore=False",
    "positions":   {},
    "occurred_at": "2026-04-17T10:00:00+00:00"
  }
]
```

**Event types:** `start` · `stop` · `crash` · `halt` · `resume` · `watchdog`

---

## Error Responses

All errors return `{ "detail": "..." }`:

| Code | Meaning |
|------|---------|
| `400` | Bad request / validation error (unknown strategy, invalid timeframe) |
| `403` | Missing or invalid `X-API-Key` header |
| `404` | Resource not found |
| `409` | Conflict (bot already running, etc.) |
| `500` | Internal server error (backtest crash, `BOT_API_SECRET` not set, etc.) |
| `502` | Exchange connectivity error |
