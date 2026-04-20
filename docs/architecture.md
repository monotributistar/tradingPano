# Architecture

## Stack

```
trading-claude/
├── frontend/               React 18 + TypeScript + Vite (port 5173)
│   └── src/
│       ├── api/client.ts   Axios client + all TypeScript interfaces (contracts)
│       ├── pages/          Route-level components (Backtests, Dashboard, etc.)
│       └── components/     Reusable UI (MetricsCard, PriceChart, ValidationPanel…)
│
├── api/                    FastAPI (Python 3.11, port 8000)
│   ├── main.py             App factory, strategy registry, config loader
│   ├── routers/            One file per resource domain
│   │   ├── backtests.py    Job lifecycle + walk-forward + Monte Carlo
│   │   ├── strategies.py   Strategy catalog with metadata
│   │   ├── trades.py       Trade history
│   │   ├── provider.py     Exchange connectivity + OHLCV
│   │   ├── presets.py      Investment profiles
│   │   ├── bot.py          Live/paper engine control
│   │   └── wallet.py       Portfolio snapshots
│   ├── schemas/            Pydantic request/response models (contracts)
│   │   ├── backtest.py     BacktestCreate, BacktestMetrics, BacktestJobResponse
│   │   ├── bot.py
│   │   └── trade.py
│   └── db/
│       ├── models.py       SQLAlchemy ORM models
│       └── engine.py       SQLite engine + session factory
│
├── crypto_bot/             Core trading engine
│   ├── strategies/         19 strategy implementations (all extend BaseStrategy)
│   │   ├── base.py         Abstract base + metadata contract
│   │   └── *.py            Individual strategies
│   ├── backtester/
│   │   ├── runner.py       Bar-by-bar simulation engine
│   │   ├── data_fetcher.py OHLCV downloader with ccxt + disk cache
│   │   ├── metrics.py      Performance metric calculations
│   │   ├── walk_forward.py Out-of-sample validation
│   │   └── monte_carlo.py  Trade-shuffle simulation
│   ├── engine/             Live and paper trading engines
│   └── risk_manager.py     Position sizing, daily loss stop
│
└── docs/                   This documentation
    ├── api-contracts.md    All endpoint contracts + TypeScript types
    ├── architecture.md     This file
    └── strategies.md       Strategy catalog with metadata table
```

---

## Request Flow — Backtest

```
Browser
  │
  ├─ POST /api/backtests { strategy, pair, period, timeframe }
  │     │
  │     ├─ FastAPI validates BacktestCreate (Pydantic)
  │     │   ├─ strategy exists in registry?
  │     │   └─ timeframe in SUPPORTED_TIMEFRAMES?
  │     │
  │     ├─ INSERT backtest_jobs (status=pending)
  │     └─ BackgroundTask: _run_backtest_worker(job_id, ...)
  │           │
  │           ├─ UPDATE status=running
  │           ├─ DataFetcher.fetch(pair, timeframe, period)   [disk cache]
  │           │   └─ ccxt.fetch_ohlcv() with exchange fallback
  │           ├─ BacktestRunner.run(strategy, candles)
  │           │   └─ bar-by-bar: strategy.on_candle() → Signal → execute trade
  │           ├─ compute_metrics(equity_curve, trades)
  │           ├─ INSERT trades (all round-trips)
  │           └─ UPDATE status=done, metrics, equity_curve, equity_timestamps
  │
  ├─ GET /api/backtests/{id}   (poll until status=done)
  ├─ GET /api/provider/ohlcv/{pair}?timeframe=4h&period=6m   (price chart)
  └─ GET /api/trades?backtest_job_id={id}                     (trade markers)
```

---

## Request Flow — Walk-Forward Validation

```
POST /api/backtests/{id}/walk-forward?n_segments=5
  │
  ├─ Load job from DB (strategy, pair, period)
  ├─ DataFetcher.fetch(pair, timeframe, period)
  ├─ Split into N equal slices (last 20% of each = OOS)
  └─ For each slice: BacktestRunner.run() → segment metrics
      └─ Aggregate: avg_return, std, consistency_score, avg_sharpe
```

---

## Strategy Contract

Every strategy implements `BaseStrategy`:

```python
class MyStrategy(BaseStrategy):
    name = "my_strategy"
    description = "One-line description"

    # ── Metadata (used by UI + recommendation engine) ──────────────────
    ideal_timeframes = ["1h", "4h"]
    min_period = "1m"
    market_type = "trending"      # "trending" | "ranging" | "both"
    trade_frequency = "medium"    # "high" (scalping) | "medium" | "low"
    min_liquidity = "any"         # "high" | "medium" | "any"

    # ── Required methods ───────────────────────────────────────────────
    def initialize(self, config: dict) -> None:
        """Load params from config.yaml strategy section."""

    def on_candle(self, pair, candles: pd.DataFrame, position) -> TradeSignal:
        """Return signal for this bar."""

    def get_params(self) -> dict:
        """Return current param values for logging."""

    # ── Optional ───────────────────────────────────────────────────────
    def get_param_grid(self) -> dict:
        """Search space for optimizer, e.g. {"rsi_period": [7, 14, 21]}"""

    def reset(self) -> None:
        """Reset state between backtest runs."""
```

---

## Database Schema

| Table | Key Columns |
|-------|-------------|
| `backtest_jobs` | id, strategy, pair, period, **timeframe**, status, metrics (JSON), equity_curve (JSON), params (JSON) |
| `trades` | id, backtest_job_id (FK), type, pair, price, qty, fee, pnl, pnl_pct, timestamp |
| `wallet_snapshots` | id, source, balance_usdt, positions_value, total_equity, positions (JSON), timestamp |
| `bot_state` | id, mode, strategy, pairs (JSON), positions (JSON), is_active |

---

## OHLCV Caching

`DataFetcher` caches downloaded candles to `data/cache/{pair}_{tf}_{period}.csv`.

| Period | Cache TTL |
|--------|-----------|
| ≤ 3m | 1 hour |
| > 3m | 6 hours |

To bypass: `fetcher.fetch(pair, tf, period, force=True)` (not exposed in the API currently).

---

## Exchange Fallback Chain

When a timeframe or pair is not available on the configured exchange:

```
Configured exchange (default: kucoin)
  → okx
  → gate
  → kraken
```

Exchanges are tried in order; first success wins.

---

## Frontend Architecture

```
src/
├── api/client.ts       Single source of truth for all TypeScript types + API calls
├── pages/
│   ├── Dashboard.tsx   Recent backtests overview, trade feed
│   ├── Backtests.tsx   Submit form + job list sidebar + detail panel
│   ├── Trades.tsx      Live trade table
│   ├── Bot.tsx         Engine start/stop
│   ├── Settings.tsx    Exchange config
│   ├── Wallet.tsx      Portfolio tracker
│   └── Presets.tsx     Investment profiles
└── components/
    ├── MetricsCard.tsx     10-stat performance grid
    ├── EquityCurve.tsx     Recharts line chart with drawdown shading
    ├── PriceChart.tsx      OHLCV line + trade markers (triangles)
    ├── TradeTable.tsx      Sortable trade list
    └── ValidationPanel.tsx Walk-forward + Monte Carlo controls + charts
```

Data fetching uses **TanStack Query** with auto-refetch (3s for job list, 2s for in-progress jobs).
