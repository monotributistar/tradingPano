# Logging Standards

This document defines how and where to log in TradingPano — which level to use, what format, how to get a logger, and what to include in each log entry.

Consistent logging makes debugging production issues fast and searching log files meaningful.

---

## Table of Contents

- [Log Levels](#log-levels)
- [Getting a Logger](#getting-a-logger)
- [Log Format](#log-format)
- [What to Log](#what-to-log)
- [What NOT to Log](#what-not-to-log)
- [Backend — Python](#backend--python)
- [Structured Fields](#structured-fields)
- [Log Rotation & Storage](#log-rotation--storage)
- [Viewing Logs](#viewing-logs)

---

## Log Levels

| Level | When to use | Example |
|---|---|---|
| `DEBUG` | Fine-grained internal state. Off in production. | EMA values, candle loop iterations |
| `INFO` | Normal operation milestones. On in production. | Strategy started, backtest completed, trade executed |
| `WARNING` | Something unexpected but recoverable. | Missing config key (using default), exchange rate limit |
| `ERROR` | Something failed that requires attention. | Strategy raised exception, exchange connection failed |
| `CRITICAL` | System cannot continue. | DB unavailable, unrecoverable crash |

**Rule of thumb:** if an operator reading logs in production should *know about it*, use `INFO`. If they need to *act on it*, use `WARNING` or `ERROR`.

---

## Getting a Logger

### Python (API + bot)

Always use a **module-level named logger**. Never use the root logger directly.

```python
import logging

logger = logging.getLogger(__name__)
```

`__name__` produces hierarchical names like `api.routers.bot`, `strategies.ema_crossover`, `backtester.runner` — which lets log levels be controlled per module.

**In strategy classes:**
```python
import logging

logger = logging.getLogger(__name__)

class EMACrossoverStrategy(BaseStrategy):
    def on_candle(self, pair, candles, position):
        logger.debug("ema_crossover.on_candle pair=%s bars=%d", pair, len(candles))
        ...
```

**In routers:**
```python
import logging
logger = logging.getLogger(__name__)

@router.post("/bot/start")
def start_bot(body: BotStartRequest):
    logger.info("bot.start mode=%s strategy=%s pairs=%s", body.mode, body.strategy, body.pairs)
    ...
```

---

## Log Format

All log entries follow this format:

```
2026-04-21T14:32:07 [INFO]  api.routers.bot: bot.start mode=paper strategy=ema_crossover pairs=['BTC/USDT']
2026-04-21T14:32:08 [DEBUG] strategies.ema_crossover: on_candle pair=BTC/USDT bars=420 fast_ema=9.42 slow_ema=8.91
2026-04-21T14:32:09 [WARNING] backtester.runner: warmup_short strategy=pullback bars=30 required=60
2026-04-21T14:32:10 [ERROR]  api.routers.backtests: backtest_failed id=42 error="exchange timeout"
```

Pattern: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`  
Date format: `%Y-%m-%dT%H:%M:%S` (ISO 8601, no microseconds)

---

## What to Log

### ✅ Always log

```python
# Major lifecycle events
logger.info("bot.started mode=%s strategy=%s pairs=%s", mode, strategy, pairs)
logger.info("bot.stopped reason=%s uptime_s=%.0f", reason, uptime)
logger.info("backtest.completed id=%d strategy=%s pair=%s duration_s=%.1f", id, strategy, pair, elapsed)

# Trade signals that result in action
logger.info(
    "signal.executed signal=%s pair=%s price=%.4f qty=%.6f reason=%r",
    signal.signal.value, signal.pair, signal.price, qty, signal.reason,
)

# Risk circuit breaker activations
logger.warning("risk.daily_loss_stop activated loss_pct=%.2f threshold=%.2f", loss_pct, threshold)
logger.warning("risk.max_drawdown reached drawdown_pct=%.2f max=%.2f", drawdown, max_dd)

# Errors with context
logger.error("exchange.fetch_ohlcv failed pair=%s tf=%s error=%s", pair, tf, str(e), exc_info=True)
logger.error("backtest.failed id=%d strategy=%s error=%s", job_id, strategy, str(e), exc_info=True)
```

### ✅ Log at DEBUG

```python
# Hot path computations (disabled in production)
logger.debug("indicator.ema pair=%s period=%d value=%.6f", pair, period, value)
logger.debug("on_candle pair=%s bars=%d pos=%s", pair, len(candles), position is not None)
logger.debug("signal.hold pair=%s reason=%r", pair, reason)
```

### ✅ Log warnings for degraded-but-operational states

```python
# Config key missing — using default
logger.warning("config.missing key=%r default=%r", key, default_value)

# Exchange returned fewer bars than requested
logger.warning(
    "ohlcv.short_response pair=%s tf=%s requested=%d got=%d",
    pair, tf, requested_bars, len(bars),
)

# Strategy returned unexpected signal type
logger.warning("signal.unexpected strategy=%s signal=%s", strategy_name, signal)
```

---

## What NOT to Log

```python
# ❌ Secrets or credentials
logger.info("connecting with api_key=%s", api_key)      # Never log keys

# ❌ PII (if any user data ever comes through)
logger.debug("user email=%s", email)

# ❌ Raw exception strings without exc_info=True (loses traceback)
logger.error("something failed: %s", str(e))             # Missing traceback
logger.error("something failed: %s", str(e), exc_info=True)  # Correct

# ❌ Spamming INFO in hot paths (use DEBUG)
for bar in candles:
    logger.info("processing bar %s", bar)   # Called thousands of times

# ❌ print() statements — use logger
print("starting bot")           # Wrong
logger.info("bot.starting")     # Correct
```

---

## Backend — Python

### Logging configuration

The API configures logging once at startup in `api/main.py → _setup_logging()`.

```python
def _setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = Path("data/bot.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # File handler — rotating, max 10 MB × 5 files = 50 MB total
    fh = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)

    # Console handler — rich output if available
    try:
        from rich.logging import RichHandler
        ch = RichHandler(rich_tracebacks=True, markup=False)
    except ImportError:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:   # Prevent duplicate handlers on reload
        root.addHandler(fh)
        root.addHandler(ch)
```

### Setting log level per module

In `.env`:
```dotenv
LOG_LEVEL=DEBUG   # All modules at DEBUG
```

For finer control in code:
```python
# Suppress noisy third-party library
logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
```

### Exception logging pattern

```python
try:
    result = do_something_risky()
except SomeSpecificError as e:
    logger.error("operation.failed context=... error=%s", str(e), exc_info=True)
    raise   # Re-raise unless you're truly handling it
except Exception as e:
    logger.critical("unexpected.error context=... error=%s", str(e), exc_info=True)
    raise
```

`exc_info=True` appends the full traceback to the log entry — **always include it on ERROR and CRITICAL**.

---

## Structured Fields

Use `key=value` pairs in message strings for easy log parsing and grepping:

```python
# ✅ Structured — grep-friendly
logger.info("trade.open pair=%s side=%s price=%.4f qty=%.6f", pair, side, price, qty)
logger.info("backtest.result id=%d strategy=%s sharpe=%.2f maxdd=%.2f winrate=%.1f",
            id, strategy, sharpe, maxdd, winrate)

# ❌ Unstructured — hard to search
logger.info("Opened a %s trade on %s at price %f", side, pair, price)
```

**Standard field names** — use these consistently:

| Field | Type | Example |
|---|---|---|
| `pair` | str | `BTC/USDT` |
| `strategy` | str | `ema_crossover` |
| `signal` | str | `BUY` · `SELL` · `HOLD` |
| `price` | float `%.4f` | `42156.7800` |
| `qty` | float `%.6f` | `0.002380` |
| `pnl` | float `%.4f` | `-1.2340` |
| `pnl_pct` | float `%.2f` | `-0.43` |
| `bars` | int | `420` |
| `id` | int | `42` |
| `mode` | str | `paper` · `live` |
| `tf` | str | `1h` · `4h` |
| `period` | str | `3m` · `1y` |
| `error` | str | error message (no newlines) |
| `elapsed` / `duration_s` | float `%.1f` | `12.3` |

---

## Log Rotation & Storage

The log file `data/bot.log` is managed by Python's `RotatingFileHandler`:

| Setting | Value |
|---|---|
| Max file size | 10 MB |
| Backup count | 5 files |
| Total max storage | ~50 MB |
| Encoding | UTF-8 |
| Rotation trigger | Size (not time) |

Older files are named `bot.log.1`, `bot.log.2`, … `bot.log.5`. File `bot.log.5` is overwritten when the 6th rotation occurs.

---

## Viewing Logs

```bash
# Live tail (development)
tail -f data/bot.log

# Live tail with level filter
tail -f data/bot.log | grep '\[ERROR\]\|\[WARNING\]'

# Docker
make docker-logs svc=api
make docker-dev-logs svc=api

# Search for a specific trade
grep 'pair=BTC/USDT signal=BUY' data/bot.log

# All errors from a specific strategy
grep 'strategies.pullback.*\[ERROR\]' data/bot.log

# Last N lines of most recent backup
tail -200 data/bot.log.1

# Count errors by type today
grep "$(date +%Y-%m-%dT)" data/bot.log | grep '\[ERROR\]' | wc -l
```
