# TradingPano

> Full-stack algorithmic crypto trading platform — 22 strategies, backtester, live/paper trading, React dashboard.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.5-3178C6.svg)](https://typescriptlang.org)

---

## Table of Contents

- [Overview](#overview)
- [Quick Start (Docker)](#quick-start-docker)
- [Local Development](#local-development)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Available Commands](#available-commands)
- [Documentation](#documentation)
- [Contributing](#contributing)

---

## Overview

TradingPano is a self-hosted trading automation platform built for backtesting and live/paper trading on crypto futures markets.

**What it includes:**

| Layer | Technology | Purpose |
|---|---|---|
| Trading engine | Python 3.11 + pandas | 22 strategies, backtester, risk manager |
| API server | FastAPI + SQLAlchemy | REST API + WebSocket, auth, DB persistence |
| Dashboard | React 18 + Recharts | Strategy picker, charts, bot control |
| Database | SQLite + Alembic | Trades, backtest jobs, wallet snapshots |
| Infra | Docker + Caddy | Containerized, TLS-ready |

**Supported exchanges** (via [ccxt](https://github.com/ccxt/ccxt)): Bybit · KuCoin · OKX · Gate · Kraken · Binance

---

## Quick Start (Docker)

**Prerequisites:** Docker ≥ 24, Docker Compose V2, `git`

```bash
# 1. Clone
git clone git@github.com:monotributistar/tradingPano.git
cd tradingPano

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set BOT_API_SECRET
# Generate one: openssl rand -hex 32

# 3. Start
make docker-up

# 4. Open dashboard
open http://localhost
```

The stack starts two containers:
- **api** → `http://localhost:8000` — FastAPI + trading engine
- **frontend** → `http://localhost` — React dashboard

Log in with the `BOT_API_SECRET` value from your `.env`.

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20+
- `make`

### Setup

```bash
# Install all dependencies
make install

# Copy and configure env
cp .env.example .env

# Apply database migrations
make db-upgrade

# Start API (port 8000) + frontend (port 5173) in parallel
make dev
```

The frontend Vite proxy forwards `/api/*` to `http://localhost:8000` — no CORS setup needed.

### Development with Docker (hot-reload)

```bash
make docker-dev-up
# API:      http://localhost:8000
# Frontend: http://localhost:5173
```

Source files are bind-mounted; saving any Python or TypeScript file reloads automatically.

---

## Project Structure

```
tradingPano/
├── api/                    # FastAPI server
│   ├── main.py             # App factory + strategy registry
│   ├── routers/            # One router per resource domain
│   ├── schemas/            # Pydantic request/response models (contracts)
│   ├── db/                 # SQLAlchemy ORM models + session factory
│   └── adapters/           # Exchange connectivity layer
│
├── crypto_bot/             # Core trading engine (pure Python, importable)
│   ├── strategies/         # 22 strategy implementations
│   ├── backtester/         # Bar-by-bar simulation + walk-forward + Monte Carlo
│   ├── engine/             # Live + paper execution loops
│   ├── risk_manager.py     # Position sizing, leverage, circuit breakers
│   └── config.yaml         # All strategy params + risk rules
│
├── frontend/               # React 18 + TypeScript + Vite
│   └── src/
│       ├── api/client.ts   # Axios client + all TypeScript interfaces
│       ├── pages/          # Route-level page components
│       ├── components/     # Reusable UI components
│       └── lib/            # Indicator math, formatters, strategy map
│
├── tests/                  # Pytest integration tests
│   ├── conftest.py         # Shared fixtures (TestClient, auth headers, in-memory DB)
│   └── api/                # API-level tests (one file per router)
│
├── alembic/                # Database migration scripts
├── docs/                   # Full project documentation
├── e2e/                    # Playwright end-to-end tests
├── docker-compose.yml      # Production stack
├── docker-compose.dev.yml  # Dev stack (hot-reload, bind mounts)
├── Makefile                # All build / dev / test / deploy targets
└── .env.example            # Environment variable reference
```

Full architecture details: [`docs/architecture.md`](docs/architecture.md)

---

## Environment Variables

Copy `.env.example` → `.env` and fill in:

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_API_SECRET` | ✅ | — | Shared key for `X-API-Key` header |
| `EXCHANGE_NAME` | ✅ | `bybit` | `bybit` · `kucoin` · `okx` · `gate` · `kraken` · `binance` |
| `EXCHANGE_API_KEY` | Live only | — | Exchange API key |
| `EXCHANGE_API_SECRET` | Live only | — | Exchange API secret |
| `EXCHANGE_PASSPHRASE` | KuCoin | — | KuCoin passphrase |
| `LOG_LEVEL` | ❌ | `INFO` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `API_PORT` | ❌ | `8000` | API listen port |
| `FRONTEND_PORT` | ❌ | `80` | Frontend port (`5173` in dev) |
| `TELEGRAM_BOT_TOKEN` | ❌ | — | Telegram notifications |
| `TELEGRAM_CHAT_ID` | ❌ | — | Telegram chat target |

Generate a secure API key:
```bash
openssl rand -hex 32
```

---

## Available Commands

```bash
# ── Development ──────────────────────────────────────────────────────────────
make install             # Install all Python + Node dependencies
make dev                 # Start API + frontend in parallel (no Docker)
make api                 # API only  — http://localhost:8000
make frontend            # Frontend only — http://localhost:5173
make build               # Production frontend build

# ── Testing ──────────────────────────────────────────────────────────────────
make test                # Full test suite
make test-unit           # Strategy unit tests only
make test-api            # API integration tests only
make test-cov            # Tests + HTML coverage report

# ── Database ─────────────────────────────────────────────────────────────────
make db-upgrade          # Apply pending Alembic migrations
make db-downgrade        # Roll back last migration
make db-revision msg="describe change"   # Generate new migration

# ── Docker (production) ──────────────────────────────────────────────────────
make docker-up           # Start production stack (detached)
make docker-down         # Stop stack
make docker-logs svc=api # Tail container logs
make docker-shell-api    # Shell inside API container

# ── Docker (development, hot-reload) ─────────────────────────────────────────
make docker-dev-up
make docker-dev-logs svc=api
make docker-dev-shell-api
```

---

## Documentation

| Document | Description |
|---|---|
| [`docs/getting-started.md`](docs/getting-started.md) | Detailed setup: local, Docker, VPS |
| [`docs/architecture.md`](docs/architecture.md) | System design, data flows, component contracts |
| [`docs/api-contracts.md`](docs/api-contracts.md) | Full API reference — every endpoint + schema |
| [`docs/testing.md`](docs/testing.md) | TDD guide — patterns, fixtures, coverage requirements |
| [`docs/logging.md`](docs/logging.md) | Logging standards, levels, structured format |
| [`docs/strategy-development.md`](docs/strategy-development.md) | How to implement and register a new strategy |
| [`docs/strategies.md`](docs/strategies.md) | Strategy catalog with metadata and selection guide |
| [`docs/docker.md`](docs/docker.md) | Docker setup and configuration reference |
| [`docs/vps-deploy.md`](docs/vps-deploy.md) | VPS deployment with TLS via Caddy |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branching model, PR process, code standards |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide.

Short version:
1. Branch from `main` — `feature/your-thing` or `fix/your-bug`
2. **Write the test first**, then implement (see [`docs/testing.md`](docs/testing.md))
3. Follow logging standards (see [`docs/logging.md`](docs/logging.md))
4. Open a PR with description + test evidence

---

## License

MIT
