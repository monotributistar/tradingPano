# Getting Started

This guide walks through every setup path: local development, Docker development (hot-reload), and production deployment.

---

## Prerequisites

| Tool | Minimum version | Check |
|---|---|---|
| Python | 3.11 | `python3 --version` |
| Node.js | 20 | `node --version` |
| Docker | 24 | `docker --version` |
| Docker Compose | v2 | `docker compose version` |
| make | any | `make --version` |
| git | any | `git --version` |

---

## 1. Clone & Configure

```bash
git clone git@github.com:monotributistar/tradingPano.git
cd tradingPano

cp .env.example .env
```

Open `.env` and set the required variables:

```dotenv
# Minimum required:
BOT_API_SECRET=<run: openssl rand -hex 32>
EXCHANGE_NAME=bybit          # or kucoin, okx, gate, kraken, binance

# Only needed for live trading:
EXCHANGE_API_KEY=
EXCHANGE_API_SECRET=
EXCHANGE_PASSPHRASE=         # KuCoin only

# Optional:
LOG_LEVEL=INFO               # DEBUG for development
```

> **Never commit `.env`** — it is in `.gitignore` by design. Only `.env.example` is tracked.

---

## 2. Local Development (no Docker)

Best for active development — fastest feedback loop.

```bash
# Install Python + Node dependencies
make install

# Apply database migrations (creates data/trading.db)
make db-upgrade

# Start both servers in parallel
make dev
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |

The Vite dev server proxies `/api/*` → `http://localhost:8000`, so login and all API calls work without configuring CORS.

### Start services individually

```bash
make api        # FastAPI only (uvicorn --reload)
make frontend   # Vite only
```

### Verify the setup

```bash
# API health
curl http://localhost:8000/api/health
# → {"status": "ok", "version": "3.0.0"}

# Authenticated endpoint
curl -H "X-API-Key: $BOT_API_SECRET" http://localhost:8000/api/strategies | jq length
# → 22
```

---

## 3. Docker Development (hot-reload)

Best for testing the full container stack while still editing source files.

```bash
make docker-dev-up
```

This starts:
- `trading-api-dev` — FastAPI with uvicorn `--reload`, source bind-mounted
- `trading-frontend-dev` — Vite with HMR, source bind-mounted

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Frontend | http://localhost:5173 |

```bash
# Tail logs
make docker-dev-logs svc=api
make docker-dev-logs svc=frontend

# Open shell inside container
make docker-dev-shell-api

# Stop
make docker-dev-down
```

---

## 4. Production Stack (Docker)

```bash
make docker-up
```

| Service | Port |
|---|---|
| Frontend (Nginx) | 80 |
| API | 8000 (internal + exposed) |

```bash
# Check running containers
docker compose ps

# Tail API logs
make docker-logs svc=api

# Apply migrations inside the container
make docker-shell-api
# then inside: alembic upgrade head
```

For TLS / HTTPS, configure `Caddyfile` with your domain and run:
```bash
docker compose -f docker-compose.prod.yml up -d
```

Full VPS guide: [`docs/vps-deploy.md`](vps-deploy.md)

---

## 5. Database Migrations

The project uses [Alembic](https://alembic.sqlalchemy.org/) for schema versioning.

```bash
# Apply all pending migrations (run this on first setup)
make db-upgrade

# Check current revision
make db-current

# Roll back one step
make db-downgrade

# Create a new migration (after editing api/db/models.py)
make db-revision msg="add column strategy_configs.is_active"
```

Migrations live in `alembic/versions/`. Each file is timestamped and sequential. **Never edit applied migration files** — always create a new one.

---

## 6. Running Tests

```bash
make test          # Full suite (unit + API integration)
make test-unit     # Strategy unit tests only (crypto_bot/tests/)
make test-api      # API integration tests only (tests/api/)
make test-cov      # Coverage report → htmlcov/index.html
```

See [`docs/testing.md`](testing.md) for the full TDD guide and how to write tests.

---

## 7. First Backtest

Once the API is running:

1. Open the dashboard → **Backtests** tab
2. Select a strategy (e.g., `ema_crossover`), pair (`BTC/USDT`), timeframe (`1h`), period (`3m`)
3. Click **Run Backtest**
4. The job runs asynchronously — status updates appear as the engine downloads and processes candles
5. When complete, the results panel shows metrics + equity curve + price chart with indicator overlays

Or via API directly:
```bash
curl -X POST http://localhost:8000/api/backtests \
  -H "X-API-Key: $BOT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "ema_crossover",
    "pair": "BTC/USDT",
    "timeframe": "1h",
    "period": "3m"
  }'
```

---

## 8. Configuring Strategy Parameters

All strategy parameters live in `crypto_bot/config.yaml` under the `strategies:` section.

```yaml
strategies:
  ema_crossover:
    fast_ema: 9
    slow_ema: 21
    signal_ema: 5
    trailing_stop_pct: 2.0
    amount_per_trade: 10
    min_volume_filter: true
```

Changes take effect on the next bot start (the API reloads config on startup). You can also edit via the Settings page in the dashboard, or via `PATCH /api/config/bot`.

---

## 9. Common Issues

### `ModuleNotFoundError: No module named 'strategies'`
The API uses `api/path_setup.py` to inject `crypto_bot/` into `sys.path`. If running the API directly (not via `make api`), set:
```bash
export PYTHONPATH=$PWD/crypto_bot:$PWD/api
```

### `403 Forbidden` on all API calls
`BOT_API_SECRET` in `.env` does not match the `X-API-Key` header value you're sending. Re-check both.

### Database doesn't exist
Run `make db-upgrade` — it creates `data/trading.db` and applies all migrations.

### Port already in use
```bash
# Find what's using port 8000
lsof -i :8000
# Kill it or change API_PORT in .env
```

### Frontend build fails
```bash
cd frontend && npm install && npm run build
# Check for TypeScript errors:
npx tsc --noEmit
```
