# CONTRIBUTING.md — Developer Contribution Guide

> This document covers everything needed to contribute to TradingPano: branching,
> commit style, PR process, code standards, and step-by-step instructions for the
> two most common contribution types — adding a strategy and adding an API endpoint.
>
> For the strategy implementation contract (full template + code) see
> [`docs/strategy-development.md`](strategy-development.md).  
> For the testing guide see [`docs/TESTING.md`](TESTING.md).  
> For API endpoint schemas see [`docs/api-contracts.md`](api-contracts.md).

---

## Table of Contents

- [Workflow Overview](#workflow-overview)
- [Branching Model](#branching-model)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)
- [Code Standards — Python](#code-standards--python)
- [Code Standards — TypeScript / React](#code-standards--typescript--react)
- [Adding a New Strategy — Step by Step](#adding-a-new-strategy--step-by-step)
- [Adding a New API Endpoint — Step by Step](#adding-a-new-api-endpoint--step-by-step)
- [Testing Requirements per PR Type](#testing-requirements-per-pr-type)
- [Pre-PR Checklist](#pre-pr-checklist)

---

## Workflow Overview

```
main  ←  squash-merge  ←  feature/your-thing
                           fix/bug-description
                           docs/topic
                           refactor/module-name
```

1. Pull the latest `main` and create your branch.
2. Write the failing test first, then implement (see [TDD Workflow](TESTING.md#tdd-workflow)).
3. Keep commits small and atomic — one logical change per commit.
4. Push the branch and open a PR against `main`.
5. Get at least one approval and green CI before merging (squash-merge).
6. Delete the branch after merge.

---

## Branching Model

| Prefix | Use case |
|---|---|
| `feature/` | New feature or strategy |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Internal restructure with no behaviour change |
| `test/` | Adding or improving tests |
| `chore/` | Dependency bumps, CI changes, tooling |

Branch names use `kebab-case`:

```
feature/keltner-breakout-strategy
fix/rsi-warmup-off-by-one
docs/strategy-development-guide
refactor/backtester-metrics
chore/bump-ccxt-4.4
```

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short imperative summary>

[optional body — explains WHY, not WHAT]

[optional footer — Closes #42, Fixes #42]
```

**Types:** `feat` · `fix` · `docs` · `test` · `refactor` · `chore` · `perf`

**Scopes:** `strategy` · `backtester` · `api` · `frontend` · `db` · `docker` · `risk`

**Examples:**

```
feat(strategy): add keltner_breakout with ATR-based channel breakout

fix(backtester): correct RSI warmup period off-by-one error

docs(api): document new /strategy-configs endpoints in api-contracts.md

test(strategy): add unit tests for stoch_rsi signal generation

refactor(backtester): extract metric computation into dedicated module

chore(deps): bump ccxt from 4.3.0 to 4.4.1
```

**Rules:**
- Summary line: 72 characters maximum
- Imperative mood: "add", "fix", "update" — not "added", "fixes", "updates"
- Body explains *why*, not *what* (the diff shows what)
- Reference issues in the footer: `Closes #42`

---

## Pull Request Process

### PR title

Same format as a commit message summary:

```
feat(strategy): add keltner_breakout long/short strategy
```

### PR description template

```markdown
## What
Brief description of the change (1-3 sentences).

## Why
Context: what problem does this solve? What gap does this fill?

## How
Key implementation decisions worth noting (edge cases, alternatives considered).

## Tests
- [ ] Unit tests added / updated
- [ ] API integration tests pass (`make test-api`)
- [ ] TypeScript compiles: `cd frontend && npx tsc --noEmit` → 0 errors
- [ ] Full suite passes: `make test`

## Checklist
- [ ] Follows logging standards (docs/LOGGING.md)
- [ ] No API keys / secrets in code or config
- [ ] Alembic migration created if DB schema changed (`make db-revision msg="..."`)
- [ ] `docs/api-contracts.md` updated if new endpoints added
- [ ] `docs/strategies.md` updated if new strategy added
```

### Review expectations

- At least **one approval** before merge
- CI must be green (tests + TypeScript check)
- No direct pushes to `main`
- Prefer squash-merge to keep a clean linear history

---

## Code Standards — Python

**Version:** Python 3.11+ (use `match`, `X | Y` union types, `tomllib`, etc. where appropriate)

### Formatting and linting

```bash
# Format before commit
black api/ crypto_bot/ --line-length 100

# Lint + auto-fix
ruff check api/ crypto_bot/ --fix
```

Line length: **100 characters**.

### Type hints

All function signatures and all class attributes must be type-annotated:

```python
# Correct
def fetch_ohlcv(pair: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    ...

# Wrong — missing return type, missing param type
def fetch_ohlcv(pair, timeframe, limit=200):
    ...
```

### Docstrings

Every public class and public method gets a docstring (Google style):

```python
def compute_sharpe(returns: pd.Series, annualisation: int = 8760) -> float:
    """Compute the annualised Sharpe ratio (risk-free rate = 0).

    Args:
        returns: Per-bar return series (fractional, e.g. 0.01 = 1%).
        annualisation: Bars per year for scaling (8760 = hourly, 365 = daily).

    Returns:
        Annualised Sharpe ratio. Returns 0.0 if returns are all zero.
    """
```

### Error handling

```python
# Correct — specific exception, context in message, traceback preserved
try:
    result = exchange.fetch_ohlcv(pair, timeframe, limit=limit)
except ccxt.NetworkError as e:
    logger.error("exchange.fetch_ohlcv failed pair=%s tf=%s error=%s", pair, timeframe, str(e), exc_info=True)
    raise

# Wrong — swallows traceback, hides context
try:
    result = exchange.fetch_ohlcv(pair, timeframe)
except:
    pass
```

### Other rules

- **No bare `except`** — always `except SpecificError as e:`
- **No mutable default arguments** — use `None` with internal assignment
- **No `print()`** — use `logger.info()` / `logger.debug()`
- **No secrets in code** — all credentials via `.env`
- **Fail fast** — raise errors early, validate inputs at function entry

---

## Code Standards — TypeScript / React

**Mode:** Strict TypeScript (`"strict": true` in `tsconfig.json`)

### Formatting and linting

```bash
cd frontend

# Format
npm run format       # prettier

# Lint
npm run lint         # eslint

# Type check (must be 0 errors before any PR)
npx tsc --noEmit
```

### Key rules

- **No `any`** — use `unknown` with type narrowing, or define the interface
- **No `// @ts-ignore`** without a comment explaining why it cannot be avoided
- **Named exports** for reusable components, utilities, and types
- **Default export** for page-level components and the primary component in a file
- **CSS Modules** for all component styles — no inline `style={{}}` except computed values
- **No `console.log`** in committed code

### Component conventions

```tsx
// Named export — reusable component
export function StatCard({ label, value }: Props) { ... }

// Default export — page component
export default function BotControl() { ... }

// CSS Module
import styles from "./BotControl.module.css";
<div className={styles.container}>

// API data — always use react-query
const { data, isLoading, error } = useQuery({
  queryKey: ["bot-status"],
  queryFn: fetchBotStatus,
  refetchInterval: 5000,
});

// Mutations
const startBot = useMutation({
  mutationFn: (req: BotStartRequest) => postBotStart(req),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bot-status"] }),
});
```

---

## Adding a New Strategy — Step by Step

This section provides the minimal checklist. For the full implementation template,
indicator helpers, and detailed code examples see
[`docs/strategy-development.md`](strategy-development.md).

### Step 1 — Create the strategy file

```
crypto_bot/strategies/<your_strategy_name>.py
```

The file must:
- Import and extend `BaseStrategy` from `crypto_bot/strategies/base.py`
- Set all required class-level metadata attributes (`name`, `description`,
  `market_type`, `ideal_timeframes`, `min_period`, `trade_frequency`,
  `min_liquidity`, `suitable_timeframes`, `suitable_market_conditions`,
  `recommended_leverage`, `max_leverage`, `risk_profile`)
- Implement the four required methods: `initialize(config)`, `on_candle(pair, candles, position)`,
  `get_params()`, `reset()`
- Optionally implement `save_state()` and `load_state(state)` (required for live-mode resume)
- Declare `logger = logging.getLogger(__name__)` at module level
- Log `INFO` on every `BUY`, `SHORT`, `SELL`, `COVER`, and `STOP_LOSS` signal

The `name` class attribute must be a unique **snake_case** string that matches the
key used in Steps 2, 3, and 4.

### Step 2 — Register in the strategy registry

File: `api/main.py` → `get_strategy_registry()`

```python
from strategies.your_strategy_name import YourStrategyClass   # add import

def get_strategy_registry() -> dict:
    ...
    return {
        ...
        "your_strategy_name": YourStrategyClass,   # add entry
    }
```

The key **must** exactly match `YourStrategyClass.name`.

### Step 3 — Add config defaults

File: `crypto_bot/config.yaml` → `strategies:` section

```yaml
strategies:
  your_strategy_name:
    description: "One-line description for humans"
    param_a: 20
    param_b: 50
    atr_period: 14
    stop_atr_mult: 2.0
    tp_atr_mult: 3.5
    amount_per_trade: 10
    use_shorts: true
```

All values here become the defaults loaded by `initialize()` when no override is passed.
Use `config.get("key", default)` in `initialize()` — never hardcode values.

### Step 4 — Add frontend indicator definitions

File: `frontend/src/lib/strategyIndicators.ts` → `STRATEGY_INDICATORS` map

```typescript
your_strategy_name: [
  // Overlaid on the price panel
  { id: "ema20", label: "EMA(20)", type: "ema", params: { period: 20 },
    panel: "price", color: "#60a5fa" },
  { id: "ema50", label: "EMA(50)", type: "ema", params: { period: 50 },
    panel: "price", color: "#f59e0b" },
  // Oscillator sub-panel (only the first osc entry is rendered)
  { id: "rsi", label: "RSI(14)", type: "rsi", params: { period: 14 },
    panel: "osc", color: "#a78bfa",
    levels: [
      { value: 30, color: "#22c55e", label: "OS" },
      { value: 70, color: "#ef4444", label: "OB" },
    ],
  },
],
```

Supported `type` values: `ema` · `sma` · `rsi` · `macd` · `bollinger` ·
`supertrend` · `atr` · `vwap`

### Step 5 — Write unit tests

File: `crypto_bot/tests/test_strategies.py`

Required test cases (see [TESTING.md](TESTING.md#unit-tests--strategies) for full examples):

| Test | What it verifies |
|---|---|
| `test_warmup_returns_hold` | Strategy returns `HOLD` before warmup bars are complete |
| `test_buy_signal_on_entry_condition` | `BUY` fires when conditions are met (use `trend=0.1` candles) |
| `test_hold_when_no_signal` | `HOLD` returned in flat market |
| `test_stop_loss_fires` | `STOP_LOSS` emitted when price breaks through the stop level |
| `test_time_exit_fires` | `TIME_EXIT` or `SELL` emitted after `max_bars_held` |
| `test_reset_clears_state` | All internal state is `None` / `0` after `reset()` |
| `test_get_params_has_all_keys` | `get_params()` returns every configurable parameter |
| `test_save_load_state_roundtrip` | `save_state()` → `reset()` → `load_state()` restores correctly |

### Step 6 — Verify

```bash
# Syntax check
python3 -m py_compile crypto_bot/strategies/your_strategy_name.py

# Registry loads and instantiates
python3 -c "
from api.main import get_strategy_registry
r = get_strategy_registry()
s = r['your_strategy_name']()
s.initialize({})
print('OK:', s.name)
"

# TypeScript check
cd frontend && npx tsc --noEmit

# Full test suite
make test
```

---

## Adding a New API Endpoint — Step by Step

### Step 1 — Define Pydantic schemas

File: `api/schemas/<resource>.py`

```python
from pydantic import BaseModel, Field
from typing import Optional

class MyResourceCreate(BaseModel):
    """Request body for POST /api/my-resource."""
    name: str = Field(..., description="Resource display name")
    value: float = Field(..., gt=0, description="Positive numeric value")
    optional_flag: bool = Field(False, description="Optional flag")

class MyResourceResponse(BaseModel):
    """Response body for GET /api/my-resource/{id}."""
    id: int
    name: str
    value: float
    optional_flag: bool
    created_at: datetime

    model_config = {"from_attributes": True}
```

### Step 2 — Implement the endpoint

File: `api/routers/<resource>.py`

```python
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import require_api_key
from api.db.engine import get_db
from api.schemas.my_resource import MyResourceCreate, MyResourceResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/my-resource", tags=["my-resource"])


@router.post("", response_model=MyResourceResponse, status_code=201)
def create_resource(
    body: MyResourceCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    """Create a new resource."""
    logger.info("my_resource.create name=%s value=%.2f", body.name, body.value)
    # ... create ORM object, add to DB session, commit ...
    return new_resource


@router.get("/{id}", response_model=MyResourceResponse)
def get_resource(
    id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    """Retrieve a single resource by ID."""
    resource = db.query(MyResourceORM).filter(MyResourceORM.id == id).first()
    if not resource:
        raise HTTPException(status_code=404, detail=f"Resource {id} not found")
    return resource
```

### Step 3 — Register the router

File: `api/main.py` — add inside `create_app()`:

```python
from api.routers.my_resource import router as my_resource_router
app.include_router(my_resource_router, prefix="/api")
```

### Step 4 — Write integration tests

File: `tests/api/test_my_resource.py`

Every new endpoint needs tests for:
- Happy path (200/201 with correct response shape)
- Unauthenticated request (403 — missing `X-API-Key`)
- Not found (404 — invalid ID) — if applicable
- Validation error (422 — malformed body) — if `POST`/`PUT`

```python
import pytest

pytestmark = pytest.mark.api

class TestCreateMyResource:
    def test_creates_resource(self, client, auth_headers):
        resp = client.post(
            "/api/my-resource",
            headers=auth_headers,
            json={"name": "test", "value": 42.0},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test"
        assert body["value"] == 42.0
        assert "id" in body

    def test_requires_auth(self, client):
        resp = client.post("/api/my-resource", json={"name": "x", "value": 1.0})
        assert resp.status_code == 403

    def test_validation_error_on_negative_value(self, client, auth_headers):
        resp = client.post(
            "/api/my-resource",
            headers=auth_headers,
            json={"name": "test", "value": -1.0},  # gt=0 constraint
        )
        assert resp.status_code == 422
```

### Step 5 — Update documentation

- Add the endpoint spec to `docs/api-contracts.md`
- Add the TypeScript interface and API function to `frontend/src/api/client.ts`
- Run `cd frontend && npx tsc --noEmit` to verify zero errors

---

## Testing Requirements per PR Type

| Change type | Required tests |
|---|---|
| New strategy | BUY signal, SELL/COVER/STOP_LOSS signal, HOLD, warmup → HOLD, reset(), get_params(), save/load state |
| New API endpoint | Happy path (200/201), 403 auth failure, 404 not found (if applicable), 422 validation error |
| Bug fix | Regression test that fails before the fix and passes after |
| Refactor | No new tests — existing suite must stay fully green |
| New UI component | Manual verification; E2E test if it is a critical user flow |

### Coverage targets

| Module | Minimum line coverage |
|---|---|
| `crypto_bot/strategies/` | 80% |
| `api/routers/` | 70% |
| `crypto_bot/backtester/` | 60% |

```bash
make test-cov
open htmlcov/index.html
```

---

## Pre-PR Checklist

Run this before opening any PR:

```bash
# 1. Format Python
black api/ crypto_bot/ --line-length 100

# 2. Lint Python
ruff check api/ crypto_bot/ --fix

# 3. Format + lint TypeScript
cd frontend && npm run format && npm run lint && cd ..

# 4. TypeScript type check — must be 0 errors
cd frontend && npx tsc --noEmit && cd ..

# 5. Full test suite — must all pass
make test

# 6. Coverage check (optional but recommended)
make test-cov
```

Strategy-specific additions:

```bash
# Syntax check
python3 -m py_compile crypto_bot/strategies/<name>.py

# Registry smoke test
python3 -c "
from api.main import get_strategy_registry
r = get_strategy_registry()
s = r['<name>']()
s.initialize({})
print('registry OK:', s.name, s.get_params())
"
```
