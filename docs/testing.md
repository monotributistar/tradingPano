# Testing Guide (TDD)

TradingPano follows a **test-first** workflow. Every bug fix and new feature begins with a failing test. This document explains the testing architecture, all fixtures, patterns to follow, and how to write tests for each layer.

---

## Table of Contents

- [Test Architecture](#test-architecture)
- [Running Tests](#running-tests)
- [TDD Workflow](#tdd-workflow)
- [Unit Tests — Strategies](#unit-tests--strategies)
- [Integration Tests — API](#integration-tests--api)
- [Frontend Type Safety](#frontend-type-safety)
- [Fixtures Reference](#fixtures-reference)
- [Coverage Requirements](#coverage-requirements)
- [Writing Good Tests](#writing-good-tests)

---

## Test Architecture

```
tests/                        # Pytest integration tests (API layer)
├── conftest.py               # Shared fixtures: client, auth_headers, in-memory DB
└── api/
    ├── test_health.py        # Public endpoints (no auth)
    ├── test_auth.py          # Auth middleware
    ├── test_bot_endpoints.py # Bot start/stop/status
    ├── test_system_metrics.py
    └── test_portfolio_endpoints.py

crypto_bot/tests/             # Unit tests (pure Python, no FastAPI)
├── conftest.py
└── test_strategies.py        # Strategy signal generation tests

e2e/tests/                    # Playwright browser tests
├── 01-navigation.spec.ts
├── 02-backtest.spec.ts
└── ...
```

**Test runner:** `pytest` with `pytest-cov` for coverage.

**Key configuration in `pytest.ini`:**
```ini
[pytest]
testpaths = tests crypto_bot/tests
markers =
    api: API integration tests
    unit: Pure unit tests
    slow: Tests that take >1 second
```

---

## Running Tests

```bash
# Full suite
make test

# Only strategy unit tests (fast — no network, no DB)
make test-unit
pytest crypto_bot/tests/ -v

# Only API integration tests
make test-api
pytest tests/api/ -v -m api

# Single test file
pytest tests/api/test_bot_endpoints.py -v

# Single test function
pytest tests/api/test_bot_endpoints.py::TestBotStatus::test_returns_stopped_when_idle -v

# With coverage report
make test-cov
# → Opens htmlcov/index.html
```

---

## TDD Workflow

Follow this sequence for every change:

```
1. Write a failing test that describes the expected behaviour
2. Run it — confirm it fails for the right reason
3. Write the minimum code to make it pass
4. Refactor — keep the test passing
5. Commit both test + implementation together
```

**Example — adding a new strategy signal:**

```python
# Step 1: Write the test FIRST
def test_pullback_issues_buy_on_dip_to_ema(uptrend_candles):
    strategy = PullbackStrategy()
    strategy.initialize({"fast_ema": 21, "slow_ema": 50, "rsi_oversold": 35})
    signal = strategy.on_candle("BTC/USDT", uptrend_candles, position=None)
    assert signal.signal == Signal.BUY

# Step 2: Run → AssertionError (strategy doesn't exist yet)
# Step 3: Implement PullbackStrategy.on_candle()
# Step 4: Test passes — refactor internals if needed
```

---

## Unit Tests — Strategies

Location: `crypto_bot/tests/test_strategies.py`

Strategy tests are **pure Python** — no network, no database, no FastAPI. They work by feeding synthetic OHLCV DataFrames into strategy instances.

### Synthetic candle fixtures

```python
import pandas as pd
import numpy as np

def make_candles(
    n: int = 200,
    start_price: float = 100.0,
    trend: float = 0.0,        # price change per bar (e.g. 0.1 = uptrend)
    noise: float = 0.5,
    volume: float = 1000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Create a synthetic OHLCV DataFrame for testing.
    All strategies need at least max(slow_period, warmup) bars.
    """
    rng = np.random.default_rng(seed)
    prices = [start_price]
    for _ in range(n - 1):
        prices.append(prices[-1] + trend + rng.normal(0, noise))
    prices = np.array(prices)

    return pd.DataFrame({
        "open":   prices * (1 - rng.uniform(0, 0.002, n)),
        "high":   prices * (1 + rng.uniform(0, 0.005, n)),
        "low":    prices * (1 - rng.uniform(0, 0.005, n)),
        "close":  prices,
        "volume": rng.uniform(volume * 0.5, volume * 1.5, n),
    })


def make_oversold_pullback(n: int = 200) -> pd.DataFrame:
    """
    Uptrend candles that have pulled back — RSI low, price at fast EMA.
    Useful for testing pullback / mean-reversion entry conditions.
    """
    candles = make_candles(n=n, trend=0.05)
    # Force the last 10 bars to dip
    close = candles["close"].values.copy()
    close[-10:] = close[-15] * 0.97  # -3% dip
    candles["close"] = close
    candles["low"] = candles[["close", "low"]].min(axis=1)
    return candles
```

### Required test cases per strategy

Every strategy **must** have tests for all four signal types:

```python
class TestMyStrategy:
    def setup_method(self):
        """Fresh instance for each test."""
        self.strategy = MyStrategy()
        self.strategy.initialize({"param_a": 10, "param_b": 20})

    # 1. HOLD during warmup
    def test_warmup_returns_hold(self):
        tiny = make_candles(n=5)  # Less than warmup period
        signal = self.strategy.on_candle("BTC/USDT", tiny, position=None)
        assert signal.signal == Signal.HOLD, "Must return HOLD during warmup"

    # 2. BUY signal
    def test_buy_signal_on_entry_condition(self):
        candles = make_candles(n=200, trend=0.1)  # Strong uptrend
        signal = self.strategy.on_candle("BTC/USDT", candles, position=None)
        assert signal.signal == Signal.BUY
        assert signal.amount_usd > 0
        assert signal.pair == "BTC/USDT"
        assert signal.price > 0
        assert signal.reason != ""

    # 3. SELL/COVER signal
    def test_exit_signal_when_condition_met(self):
        candles = make_candles(n=200, trend=0.1)
        position = {"side": "long", "qty": 0.1, "avg_cost": 100.0, "bars_held": 5}
        signal = self.strategy.on_candle("BTC/USDT", candles, position=position)
        # Depends on strategy — SELL, STOP_LOSS, or TIME_EXIT
        assert signal.signal in (Signal.SELL, Signal.STOP_LOSS, Signal.TIME_EXIT)

    # 4. HOLD when no signal
    def test_hold_when_no_entry_condition(self):
        candles = make_candles(n=200, trend=0.0, noise=0.01)  # Flat
        signal = self.strategy.on_candle("BTC/USDT", candles, position=None)
        assert signal.signal == Signal.HOLD

    # 5. State resets between runs
    def test_reset_clears_state(self):
        self.strategy._some_internal_state = 999
        self.strategy.reset()
        assert self.strategy._some_internal_state is None  # or 0

    # 6. get_params() returns all expected keys
    def test_get_params_returns_expected_keys(self):
        params = self.strategy.get_params()
        assert "param_a" in params
        assert "param_b" in params

    # 7. State save/restore
    def test_save_and_load_state(self):
        self.strategy._stop_price = 99.5
        state = self.strategy.save_state()
        self.strategy.reset()
        self.strategy.load_state(state)
        assert self.strategy._stop_price == 99.5
```

### Testing stop loss behaviour

```python
def test_stop_loss_fires_when_price_drops(self):
    strategy = MyStrategy()
    strategy.initialize({"stop_atr_mult": 1.0, "atr_period": 14})

    candles = make_candles(n=200, trend=0.05)
    # Simulate an open long position at price 100, stop at 98
    strategy._stop_price = 98.0
    position = {"side": "long", "qty": 0.1, "avg_cost": 100.0, "bars_held": 3}

    # Inject candle where price < stop
    candles_drop = candles.copy()
    candles_drop.iloc[-1, candles_drop.columns.get_loc("close")] = 97.0

    signal = strategy.on_candle("BTC/USDT", candles_drop, position=position)
    assert signal.signal == Signal.STOP_LOSS
```

---

## Integration Tests — API

Location: `tests/api/`

API tests use FastAPI's `TestClient` with an **in-memory SQLite** database — completely isolated from any real data.

### Fixtures (from `tests/conftest.py`)

```python
# Available in every test file automatically:

client         # FastAPI TestClient — makes HTTP requests
auth_headers   # {"X-API-Key": "test-secret-key"}
```

### Test structure template

```python
# tests/api/test_my_resource.py
import pytest

pytestmark = pytest.mark.api   # Tag all tests in this file


class TestListMyResource:
    """GET /api/my-resource"""

    def test_returns_empty_list(self, client, auth_headers):
        resp = client.get("/api/my-resource", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_requires_auth(self, client):
        resp = client.get("/api/my-resource")
        assert resp.status_code == 403

    def test_invalid_key_rejected(self, client):
        resp = client.get("/api/my-resource", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 403


class TestCreateMyResource:
    """POST /api/my-resource"""

    def test_creates_and_returns_resource(self, client, auth_headers):
        resp = client.post(
            "/api/my-resource",
            headers=auth_headers,
            json={"name": "test", "value": 42},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test"
        assert body["value"] == 42
        assert "id" in body

    def test_returns_422_on_missing_required_field(self, client, auth_headers):
        resp = client.post(
            "/api/my-resource",
            headers=auth_headers,
            json={"value": 42},   # missing "name"
        )
        assert resp.status_code == 422

    def test_returns_404_for_unknown_strategy(self, client, auth_headers):
        resp = client.post(
            "/api/my-resource",
            headers=auth_headers,
            json={"name": "test", "strategy": "nonexistent_strategy"},
        )
        assert resp.status_code == 404
```

### Testing patterns for common scenarios

```python
# Assert specific JSON shape
def test_strategy_list_structure(self, client, auth_headers):
    resp = client.get("/api/strategies", headers=auth_headers)
    strategies = resp.json()
    first = strategies[0]
    assert "name" in first
    assert "description" in first
    assert "market_type" in first
    assert first["market_type"] in ("trending", "ranging", "both")

# Assert error detail message
def test_not_found_returns_clear_message(self, client, auth_headers):
    resp = client.get("/api/backtests/99999", headers=auth_headers)
    assert resp.status_code == 404
    assert "99999" in resp.json()["detail"]   # ID mentioned in message

# Assert response contains numeric range
def test_metrics_values_are_valid(self, client, auth_headers):
    # ... set up a completed backtest job ...
    resp = client.get(f"/api/backtests/{job_id}", headers=auth_headers)
    metrics = resp.json()["metrics"]
    assert 0 <= metrics["win_rate_pct"] <= 100
    assert metrics["max_drawdown_pct"] >= 0
```

---

## Frontend Type Safety

TypeScript compilation with zero errors is **a mandatory test** before any PR:

```bash
cd frontend && npx tsc --noEmit
```

This catches:
- Missing properties in API response types
- Wrong prop types on components
- Unhandled `null | undefined` values from API responses
- Breaking changes in shared interfaces

### When you change an API response schema

1. Update `api/schemas/<resource>.py` (Pydantic model)
2. Update `frontend/src/api/client.ts` (TypeScript interface)
3. Run `npx tsc --noEmit` — fix any type errors
4. Run `make test` — verify no API tests break

---

## Fixtures Reference

### `tests/conftest.py`

```python
@pytest.fixture(scope="session")
def client():
    """
    FastAPI TestClient backed by an in-memory SQLite DB.
    All migrations are applied before the session starts.
    Shared across all tests in the session for performance.
    """

@pytest.fixture(scope="session")
def auth_headers():
    """
    {"X-API-Key": "test-secret-key"}
    Matches TEST_API_SECRET set in the conftest environment override.
    """
```

### `crypto_bot/tests/conftest.py`

```python
@pytest.fixture
def flat_candles():
    """200 bars with no trend, low noise."""

@pytest.fixture
def uptrend_candles():
    """200 bars with strong upward trend (trend=0.2)."""

@pytest.fixture
def downtrend_candles():
    """200 bars with strong downward trend (trend=-0.2)."""

@pytest.fixture
def volatile_candles():
    """200 bars with high noise, no trend."""
```

---

## Coverage Requirements

| Module | Minimum |
|---|---|
| `crypto_bot/strategies/` | 80% |
| `api/routers/` | 70% |
| `api/schemas/` | 60% (Pydantic validates itself) |
| `crypto_bot/backtester/` | 60% |

Generate the report:
```bash
make test-cov
open htmlcov/index.html
```

---

## Writing Good Tests

### DO

```python
# ✅ One assertion per behaviour
def test_rsi_buy_requires_oversold_condition():
    ...
    assert signal.signal == Signal.BUY   # Not 3 things at once

# ✅ Descriptive test names — reads like a sentence
def test_dual_thrust_returns_hold_when_range_below_minimum_threshold():
    ...

# ✅ Test behaviour, not implementation
def test_strategy_emits_stop_loss_when_price_drops_through_stop():
    # Don't test that _stop_price is set — test the observable signal
    ...

# ✅ Use make_candles() helpers — not magic numbers
candles = make_candles(n=200, trend=0.1, noise=0.3, seed=42)

# ✅ Fixtures for shared setup
@pytest.fixture
def initialized_strategy():
    s = MyStrategy()
    s.initialize({"fast_ema": 9, "slow_ema": 21})
    return s
```

### DON'T

```python
# ❌ Don't test private methods directly
assert strategy._compute_ema(data, 9)[-1] == 42.3

# ❌ Don't use real exchange calls in unit/integration tests
# All tests must work offline

# ❌ Don't share mutable state between tests
class TestFoo:
    strategy = MyStrategy()   # ← WRONG — shared across all tests

    def setup_method(self):
        self.strategy = MyStrategy()   # ← CORRECT — fresh per test

# ❌ Don't assert floating point equality without tolerance
assert sharpe == 1.4523    # ← Will fail due to float math
assert abs(sharpe - 1.45) < 0.01   # ← Correct

# ❌ Don't swallow errors
try:
    result = strategy.on_candle(...)
except:
    pass   # ← Never do this in tests
```
