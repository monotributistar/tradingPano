# CLAUDE.md — TradingPano Claude Code Instructions

This file gives Claude Code context-specific instructions for working on TradingPano.

---

## Project Overview

TradingPano is a full-stack self-hosted algorithmic crypto trading platform:

- **`crypto_bot/`** — Pure Python trading engine: 22 strategies, backtester, paper/live engine, risk manager
- **`api/`** — FastAPI server (port 8000): REST + WebSocket, SQLite persistence via SQLAlchemy + Alembic
- **`frontend/`** — React 18 + TypeScript + Vite (port 5173): dashboard, charts, bot control
- **`tests/`** — API integration tests (pytest + FastAPI TestClient + in-memory SQLite)
- **`crypto_bot/tests/`** — Strategy unit tests (pure Python, no I/O)
- **`e2e/`** — Playwright end-to-end tests

---

## Build and Run Commands

```bash
# Install all dependencies
make install

# Start API + frontend in parallel (no Docker)
make dev
# API: http://localhost:8000
# Frontend: http://localhost:5173

# API only
make api

# Frontend only
make frontend

# Production frontend build
make build

# Docker (production)
make docker-up
make docker-down
make docker-logs svc=api

# Docker (dev, hot-reload)
make docker-dev-up
make docker-dev-logs svc=api
```

---

## Test Commands

```bash
# Full test suite (unit + API integration)
make test
# equivalent: python3 -m pytest crypto_bot/tests/ tests/ -v

# Strategy unit tests only (fast, no network, no DB)
make test-unit
# equivalent: python3 -m pytest crypto_bot/tests/ -v -m "not slow"

# API integration tests only
make test-api
# equivalent: python3 -m pytest tests/api/ -v -m api

# With HTML coverage report → htmlcov/index.html
make test-cov

# TypeScript type check — must be 0 errors before any PR
cd frontend && npx tsc --noEmit

# Single test file
python3 -m pytest tests/api/test_bot_endpoints.py -v

# Single test function
python3 -m pytest tests/api/test_bot_endpoints.py::TestBotStatus::test_returns_stopped_when_idle -v
```

**Test markers in `pytest.ini`:**
- `unit` — pure unit tests (no I/O, no DB, no network)
- `api` — FastAPI integration tests using TestClient + in-memory SQLite
- `slow` — tests that take > 5 seconds

---

## Database Commands

```bash
make db-upgrade                             # Apply pending Alembic migrations
make db-downgrade                           # Roll back last migration
make db-revision msg="add column foo"       # Generate new migration
make db-history                             # Show migration history
make db-current                             # Show current revision
```

---

## Code Quality Commands

```bash
# Format Python (run before committing)
black api/ crypto_bot/ --line-length 100

# Lint Python (auto-fix)
ruff check api/ crypto_bot/ --fix

# Format + lint TypeScript
cd frontend && npm run format && npm run lint

# Type check TypeScript (must be 0 errors)
cd frontend && npx tsc --noEmit
```

---

## Architecture Notes

### Key architectural rules

1. **`crypto_bot/` has no dependency on FastAPI or SQLAlchemy.** It can be unit-tested
   with synthetic DataFrames and imported by the API, CLI, or tests without modification.

2. **All 22 strategies follow the same interface:** `BaseStrategy` in
   `crypto_bot/strategies/base.py`. The core methods are `initialize(config)`,
   `on_candle(pair, candles, position) → TradeSignal`, `get_params()`, `reset()`.

3. **Single source of API contract truth:** Pydantic v2 schemas in `api/schemas/`.
   TypeScript interfaces in `frontend/src/api/client.ts` are manually maintained mirrors.
   `npx tsc --noEmit` enforces correctness.

4. **Testnet is enabled by default** in `crypto_bot/config.yaml` (`testnet: true`).
   Must be explicitly set to `false` for live trading.

5. **All auth uses `X-API-Key: <BOT_API_SECRET>` header** (or `?api_key=` for WebSocket).
   Set `BOT_API_SECRET` in `.env`. Never hardcode it.

6. **Bot lifecycle events are an immutable audit log** (`bot_events` table). Never
   delete or update these rows.

### File locations for common changes

| Task | File(s) to change |
|---|---|
| Add a new strategy | `crypto_bot/strategies/<name>.py`, `api/main.py`, `crypto_bot/config.yaml`, `frontend/src/lib/strategyIndicators.ts` |
| Add an API endpoint | `api/schemas/<resource>.py`, `api/routers/<resource>.py`, `api/main.py`, `frontend/src/api/client.ts` |
| Change a DB schema | `api/db/models/<model>.py`, then `make db-revision msg="..."` |
| Change an API response shape | `api/schemas/<resource>.py` + `frontend/src/api/client.ts` + `docs/CONTRACTS.md` |
| Add a frontend indicator | `frontend/src/lib/strategyIndicators.ts` + `frontend/src/lib/indicators.ts` |
| Change risk defaults | `crypto_bot/config.yaml` under `risk:` |
| Change log level | `.env` → `LOG_LEVEL=DEBUG` |

### Logging

```python
# Always use named module logger — never root logger
import logging
logger = logging.getLogger(__name__)

# Log file: data/bot.log (RotatingFileHandler, 10 MB × 5 files)
# Format:   2026-04-21T14:32:07 [INFO] api.routers.bot: bot.start mode=paper strategy=ema_crossover
# Levels:   DEBUG (hot paths) | INFO (milestones) | WARNING (degraded) | ERROR (failures)
```

See `docs/LOGGING.md` for the full logging guide.

### Strategy signal flow

```
BacktestRunner / PaperEngine / LiveEngine
  → strategy.on_candle(pair, candles, position)
  → TradeSignal(signal, pair, price, amount_usd, reason, metadata)
  → risk_manager.approve(signal, position, equity)
  → execute_order() / simulate_fill()
  → write trade to DB
  → write wallet snapshot to DB
  → ws.broadcast(trade event)
```

### OHLCV caching

Historical data is cached to `crypto_bot/data/cache/` as CSV (1 hour TTL).
To invalidate: `rm crypto_bot/data/cache/*.csv.gz`

---

## Documentation Map

| Document | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Full ASCII component diagrams + data flows |
| `docs/CONTRACTS.md` | All type contracts: TradeSignal, BaseStrategy, API schemas, TypeScript interfaces |
| `docs/CONTRIBUTING.md` | Step-by-step: add strategy, add endpoint, PR process, code standards |
| `docs/TESTING.md` | TDD guide: strategy unit tests, API integration tests, fixtures reference |
| `docs/LOGGING.md` | Log levels, structured field names, log format, viewing commands |
| `docs/strategy-development.md` | Full strategy implementation template with code |
| `docs/api-contracts.md` | Every API endpoint with request/response JSON examples |
| `docs/strategies.md` | Strategy catalog with metadata and selection guide |
| `docs/getting-started.md` | Local, Docker, and VPS setup |
| `docs/OANDA.md` | OANDA CFD adapter: setup, engine API, MarginMonitor, swap cost, troubleshooting |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_API_SECRET` | Yes | — | Shared key for `X-API-Key` header |
| `EXCHANGE_NAME` | Yes | `bybit` | `bybit` · `kucoin` · `okx` · `gate` · `kraken` · `binance` |
| `EXCHANGE_API_KEY` | Live only | — | Exchange API key |
| `EXCHANGE_API_SECRET` | Live only | — | Exchange API secret |
| `EXCHANGE_PASSPHRASE` | KuCoin only | — | KuCoin passphrase |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `API_PORT` | No | `8000` | API listen port |
| `FRONTEND_PORT` | No | `80` (prod) / `5173` (dev) | Frontend port |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram notifications |
| `TELEGRAM_CHAT_ID` | No | — | Telegram chat target |
| `BOT_CONFIG_PATH` | No | `crypto_bot/config.yaml` | Override config file path |

Generate a secure API key: `openssl rand -hex 32`

---

## Common Gotchas

- **Never call `strategy.on_candle()` before `strategy.initialize(config)`.**
  The backtester calls `initialize()` once then `reset()` before each run.

- **`candles` DataFrame uses RangeIndex, not DatetimeIndex.**
  Always access the current bar with `candles["close"].iloc[-1]`, never `.loc[timestamp]`.

- **`position` is `None` when flat** — always check before accessing position fields.

- **`amount_usd` should be `0` for all exit signals** (SELL, COVER, STOP_LOSS, TIME_EXIT).
  The engine uses the open position's `qty` to size the exit order.

- **The registry key must exactly match `strategy.name`.**
  Mismatch causes a `KeyError` at bot start or backtest submission.

- **Alembic migrations must be created and committed with any DB schema change.**
  The API calls `init_db()` on startup which applies pending migrations automatically.

- **`testnet: true` in config.yaml is the safety default.**
  Live orders require `testnet: false` — do not change this without explicit intent.
