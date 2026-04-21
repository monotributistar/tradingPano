# Strategy Development Guide

This guide walks through everything needed to add a new trading strategy to TradingPano — from the contract every strategy must satisfy, through implementation, registration, configuration, and testing.

---

## Table of Contents

- [The Strategy Contract](#the-strategy-contract)
- [Step-by-Step Checklist](#step-by-step-checklist)
- [Full Implementation Template](#full-implementation-template)
- [Signal Types Reference](#signal-types-reference)
- [Position Object Reference](#position-object-reference)
- [OHLCV Data Reference](#ohlcv-data-reference)
- [Common Indicator Helpers](#common-indicator-helpers)
- [Registering the Strategy](#registering-the-strategy)
- [Config Parameters](#config-parameters)
- [Frontend Indicator Map](#frontend-indicator-map)
- [Writing the Tests](#writing-the-tests)
- [Checklist Before PR](#checklist-before-pr)

---

## The Strategy Contract

Every strategy is a Python class that:
1. Extends `BaseStrategy` from `crypto_bot/strategies/base.py`
2. Implements four required methods: `initialize()`, `on_candle()`, `get_params()`, `reset()`
3. Declares class-level metadata attributes (used by the UI and recommendation engine)
4. Optionally implements `save_state()` / `load_state()` (required for live trading resume)

```python
from .base import BaseStrategy, Signal, TradeSignal
from typing import Optional
import pandas as pd

class MyStrategy(BaseStrategy):
    # ── Class-level metadata (used by API + UI) ───────────────
    name = "my_strategy"                      # snake_case, unique
    description = "One sentence description"  # shown in strategy picker
    ideal_timeframes = ["1h", "4h"]           # tuned timeframes
    min_period = "2m"                         # minimum backtest window
    market_type = "trending"                  # "trending"|"ranging"|"both"
    trade_frequency = "medium"                # "high"|"medium"|"low"
    min_liquidity = "medium"                  # "high"|"medium"|"any"
    suitable_timeframes = ["1h", "4h"]        # alias used by UI
    suitable_market_conditions = ["trending"]
    recommended_leverage = 2.0
    max_leverage = 8.0
    risk_profile = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   5.0,
        "position_size_pct": 5.0,
    }

    def initialize(self, config: dict) -> None: ...
    def on_candle(self, pair: str, candles: pd.DataFrame, position: Optional[dict]) -> TradeSignal: ...
    def get_params(self) -> dict: ...
    def reset(self) -> None: ...
```

---

## Step-by-Step Checklist

```
□ 1. Create  crypto_bot/strategies/<name>.py
□ 2. Register in api/main.py → get_strategy_registry()
□ 3. Add config to crypto_bot/config.yaml under strategies:<name>:
□ 4. Add indicators to frontend/src/lib/strategyIndicators.ts
□ 5. Write unit tests (4 signal types + warmup + state)
□ 6. python3 -m py_compile crypto_bot/strategies/<name>.py
□ 7. Verify registry loads: python3 -c "from api.main import get_strategy_registry; ..."
□ 8. cd frontend && npx tsc --noEmit
□ 9. make test
```

---

## Full Implementation Template

```python
"""
My Strategy Name
================
One-paragraph description of the strategy concept, edge, and when it works.

Entry conditions (LONG):
  - Condition A
  - Condition B

Entry conditions (SHORT):
  - Condition C

Exit:
  - ATR-based trailing stop
  - Take profit at tp_atr_mult × ATR
  - Time exit after max_bars_held bars

Edge: why this strategy has a statistical edge in the described conditions.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal

logger = logging.getLogger(__name__)


class MyStrategyName(BaseStrategy):
    # ── Metadata ─────────────────────────────────────────────────────────────
    name = "my_strategy"
    description = "Short description for the UI"
    ideal_timeframes: list = ["1h", "4h"]
    min_period: str = "2m"
    market_type: str = "trending"          # "trending" | "ranging" | "both"
    trade_frequency: str = "medium"        # "high" | "medium" | "low"
    min_liquidity: str = "medium"          # "high" | "medium" | "any"
    suitable_timeframes: list = ["1h", "4h"]
    suitable_market_conditions: list = ["trending"]
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   5.0,
        "position_size_pct": 5.0,
    }

    # ── Initialization ────────────────────────────────────────────────────────

    def initialize(self, config: dict) -> None:
        """Load parameters from config.yaml. Called once before any on_candle()."""
        self.param_a        = config.get("param_a", 20)
        self.param_b        = config.get("param_b", 50)
        self.atr_period     = config.get("atr_period", 14)
        self.stop_atr_mult  = config.get("stop_atr_mult", 2.0)
        self.tp_atr_mult    = config.get("tp_atr_mult", 3.5)
        self.max_bars_held  = config.get("max_bars_held", 40)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self.use_shorts     = config.get("use_shorts", True)

        # Internal state — must be reset between backtest runs
        self._stop_price: Optional[float] = None
        self._tp_price:   Optional[float] = None
        self._peak:       Optional[float] = None
        self._bars_held:  int = 0

    def reset(self) -> None:
        """Called before each backtest run. Clear all internal state."""
        self._stop_price = None
        self._tp_price   = None
        self._peak       = None
        self._bars_held  = 0

    # ── Indicator helpers ─────────────────────────────────────────────────────

    def _atr(self, candles: pd.DataFrame, period: int) -> float:
        """Wilder-smoothed Average True Range."""
        high  = candles["high"]
        low   = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    def _rsi(self, close: pd.Series, period: int) -> float:
        """Wilder RSI, returns float 0-100."""
        delta = close.diff().dropna()
        gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    # ── Signal generation ─────────────────────────────────────────────────────

    def on_candle(
        self, pair: str, candles: pd.DataFrame, position: Optional[dict]
    ) -> TradeSignal:
        """
        Called once per bar during backtesting and once per new candle in live mode.

        Args:
            pair:     Trading pair, e.g. "BTC/USDT"
            candles:  Full OHLCV DataFrame up to and including current bar.
                      Columns: open, high, low, close, volume
            position: Open position dict, or None if flat.

        Returns:
            TradeSignal with Signal enum + price + reason + metadata.
        """
        # ── Warmup guard ─────────────────────────────────────────────────────
        needed = max(self.param_a, self.param_b, self.atr_period) + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])
        atr   = self._atr(candles, self.atr_period)

        # ── Compute indicators ────────────────────────────────────────────────
        # ... your indicator calculations ...
        entry_signal_long  = False   # Replace with real condition
        entry_signal_short = False   # Replace with real condition

        # ── Manage open position ──────────────────────────────────────────────
        if position is not None:
            self._bars_held += 1
            side = position.get("side", "long")

            if side == "long":
                # Update peak for trailing stop
                if self._peak is None:
                    self._peak = price
                self._peak = max(self._peak, price)
                trailing_stop = self._peak - self.stop_atr_mult * atr

                # Hard stop
                if self._stop_price is not None and price <= self._stop_price:
                    s = self._stop_price
                    self.reset()
                    logger.info("signal.stop_loss pair=%s price=%.4f stop=%.4f", pair, price, s)
                    return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                       f"stop loss {s:.4f}", metadata={"atr": atr})

                # Trailing stop
                if price <= trailing_stop:
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"trailing stop {trailing_stop:.4f}",
                                       metadata={"peak": self._peak, "atr": atr})

                # Take profit
                if self._tp_price is not None and price >= self._tp_price:
                    tp = self._tp_price
                    self.reset()
                    return TradeSignal(Signal.SELL, pair, price, 0,
                                       f"take profit {tp:.4f}", metadata={"atr": atr})

                # Time exit
                if self._bars_held >= self.max_bars_held:
                    self.reset()
                    return TradeSignal(Signal.TIME_EXIT, pair, price, 0,
                                       f"time exit after {self._bars_held} bars")

            else:  # short
                if self._peak is None:
                    self._peak = price
                self._peak = min(self._peak, price)
                trailing_stop = self._peak + self.stop_atr_mult * atr

                if self._stop_price is not None and price >= self._stop_price:
                    s = self._stop_price
                    self.reset()
                    return TradeSignal(Signal.STOP_LOSS, pair, price, 0,
                                       f"stop loss {s:.4f}", metadata={"atr": atr})

                if price >= trailing_stop:
                    self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"trailing stop {trailing_stop:.4f}",
                                       metadata={"peak": self._peak, "atr": atr})

                if self._tp_price is not None and price <= self._tp_price:
                    tp = self._tp_price
                    self.reset()
                    return TradeSignal(Signal.COVER, pair, price, 0,
                                       f"take profit {tp:.4f}", metadata={"atr": atr})

                if self._bars_held >= self.max_bars_held:
                    self.reset()
                    return TradeSignal(Signal.TIME_EXIT, pair, price, 0,
                                       f"time exit after {self._bars_held} bars")

        # ── New entry ─────────────────────────────────────────────────────────
        else:
            self.reset()

            if entry_signal_long:
                stop = price - self.stop_atr_mult * atr
                tp   = price + self.tp_atr_mult   * atr
                self._stop_price = stop
                self._tp_price   = tp
                self._peak       = price
                self._bars_held  = 0
                logger.info("signal.buy pair=%s price=%.4f stop=%.4f tp=%.4f", pair, price, stop, tp)
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    "entry condition met",
                    metadata={"stop": round(stop, 4), "tp": round(tp, 4), "atr": round(atr, 6)},
                )

            if self.use_shorts and entry_signal_short:
                stop = price + self.stop_atr_mult * atr
                tp   = price - self.tp_atr_mult   * atr
                self._stop_price = stop
                self._tp_price   = tp
                self._peak       = price
                self._bars_held  = 0
                logger.info("signal.short pair=%s price=%.4f stop=%.4f tp=%.4f", pair, price, stop, tp)
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    "short entry condition met",
                    metadata={"stop": round(stop, 4), "tp": round(tp, 4), "atr": round(atr, 6)},
                )

        return TradeSignal(Signal.HOLD, pair, price, 0, "no signal",
                           metadata={"atr": round(atr, 6)})

    # ── Introspection ─────────────────────────────────────────────────────────

    def get_params(self) -> dict:
        """Return all current parameter values. Used by the API and optimizer."""
        return {
            "param_a":          self.param_a,
            "param_b":          self.param_b,
            "atr_period":       self.atr_period,
            "stop_atr_mult":    self.stop_atr_mult,
            "tp_atr_mult":      self.tp_atr_mult,
            "max_bars_held":    self.max_bars_held,
            "amount_per_trade": self.amount_per_trade,
            "use_shorts":       self.use_shorts,
        }

    def get_param_grid(self) -> dict:
        """Return search space for the parameter optimizer (optional but recommended)."""
        return {
            "param_a":       [10, 20, 30],
            "param_b":       [30, 50, 100],
            "stop_atr_mult": [1.5, 2.0, 2.5],
            "tp_atr_mult":   [2.5, 3.5, 5.0],
        }

    # ── State persistence (required for live trading resume) ─────────────────

    def save_state(self) -> dict:
        """Serialize internal state to DB before bot shuts down."""
        return {
            "stop_price": self._stop_price,
            "tp_price":   self._tp_price,
            "peak":       self._peak,
            "bars_held":  self._bars_held,
        }

    def load_state(self, state: dict) -> None:
        """Restore state after bot restarts (live trading only)."""
        self._stop_price = state.get("stop_price")
        self._tp_price   = state.get("tp_price")
        self._peak       = state.get("peak")
        self._bars_held  = state.get("bars_held", 0)
```

---

## Signal Types Reference

| Signal | Meaning | When to use |
|---|---|---|
| `Signal.BUY` | Open or add to long position | Price expected to rise |
| `Signal.SELL` | Close long position | Target reached, trend reversed |
| `Signal.SHORT` | Open short position | Price expected to fall |
| `Signal.COVER` | Close short position | Target reached, reversal |
| `Signal.STOP_LOSS` | Emergency close (respects side) | Price breached stop level |
| `Signal.TIME_EXIT` | Close due to max hold time | Max bars held exceeded |
| `Signal.HOLD` | No action | Default — no condition met |

`STOP_LOSS` and `TIME_EXIT` close the position regardless of side. The engine handles direction automatically.

---

## Position Object Reference

```python
position = {
    "side":       "long" | "short",
    "qty":        float,          # position size in base asset
    "avg_cost":   float,          # average entry price
    "entry_bar":  int,            # bar index when position was opened
    "bars_held":  int,            # how many bars the position has been open
    "entries":    list[dict],     # list of individual entry records (DCA)
    # For short positions:
    "collateral": float,          # collateral in USDT
}
```

`position` is `None` when there is no open position for this pair.

---

## OHLCV Data Reference

```python
candles: pd.DataFrame
# Index:   RangeIndex (0 to n-1) — NOT a DatetimeIndex
# Columns: open, high, low, close, volume   (all float64)

price  = float(candles["close"].iloc[-1])   # current bar's close
high   = float(candles["high"].iloc[-1])    # current bar's high
low    = float(candles["low"].iloc[-1])     # current bar's low
volume = float(candles["volume"].iloc[-1])  # current bar's volume
```

The DataFrame includes **all bars up to and including the current one**. Strategies should only look backward (use `.iloc[:-1]` for "prior bar" when needed to avoid look-ahead bias).

---

## Common Indicator Helpers

Copy these patterns into your strategy or import from a shared utility if added:

```python
# EMA
def _ema(self, close: pd.Series, period: int) -> float:
    return float(close.ewm(span=period, adjust=False).mean().iloc[-1])

# SMA
def _sma(self, close: pd.Series, period: int) -> float:
    return float(close.rolling(period).mean().iloc[-1])

# ATR (Wilder smoothing)
def _atr(self, candles: pd.DataFrame, period: int) -> float:
    high = candles["high"]; low = candles["low"]; close = candles["close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

# RSI (Wilder)
def _rsi(self, close: pd.Series, period: int) -> float:
    delta = close.diff().dropna()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return float((100 - (100 / (1 + rs))).iloc[-1])

# MACD
def _macd(self, close: pd.Series, fast: int, slow: int, signal: int):
    fast_e  = close.ewm(span=fast, adjust=False).mean()
    slow_e  = close.ewm(span=slow, adjust=False).mean()
    macd    = fast_e - slow_e
    sig     = macd.ewm(span=signal, adjust=False).mean()
    return float(macd.iloc[-1]), float(sig.iloc[-1]), float((macd - sig).iloc[-1])

# Bollinger Bands
def _bollinger(self, close: pd.Series, period: int, mult: float):
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    return float(sma.iloc[-1]), float((sma + mult * std).iloc[-1]), float((sma - mult * std).iloc[-1])
```

---

## Registering the Strategy

**File:** `api/main.py` → `get_strategy_registry()`

```python
def get_strategy_registry() -> dict:
    # ... existing imports ...
    from strategies.my_strategy import MyStrategyName   # ← Add this

    return {
        # ... existing entries ...
        "my_strategy": MyStrategyName,                   # ← Add this
    }
```

The key must exactly match the `name` class attribute on your strategy.

---

## Config Parameters

**File:** `crypto_bot/config.yaml` → `strategies:` section

```yaml
strategies:
  my_strategy:
    description: "Short description for humans"
    param_a: 20
    param_b: 50
    atr_period: 14
    stop_atr_mult: 2.0
    tp_atr_mult: 3.5
    max_bars_held: 40
    amount_per_trade: 10
    use_shorts: true
```

All values listed here become the **defaults** loaded by `initialize()` when no override is provided. They can also be overridden per-run in a `StrategyConfig` (via the Strategy Engine page in the dashboard).

---

## Frontend Indicator Map

**File:** `frontend/src/lib/strategyIndicators.ts`

Add an entry to `STRATEGY_INDICATORS` so the dashboard shows indicator overlays on price charts and chips on strategy cards:

```typescript
my_strategy: [
  // Price-panel overlays
  { id: "ema20",  label: "EMA(20)",  type: "ema",  params: { period: 20 }, panel: "price", color: "#60a5fa" },
  { id: "ema50",  label: "EMA(50)",  type: "ema",  params: { period: 50 }, panel: "price", color: "#f59e0b" },

  // Oscillator sub-panel (RSI or MACD — only one rendered)
  { id: "rsi",    label: "RSI(14)",  type: "rsi",  params: { period: 14 }, panel: "osc",   color: "#a78bfa",
    levels: [{ value: 35, color: "#22c55e", label: "OS" }, { value: 65, color: "#ef4444", label: "OB" }] },
],
```

**Supported indicator types:** `ema` · `sma` · `rsi` · `macd` · `bollinger` · `supertrend` · `atr` · `vwap`

**Panels:** `"price"` (overlaid on candles) · `"osc"` (sub-panel below volume)

Only the **first** `osc` indicator is rendered in the sub-panel. If your strategy uses MACD, the histogram + signal/macd lines are drawn automatically when `type: "macd"` is set.

---

## Writing the Tests

Location: `crypto_bot/tests/test_strategies.py`

Minimum test coverage for every new strategy:

```python
import pytest
import pandas as pd
import numpy as np
from strategies.my_strategy import MyStrategyName
from strategies.base import Signal


def make_candles(n=200, trend=0.0, noise=0.5, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] + trend + rng.normal(0, noise))
    prices = np.array(prices).clip(1)
    return pd.DataFrame({
        "open":   prices * (1 - rng.uniform(0, 0.002, n)),
        "high":   prices * (1 + rng.uniform(0, 0.005, n)),
        "low":    prices * (1 - rng.uniform(0, 0.005, n)),
        "close":  prices,
        "volume": rng.uniform(500, 1500, n),
    })


class TestMyStrategy:
    def setup_method(self):
        self.strategy = MyStrategyName()
        self.strategy.initialize({
            "param_a": 20,
            "param_b": 50,
            "atr_period": 14,
            "stop_atr_mult": 2.0,
            "amount_per_trade": 10.0,
        })

    def test_warmup_returns_hold(self):
        """Strategy must return HOLD before warmup period is complete."""
        tiny = make_candles(n=10)
        result = self.strategy.on_candle("BTC/USDT", tiny, position=None)
        assert result.signal == Signal.HOLD

    def test_buy_signal_in_favourable_condition(self):
        """BUY signal fires when entry conditions are met."""
        candles = make_candles(n=200, trend=0.15)   # Adjust to trigger your entry
        result = self.strategy.on_candle("BTC/USDT", candles, position=None)
        assert result.signal == Signal.BUY
        assert result.amount_usd > 0
        assert result.pair == "BTC/USDT"
        assert result.price > 0
        assert isinstance(result.reason, str) and result.reason

    def test_hold_when_no_signal(self):
        """No signal when conditions aren't met."""
        candles = make_candles(n=200, trend=0.0, noise=0.01)  # Flat market
        result = self.strategy.on_candle("BTC/USDT", candles, position=None)
        assert result.signal == Signal.HOLD

    def test_stop_loss_fires_when_price_below_stop(self):
        """Stop loss triggers when price falls through the stop level."""
        candles = make_candles(n=200, trend=0.1)
        position = {"side": "long", "qty": 0.1, "avg_cost": 100.0, "bars_held": 3}
        self.strategy._stop_price = 999.0   # Force stop above any reasonable price
        result = self.strategy.on_candle("BTC/USDT", candles, position=position)
        assert result.signal == Signal.STOP_LOSS

    def test_time_exit_after_max_bars(self):
        """Position closes after max_bars_held regardless of price."""
        candles = make_candles(n=200, trend=0.0)
        position = {"side": "long", "qty": 0.1, "avg_cost": 100.0, "bars_held": 0}
        self.strategy._bars_held = 999   # Force time exit
        result = self.strategy.on_candle("BTC/USDT", candles, position=position)
        assert result.signal in (Signal.TIME_EXIT, Signal.SELL)

    def test_reset_clears_all_state(self):
        """reset() must clear everything set during initialize or on_candle."""
        self.strategy._stop_price = 50.0
        self.strategy._peak = 120.0
        self.strategy._bars_held = 10
        self.strategy.reset()
        assert self.strategy._stop_price is None
        assert self.strategy._peak is None
        assert self.strategy._bars_held == 0

    def test_get_params_returns_all_keys(self):
        """get_params() must return every configurable parameter."""
        params = self.strategy.get_params()
        for key in ["param_a", "param_b", "atr_period", "stop_atr_mult", "amount_per_trade"]:
            assert key in params, f"Missing key: {key}"

    def test_save_and_restore_state(self):
        """State round-trips through save_state / load_state."""
        self.strategy._stop_price = 42.5
        self.strategy._peak = 110.0
        state = self.strategy.save_state()
        self.strategy.reset()
        self.strategy.load_state(state)
        assert self.strategy._stop_price == 42.5
        assert self.strategy._peak == 110.0
```

---

## Checklist Before PR

```
□ Strategy file: crypto_bot/strategies/<name>.py
    □ Extends BaseStrategy
    □ All metadata class attributes set
    □ initialize() loads all params from config dict with .get(key, default)
    □ on_candle() has warmup guard at the top
    □ on_candle() handles both position=None and position=<dict>
    □ reset() clears ALL internal state
    □ get_params() returns ALL configurable parameters
    □ save_state() / load_state() round-trips correctly
    □ logger = logging.getLogger(__name__) at module level
    □ INFO logged on BUY/SHORT/SELL/COVER/STOP_LOSS signals

□ Registry: api/main.py
    □ Import added
    □ Entry added to return dict

□ Config: crypto_bot/config.yaml
    □ Section added under strategies:
    □ All parameters with sensible defaults

□ Frontend: frontend/src/lib/strategyIndicators.ts
    □ Entry added to STRATEGY_INDICATORS
    □ At least one price-panel indicator
    □ Oscillator indicator if strategy uses RSI or MACD

□ Tests: crypto_bot/tests/test_strategies.py
    □ warmup → HOLD
    □ entry condition → BUY (or SHORT)
    □ stop loss fires
    □ time exit fires
    □ reset() works
    □ get_params() contains all keys
    □ save_state/load_state round-trips

□ Verification:
    □ python3 -m py_compile crypto_bot/strategies/<name>.py → no errors
    □ Registry instantiates and initializes without error
    □ cd frontend && npx tsc --noEmit → 0 errors
    □ make test → all pass
```
