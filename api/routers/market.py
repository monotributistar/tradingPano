"""
Market Scanner router — real-time volatility, momentum, and strategy suggestions.

Endpoints
---------
GET /api/market/scanner   Volatility + trend metrics for a list of pairs
GET /api/market/summary   Single high-level market overview (top mover, most volatile, etc.)

All metrics are derived from the 1 h OHLCV feed (DataFetcher with cache).
No auth or API keys required — uses public market data.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from api.main import load_bot_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

# ── In-memory market cache ────────────────────────────────────────────────────
# Stores the last computed scanner results per (timeframe, sorted-pairs) key.
# TTL = 10 minutes.  Thread-safe via _cache_lock.

_CACHE_TTL = 600  # seconds


@dataclass
class _CacheEntry:
    data:       List[Dict[str, Any]]
    pairs:      List[str]
    timeframe:  str
    fetched_at: float = dc_field(default_factory=time.monotonic)

    def age_seconds(self) -> float:
        return time.monotonic() - self.fetched_at

    def is_fresh(self, ttl: float = _CACHE_TTL) -> bool:
        return self.age_seconds() < ttl

    def fetched_at_iso(self) -> str:
        # Convert monotonic age back to a UTC wall-clock timestamp
        wall = datetime.now(tz=timezone.utc).timestamp() - self.age_seconds()
        return datetime.fromtimestamp(wall, tz=timezone.utc).isoformat()


_cache: Dict[str, _CacheEntry] = {}
_cache_lock = threading.Lock()


def _cache_key(pairs: List[str], timeframe: str) -> str:
    return f"{timeframe}|{','.join(sorted(pairs))}"


# ── Default pairs scanned when no list is supplied ────────────────────────────

DEFAULT_SCAN_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT",
    "SOL/USDT", "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT",
    "MATIC/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "SUI/USDT", "DOGE/USDT", "LTC/USDT", "ATOM/USDT",
    "INJ/USDT", "TIA/USDT",
]

# ── Technical indicator helpers ────────────────────────────────────────────────

def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    out = np.zeros_like(arr)
    if len(arr) < period:
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = arr[:period].mean()
    for i in range(period, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def _wilder_smooth(arr: np.ndarray, period: int) -> np.ndarray:
    """Wilder smoothing (used for ATR / ADX).

    Seed = mean of the first ``period`` values (standard Wilder initialisation).
    Recursive formula: ``out[i] = out[i-1] * (period-1)/period + arr[i] / period``
    This keeps the output on the same scale as the input (0–100 for DX → 0–100 ADX).
    """
    out = np.zeros(len(arr))
    if len(arr) < period:
        return out
    out[period - 1] = arr[:period].mean()          # ← mean, not sum
    for i in range(period, len(arr)):
        out[i] = (out[i - 1] * (period - 1) + arr[i]) / period   # standard Wilder
    return out


def _compute_atr_pct(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     period: int = 14) -> float:
    """ATR(14) as a percentage of the current close price."""
    if len(close) < period + 1:
        return 0.0
    h, l, c = high[1:], low[1:], close[1:]
    cp = close[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - cp), np.abs(l - cp)))
    atr_s = _wilder_smooth(tr, period)
    atr_val = atr_s[-1]
    return float(atr_val / close[-1] * 100) if close[-1] > 0 else 0.0


def _compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                 period: int = 14) -> float:
    """ADX(14) — directional movement index strength (0–100).

    >25 = trending, 15–25 = weak trend, <15 = ranging/choppy.
    """
    n = len(close)
    if n < period * 2:
        return 0.0

    h, l, c = high[1:], low[1:], close[1:]
    cp = close[:-1]

    tr = np.maximum(h - l, np.maximum(np.abs(h - cp), np.abs(l - cp)))
    dm_up = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                     np.maximum(high[1:] - high[:-1], 0.0), 0.0)
    dm_dn = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                     np.maximum(low[:-1] - low[1:], 0.0), 0.0)

    atr_s = _wilder_smooth(tr, period)
    dmp_s = _wilder_smooth(dm_up, period)
    dmn_s = _wilder_smooth(dm_dn, period)

    safe = np.where(atr_s > 0, atr_s, 1.0)
    di_p = 100.0 * dmp_s / safe
    di_n = 100.0 * dmn_s / safe

    denom = di_p + di_n
    dx = np.where(denom > 0, 100.0 * np.abs(di_p - di_n) / denom, 0.0)
    dx_trimmed = dx[period - 1:]
    adx_s = _wilder_smooth(dx_trimmed, period)
    valid = adx_s[adx_s > 0]
    return float(valid[-1]) if len(valid) else 0.0


def _compute_rsi(close: np.ndarray, period: int = 14) -> float:
    """RSI(14) — momentum oscillator (0–100)."""
    if len(close) < period + 1:
        return 50.0
    diff = np.diff(close)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


# ── Strategy suggestion engine ────────────────────────────────────────────────

def _suggest_strategies(
    market_type: str,
    trend_direction: str,
    volatility: str,
    timeframe: str,
) -> List[Dict[str, str]]:
    """Return top-3 strategy suggestions with a one-line reason each.

    Args:
        market_type:     "trending" | "ranging" | "mixed"
        trend_direction: "up" | "down" | "sideways"
        volatility:      "low" | "medium" | "high"
        timeframe:       "1h" | "4h" etc.
    """
    candidates: List[Dict[str, str]] = []

    if market_type == "trending" and trend_direction == "up":
        candidates = [
            {"name": "supertrend_pro",   "reason": "Strong uptrend — dual Supertrend + ADX confirms trend"},
            {"name": "trend_following",  "reason": "ADX uptrend — follow momentum with EMA filter"},
            {"name": "macd_rsi",         "reason": "Bullish momentum confirmed — MACD/RSI confluence"},
            {"name": "momentum_burst",   "reason": "Price breaking out — capture the impulse move"},
            {"name": "ema_crossover",    "reason": "Golden cross regime — EMA trend following"},
        ]
    elif market_type == "trending" and trend_direction == "down":
        candidates = [
            {"name": "trend_following_ls", "reason": "Downtrend confirmed — short bias futures strategy"},
            {"name": "supertrend_pro",     "reason": "Bearish Supertrend flip — short with trailing stop"},
            {"name": "momentum_burst",     "reason": "Short momentum — captures the sell-off impulse"},
            {"name": "macd_rsi",           "reason": "Bearish MACD divergence — high-quality short signal"},
        ]
    elif market_type == "ranging":
        candidates = [
            {"name": "rsi_mean_revert",   "reason": "Sideways market — RSI extremes are reliable signals"},
            {"name": "bb_squeeze",        "reason": "Volatility compressed — mean reversion on band touches"},
            {"name": "vwap_bounce",       "reason": "Range-bound — VWAP deviations snap back quickly"},
            {"name": "grid_dynamic",      "reason": "Flat market — grid harvests oscillation profit"},
            {"name": "mean_reversion",    "reason": "No trend — statistical reversion from extremes"},
        ]
    else:  # mixed / transitional
        candidates = [
            {"name": "stoch_rsi",    "reason": "Mixed signals — StochRSI handles both regimes well"},
            {"name": "macd_rsi",     "reason": "Dual-filter reduces false signals in choppy conditions"},
            {"name": "bb_squeeze",   "reason": "Compression before expansion — volatility timing play"},
            {"name": "scalping",     "reason": "Short duration reduces directional exposure"},
        ]

    # Promote high-volatility burst strategies when vol is elevated
    if volatility == "high":
        hv_boost = ["momentum_burst", "breakout", "bb_squeeze", "scalping"]
        boosted = [c for c in candidates if c["name"] in hv_boost]
        rest = [c for c in candidates if c["name"] not in hv_boost]
        candidates = boosted + rest

    # Promote slow strategies for very short timeframes (avoid over-trading)
    if timeframe in ("15m", "30m"):
        scalp_first = ["scalping", "vwap_bounce", "momentum_burst"]
        first = [c for c in candidates if c["name"] in scalp_first]
        rest = [c for c in candidates if c["name"] not in scalp_first]
        candidates = first + rest

    seen: set = set()
    result: List[Dict[str, str]] = []
    for c in candidates:
        if c["name"] not in seen:
            seen.add(c["name"])
            result.append(c)
        if len(result) == 3:
            break

    return result


# ── Per-pair scanner core ─────────────────────────────────────────────────────

def _scan_pair(pair: str, timeframe: str, fetcher: Any) -> Optional[Dict[str, Any]]:
    """Compute all market metrics for a single pair.

    ``fetcher`` is a shared DataFetcher instance (load_markets already done).

    Returns None on error (missing data, exchange timeout, etc.).
    Stale cache is used as a fallback when a live download fails so the page
    always shows something rather than going blank.
    """
    try:
        import pandas as pd

        # Fetch 2 weeks of 1h candles → 336 bars (plenty for all indicators).
        # If the live download fails, fall back to whatever is on disk.
        try:
            df = fetcher.fetch(pair, timeframe, "2w")
        except Exception as dl_err:
            logger.warning("Live download failed for %s (%s) — trying stale cache", pair, dl_err)
            cache_path = fetcher._cache_path(pair, timeframe, "2w")
            if cache_path.exists():
                df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                df.index = pd.to_datetime(df.index, utc=True)
            else:
                return None

        if df is None or len(df) < 30:
            return None

        close  = df["close"].values.astype(float)
        high   = df["high"].values.astype(float)
        low    = df["low"].values.astype(float)
        volume = df["volume"].values.astype(float)

        price = float(close[-1])
        if price <= 0:
            return None

        # ── Price changes ──────────────────────────────────────────────────
        # 1 h change: last candle vs previous candle
        change_1h = (
            float((close[-1] - close[-2]) / close[-2] * 100)
            if len(close) >= 2 and close[-2] > 0 else 0.0
        )
        # 4h change (last 4 candles when timeframe=1h)
        tf_hours = {"15m": 0.25, "30m": 0.5, "1h": 1, "2h": 2,
                    "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}
        bars_per_hour = 1.0 / tf_hours.get(timeframe, 1)

        def pct_change_nbars(n_hours: float) -> float:
            n = max(1, int(round(n_hours * bars_per_hour)))
            if len(close) > n and close[-n - 1] > 0:
                return float((close[-1] - close[-n - 1]) / close[-n - 1] * 100)
            return 0.0

        change_4h  = pct_change_nbars(4)
        change_24h = pct_change_nbars(24)
        change_7d  = pct_change_nbars(24 * 7)

        # ── Volume (24 h in USDT) ──────────────────────────────────────────
        bars_24h = max(1, int(round(24 * bars_per_hour)))
        vol_slice = volume[-bars_24h:]
        price_slice = close[-bars_24h:]
        volume_24h_usd = float(np.sum(vol_slice * price_slice))

        # ── ATR volatility ─────────────────────────────────────────────────
        atr_pct = _compute_atr_pct(high, low, close, period=14)

        if atr_pct < 0.5:
            volatility = "low"
        elif atr_pct < 2.0:
            volatility = "medium"
        else:
            volatility = "high"

        # ── ADX + trend direction ──────────────────────────────────────────
        adx = _compute_adx(high, low, close, period=14)
        rsi = _compute_rsi(close, period=14)

        # EMA 20 vs EMA 50 slope for direction
        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        ema20_val = float(ema20[-1]) if ema20[-1] > 0 else price
        ema50_val = float(ema50[-1]) if ema50[-1] > 0 else price

        if adx >= 25:
            market_type = "trending"
            trend_direction = "up" if ema20_val > ema50_val else "down"
        elif adx >= 18:
            market_type = "mixed"
            trend_direction = "up" if price > ema50_val else "down"
        else:
            market_type = "ranging"
            trend_direction = "sideways"

        # ── Support / Resistance (simple 14-bar high/low) ─────────────────
        lookback = min(14 * bars_24h, len(close))
        resistance = float(high[-lookback:].max())
        support = float(low[-lookback:].min())
        price_in_range_pct = (
            float((price - support) / (resistance - support) * 100)
            if resistance > support else 50.0
        )

        # ── Strategy suggestions ───────────────────────────────────────────
        suggestions = _suggest_strategies(market_type, trend_direction, volatility, timeframe)

        return {
            "pair": pair,
            "price": round(price, 6 if price < 0.01 else 4 if price < 1 else 2),
            # Price changes
            "change_1h_pct":  round(change_1h, 2),
            "change_4h_pct":  round(change_4h, 2),
            "change_24h_pct": round(change_24h, 2),
            "change_7d_pct":  round(change_7d, 2),
            # Volume & volatility
            "volume_24h_usd": round(volume_24h_usd, 0),
            "atr_pct":        round(atr_pct, 2),
            "volatility":     volatility,        # low / medium / high
            # Trend
            "adx":            round(adx, 1),
            "rsi":            round(rsi, 1),
            "market_type":    market_type,       # trending / ranging / mixed
            "trend_direction": trend_direction,  # up / down / sideways
            # Range position
            "support":             round(support, 4),
            "resistance":          round(resistance, 4),
            "price_in_range_pct":  round(price_in_range_pct, 1),
            # Suggestions
            "top_strategies": suggestions,
        }

    except Exception as exc:
        logger.warning("Market scan failed for %s: %s", pair, exc)
        return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "/scanner",
    summary="Market volatility & strategy scanner",
    response_description="Array of per-pair market metrics with strategy suggestions",
)
def market_scanner(
    pairs: Optional[str] = Query(
        None,
        description="Comma-separated pairs to scan, e.g. 'BTC/USDT,ETH/USDT'. "
                    "Defaults to 20 major pairs.",
    ),
    timeframe: str = Query(
        "1h",
        description="Candle size used for metric calculation: 15m, 30m, 1h, 4h, 1d",
    ),
) -> List[Dict[str, Any]]:
    """Compute volatility, momentum, and trend metrics for multiple pairs in parallel.

    Returns one entry per pair with:

    - **price** — latest close
    - **change_1h_pct / change_4h_pct / change_24h_pct / change_7d_pct** — rolling price changes
    - **volume_24h_usd** — approximate 24-hour trading volume in USDT
    - **atr_pct** — ATR(14) as % of price (normalised volatility)
    - **volatility** — low (<0.5%) / medium (0.5–2%) / high (>2%)
    - **adx** — ADX(14) trend strength (0–100, >25 = trending)
    - **rsi** — RSI(14) momentum (0–100)
    - **market_type** — trending / ranging / mixed
    - **trend_direction** — up / down / sideways
    - **support / resistance** — 14-day high/low levels
    - **price_in_range_pct** — 0 = at support, 100 = at resistance
    - **top_strategies** — 3 strategy suggestions with reasoning

    Results are sorted by 24-hour volume (largest first).
    Failed pairs are silently omitted.
    """
    pair_list = (
        [p.strip() for p in pairs.split(",") if p.strip()]
        if pairs
        else DEFAULT_SCAN_PAIRS
    )

    if len(pair_list) > 40:
        raise HTTPException(400, "Maximum 40 pairs per request")

    # ── Cache lookup ──────────────────────────────────────────────────────────
    key = _cache_key(pair_list, timeframe)
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry.is_fresh():
            logger.debug("Market cache hit: %s (age=%ds)", key, int(entry.age_seconds()))
            return entry.data

    config = load_bot_config()

    # Build ONE shared DataFetcher — load_markets() is called only once here
    # instead of once per pair (which was the cause of the 20-second hang).
    try:
        from backtester.data_fetcher import DataFetcher
        data_source = config.get("backtest", {}).get("data_source", "kucoin")
        fetcher = DataFetcher(exchange_id=data_source)
    except Exception as exc:
        logger.error("Could not initialise DataFetcher: %s", exc)
        raise HTTPException(503, "Market data source unavailable")

    results: List[Dict[str, Any]] = []

    # Run per-pair scans in parallel (IO-bound: DataFetcher uses cached CSVs).
    # Cap the whole scan at 20 s and each individual pair at 8 s so a single
    # slow exchange call never hangs the endpoint.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_scan_pair, pair, timeframe, fetcher): pair
            for pair in pair_list
        }
        for future in as_completed(futures, timeout=20):
            try:
                result = future.result(timeout=8)
            except Exception as exc:
                logger.warning("Pair scan timed out or errored: %s", exc)
                continue
            if result is not None:
                results.append(result)

    # Sort by volume (highest first); put failed pairs last
    results.sort(key=lambda r: r.get("volume_24h_usd", 0), reverse=True)

    # ── Cache store ───────────────────────────────────────────────────────────
    with _cache_lock:
        _cache[key] = _CacheEntry(data=results, pairs=pair_list, timeframe=timeframe)
    logger.info("Market cache updated: %d pairs, timeframe=%s", len(results), timeframe)

    return results


@router.get(
    "/summary",
    summary="Market overview — top movers, most volatile, trending pairs",
)
def market_summary(
    timeframe: str = Query("1h", description="Candle timeframe for calculations"),
) -> Dict[str, Any]:
    """Return a high-level market snapshot derived from scanning all default pairs.

    Useful for the summary cards at the top of the Market page.

    Returns:
        top_gainer:    pair with best 24h return
        top_loser:     pair with worst 24h return
        most_volatile: pair with highest ATR%
        highest_volume: pair with highest 24h USD volume
        trending_count: number of pairs with ADX > 25
        ranging_count:  number of pairs with ADX < 18
        avg_atr_pct:    average volatility across all scanned pairs
        market_mood:    "bullish" | "bearish" | "neutral"
        gainers:        number of pairs up >0% in 24h
        losers:         number of pairs down <0% in 24h
    """
    # Try the cache first (summary always uses the default pair list)
    cache_key = _cache_key(DEFAULT_SCAN_PAIRS, timeframe)
    with _cache_lock:
        entry = _cache.get(cache_key)
        cached_results = entry.data if (entry and entry.is_fresh()) else None

    if cached_results:
        results = cached_results
    else:
        config = load_bot_config()

        try:
            from backtester.data_fetcher import DataFetcher
            data_source = config.get("backtest", {}).get("data_source", "kucoin")
            fetcher = DataFetcher(exchange_id=data_source)
        except Exception as exc:
            logger.error("Could not initialise DataFetcher for summary: %s", exc)
            return {"error": "Market data source unavailable"}

        results = []

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_scan_pair, p, timeframe, fetcher): p
                for p in DEFAULT_SCAN_PAIRS
            }
            for future in as_completed(futures, timeout=20):
                try:
                    r = future.result(timeout=8)
                except Exception as exc:
                    logger.warning("Summary pair scan timed out or errored: %s", exc)
                    continue
                if r is not None:
                    results.append(r)

        with _cache_lock:
            _cache[cache_key] = _CacheEntry(
                data=results, pairs=DEFAULT_SCAN_PAIRS, timeframe=timeframe
            )

    if not results:
        return {"error": "No market data available"}

    changes_24h = [r["change_24h_pct"] for r in results]
    gainers = sum(1 for c in changes_24h if c > 0)
    losers = sum(1 for c in changes_24h if c < 0)
    mood = "bullish" if gainers > losers * 1.5 else "bearish" if losers > gainers * 1.5 else "neutral"

    top_gainer = max(results, key=lambda r: r["change_24h_pct"])
    top_loser = min(results, key=lambda r: r["change_24h_pct"])
    most_volatile = max(results, key=lambda r: r["atr_pct"])
    highest_vol = max(results, key=lambda r: r["volume_24h_usd"])

    return {
        "scanned_pairs": len(results),
        "market_mood": mood,
        "gainers": gainers,
        "losers": losers,
        "avg_atr_pct": round(float(np.mean([r["atr_pct"] for r in results])), 2),
        "trending_count": sum(1 for r in results if r["adx"] > 25),
        "ranging_count": sum(1 for r in results if r["adx"] < 18),
        "top_gainer": {
            "pair": top_gainer["pair"],
            "change_24h_pct": top_gainer["change_24h_pct"],
            "price": top_gainer["price"],
        },
        "top_loser": {
            "pair": top_loser["pair"],
            "change_24h_pct": top_loser["change_24h_pct"],
            "price": top_loser["price"],
        },
        "most_volatile": {
            "pair": most_volatile["pair"],
            "atr_pct": most_volatile["atr_pct"],
            "volatility": most_volatile["volatility"],
        },
        "highest_volume": {
            "pair": highest_vol["pair"],
            "volume_24h_usd": highest_vol["volume_24h_usd"],
        },
    }


@router.get(
    "/cache",
    summary="Market data cache status",
)
def market_cache_status() -> Dict[str, Any]:
    """Return the current state of the in-memory market data cache.

    Shows all cached (timeframe, pairs) combinations with their age and
    freshness status.  Entries older than the TTL are marked stale but
    kept until evicted by the next successful scan.
    """
    with _cache_lock:
        entries = [
            {
                "key":          key,
                "timeframe":    entry.timeframe,
                "pairs":        entry.pairs,
                "pairs_count":  len(entry.pairs),
                "pairs_cached": len(entry.data),
                "age_seconds":  round(entry.age_seconds()),
                "is_fresh":     entry.is_fresh(),
                "fetched_at":   entry.fetched_at_iso(),
            }
            for key, entry in _cache.items()
        ]
    return {
        "ttl_seconds": _CACHE_TTL,
        "total_entries": len(entries),
        "entries": entries,
    }


@router.post(
    "/cache/warm",
    summary="Pre-warm market cache in the background",
)
def warm_market_cache(
    timeframe: str = Query("1h", description="Timeframe to warm"),
    pairs:     Optional[str] = Query(
        None, description="Comma-separated pairs; defaults to the standard 20-pair list",
    ),
) -> Dict[str, Any]:
    """Trigger a background scan to pre-populate the market cache.

    Returns immediately — the scan runs in a daemon thread.
    Useful to call on application startup or after a cache expiry to ensure
    the first real request is fast.
    """
    pair_list = (
        [p.strip() for p in pairs.split(",") if p.strip()]
        if pairs else DEFAULT_SCAN_PAIRS
    )

    def _do_warm() -> None:
        try:
            config = load_bot_config()
            from backtester.data_fetcher import DataFetcher
            data_source = config.get("backtest", {}).get("data_source", "kucoin")
            fetcher = DataFetcher(exchange_id=data_source)

            results: List[Dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_scan_pair, p, timeframe, fetcher): p for p in pair_list}
                for future in as_completed(futures, timeout=60):
                    try:
                        r = future.result(timeout=10)
                        if r is not None:
                            results.append(r)
                    except Exception as exc:
                        logger.warning("Cache warm scan error: %s", exc)

            results.sort(key=lambda r: r.get("volume_24h_usd", 0), reverse=True)
            key = _cache_key(pair_list, timeframe)
            with _cache_lock:
                _cache[key] = _CacheEntry(data=results, pairs=pair_list, timeframe=timeframe)
            logger.info("Market cache warmed: %d/%d pairs, tf=%s", len(results), len(pair_list), timeframe)
        except Exception as exc:
            logger.error("Market cache warm failed: %s", exc)

    t = threading.Thread(target=_do_warm, daemon=True, name="market-cache-warm")
    t.start()

    return {
        "ok":       True,
        "pairs":    len(pair_list),
        "timeframe": timeframe,
        "detail":   f"Warming cache for {len(pair_list)} pairs (timeframe={timeframe}) in background",
    }


@router.delete(
    "/cache",
    summary="Invalidate the entire market cache",
)
def clear_market_cache() -> Dict[str, Any]:
    """Remove all cached market data.  The next scanner request will fetch fresh data."""
    with _cache_lock:
        count = len(_cache)
        _cache.clear()
    return {"ok": True, "cleared": count}
