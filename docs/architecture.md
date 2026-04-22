# Architecture

This document describes the system design, data flows, component contracts, and key decisions in TradingPano.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser / Client                           │
│                   React 18 + TypeScript + Vite                      │
│       pages/  components/  api/client.ts  lib/indicators.ts         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  REST (axios)  +  WebSocket
                               │  X-API-Key header
┌──────────────────────────────▼──────────────────────────────────────┐
│                         FastAPI Server                              │
│                     api/  (port 8000)                               │
│                                                                     │
│  ┌────────────┐  ┌─────────────┐  ┌────────────┐  ┌─────────────┐ │
│  │  routers/  │  │  schemas/   │  │    auth    │  │  ws_manager │ │
│  │ (1 per     │  │ (Pydantic   │  │ (X-API-Key │  │ (broadcast  │ │
│  │ resource)  │  │  contracts) │  │  header)   │  │  to clients)│ │
│  └─────┬──────┘  └─────────────┘  └────────────┘  └─────────────┘ │
│        │                                                            │
│  ┌─────▼──────────────────────────────────────────────────────┐    │
│  │                      bot_manager.py                        │    │
│  │  Start/stop bot thread, track status, broadcast events     │    │
│  └─────┬──────────────────────────────────────────────────────┘    │
│        │                                                            │
│  ┌─────▼──────────────────────────────────────────────────────┐    │
│  │                     SQLite + SQLAlchemy                    │    │
│  │  trades · backtest_jobs · wallet_snapshots ·               │    │
│  │  bot_state · bot_events · strategy_configs                 │    │
│  └────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  Python import (same process)
┌──────────────────────────────▼──────────────────────────────────────┐
│                       crypto_bot/                                   │
│                  Core Trading Engine (pure Python)                  │
│                                                                     │
│  ┌───────────────────┐   ┌──────────────────┐   ┌───────────────┐  │
│  │   strategies/     │   │   backtester/    │   │   engine/     │  │
│  │  22 strategies    │   │  runner          │   │  paper + live │  │
│  │  base.py contract │   │  data_fetcher    │   │               │  │
│  │  Signal enum      │   │  metrics         │   │               │  │
│  │  TradeSignal      │   │  walk_forward    │   │               │  │
│  └─────────┬─────────┘   │  monte_carlo     │   └───────┬───────┘  │
│            │             └──────────────────┘           │          │
│  ┌─────────▼──────────────────────────────────────────────────┐    │
│  │                    risk_manager.py                         │    │
│  │  Leverage · position sizing · daily loss stop · max DD     │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                │                                    │
│  ┌─────────────────────────────▼──────────────────────────────┐    │
│  │           engine/__init__.py  create_engine()             │    │
│  │  exchange=bybit/…  mode=live  → LiveEngine  (ccxt)        │    │
│  │  exchange=bybit/…  mode=paper → PaperEngine (ccxt prices) │    │
│  │  exchange=oanda    mode=live  → OandaEngine (v20 REST)    │    │
│  │  exchange=oanda    mode=paper → OandaPaperEngine          │    │
│  └────────────────────────┬───────────────────┬─────────────┘    │
│                           │                   │                    │
│  ┌────────────────────────▼──┐  ┌─────────────▼───────────────┐   │
│  │  ccxt                     │  │  oandapyV20                 │   │
│  │  Bybit · KuCoin · OKX ·  │  │  OANDA v20 REST API         │   │
│  │  Gate · Kraken · Binance  │  │  Forex · CFD · Commodities  │   │
│  └───────────────────────────┘  └─────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  margin_monitor.py  MarginMonitor (daemon thread, OANDA)    │   │
│  │  Polls get_margin_info() · alerts ≤150% · stops ≤110%       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Request Flow — Backtest

```
Browser                  FastAPI                   crypto_bot
   │                        │                          │
   │  POST /api/backtests   │                          │
   │ ─────────────────────► │                          │
   │                        │  Create BacktestJob row  │
   │                        │  status="pending"        │
   │  201 BacktestJob       │                          │
   │ ◄───────────────────── │                          │
   │                        │                          │
   │                        │  Thread: BacktestRunner  │
   │                        │ ─────────────────────── ►│
   │                        │                          │  DataFetcher.fetch()
   │                        │                          │  (OHLCV from ccxt or cache)
   │                        │                          │  ┌──────────────────────┐
   │                        │                          │  │ Bar-by-bar loop       │
   │                        │                          │  │ strategy.on_candle()  │
   │                        │                          │  │ risk_manager.check()  │
   │                        │                          │  │ log trade to DB       │
   │                        │                          │  └──────────────────────┘
   │                        │                          │  compute_metrics()
   │                        │  Update job: status="done"│
   │                        │ ◄────────────────────────│
   │                        │  write metrics + equity   │
   │  GET /api/backtests/42 │                          │
   │ ─────────────────────► │                          │
   │  200 + metrics         │                          │
   │ ◄───────────────────── │                          │
```

---

## Request Flow — Live Bot

```
Browser             FastAPI/bot_manager          crypto_bot/engine
   │                        │                          │
   │  POST /api/bot/start   │                          │
   │ ─────────────────────► │                          │
   │                        │  Thread: PaperEngine     │
   │                        │ ────────────────────────►│
   │  200 {started}         │                          │  Every N seconds:
   │ ◄───────────────────── │                          │  fetch_ohlcv() → ccxt
   │                        │                          │  strategy.on_candle()
   │                        │                          │  risk_manager.approve()
   │                        │                          │  execute_order() (paper/live)
   │                        │                          │  log trade → DB
   │                        │                          │  snapshot wallet → DB
   │                        │  ws broadcast: trade     │
   │  WS: trade event       │ ◄────────────────────────│
   │ ◄───────────────────── │                          │
```

---

## Component Contracts

### Strategy Contract

Every strategy must satisfy this interface (see [`docs/strategy-development.md`](strategy-development.md)):

```python
class BaseStrategy(ABC):
    # Required class-level metadata
    name: str
    description: str
    market_type: str   # "trending" | "ranging" | "both"
    risk_profile: dict

    @abstractmethod
    def initialize(self, config: dict) -> None: ...

    @abstractmethod
    def on_candle(
        self,
        pair: str,
        candles: pd.DataFrame,   # OHLCV, columns: open high low close volume
        position: Optional[dict],
    ) -> TradeSignal: ...

    @abstractmethod
    def get_params(self) -> dict: ...

    @abstractmethod
    def reset(self) -> None: ...

    # Optional — required for live trading resume
    def save_state(self) -> dict: ...
    def load_state(self, state: dict) -> None: ...
```

**Signal types:** `BUY` · `SELL` · `SHORT` · `COVER` · `STOP_LOSS` · `TIME_EXIT` · `HOLD`

### API Contract

All API endpoints are typed via Pydantic schemas in `api/schemas/`. The TypeScript counterparts live in `frontend/src/api/client.ts`.

When an API response schema changes:
1. Update the Pydantic model
2. Update the TypeScript interface
3. Run `cd frontend && npx tsc --noEmit` — zero errors required

Full API reference: [`docs/api-contracts.md`](api-contracts.md)

---

## Data Models

```
backtest_jobs
  id, strategy, pair, timeframe, period, params
  status (pending → running → done|error)
  metrics (JSON), equity_curve (JSON)
  created_at, started_at, finished_at
      │
      │ 1:M
      ▼
trades
  id, source (paper|live|backtest), backtest_job_id
  type (buy|sell|short|cover), pair, strategy
  price, qty, fee, pnl, pnl_pct
  reason, duration_bars, timestamp

wallet_snapshots
  id, source, balance_usdt, positions_value, total_equity
  positions (JSON), timestamp

bot_state          — persisted position state for resume
  id, mode, strategy, pairs, positions (JSON)
  strategy_state (JSON), is_active, saved_at

bot_events         — immutable audit log
  id, event_type, mode, strategy, pairs, detail
  positions (JSON), occurred_at

strategy_configs   — saved composable configs
  id, name, execution_strategy, execution_timeframe
  trend_filter_strategy, trend_filter_timeframe
  risk_profile (JSON), pairs (JSON), notes
  created_at, updated_at
```

---

## OHLCV Caching

Historical candles are cached to disk to avoid re-fetching from the exchange on every backtest:

```
Cache key: {pair}_{timeframe}_{period}
Cache location: crypto_bot/data/cache/
Cache format: CSV (pandas)

Flow:
  DataFetcher.fetch(pair, tf, period)
    → check cache file exists AND mtime < 1h
    → HIT:  read from CSV
    → MISS: fetch from exchange, write CSV, return
```

Cache TTL: **1 hour**. Manual invalidation: delete files in `crypto_bot/data/cache/`.

---

## Exchange Connectivity

### Crypto (ccxt)

```
ccxt exchange instance
  └── fallback chain:
      1. Exchange from config (EXCHANGE_NAME env var)
      2. bybit (default)
      3. kucoin (fallback for market scanner)

Live/paper mode: uses EXCHANGE_API_KEY + EXCHANGE_API_SECRET
Backtest mode:   uses public endpoints (no auth needed)
Testnet:         enabled by default (config.yaml: testnet: true)
```

### Forex / CFD (OANDA v20)

```
OandaEngine / OandaPaperEngine
  └── oandapyV20 REST client
      Credentials: OANDA_API_KEY + OANDA_ACCOUNT_ID (env vars)
      Environment: OANDA_ENVIRONMENT = "practice" | "live"

Pair convention:  EUR/USD (internal) ↔ EUR_USD (OANDA API)
Order sizing:     USDT amount → integer units via mid price × leverage
Short selling:    negative units (no separate short account needed)
Overnight cost:   tracked via _swap_accrual + accrue_swap()
Margin guard:     MarginMonitor daemon thread (alerts 150%, stops 110%)
```

Full OANDA reference: [`docs/OANDA.md`](OANDA.md)

---

## Frontend Architecture

```
App.tsx
├── Layout (nav, auth gate)
└── Routes
    ├── /               Dashboard.tsx
    ├── /backtests      Backtests.tsx
    ├── /bot            BotControl.tsx
    ├── /trades         Trades.tsx
    ├── /strategies     StrategyEngine.tsx
    ├── /market         Market.tsx
    ├── /wallet         Wallet.tsx
    ├── /portfolio      Portfolio.tsx
    ├── /presets        Presets.tsx
    └── /settings       Settings.tsx

Data layer:
  api/client.ts         All API functions + TypeScript types
  @tanstack/react-query  Async state management
  useBotSocket.ts        WebSocket hook (live status + trades)

UI components (components/ui/):
  Alert · Badge · Button · Card · DataTable · DetailRow
  EmptyState · Input · LoadingState · Modal · PageHeader
  ProgressBar · SectionHeader · Select · Spinner · StatCard
  TabBar · Textarea · Toast · Tooltip

Chart components:
  PriceChart.tsx         OHLCV candles + indicator overlays + oscillator
  EquityCurve.tsx        Equity curve area chart
  lib/indicators.ts      Pure math: EMA, SMA, RSI, MACD, BB, Supertrend, VWAP
  lib/strategyIndicators.ts  Strategy → indicator map (22 strategies)
```

---

## Authentication

Simple shared-secret API key model:

1. Set `BOT_API_SECRET` in `.env`
2. All requests must include `X-API-Key: <value>` header
3. `api/auth.py → require_api_key` dependency validates it via constant-time comparison
4. WebSocket auth uses `?api_key=<value>` query parameter

This is designed for single-user self-hosted deployments. For multi-user, replace `require_api_key` with JWT auth.

---

## Logging Architecture

See [`docs/logging.md`](logging.md) for the full guide.

```
logging.getLogger(__name__)     # All modules use named loggers
    │
    ├── RotatingFileHandler → data/bot.log (10 MB × 5 files)
    └── RichHandler (console)  → colored, with tracebacks

Log level: from LOG_LEVEL env var (default: INFO)
Format:    %(asctime)s [%(levelname)s] %(name)s: %(message)s
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| SQLite as database | Single-user, self-hosted. No external DB service to manage. Alembic handles migrations cleanly. |
| crypto_bot as separate importable package | The core engine can be used without FastAPI — CLI backtesting, unit tests, and the API all import the same code. |
| Strategies as pure Python classes | No framework coupling. Each strategy is isolated, testable with synthetic DataFrames, and hot-swappable. |
| Strategy parameters via YAML + DB | YAML for global defaults; StrategyConfig DB records for per-run overrides. No hardcoded values. |
| Backtest in background thread | Keeps the API responsive. The client polls `GET /backtests/{id}` until status changes. |
| Pydantic v2 schemas as contracts | Single source of truth for request/response shapes. TypeScript interfaces in `client.ts` are manually maintained mirrors — `tsc --noEmit` enforces correctness. |
| ccxt for exchange connectivity | Unified API across 100+ exchanges. Rate limiting, retry, and error handling built-in. |
| React Query for data fetching | Handles caching, background refetch, loading states, and error boundaries without manual useEffect. |
