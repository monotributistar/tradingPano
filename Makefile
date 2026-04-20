.PHONY: install install-api install-frontend \
        api frontend dev test build \
        db-upgrade db-downgrade db-revision db-history db-current \
        docker-build docker-up docker-down docker-restart docker-logs \
        docker-shell-api docker-shell-frontend docker-clean \
        docker-dev-build docker-dev-up docker-dev-down docker-dev-logs \
        docker-dev-shell-api docker-dev-shell-frontend

# ── Local development (no Docker) ───────────────────────────────────────────
install: install-api install-frontend

install-api:
	python3 -m pip install -r api/requirements.txt

install-frontend:
	cd frontend && npm install

api:
	python3 -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

## Run both services in parallel (requires GNU make)
dev:
	@echo "Starting API + Frontend in parallel…"
	$(MAKE) -j2 api frontend

test:
	cd crypto_bot && python3 -m pytest tests/ -v

build:
	cd frontend && npm run build

# ── Database migrations (Alembic) ────────────────────────────────────────────
## Apply all pending migrations to the local SQLite DB
db-upgrade:
	alembic upgrade head

## Roll back the last migration
db-downgrade:
	alembic downgrade -1

## Create a new migration (auto-generate from model diff).
## Usage: make db-revision msg="add column foo to trades"
db-revision:
	alembic revision --autogenerate -m "$(msg)"

## Show applied migration history
db-history:
	alembic history --verbose

## Show current DB revision
db-current:
	alembic current

# ── Production Docker ────────────────────────────────────────────────────────
## Build production images
docker-build:
	docker compose build

## Start production stack (detached)
docker-up:
	docker compose up -d --build
	@echo ""
	@echo "  Frontend →  http://localhost:$${FRONTEND_PORT:-80}"
	@echo "  API docs →  http://localhost:$${API_PORT:-8000}/docs"

## Stop production stack
docker-down:
	docker compose down

## Restart a single service:  make docker-restart svc=api
docker-restart:
	docker compose restart $(svc)

## Tail logs (all services, or: make docker-logs svc=api)
docker-logs:
	docker compose logs -f $(svc)

## Open a shell inside the API container
docker-shell-api:
	docker compose exec api sh

## Open a shell inside the frontend container
docker-shell-frontend:
	docker compose exec frontend sh

## Remove containers, networks and volumes (⚠ deletes data volume)
docker-clean:
	docker compose down -v --remove-orphans

# ── Development Docker (hot-reload) ─────────────────────────────────────────
## Build dev images
docker-dev-build:
	docker compose -f docker-compose.dev.yml build

## Start dev stack (detached)
docker-dev-up:
	docker compose -f docker-compose.dev.yml up -d --build
	@echo ""
	@echo "  Frontend (HMR) →  http://localhost:$${FRONTEND_PORT:-5173}"
	@echo "  API (reload)   →  http://localhost:$${API_PORT:-8000}"
	@echo "  API docs       →  http://localhost:$${API_PORT:-8000}/docs"

## Stop dev stack
docker-dev-down:
	docker compose -f docker-compose.dev.yml down

## Tail dev logs (all services, or: make docker-dev-logs svc=api)
docker-dev-logs:
	docker compose -f docker-compose.dev.yml logs -f $(svc)

## Open a shell in the dev API container
docker-dev-shell-api:
	docker compose -f docker-compose.dev.yml exec api sh

## Open a shell in the dev frontend container
docker-dev-shell-frontend:
	docker compose -f docker-compose.dev.yml exec frontend sh
