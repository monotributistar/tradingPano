# CONTRACTS.md — Type Contracts and Interface Reference

> This document is the canonical reference for every type boundary in TradingPano:
> Python strategy interfaces, Pydantic API schemas, and their TypeScript counterparts.
>
> When a type changes, update it here and in **both** the Pydantic schema and the
> TypeScript interface in `frontend/src/api/client.ts`, then run
> `cd frontend && npx tsc --noEmit` to verify zero errors.

---

## Table of Contents

- [Strategy Contract — Python](#strategy-contract--python)
  - [Signal enum](#signal-enum)
  - [TradeSignal dataclass](#tradesignal-dataclass)
  - [BaseStrategy ABC](#basestrategy-abc)
  - [position dict](#position-dict)
  - [candles DataFrame](#candles-dataframe)
- [API Request / Response Schemas](#api-request--response-schemas)
  - [POST /api/backtests — BacktestCreate](#post-apibacktests--backtestcreate)
  - [GET /api/backtests/{id} — BacktestJobResponse](#get-apibacktestsid--backtestjobresponse)
  - [BacktestMetrics](#backtestmetrics)
  - [POST /api/bot/start — BotStartRequest](#post-apibotstart--botstarrequest)
  - [GET /api/bot/status — BotStatusResponse](#get-apibotstatus--botstatusresponse)
  - [GET /api/strategies — StrategyInfo](#get-apistrategies--strategyinfo)
  - [Trade object](#trade-object)
  - [WalletSnapshot](#walletsnapshot)
  - [StrategyConfig](#strategyconfig)
  - [BotEvent](#botevent)
- [TypeScript Counterparts](#typescript-counterparts)
- [Invariants and Validation Rules](#invariants-and-validation-rules)
- [OANDA Engine Contracts](#oanda-engine-contracts)
  - [BaseEngine optional CFD methods](#baseengine--optional-cfd-methods)
  - [get_balance() OandaEngine shape](#get_balance-return-shape-oandaengine)
  - [_place_order() return shape](#_place_order-return-shape)
  - [get_margin_info() return shape](#get_margin_info-return-shape)
  - [MarginMonitor.check_once() return shape](#marginmonitorcheck_once-return-shape)
  - [BacktestRunner total_swap_cost key](#backtestrunnerrun--additional-result-key)
- [Contract Change Protocol](#contract-change-protocol)

---

## Strategy Contract — Python

Source: `crypto_bot/strategies/base.py`

### Signal enum

```python
class Signal(Enum):
    BUY       = "buy"        # Open or add to a long position
    SELL      = "sell"       # Close a long position
    HOLD      = "hold"       # No action this bar
    STOP_LOSS = "stop_loss"  # Emergency close (honours position side)
    TIME_EXIT = "time_exit"  # Time-based close (honours position side)
    SHORT     = "short"      # Open a short position (futures)
    COVER     = "cover"      # Close a short position
```

**Rules:**
- `STOP_LOSS` and `TIME_EXIT` close the position regardless of side. The engine resolves
  direction from the open `position` dict.
- A strategy must never emit `SELL` when there is no open position, and must never
  emit `BUY` when already long (use `HOLD` and let the engine manage the state).
- During the warmup period (insufficient bars), always return `Signal.HOLD`.

---

### TradeSignal dataclass

```python
@dataclass
class TradeSignal:
    signal:     Signal        # Required — action to take
    pair:       str           # Required — e.g. "BTC/USDT"
    price:      float         # Required — reference price for sizing (last close)
    amount_usd: float         # Required — desired position size in USDT (0 for exits)
    reason:     str           # Required — human-readable explanation (stored on trade record)
    confidence: float = 1.0   # Optional — normalised score [0, 1], informational only
    metadata:   dict  = {}    # Optional — extra data for risk manager, e.g. {"atr": 42.0, "stop": 100.0}
```

**Field constraints:**

| Field | Valid range | Notes |
|---|---|---|
| `signal` | Any `Signal` member | Never `None` |
| `pair` | `"BASE/QUOTE"` format | e.g. `"BTC/USDT"`, `"ETH/USDT"` |
| `price` | `> 0` | Last bar close price |
| `amount_usd` | `>= 0` | Use `0` for all exit signals (SELL, COVER, STOP_LOSS, TIME_EXIT, HOLD) |
| `reason` | Non-empty string | Written to the `reason` column on the trade record |
| `confidence` | `[0.0, 1.0]` | Informational; the risk manager currently ignores it |
| `metadata` | JSON-serialisable dict | Common keys: `stop`, `tp`, `atr`, `peak` |

**Construction examples:**

```python
# Entry signal
TradeSignal(
    Signal.BUY, "BTC/USDT", price, self.amount_per_trade,
    "golden cross ema9/ema21",
    metadata={"stop": round(stop, 4), "tp": round(tp, 4), "atr": round(atr, 6)},
)

# Exit signal (amount_usd is always 0 for exits)
TradeSignal(Signal.STOP_LOSS, "BTC/USDT", price, 0, f"stop loss hit at {stop:.4f}")

# Warmup / no-signal
TradeSignal(Signal.HOLD, "BTC/USDT", price, 0, "warmup")
TradeSignal(Signal.HOLD, "BTC/USDT", price, 0, "no signal", metadata={"atr": atr})
```

---

### BaseStrategy ABC

Full source: `crypto_bot/strategies/base.py`

```python
class BaseStrategy(ABC):
    # ── Required class-level metadata ──────────────────────────────────────────
    name:                       str    # Unique snake_case ID — matches registry key + config key
    description:                str    # One-line description shown in UI strategy picker

    ideal_timeframes:           list   # e.g. ["1h", "4h"] — tuned candle sizes
    min_period:                 str    # Minimum backtest window, e.g. "3m"
    market_type:                str    # "trending" | "ranging" | "both"
    trade_frequency:            str    # "high" | "medium" | "low"
    min_liquidity:              str    # "high" | "medium" | "any"
    suitable_timeframes:        list   # Alias for ideal_timeframes (used by Strategy Engine)
    suitable_market_conditions: list   # ["trending", "ranging", "high_vol", …]
    recommended_leverage:       float  # Default leverage shown in Risk Profile form
    max_leverage:               float  # Strategy-level ceiling — never > 15x global cap
    risk_profile:               dict   # {"stop_loss_pct": 2.0, "take_profit_pct": 5.0, "position_size_pct": 5.0}

    # ── Required abstract methods ───────────────────────────────────────────────

    @abstractmethod
    def initialize(self, config: dict) -> None:
        """
        Load strategy parameters from the config dict.
        Called once before any on_candle() calls.
        Always use config.get("key", default) — never assume a key exists.

        Args:
            config: Strategy section from config.yaml, e.g.
                    {"fast_ema": 9, "slow_ema": 21, "amount_per_trade": 10}
        """

    @abstractmethod
    def on_candle(
        self,
        pair:     str,
        candles:  pd.DataFrame,
        position: Optional[dict],
    ) -> TradeSignal:
        """
        Process the latest candle and return a trading signal.
        Called once per bar during backtesting, once per closed candle during live.

        Args:
            pair:     Trading pair, e.g. "BTC/USDT"
            candles:  Full OHLCV DataFrame up to and including the current bar.
                      Index is RangeIndex (not DatetimeIndex).
                      Columns: open, high, low, close, volume (all float64)
            position: Open position dict (see position dict reference below),
                      or None when the strategy is flat.

        Returns:
            TradeSignal — never None, never raises.
        """

    @abstractmethod
    def get_params(self) -> dict:
        """
        Return current parameter values for the API and optimizer.
        Must include every key loaded in initialize().

        Returns:
            dict mapping param_name → current value
        """

    # ── Optional methods (override if needed) ──────────────────────────────────

    def reset(self) -> None:
        """
        Reset all internal state between backtest runs.
        Called by BacktestRunner before each simulation.
        Override if your strategy accumulates state across bars.
        After reset(), on_candle() must behave as if just initialized.
        """

    def get_param_grid(self) -> dict:
        """
        Return parameter search space for the optimizer.
        Returns: dict mapping param_name → list[candidate_values]
        Example: {"fast_ema": [5, 9, 12], "stop_atr_mult": [1.5, 2.0, 2.5]}
        """
        return {}

    def save_state(self) -> dict:
        """
        Serialise internal state for live-engine persistence.
        Required for live trading with position resume.
        Returns: JSON-serialisable dict passable to load_state().
        """
        return {}

    def load_state(self, state: dict) -> None:
        """
        Restore internal state from a previously saved dict.
        Called by the engine when restore=True on bot start.
        Args:
            state: Dict returned by a previous save_state() call.
        """
```

---

### position dict

The `position` argument passed to `on_candle()` when a position is open:

```python
position: dict | None = {
    "side":       "long" | "short",
    "qty":        float,      # position size in base asset units
    "avg_cost":   float,      # average entry price in USDT
    "entry_bar":  int,        # bar index (candles.index) when position was opened
    "bars_held":  int,        # number of bars the position has been open
    "entries":    list[dict], # individual entry records for DCA strategies
    # Short positions only:
    "collateral": float,      # collateral locked in USDT
}
```

`position` is `None` when the strategy is flat (no open position for this pair).

---

### candles DataFrame

```python
candles: pd.DataFrame
# Index:   RangeIndex(0, n)     — NOT a DatetimeIndex
# Columns: open, high, low, close, volume   (all float64)
# Sorted:  ascending (oldest first, newest last)

# Access current bar
price  = float(candles["close"].iloc[-1])
high   = float(candles["high"].iloc[-1])
low    = float(candles["low"].iloc[-1])
volume = float(candles["volume"].iloc[-1])

# Prior bar (use iloc[-2] to avoid look-ahead bias)
prev_close = float(candles["close"].iloc[-2])

# Full series (for indicator calculations)
close_series = candles["close"]   # pd.Series of floats
```

The DataFrame always includes **all bars up to and including the current one**.
Access `iloc[-1]` for the current bar. Use `iloc[:-1]` for the "prior bars" view
to eliminate look-ahead bias in indicator calculations.

---

## API Request / Response Schemas

Source: `api/schemas/` (Pydantic v2)  
Interactive docs: `http://localhost:8000/docs`

---

### POST /api/backtests — BacktestCreate

**Source:** `api/schemas/backtest.py::BacktestCreate`

```python
class BacktestCreate(BaseModel):
    strategy:  str  # Required — registered strategy name
    pair:      str  = "BTC/USDT"   # BASE/QUOTE format
    period:    str  = "6m"         # History window
    timeframe: str  = "1h"         # Candle size
    params:    dict = {}           # Strategy parameter overrides (optional)
```

**Supported timeframes:** `15m` · `30m` · `1h` · `2h` · `4h` · `6h` · `8h` · `12h` · `1d` · `1w`

**Supported periods:** `1w` · `2w` · `1m` · `2m` · `3m` · `6m` · `9m` · `1y` · `18m` · `2y` · `3y` · `4y` · `5y`

**JSON example:**
```json
{
  "strategy": "stoch_rsi",
  "pair": "NEAR/USDT",
  "period": "6m",
  "timeframe": "4h"
}
```

**Errors:**
- `404` — strategy name not found in registry
- `422` — timeframe or period not in the allowed set

---

### GET /api/backtests/{id} — BacktestJobResponse

**Source:** `api/schemas/backtest.py::BacktestJobResponse`

```python
class BacktestJobResponse(BaseModel):
    id:                int
    strategy:          str
    pair:              str
    period:            str
    timeframe:         str
    status:            str              # "pending" | "running" | "done" | "error"
    error_msg:         Optional[str]    # Populated only when status="error"
    metrics:           Optional[dict]   # BacktestMetrics (populated when status="done")
    equity_curve:      Optional[list[float]]  # Portfolio value per bar (post-warmup)
    equity_timestamps: Optional[list[str]]    # ISO 8601 UTC string per equity bar
    params:            Optional[dict]   # Strategy params used for this run
    created_at:        datetime         # UTC
    started_at:        Optional[datetime]
    finished_at:       Optional[datetime]
```

**Status lifecycle:** `pending` → `running` → `done` | `error`

**JSON example (completed):**
```json
{
  "id": 42,
  "strategy": "stoch_rsi",
  "pair": "NEAR/USDT",
  "period": "6m",
  "timeframe": "4h",
  "status": "done",
  "error_msg": null,
  "metrics": { "total_return_pct": 18.4, "sharpe_ratio": 1.82, "... " : "..." },
  "equity_curve": [20.0, 20.15, 19.87, "..."],
  "equity_timestamps": ["2025-10-01T00:00:00Z", "..."],
  "params": { "rsi_period": 14, "stoch_period": 14 },
  "created_at": "2026-04-21T14:00:00Z",
  "started_at":  "2026-04-21T14:00:01Z",
  "finished_at": "2026-04-21T14:00:08Z"
}
```

---

### BacktestMetrics

**Source:** `api/schemas/backtest.py::BacktestMetrics`

```python
class BacktestMetrics(BaseModel):
    # Returns
    total_return_pct:            float   # Strategy return in %, e.g. 18.4 means +18.4%
    final_capital:               float   # Final portfolio value in USDT
    initial_capital:             float   # Starting capital in USDT

    # Risk-adjusted returns
    sharpe_ratio:                float   # Annualised Sharpe (risk-free rate = 0)
    sortino_ratio:                float   # Annualised Sortino

    # Drawdown
    max_drawdown_pct:            float   # Max peak-to-trough drawdown (positive %)
    max_drawdown_duration_bars:  Optional[int]   # Bars from drawdown peak to recovery

    # Trade statistics
    win_rate_pct:                float   # % of closed trades that were profitable
    profit_factor:               float   # Gross profit / gross loss (> 1 is profitable)
    total_trades:                int     # Total completed round-trips
    avg_trade_duration_bars:     float   # Mean trade duration in candles
    expectancy_usd:              float   # Expected USD profit per trade
    capital_utilization_pct:     float   # Average % of capital deployed per trade
    avg_win_usd:                 Optional[float]  # Average winning trade in USDT
    avg_loss_usd:                Optional[float]  # Average losing trade in USDT (negative)
```

---

### POST /api/bot/start — BotStartRequest

**Source:** `api/schemas/bot.py::BotStartRequest`

```python
class BotStartRequest(BaseModel):
    mode:               str           = "paper"          # "paper" | "live"
    strategy:           str           = "mean_reversion" # Registered strategy name
    pairs:              list[str]     = ["BTC/USDT"]     # Trading pairs
    restore:            bool          = False             # Resume from last saved state
    strategy_config_id: Optional[int] = None             # Override all from StrategyConfig
```

**Field notes:**
- `strategy` is ignored when `strategy_config_id` is provided — the config's
  `execution_strategy` takes precedence.
- `pairs` is overridden by the config's `pairs` if `strategy_config_id` is set
  and the config has non-empty pairs.
- `restore=True` re-loads `BotState` from the DB (open positions, strategy state).
  Use this after a VPS reboot or manual stop with live positions open.

**JSON example:**
```json
{
  "mode": "paper",
  "strategy": "stoch_rsi",
  "pairs": ["BTC/USDT", "ETH/USDT"],
  "restore": false,
  "strategy_config_id": null
}
```

**Responses:**
- `200` → `{"status": "started", "mode": "paper", "strategy": "stoch_rsi"}`
- `409` → `{"detail": "Bot is already running"}`
- `404` → `{"detail": "Strategy 'xyz' not found"}`

---

### GET /api/bot/status — BotStatusResponse

**Source:** `api/schemas/bot.py::BotStatusResponse`

```python
class BotStatusResponse(BaseModel):
    running:              bool
    crashed:              bool          # True when watchdog detected unexpected thread death
    mode:                 Optional[str] # "paper" | "live" | None
    strategy:             Optional[str] # Active strategy name, or None
    pairs:                list[str]
    started_at:           Optional[str] # ISO-8601 UTC
    uptime_seconds:       Optional[float]
    error:                Optional[str] # Last crash message
    equity_usdt:          Optional[float]
    positions:            dict          # { "BTC/USDT": { "side": "long", "qty": 0.001, ... } }
    last_signal:          Optional[str] # Last Signal enum value
    last_signal_at:       Optional[str] # ISO-8601 UTC
    ws_connected:         bool
    strategy_config_id:   Optional[int]
    strategy_config_name: Optional[str]
```

**JSON example (running):**
```json
{
  "running": true,
  "crashed": false,
  "mode": "paper",
  "strategy": "stoch_rsi",
  "pairs": ["BTC/USDT"],
  "started_at": "2026-04-21T10:00:00Z",
  "uptime_seconds": 14400,
  "error": null,
  "equity_usdt": 21.45,
  "positions": {
    "BTC/USDT": { "side": "long", "qty": 0.0005, "avg_cost": 42100.0 }
  },
  "last_signal": "BUY",
  "last_signal_at": "2026-04-21T13:45:00Z",
  "ws_connected": true,
  "strategy_config_id": null,
  "strategy_config_name": null
}
```

---

### GET /api/strategies — StrategyInfo

```json
[
  {
    "name":                      "ema_crossover",
    "description":               "Golden/death cross momentum strategy",
    "ideal_timeframes":          ["1h", "4h", "1d"],
    "min_period":                "2m",
    "market_type":               "trending",
    "trade_frequency":           "medium",
    "min_liquidity":             "any",
    "suitable_timeframes":       ["1h", "4h"],
    "suitable_market_conditions":["trending"],
    "recommended_leverage":      2.0,
    "max_leverage":              8.0,
    "risk_profile": {
      "stop_loss_pct":     2.0,
      "take_profit_pct":   5.0,
      "position_size_pct": 5.0
    },
    "params": {
      "fast_ema": 9,
      "slow_ema": 21,
      "amount_per_trade": 5
    },
    "param_grid": {
      "fast_ema": [5, 9, 12],
      "slow_ema": [21, 26, 50]
    }
  }
]
```

This is a live introspection of the registry: each entry is built from the strategy
class attributes + `get_params()` + `get_param_grid()` of a freshly initialised instance.

---

### Trade object

Returned by `GET /api/trades` and pushed via WebSocket (`type: "trade"`):

```json
{
  "id":             1,
  "source":         "paper",
  "backtest_job_id": null,
  "type":           "buy",
  "pair":           "BTC/USDT",
  "strategy":       "stoch_rsi",
  "price":          42156.78,
  "qty":            0.000237,
  "fee":            0.004,
  "pnl":            null,
  "pnl_pct":        null,
  "reason":         "stoch_rsi oversold cross",
  "duration_bars":  null,
  "timestamp":      "2026-04-21T14:32:00Z"
}
```

`pnl` and `pnl_pct` are `null` for entry trades (buy/short) and populated for
exit trades (sell/cover/stop_loss/time_exit).

---

### WalletSnapshot

Returned by `GET /api/wallet/history` and pushed via WebSocket (`type: "equity"`):

```json
{
  "id":               1,
  "source":           "paper",
  "balance_usdt":     19.5,
  "positions_value":  2.1,
  "total_equity":     21.6,
  "positions": {
    "BTC/USDT": { "qty": 0.0005, "avg_cost": 42000.0 }
  },
  "timestamp": "2026-04-21T14:00:00Z"
}
```

`total_equity = balance_usdt + positions_value` (mark-to-market).

---

### StrategyConfig

Saved composable configuration (execution strategy + HTF filter + risk + pairs).

```json
{
  "id":                       1,
  "name":                     "BTC Trend Follower",
  "execution_strategy":       "stoch_rsi",
  "execution_timeframe":      "1h",
  "trend_filter_strategy":    "ema_crossover",
  "trend_filter_timeframe":   "4h",
  "risk_profile": {
    "stop_loss_pct":       2.0,
    "take_profit_pct":     5.0,
    "position_size_pct":   5.0,
    "leverage":            3.0,
    "max_drawdown_pct":    8.0,
    "daily_loss_stop_pct": 3.0
  },
  "pairs":       ["BTC/USDT"],
  "notes":       "Conservative BTC trend config",
  "created_at":  "2026-04-01T00:00:00Z",
  "updated_at":  "2026-04-21T00:00:00Z"
}
```

---

### BotEvent

Immutable audit log of lifecycle transitions. Returned by `GET /api/bot/events`
and pushed via WebSocket (`type: "event"`):

```json
{
  "id":          1,
  "event_type":  "start",
  "mode":        "paper",
  "strategy":    "stoch_rsi",
  "pairs":       ["BTC/USDT"],
  "detail":      null,
  "positions":   {},
  "occurred_at": "2026-04-21T10:00:00Z"
}
```

**`event_type` values:** `start` · `stop` · `crash` · `halt` · `resume` · `watchdog`

---

## TypeScript Counterparts

All TypeScript interfaces live in `frontend/src/api/client.ts`.
They must mirror the Pydantic schemas exactly.

```typescript
// Mirrors BacktestCreate
export interface BacktestCreate {
  strategy:  string;
  pair:      string;
  period:    string;
  timeframe: string;
  params?:   Record<string, unknown>;
}

// Mirrors BacktestJobResponse
export interface BacktestJobResponse {
  id:                  number;
  strategy:            string;
  pair:                string;
  period:              string;
  timeframe:           string;
  status:              "pending" | "running" | "done" | "error";
  error_msg:           string | null;
  metrics:             BacktestMetrics | null;
  equity_curve:        number[] | null;
  equity_timestamps:   string[] | null;
  params:              Record<string, unknown> | null;
  created_at:          string;  // ISO-8601
  started_at:          string | null;
  finished_at:         string | null;
}

// Mirrors BacktestMetrics
export interface BacktestMetrics {
  total_return_pct:           number;
  final_capital:              number;
  initial_capital:            number;
  sharpe_ratio:               number;
  sortino_ratio:              number;
  max_drawdown_pct:           number;
  max_drawdown_duration_bars: number | null;
  win_rate_pct:               number;
  profit_factor:              number;
  total_trades:               number;
  avg_trade_duration_bars:    number;
  expectancy_usd:             number;
  capital_utilization_pct:    number;
  avg_win_usd:                number | null;
  avg_loss_usd:               number | null;
}

// Mirrors BotStartRequest
export interface BotStartRequest {
  mode:               "paper" | "live";
  strategy:           string;
  pairs:              string[];
  restore:            boolean;
  strategy_config_id: number | null;
}

// Mirrors BotStatusResponse
export interface BotStatusResponse {
  running:              boolean;
  crashed:              boolean;
  mode:                 "paper" | "live" | null;
  strategy:             string | null;
  pairs:                string[];
  started_at:           string | null;
  uptime_seconds:       number | null;
  error:                string | null;
  equity_usdt:          number | null;
  positions:            Record<string, { side: string; qty: number; avg_cost: number }>;
  last_signal:          string | null;
  last_signal_at:       string | null;
  ws_connected:         boolean;
  strategy_config_id:   number | null;
  strategy_config_name: string | null;
}

// Mirrors Trade
export interface Trade {
  id:              number;
  source:          "paper" | "live" | "backtest";
  backtest_job_id: number | null;
  type:            "buy" | "sell" | "short" | "cover";
  pair:            string;
  strategy:        string;
  price:           number;
  qty:             number;
  fee:             number;
  pnl:             number | null;
  pnl_pct:         number | null;
  reason:          string;
  duration_bars:   number | null;
  timestamp:       string;
}

// Mirrors StrategyInfo
export interface StrategyInfo {
  name:                       string;
  description:                string;
  ideal_timeframes:           string[];
  min_period:                 string;
  market_type:                "trending" | "ranging" | "both";
  trade_frequency:            "high" | "medium" | "low";
  min_liquidity:              "high" | "medium" | "any";
  suitable_timeframes:        string[];
  suitable_market_conditions: string[];
  recommended_leverage:       number;
  max_leverage:               number;
  risk_profile:               { stop_loss_pct: number; take_profit_pct: number; position_size_pct: number };
  params:                     Record<string, unknown>;
  param_grid:                 Record<string, unknown[]>;
}
```

---

## Invariants and Validation Rules

These invariants must hold at all times. Tests should encode them explicitly.

### Signal invariants

- A strategy must never raise an exception from `on_candle()`. Errors must be caught
  internally and a `HOLD` signal returned.
- `amount_usd` must be `0` for all exit signals (`SELL`, `COVER`, `STOP_LOSS`, `TIME_EXIT`, `HOLD`).
- A strategy must return `HOLD` when `len(candles) < warmup_period`.
- `reason` must never be an empty string.

### API invariants

- Every protected endpoint returns `403` (not `401`) when `X-API-Key` is missing or wrong.
- `GET /api/backtests/{id}` returns `404` (not `500`) for unknown IDs.
- `POST /api/bot/start` returns `409` when the bot is already running.
- `metrics` is `null` on a `BacktestJobResponse` until `status == "done"`.
- `equity_curve` and `equity_timestamps` always have the same length when non-null.
- `total_equity == balance_usdt + positions_value` on every `WalletSnapshot`.

### Metric value ranges

| Field | Expected range |
|---|---|
| `win_rate_pct` | `[0, 100]` |
| `max_drawdown_pct` | `>= 0` |
| `profit_factor` | `>= 0` (0 = all losses, 1 = breakeven) |
| `sharpe_ratio` | Any real number (negative means underperformed risk-free) |
| `total_trades` | `>= 0` |
| `avg_trade_duration_bars` | `>= 0` |

---

## OANDA Engine Contracts

### BaseEngine — optional CFD methods

Source: `crypto_bot/engine/base.py`

These methods have default no-op implementations in `BaseEngine` so that
`LiveEngine` and `PaperEngine` work unchanged.  `OandaEngine` overrides all four.

```python
def short_open(self, pair: str, usdt_amount: float) -> dict:
    """Open a short position. Default: returns {"status": "unsupported"}."""

def short_cover(self, pair: str, qty: float) -> dict:
    """Close a short position. Default: returns {"status": "unsupported"}."""

def get_margin_info(self) -> dict:
    """Return CFD margin info. Default: returns {}."""

def get_financing_cost(self) -> float:
    """Return total accrued overnight financing. Default: returns 0.0."""
```

### `get_balance()` return shape (OandaEngine)

```python
{
    "USDT":         float,   # account balance (base currency)
    "nav":          float,   # net asset value
    "unrealizedPL": float,   # open position unrealized P&L
    "margin_used":  float,   # margin currently allocated
    "margin_avail": float,   # margin available for new positions
    "margin_level": float,   # (NAV / margin_used) × 100; 9999.0 if no positions
}
```

### `_place_order()` return shape

```python
# Success:
{"status": "filled", "price": float, "qty": float, "fee": float, "order_id": str}

# Failure (any exception):
{"status": "error", "reason": str}
```

### `get_margin_info()` return shape

```python
{
    "margin_level":     float,   # % — 9999.0 when no open positions
    "margin_used":      float,
    "margin_available": float,
    "nav":              float,
}
```

### `MarginMonitor.check_once()` return shape

Source: `crypto_bot/margin_monitor.py`

```python
# Normal cases:
{"level": float, "action": "ok" | "warn" | "alert" | "stop"}

# Engine error:
{"level": 0.0, "action": "error", "error": str}
```

Action thresholds:

| `action` | Condition |
|---|---|
| `"ok"` | level > 200% (or 9999 — no open positions) |
| `"warn"` | 150% < level ≤ 200% |
| `"alert"` | 110% < level ≤ 150% — Telegram notifier called |
| `"stop"` | level ≤ 110% — notifier + `bot_manager.stop()` |
| `"error"` | `get_margin_info()` raised an exception |

### `BacktestRunner.run()` — additional result key

When `config["backtest"]["swap_cost_daily_pct"] > 0`:

```python
result["total_swap_cost"]  # float — total financing deducted from balance
```

The equity curve and metrics already reflect this deduction.  The key is
always present (value `0.0` when swap rate is `0`).

---

## Contract Change Protocol

When changing any type boundary (Pydantic schema, Signal enum, TradeSignal fields):

1. Update the Pydantic model in `api/schemas/<resource>.py`
2. Update the matching TypeScript interface in `frontend/src/api/client.ts`
3. Run `cd frontend && npx tsc --noEmit` — zero errors required
4. Run `make test` — no regressions
5. Update this file (`docs/CONTRACTS.md`) to reflect the change
6. Update `docs/api-contracts.md` if the change affects an API endpoint

**Never** change a response field name without updating both layers simultaneously.
The TypeScript check in CI will catch mismatches, but only if both sides are updated.
