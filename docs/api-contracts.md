# API Contracts

> Interactive docs: **http://localhost:8000/docs** (Swagger UI)  
> Alternative: **http://localhost:8000/redoc** (ReDoc)

**Base URL:** `http://localhost:8000` (development) · `https://yourdomain.com` (production)  
**API prefix:** all endpoints under `/api/`  
**Version:** 3.0.0

---

## Authentication

All endpoints except `/api/health` and `/api/auth/login` require:

```http
X-API-Key: <BOT_API_SECRET>
```

Missing or wrong key → `403 Forbidden`:
```json
{"detail": "Not authenticated"}
```

---

## Common Error Shapes

```json
// 404
{"detail": "Backtest 42 not found"}

// 422 Validation error
{
  "detail": [{"loc": ["body", "strategy"], "msg": "field required", "type": "value_error.missing"}]
}

// 409 Conflict
{"detail": "Bot is already running"}
```

---

## Health

### `GET /api/health` — public

```json
{"status": "ok", "version": "3.0.0"}
```

---

## Auth

### `POST /api/auth/login` — public

**Body:** `{"api_key": "your-key"}`  
**200:** `{"authenticated": true}`  
**403:** `{"detail": "Invalid API key"}`

---

## Strategies

### `GET /api/strategies`

Returns the full 22-strategy catalog.

**200:**
```json
[
  {
    "name": "ema_crossover",
    "description": "Golden/death cross momentum strategy",
    "ideal_timeframes": ["1h", "4h", "1d"],
    "min_period": "2m",
    "market_type": "trending",
    "trade_frequency": "medium",
    "min_liquidity": "any",
    "suitable_timeframes": ["1h", "4h"],
    "suitable_market_conditions": ["trending"],
    "recommended_leverage": 2.0,
    "max_leverage": 8.0,
    "risk_profile": {
      "stop_loss_pct": 2.0,
      "take_profit_pct": 5.0,
      "position_size_pct": 5.0
    },
    "params": {"fast_ema": 9, "slow_ema": 21},
    "param_grid": {"fast_ema": [5, 9, 12], "slow_ema": [21, 26, 50]}
  }
]
```

---

## Backtests

### `POST /api/backtests`

Submit a backtest job (async, runs in background thread).

**Body:**
```json
{
  "strategy":  "ema_crossover",
  "pair":      "BTC/USDT",
  "timeframe": "1h",
  "period":    "3m",
  "params":    {}
}
```

| Field | Type | Required | Values |
|---|---|---|---|
| `strategy` | string | ✅ | Any registered strategy name |
| `pair` | string | ✅ | e.g. `"BTC/USDT"` |
| `timeframe` | string | ✅ | `1m` `5m` `15m` `30m` `1h` `2h` `4h` `6h` `12h` `1d` `1w` |
| `period` | string | ✅ | `1w` `2w` `1m` `2m` `3m` `6m` `9m` `1y` `18m` `2y` `3y` `4y` `5y` |
| `params` | object | ❌ | Strategy parameter overrides |

**201 — BacktestJob:**
```json
{
  "id": 42,
  "strategy": "ema_crossover",
  "pair": "BTC/USDT",
  "timeframe": "1h",
  "period": "3m",
  "status": "pending",
  "metrics": null,
  "equity_curve": null,
  "created_at": "2026-04-21T14:00:00Z"
}
```

`status` progression: `pending` → `running` → `done` | `error`

---

### `GET /api/backtests`

**Query:** `strategy` · `pair` · `limit` (default 50)

**200:** Array of BacktestJob (includes `metrics` when `status=done`).

---

### `GET /api/backtests/{id}`

**200:**
```json
{
  "id": 42,
  "status": "done",
  "metrics": {
    "total_trades": 48,
    "win_rate_pct": 58.3,
    "total_return_pct": 12.4,
    "sharpe_ratio": 1.82,
    "sortino_ratio": 2.14,
    "max_drawdown_pct": 6.3,
    "profit_factor": 1.74,
    "avg_trade_pnl": 0.043,
    "avg_win": 0.12,
    "avg_loss": -0.06,
    "best_trade": 0.41,
    "worst_trade": -0.18,
    "avg_holding_bars": 8.2
  },
  "equity_curve": [20.0, 20.15, 19.87],
  "equity_timestamps": ["2026-01-01T00:00:00Z"]
}
```

**404:** Job not found.

---

### `DELETE /api/backtests/{id}` → `204`

---

### `POST /api/backtests/{id}/walk-forward`

**Query:** `n_segments` (default 5) · `period` (default `"1y"`)

**200:**
```json
{
  "segments": [
    {
      "train_start": "2025-01-01",
      "train_end":   "2025-07-01",
      "test_start":  "2025-07-01",
      "test_end":    "2025-10-01",
      "train_return_pct": 18.4,
      "test_return_pct":   7.2,
      "test_sharpe": 1.4
    }
  ],
  "avg_test_return_pct": 7.2,
  "consistency_pct": 80.0
}
```

---

### `POST /api/backtests/{id}/monte-carlo`

**Query:** `n_runs` (default 500) · `seed` (default 42)

**200:**
```json
{
  "original_return_pct": 12.4,
  "mean_return_pct":     10.8,
  "median_return_pct":   11.1,
  "std_return_pct":       3.2,
  "percentile_5_pct":     4.5,
  "percentile_95_pct":   17.2,
  "probability_profit":  78.0,
  "histogram": [{"bucket_pct": -5.0, "count": 3}]
}
```

---

## Trades

### `GET /api/trades`

**Query:** `pair` · `strategy` · `source` (`paper`|`live`|`backtest`) · `type` (`buy`|`sell`|`short`|`cover`) · `backtest_job_id` · `limit` (default 200)

**200:**
```json
[
  {
    "id": 1,
    "source": "paper",
    "type": "buy",
    "pair": "BTC/USDT",
    "strategy": "ema_crossover",
    "price": 42156.78,
    "qty": 0.000237,
    "fee": 0.004,
    "pnl": null,
    "pnl_pct": null,
    "reason": "golden cross",
    "duration_bars": null,
    "timestamp": "2026-04-21T14:32:00Z"
  }
]
```

---

### `GET /api/trades/stats`

**Query:** `source` · `strategy`

**200:**
```json
{
  "total_trades": 48,
  "wins": 28,
  "losses": 20,
  "win_rate_pct": 58.3,
  "total_pnl": 2.14,
  "avg_pnl": 0.044,
  "profit_factor": 1.74
}
```

---

## Bot Control

### `POST /api/bot/start`

**Body:**
```json
{
  "mode":               "paper",
  "strategy":           "ema_crossover",
  "pairs":              ["BTC/USDT"],
  "restore":            false,
  "strategy_config_id": null
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `mode` | string | `"paper"` | `"paper"` or `"live"` |
| `strategy` | string | `"mean_reversion"` | Registered strategy name |
| `pairs` | string[] | `["BTC/USDT"]` | Trading pairs |
| `restore` | boolean | `false` | Resume from saved DB state |
| `strategy_config_id` | int\|null | `null` | Override all from a saved StrategyConfig |

**200:** `{"status": "started", "mode": "paper", "strategy": "ema_crossover"}`  
**409:** Bot already running.  
**404:** Strategy or config not found.

---

### `POST /api/bot/stop` → `{"status": "stopping"}`

---

### `GET /api/bot/status`

**200:**
```json
{
  "running": true,
  "mode": "paper",
  "strategy": "ema_crossover",
  "pairs": ["BTC/USDT"],
  "uptime_seconds": 3600,
  "equity_usdt": 21.45,
  "positions": {
    "BTC/USDT": {"side": "long", "qty": 0.0005, "avg_cost": 42100.0}
  },
  "last_signal": "BUY",
  "last_signal_at": "2026-04-21T14:00:00Z",
  "ws_connected": true,
  "strategy_config_id": null,
  "strategy_config_name": null
}
```

---

### `GET /api/bot/history` — Query: `limit` (default 20)
Array of status snapshots.

### `GET /api/bot/events`

```json
[{
  "id": 1,
  "event_type": "start",
  "mode": "paper",
  "strategy": "ema_crossover",
  "pairs": ["BTC/USDT"],
  "detail": null,
  "occurred_at": "2026-04-21T10:00:00Z"
}]
```

`event_type`: `start` · `stop` · `crash` · `halt` · `resume` · `watchdog`

---

## Wallet

### `GET /api/wallet/history` — Query: `source` · `limit`

```json
[{
  "id": 1,
  "source": "paper",
  "balance_usdt": 19.5,
  "positions_value": 2.1,
  "total_equity": 21.6,
  "positions": {"BTC/USDT": {"qty": 0.0005, "avg_cost": 42000.0}},
  "timestamp": "2026-04-21T14:00:00Z"
}]
```

### `GET /api/wallet/summary` — Most recent wallet snapshot.

---

## Provider

### `GET /api/provider/ohlcv/{pair}`

**Path:** `pair` — URL-encoded, e.g. `BTC%2FUSDT`  
**Query:** `timeframe` (default `"1h"`) · `period` (default `"3m"`)

**200:**
```json
[{"t": 1745234400000, "o": 42100.0, "h": 42350.0, "l": 41900.0, "c": 42200.0, "v": 143.5}]
```

`t` = Unix millisecond timestamp (UTC).

### `PATCH /api/provider/config`
Update exchange credentials at runtime.

---

## Market Scanner

### `GET /api/market/scanner`

**Query:** `pairs` (comma-separated) · `timeframe` · `period`

**200:**
```json
[{
  "pair": "BTC/USDT",
  "price": 42200.0,
  "change_1h_pct": 0.4,
  "change_24h_pct": 2.8,
  "atr_pct": 1.8,
  "adx": 28.4,
  "rsi": 56.2,
  "volume_24h_usd": 1420000.0,
  "trend": "bullish",
  "regime": "trending",
  "suggested_strategies": [
    {"name": "trend_following", "reason": "ADX > 25, uptrend confirmed"}
  ]
}]
```

### `GET /api/market/summary` — High-level market overview.

---

## Strategy Configs

Saved composable configurations (execution strategy + HTF filter + risk overrides + pairs).

### `GET /api/strategy-configs`

**200:**
```json
[{
  "id": 1,
  "name": "BTC Trend Follower",
  "execution_strategy": "ema_crossover",
  "execution_timeframe": "1h",
  "trend_filter_strategy": "trend_following",
  "trend_filter_timeframe": "4h",
  "risk_profile": {
    "stop_loss_pct": 2.0,
    "take_profit_pct": 5.0,
    "position_size_pct": 5.0,
    "leverage": 3.0,
    "max_drawdown_pct": 8.0,
    "daily_loss_stop_pct": 3.0
  },
  "pairs": ["BTC/USDT"],
  "notes": "Conservative BTC trend config",
  "created_at": "2026-04-01T00:00:00Z"
}]
```

### `POST /api/strategy-configs` → `201` — Body: same schema minus `id`, `created_at`.

### `GET /api/strategy-configs/{id}` → `200` single config | `404`

### `PUT /api/strategy-configs/{id}` → `200` full replace

### `DELETE /api/strategy-configs/{id}` → `204`

### `POST /api/strategy-configs/{id}/activate`

Writes config to `config.yaml` as the active strategy.

**200:** `{"activated": true, "strategy": "ema_crossover", "timeframe": "1h"}`

---

## System Metrics

### `GET /api/system/metrics`

```json
{
  "cpu_pct": 12.4,
  "ram_pct": 48.2,
  "ram_used_mb": 386,
  "disk_pct": 23.1,
  "disk_used_gb": 4.6,
  "process_uptime_s": 86400,
  "python_version": "3.11.9"
}
```

---

## Config Editor

### `GET /api/config/settings` — Editable config (secrets stripped)

### `PATCH /api/config/risk`
```json
{"leverage": 3.0, "max_drawdown_pct": 8.0, "daily_loss_stop_pct": 3.0}
```

### `PATCH /api/config/bot`
```json
{"strategy": "pullback", "pairs": ["BTC/USDT", "ETH/USDT"], "timeframe": "4h"}
```

---

## Portfolio

### `GET /api/portfolio/status` — Aggregate + per-slot breakdown.
### `POST /api/portfolio/start` → `200`
### `POST /api/portfolio/stop` → `200`

---

## WebSocket

### `WS /api/ws/bot`

```
ws://localhost:8000/api/ws/bot?api_key=<BOT_API_SECRET>
```

**Message envelope:**
```json
{"type": "status|trade|equity|event|ping", "data": {...}}
```

| Type | Payload | Cadence |
|---|---|---|
| `status` | Full BotStatus | Every 30s + on change |
| `trade` | Trade object | On each trade |
| `equity` | `{"equity_usdt": 21.5, "ts": "..."}` | Every 5 min |
| `event` | BotEvent | On lifecycle change |
| `ping` | `{"ts": "..."}` | Every 30s (keepalive) |

Reconnect with exponential backoff on disconnect.

---

## Default Limits

| Endpoint | Default | Max |
|---|---|---|
| `GET /api/backtests` | 50 | 200 |
| `GET /api/trades` | 200 | 1000 |
| `GET /api/bot/history` | 20 | 100 |
| `GET /api/wallet/history` | 100 | 500 |
