# Docker Workflow

Two compose files cover the full lifecycle:

| File | Purpose | Hot-reload |
|------|---------|------------|
| `docker-compose.yml` | **Production** — built images, nginx, non-root API | ✗ |
| `docker-compose.dev.yml` | **Development** — bind mounts, Vite HMR, uvicorn `--reload` | ✓ |

---

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
# Fill in EXCHANGE_NAME, EXCHANGE_API_KEY, EXCHANGE_API_SECRET (optional for paper trading)
```

### 2a. Production

```bash
make docker-up          # build + start detached
# → Frontend:  http://localhost:80
# → API docs:  http://localhost:8000/docs

make docker-logs        # tail all logs
make docker-down        # stop
```

### 2b. Development (hot-reload)

```bash
make docker-dev-up      # build + start detached
# → Frontend (HMR): http://localhost:5173
# → API (reload):   http://localhost:8000
# → API docs:       http://localhost:8000/docs

make docker-dev-logs    # tail all logs
make docker-dev-down    # stop
```

Edit any Python or TypeScript file and the relevant service reloads automatically.

---

## Makefile targets

### Local (no Docker)

| Target | Description |
|--------|-------------|
| `make install` | Install all Python + npm dependencies |
| `make api` | Run FastAPI with auto-reload |
| `make frontend` | Run Vite dev server |
| `make dev` | Run both in parallel (`-j2`) |
| `make test` | Run pytest suite |
| `make build` | Build frontend production bundle |

### Production Docker

| Target | Description |
|--------|-------------|
| `make docker-build` | Build production images |
| `make docker-up` | Start stack (detached) |
| `make docker-down` | Stop stack |
| `make docker-restart svc=api` | Restart a single service |
| `make docker-logs [svc=api]` | Tail logs |
| `make docker-shell-api` | Shell into API container |
| `make docker-shell-frontend` | Shell into frontend container |
| `make docker-clean` | Remove containers + volumes (**destructive**) |

### Development Docker

| Target | Description |
|--------|-------------|
| `make docker-dev-build` | Build dev images |
| `make docker-dev-up` | Start dev stack (detached) |
| `make docker-dev-down` | Stop dev stack |
| `make docker-dev-logs [svc=api]` | Tail dev logs |
| `make docker-dev-shell-api` | Shell into dev API container |
| `make docker-dev-shell-frontend` | Shell into dev frontend container |

---

## Architecture

```
                 ┌─────────────────────────────────────────┐
Browser          │  Docker network: app-net / app-dev-net  │
   │             │                                         │
   │  :80        │  ┌──────────────┐   /api/*   ┌───────┐ │
   └────────────►│  │   nginx       ├──────────►│  API  │ │
   │  :5173 (dev)│  │  (frontend)  │            │ :8000 │ │
                 │  └──────────────┘            └───┬───┘ │
                 │                                  │     │
                 │                          ┌───────▼───┐ │
                 │                          │ data vol  │ │
                 │                          │ (SQLite + │ │
                 │                          │  cache)   │ │
                 │                          └───────────┘ │
                 └─────────────────────────────────────────┘
```

### Production services

- **api** — Python 3.11-slim, non-root user, 2 uvicorn workers, `/api/health` healthcheck
- **frontend** — nginx 1.27-alpine, gzip, security headers, SPA fallback, proxies `/api/` to backend

### Development services

- **api** — Python 3.11-slim, source bind-mounted, `uvicorn --reload`
- **frontend** — node:20-alpine, source bind-mounted, `npm run dev -- --host 0.0.0.0`

---

## Data persistence

The production `data/` volume is a named Docker volume (`app-data`). It survives `docker compose down` but is removed by `docker-clean`.

To back it up:

```bash
docker run --rm \
  -v trading-claude_app-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/data-backup.tar.gz -C / data
```

To restore:

```bash
docker run --rm \
  -v trading-claude_app-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/data-backup.tar.gz -C /
```

---

## Ports

| Service | Default port | Env override |
|---------|-------------|--------------|
| Frontend (prod) | `80` | `FRONTEND_PORT` |
| Frontend (dev) | `5173` | `FRONTEND_PORT` |
| API | `8000` | `API_PORT` |

---

## Environment variables

See [`.env.example`](../.env.example) for the full list with descriptions.

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `EXCHANGE_NAME` | `kucoin` | ccxt exchange ID |
| `EXCHANGE_API_KEY` | — | API key (blank = public data only) |
| `EXCHANGE_API_SECRET` | — | API secret |
| `EXCHANGE_PASSPHRASE` | — | Required for KuCoin |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `API_PORT` | `8000` | Host port for the API |
| `FRONTEND_PORT` | `80` / `5173` | Host port for the frontend |
