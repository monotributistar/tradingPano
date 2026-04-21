# Contributing to TradingPano

Thank you for contributing. This document covers the workflow, standards, and expectations for everyone working on this project — whether you're adding a strategy, fixing a bug, or improving the UI.

---

## Table of Contents

- [Workflow](#workflow)
- [Branching Model](#branching-model)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Code Standards](#code-standards)
- [Testing Requirements](#testing-requirements)
- [Adding a New Strategy](#adding-a-new-strategy)
- [Adding an API Endpoint](#adding-an-api-endpoint)
- [Adding a Frontend Feature](#adding-a-frontend-feature)

---

## Workflow

```
main  ←  PR  ←  feature/your-thing
                fix/bug-description
                docs/topic
                refactor/module-name
```

1. Pull latest `main` → create your branch
2. Write the test **first**, then implement
3. Keep commits small and atomic
4. Push → open a PR → request review
5. Squash-merge after approval

---

## Branching Model

| Prefix | Use |
|---|---|
| `feature/` | New feature or strategy |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Internal restructure, no behaviour change |
| `test/` | Adding or improving tests |
| `chore/` | Deps bump, CI, tooling |

Branch names use `kebab-case`. Examples:
```
feature/keltner-breakout-strategy
fix/rsi-warmup-off-by-one
docs/strategy-development-guide
refactor/backtester-metrics
```

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer]
```

**Types:** `feat` · `fix` · `docs` · `test` · `refactor` · `chore` · `perf`

**Scopes:** `strategy` · `backtester` · `api` · `frontend` · `db` · `docker` · `risk`

**Examples:**
```
feat(strategy): add keltner_breakout strategy with ATR bands

fix(backtester): correct RSI warmup period off-by-one

docs(api): update api-contracts.md with new /strategy-configs endpoints

test(strategy): add unit tests for pullback signal generation

chore(deps): bump ccxt to 4.3.1
```

Rules:
- Summary line ≤ 72 characters
- Use imperative mood ("add", "fix", "update" — not "added", "fixes")
- Body explains *why*, not *what* (the diff shows what)
- Reference issues: `Closes #42` or `Fixes #42`

---

## Pull Requests

### PR title

Same format as a commit message:
```
feat(strategy): add pullback trend-following strategy
```

### PR description template

```markdown
## What
Brief description of the change.

## Why
Context: what problem does this solve?

## How
Key implementation decisions worth noting.

## Tests
- [ ] Unit tests added / updated
- [ ] API integration tests pass
- [ ] TypeScript compiles with 0 errors
- [ ] `make test` passes locally

## Checklist
- [ ] Follows logging standards (docs/logging.md)
- [ ] No secrets in code or config
- [ ] Migrations created if DB schema changed
- [ ] CHANGELOG or docs updated if user-facing
```

### Review expectations

- At least one approval before merge
- CI must be green (tests + TypeScript check)
- No direct pushes to `main`

---

## Code Standards

### Python

- **Python 3.11+** — use `match`, `|` union types, `tomllib`, etc. where appropriate
- **Type hints everywhere** — all function signatures, all class attributes
- **Docstrings** — every public class and public method gets one (Google style)
- **No bare `except`** — always `except SpecificError as e:`
- **No mutable default args** — use `None` + internal assignment
- Line length: 100 characters
- Formatter: `black` (run before commit)
- Linter: `ruff`

```bash
black api/ crypto_bot/
ruff check api/ crypto_bot/ --fix
```

### TypeScript / React

- **Strict TypeScript** — no `any`, no `// @ts-ignore` without a comment explaining why
- **Named exports** for components, types, and utilities
- **Default export** for page components and the main component in a file
- **CSS Modules** for all component styles (no inline `style={{}}` except dynamic values)
- **No `console.log`** in committed code — use the API's log endpoints or remove before PR
- Formatter: `prettier` (run before commit)

```bash
cd frontend && npm run format && npm run lint
```

### General

- **No secrets in source code** — all credentials through `.env`
- **Fail fast** — raise errors early, return early in functions
- **One concern per file** — split large files rather than growing them
- **Reuse before rewriting** — check `lib/`, `components/ui/`, and existing helpers first

---

## Testing Requirements

> See [`docs/testing.md`](docs/testing.md) for the full TDD guide.

### Minimum requirements per PR type

| Change type | Minimum tests required |
|---|---|
| New strategy | Unit tests for BUY, SELL/COVER, HOLD, STOP_LOSS signals + warmup |
| New API endpoint | Integration test for success case + auth failure + validation error |
| Bug fix | Regression test that fails before the fix, passes after |
| Refactor | No new tests needed — existing suite must stay green |
| New component | Manual verification is fine; E2E test if it's a critical flow |

### Running tests

```bash
make test          # All tests
make test-unit     # crypto_bot/tests/ only
make test-api      # tests/api/ only
make test-cov      # With HTML coverage report → htmlcov/index.html
```

### Coverage target

- Strategies: **≥ 80%** line coverage
- API routers: **≥ 70%** line coverage

---

## Adding a New Strategy

Full guide: [`docs/strategy-development.md`](docs/strategy-development.md)

Quick checklist:

```
□ 1. Create crypto_bot/strategies/<name>.py
      - Extend BaseStrategy
      - Implement initialize(), on_candle(), get_params(), reset()
      - Set all class-level metadata attributes

□ 2. Register in api/main.py → get_strategy_registry()

□ 3. Add config section to crypto_bot/config.yaml
      under strategies: <name>:

□ 4. Add indicator definitions to
      frontend/src/lib/strategyIndicators.ts

□ 5. Write unit tests in crypto_bot/tests/test_strategies.py
      - Test BUY signal
      - Test exit (SELL/COVER/STOP_LOSS) signal
      - Test HOLD when conditions not met
      - Test warmup returns HOLD

□ 6. Verify with: python3 -m py_compile crypto_bot/strategies/<name>.py
□ 7. Verify registry: python3 -c "from api.main import get_strategy_registry; ..."
□ 8. Verify TypeScript: cd frontend && npx tsc --noEmit
```

---

## Adding an API Endpoint

```
□ 1. Add Pydantic schema to api/schemas/ (request + response models)
□ 2. Implement endpoint in the appropriate api/routers/<resource>.py
□ 3. Write integration test in tests/api/test_<resource>.py
      - Happy path (200/201)
      - Unauthorized (403) — missing X-API-Key
      - Not found (404) — if applicable
      - Validation error (422) — bad body
□ 4. Update docs/api-contracts.md with the new endpoint spec
```

### Endpoint conventions

```python
# Use consistent response patterns
@router.get("/resource/{id}", response_model=ResourceSchema)
def get_resource(id: int, db: Session = Depends(get_db), _: None = Depends(require_api_key)):
    resource = db.query(ResourceORM).filter(ResourceORM.id == id).first()
    if not resource:
        raise HTTPException(status_code=404, detail=f"Resource {id} not found")
    return resource
```

- Always use `Depends(require_api_key)` for authenticated endpoints
- Raise `HTTPException` with specific `detail` strings, not generic messages
- Use `response_model=` on every route for automatic schema validation

---

## Adding a Frontend Feature

```
□ 1. Add TypeScript interfaces to frontend/src/api/client.ts
□ 2. Add API function to client.ts (name: verb + noun, e.g. fetchStrategies)
□ 3. Implement component(s) using CSS Modules for styles
□ 4. Run: cd frontend && npx tsc --noEmit   (must be 0 errors)
□ 5. Test manually in browser
```

### React component conventions

```tsx
// ── Named export for reusable components ─────────────────────
export function MyComponent({ prop }: Props) { ... }

// ── Default export for page components ───────────────────────
export default function MyPage() { ... }

// ── CSS Module pattern ────────────────────────────────────────
import styles from "./MyComponent.module.css";
<div className={styles.container}>

// ── API data — always use react-query ────────────────────────
const { data, isLoading, error } = useQuery({
  queryKey: ["strategies"],
  queryFn: fetchStrategies,
});

// ── Never fire raw useEffect for data fetching ───────────────
// Prefer useQuery / useMutation from @tanstack/react-query
```
