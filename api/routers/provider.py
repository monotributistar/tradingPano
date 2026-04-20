from __future__ import annotations

import os
from typing import Any, Dict, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.main import load_bot_config, _BOT_CONFIG_PATH

router = APIRouter(prefix="/provider", tags=["provider"])

# ── Schemas ────────────────────────────────────────────────────────────────────

class ProviderConfig(BaseModel):
    exchange: str = "bybit"
    testnet: bool = True
    api_key: str = ""
    secret: str = ""


class ConfigPatch(BaseModel):
    exchange: Optional[str] = None
    testnet: Optional[bool] = None
    api_key: Optional[str] = None
    secret: Optional[str] = None
    active_strategy: Optional[str] = None
    pairs: Optional[list] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_exchange(config: Optional[dict] = None):
    """Instantiate ccxt exchange from config (or env vars)."""
    import ccxt
    cfg = config or load_bot_config()
    exchange_id = cfg.get("exchange", "bybit")
    api_key = cfg.get("api_key") or os.environ.get("EXCHANGE_API_KEY", "")
    secret = cfg.get("secret") or os.environ.get("EXCHANGE_SECRET", "")
    testnet = cfg.get("testnet", True)

    ex_cls = getattr(ccxt, exchange_id, None)
    if ex_cls is None:
        raise HTTPException(400, f"Unknown exchange: {exchange_id}")

    kwargs: Dict[str, Any] = {
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
    if api_key:
        kwargs["apiKey"] = api_key
    if secret:
        kwargs["secret"] = secret

    exchange = ex_cls(kwargs)

    if testnet:
        if exchange_id == "bybit":
            exchange.set_sandbox_mode(True)
        elif exchange_id == "binance":
            exchange.urls["api"] = "https://testnet.binance.vision"

    return exchange


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status")
def provider_status():
    """Return current provider config (without secrets)."""
    cfg = load_bot_config()
    api_key = cfg.get("api_key") or os.environ.get("EXCHANGE_API_KEY", "")
    secret = cfg.get("secret") or os.environ.get("EXCHANGE_SECRET", "")
    return {
        "exchange": cfg.get("exchange", "bybit"),
        "testnet": cfg.get("testnet", True),
        "has_api_key": bool(api_key),
        "has_secret": bool(secret),
        "pairs": cfg.get("pairs", []),
        "active_strategy": cfg.get("active_strategy", ""),
    }


@router.post("/test")
def test_connection():
    """
    Test exchange connectivity.
    - Without API keys: fetches public ticker (BTC/USDT) — always works.
    - With API keys: fetches balance to verify auth.
    """
    cfg = load_bot_config()
    api_key = cfg.get("api_key") or os.environ.get("EXCHANGE_API_KEY", "")
    secret = cfg.get("secret") or os.environ.get("EXCHANGE_SECRET", "")

    try:
        exchange = _get_exchange(cfg)
        result: Dict[str, Any] = {
            "exchange": cfg.get("exchange"),
            "testnet": cfg.get("testnet", True),
            "public_ok": False,
            "auth_ok": None,
            "ticker": None,
            "error": None,
        }

        # Public test — fetch BTC/USDT ticker
        ticker = exchange.fetch_ticker("BTC/USDT")
        result["public_ok"] = True
        result["ticker"] = {
            "pair": "BTC/USDT",
            "last": ticker.get("last"),
            "bid": ticker.get("bid"),
            "ask": ticker.get("ask"),
        }

        # Auth test — only if credentials provided
        if api_key and secret:
            balance = exchange.fetch_balance()
            total = {k: v for k, v in balance.get("total", {}).items() if v > 0}
            result["auth_ok"] = True
            result["balance"] = total
        else:
            result["auth_ok"] = None  # not attempted

        return result

    except Exception as exc:
        return {
            "exchange": cfg.get("exchange"),
            "testnet": cfg.get("testnet", True),
            "public_ok": False,
            "auth_ok": False,
            "ticker": None,
            "error": str(exc),
        }


@router.get("/balance")
def get_balance():
    """Fetch live account balance. Requires API keys."""
    cfg = load_bot_config()
    api_key = cfg.get("api_key") or os.environ.get("EXCHANGE_API_KEY", "")
    if not api_key:
        raise HTTPException(401, "API key required to fetch balance")
    try:
        exchange = _get_exchange(cfg)
        balance = exchange.fetch_balance()
        total = {k: round(v, 8) for k, v in balance.get("total", {}).items() if v > 0}
        free = {k: round(v, 8) for k, v in balance.get("free", {}).items() if v > 0}
        return {"total": total, "free": free}
    except Exception as exc:
        raise HTTPException(502, f"Exchange error: {exc}")


@router.get("/ticker/{pair:path}")
def get_ticker(pair: str):
    """Fetch current price for a pair. Public, no auth required."""
    try:
        exchange = _get_exchange()
        ticker = exchange.fetch_ticker(pair)
        return {
            "pair": pair,
            "last": ticker.get("last"),
            "bid": ticker.get("bid"),
            "ask": ticker.get("ask"),
            "volume": ticker.get("baseVolume"),
            "change_pct": ticker.get("percentage"),
        }
    except Exception as exc:
        raise HTTPException(502, f"Exchange error: {exc}")


@router.get("/ohlcv/{pair:path}")
def get_ohlcv(pair: str, timeframe: str = "1h", limit: int = 200, period: str = ""):
    """Fetch OHLCV candles for a pair using the DataFetcher (with fallback exchanges)."""
    try:
        from backtester.data_fetcher import DataFetcher
        cfg = load_bot_config()
        data_source = cfg.get("backtest", {}).get("data_source", "kucoin")
        fetcher = DataFetcher(exchange_id=data_source)
        # Always use DataFetcher (handles fallback exchanges automatically)
        if not period:
            period = "3m"  # default to 3 months when no period given
        df = fetcher.fetch(pair, timeframe, period)
        candles = [
            {
                "t": int(ts.timestamp() * 1000),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"]),
            }
            for ts, row in df.iterrows()
        ]
        return candles
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"OHLCV fetch error: {exc}")


@router.patch("/config")
def update_config(patch: ConfigPatch):
    """
    Persist config changes to config.yaml.
    Only non-None fields are updated.
    """
    config_path = str(_BOT_CONFIG_PATH)
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    updates = patch.model_dump(exclude_none=True)
    # Never allow exchange to be set to empty string
    if "exchange" in updates and not updates["exchange"]:
        updates.pop("exchange")
    cfg.update(updates)

    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    return {"ok": True, "updated": list(updates.keys())}
