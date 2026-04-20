"""
api/main.py — FastAPI application factory
==========================================

Responsibilities
----------------
- Build and configure the FastAPI application
- Register all routers (protected with ``X-API-Key`` authentication)
- Set up structured logging with rotation on startup
- Expose ``/api/health`` without authentication (Docker / nginx healthcheck)
- Load and expose ``config.yaml`` (secrets stripped)

Authentication
--------------
Every endpoint except ``GET /api/health`` requires the ``X-API-Key`` header.
Set ``BOT_API_SECRET`` in the environment.  See ``api/auth.py``.

Environment variables
---------------------
BOT_CONFIG_PATH   Path to config.yaml (default: crypto_bot/config.yaml)
BOT_API_SECRET    Shared API key for all protected endpoints
ALLOWED_ORIGINS   Comma-separated extra CORS origins (e.g. https://my-vps.com)
LOG_LEVEL         Logging level: DEBUG | INFO | WARNING | ERROR  (default: INFO)
"""

import api.path_setup  # noqa: F401 — must be first

import logging
import logging.handlers
import os
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import require_api_key
from api.db.engine import init_db

# ── Config helpers ─────────────────────────────────────────────────────────────

_BOT_CONFIG_PATH = Path(__file__).parent.parent / "crypto_bot" / "config.yaml"


def load_bot_config() -> dict:
    """Load config.yaml, merging exchange credentials from env vars."""
    path = os.environ.get("BOT_CONFIG_PATH", str(_BOT_CONFIG_PATH))
    with open(path) as f:
        cfg = yaml.safe_load(f)

    # Env vars always override YAML — credentials should never live in the file
    if os.environ.get("EXCHANGE_API_KEY"):
        cfg["api_key"] = os.environ["EXCHANGE_API_KEY"]
    if os.environ.get("EXCHANGE_API_SECRET"):
        cfg["secret"] = os.environ["EXCHANGE_API_SECRET"]
    if os.environ.get("EXCHANGE_PASSPHRASE"):
        cfg["passphrase"] = os.environ["EXCHANGE_PASSPHRASE"]
    if os.environ.get("EXCHANGE_NAME"):
        cfg["exchange"] = os.environ["EXCHANGE_NAME"]

    return cfg


def get_strategy_registry() -> dict:
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.ema_crossover import EMACrossoverStrategy
    from strategies.bollinger_dca import BollingerDCAStrategy
    from strategies.rsi_mean_revert import RSIMeanRevertStrategy
    from strategies.grid_dynamic import GridDynamicStrategy
    from strategies.threshold_rebalance import ThresholdRebalanceStrategy
    from strategies.trend_following import TrendFollowingStrategy
    from strategies.trend_following_ls import TrendFollowingLSStrategy
    from strategies.breakout import BreakoutStrategy
    from strategies.macd_rsi import MACDRSIStrategy
    from strategies.scalping import ScalpingStrategy
    from strategies.momentum_burst import MomentumBurstStrategy
    from strategies.bb_squeeze import BBSqueezeStrategy
    from strategies.supertrend import SupertrendStrategy
    from strategies.vwap_bounce import VWAPBounceStrategy
    from strategies.stoch_rsi import StochRSIStrategy
    from strategies.ichimoku import IchimokuStrategy
    from strategies.supertrend_pro import SupertrendProStrategy
    from strategies.funding_rate_arb import FundingRateArbStrategy
    # ── Kraken Futures Strategies (2025-04) ────────────────────────────────────
    from strategies.pullback import PullbackStrategy
    from strategies.dual_thrust import DualThrustStrategy
    from strategies.keltner_breakout import KeltnerBreakoutStrategy

    return {
        "mean_reversion": MeanReversionStrategy,
        "ema_crossover": EMACrossoverStrategy,
        "bollinger_dca": BollingerDCAStrategy,
        "rsi_mean_revert": RSIMeanRevertStrategy,
        "grid_dynamic": GridDynamicStrategy,
        "threshold_rebalance": ThresholdRebalanceStrategy,
        "trend_following": TrendFollowingStrategy,
        "trend_following_ls": TrendFollowingLSStrategy,
        "breakout": BreakoutStrategy,
        "macd_rsi": MACDRSIStrategy,
        "scalping": ScalpingStrategy,
        "momentum_burst": MomentumBurstStrategy,
        "bb_squeeze": BBSqueezeStrategy,
        "supertrend": SupertrendStrategy,
        "vwap_bounce": VWAPBounceStrategy,
        "stoch_rsi": StochRSIStrategy,
        "ichimoku": IchimokuStrategy,
        "supertrend_pro": SupertrendProStrategy,
        "funding_rate_arb": FundingRateArbStrategy,
        # ── Kraken Futures Strategies ─────────────────────────────────────────
        "pullback":         PullbackStrategy,
        "dual_thrust":      DualThrustStrategy,
        "keltner_breakout": KeltnerBreakoutStrategy,
    }


# ── Logging setup ──────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    """
    Configure root logger with rotating file + console handlers.

    File:    data/bot.log  (10 MB × 5 files = 50 MB max)
    Console: coloured via RichHandler when available, plain otherwise
    """
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "bot.log"

    root = logging.getLogger()
    root.setLevel(log_level)

    # Avoid adding duplicate handlers on hot-reload
    if root.handlers:
        return

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # ── Rotating file handler (50 MB total max) ────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # ── Console handler ────────────────────────────────────────────────────
    try:
        from rich.logging import RichHandler
        console_handler = RichHandler(
            rich_tracebacks=True,
            show_path=False,
            log_time_format="[%H:%M:%S]",
        )
    except ImportError:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)

    root.addHandler(console_handler)
    logging.getLogger(__name__).info(
        f"Logging initialised — level={log_level_name}, file={log_path}"
    )


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="CryptoBot Trading API",
        description="""
## CryptoBot API — v2.1

Multi-strategy crypto trading backtester and live trading engine.

### Authentication

All endpoints (except `GET /api/health`) require an API key:

```
X-API-Key: <BOT_API_SECRET>
```

Set `BOT_API_SECRET` in your `.env` file.  Generate one with:
```
openssl rand -hex 32
```

### Quick start

1. Browse strategies: `GET /api/strategies`
2. Submit a backtest: `POST /api/backtests`
3. Start paper trading: `POST /api/bot/start`
4. Check status: `GET /api/bot/status`

### Modules

| Module | Description |
|--------|-------------|
| **Backtests** | Submit jobs, retrieve metrics & equity curves, walk-forward & Monte Carlo |
| **Strategies** | 19 strategies with ideal timeframes, market type, and liquidity metadata |
| **Trades** | Full trade history (entry/exit, PnL, duration) for any backtest or live session |
| **Provider** | Exchange connectivity, OHLCV candles (multi-exchange fallback + disk cache) |
| **Presets** | Predefined investment profiles (Conservative → Aggressive) |
| **Bot** | Start/stop live or paper trading engine with position resume |
| **Wallet** | Portfolio snapshots, equity curve, and P&L tracking |
| **Market** | Real-time volatility scanner — ATR%, ADX, RSI, volume, strategy suggestions |

### Supported timeframes
`15m` · `30m` · `1h` · `2h` · `4h` · `6h` · `8h` · `12h` · `1d` · `1w`
        """,
        version="3.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {"name": "backtests",   "description": "Backtest job lifecycle"},
            {"name": "strategies",  "description": "19-strategy catalog with metadata"},
            {"name": "trades",      "description": "Trade history and per-trade analytics"},
            {"name": "provider",    "description": "Exchange connectivity and OHLCV candles"},
            {"name": "presets",     "description": "Investment profiles"},
            {"name": "bot",         "description": "Paper and live trading engine"},
            {"name": "wallet",      "description": "Portfolio snapshots and equity curve"},
            {"name": "market",      "description": "Real-time volatility scanner"},
            {"name": "system",      "description": "VPS / container system metrics (CPU, RAM, disk)"},
            {"name": "portfolio",   "description": "Multi-strategy portfolio manager"},
            {"name": "config",      "description": "Runtime config editor — risk rules, anomaly thresholds, bot settings"},
            {"name": "auth",            "description": "API key validation — verify BOT_API_SECRET before storing in browser"},
            {"name": "strategy-engine", "description": "Composable strategy configs — MTF trend filter, per-strategy risk profiles"},
        ],
    )

    # ── CORS ───────────────────────────────────────────────────────────────
    # Default origins cover local dev.  Add VPS domain via ALLOWED_ORIGINS env var.
    # Example: ALLOWED_ORIGINS=https://my-vps.com,https://trading.mydomain.com
    default_origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4173",
        "http://localhost:80",
    ]
    extra = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    allowed_origins = default_origins + extra

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Startup ────────────────────────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup():
        import asyncio
        _setup_logging()
        init_db()

        # WebSocket manager — bind to the running event loop
        from api import ws_manager
        ws_manager.setup(asyncio.get_event_loop())

        # Telegram command polling (no-op if token/chat_id not configured)
        from api.telegram_bot import start_command_handler
        start_command_handler()

        logging.getLogger(__name__).info("API startup complete — v3.0.0")

    @app.on_event("shutdown")
    def on_shutdown():
        from api.telegram_bot import stop_command_handler
        stop_command_handler()
        logging.getLogger(__name__).info("API shutdown")

    # ── Public endpoints (no auth) ─────────────────────────────────────────
    @app.get("/api/health", tags=["health"])
    def health():
        """Lightweight healthcheck — used by Docker and nginx. No auth required."""
        return {"status": "ok", "version": "3.0.0"}

    # ── Protected: config ──────────────────────────────────────────────────
    @app.get("/api/config", dependencies=[Depends(require_api_key)])
    def get_config():
        """Return current config.yaml with all secrets stripped."""
        cfg = load_bot_config()
        cfg.pop("api_key", None)
        cfg.pop("secret", None)
        cfg.pop("passphrase", None)
        return cfg

    # ── Routers (all protected) ────────────────────────────────────────────
    from api.routers import backtests, trades, bot, strategies, provider, wallet, presets, market
    from api.routers import ws as ws_router
    from api.routers import system as system_router
    from api.routers import portfolio as portfolio_router
    from api.routers import settings as settings_router
    from api.routers import auth as auth_router
    from api.routers import strategy_configs as strategy_configs_router

    _auth = [Depends(require_api_key)]

    # Public — no auth dependency (this IS the auth endpoint)
    app.include_router(auth_router.router,  prefix="/api")

    app.include_router(strategies.router,  prefix="/api", dependencies=_auth)
    app.include_router(backtests.router,   prefix="/api", dependencies=_auth)
    app.include_router(trades.router,      prefix="/api", dependencies=_auth)
    app.include_router(bot.router,         prefix="/api", dependencies=_auth)
    app.include_router(provider.router,    prefix="/api", dependencies=_auth)
    app.include_router(wallet.router,      prefix="/api", dependencies=_auth)
    app.include_router(presets.router,     prefix="/api", dependencies=_auth)
    app.include_router(market.router,      prefix="/api", dependencies=_auth)
    app.include_router(system_router.router,    prefix="/api", dependencies=_auth)
    app.include_router(portfolio_router.router, prefix="/api", dependencies=_auth)
    app.include_router(settings_router.router,        prefix="/api", dependencies=_auth)
    app.include_router(strategy_configs_router.router, prefix="/api", dependencies=_auth)
    # WebSocket — auth is handled inside the endpoint (query param api_key)
    app.include_router(ws_router.router,   prefix="/api")

    return app


app = create_app()
