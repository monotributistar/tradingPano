"""
OHLCV Data Fetcher — downloads and caches historical candlestick data via ccxt.

Supported timeframes
--------------------
1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d, 1w

Supported periods
-----------------
1w, 2w, 1m, 2m, 3m, 6m, 9m, 1y, 18m, 2y, 3y, 4y, 5y

Caching
-------
- Cache stored in data/cache/ as CSV files
- Short periods (≤3m): 1-hour freshness
- Long periods: 6-hour freshness
- Pass force=True to bypass cache

Exchange fallback
-----------------
Primary exchange is configurable (default: kucoin).
On failure, automatically retries against: kucoin → okx → gate → kraken.
"""
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "1w":  timedelta(days=7),
    "2w":  timedelta(days=14),
    "1m":  timedelta(days=30),
    "2m":  timedelta(days=60),
    "3m":  timedelta(days=90),
    "6m":  timedelta(days=180),
    "9m":  timedelta(days=270),
    "1y":  timedelta(days=365),
    "18m": timedelta(days=548),
    "2y":  timedelta(days=730),
    "3y":  timedelta(days=1095),
    "4y":  timedelta(days=1460),
    "5y":  timedelta(days=1825),
}

TIMEFRAME_MS = {
    "1m":   60_000,
    "5m":   300_000,
    "15m":  900_000,
    "30m":  1_800_000,
    "1h":   3_600_000,
    "2h":   7_200_000,
    "4h":   14_400_000,
    "6h":   21_600_000,
    "8h":   28_800_000,
    "12h":  43_200_000,
    "1d":   86_400_000,
    "1w":   604_800_000,
}


FALLBACK_EXCHANGES = ["kucoin", "okx", "gate", "kraken"]


class DataFetcher:
    def __init__(self, exchange_id: str = "bybit",
                 cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.exchange = self._init_exchange(exchange_id)

    def _init_exchange(self, exchange_id: str):
        """Try the configured exchange first, then fallbacks if unreachable."""
        candidates = [exchange_id] + [e for e in FALLBACK_EXCHANGES if e != exchange_id]
        last_err = None
        for eid in candidates:
            try:
                ex_cls = getattr(ccxt, eid, None)
                if ex_cls is None:
                    continue
                ex = ex_cls({"enableRateLimit": True, "timeout": 10000, "options": {"defaultType": "spot"}})
                # Quick reachability check — load markets (public, no auth)
                ex.load_markets()
                logger.info(f"Data source: {eid}")
                return ex
            except Exception as e:
                logger.warning(f"Exchange {eid} unreachable: {e}")
                last_err = e
        raise RuntimeError(f"No exchange reachable for market data. Last error: {last_err}")

    def _cache_path(self, pair: str, timeframe: str, period: str) -> Path:
        safe_pair = pair.replace("/", "_")
        return self.cache_dir / f"{safe_pair}_{timeframe}_{period}.csv"

    def _is_cache_valid(self, path: Path, period: str) -> bool:
        """Cache válido si el archivo existe y fue creado hoy."""
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = datetime.now(tz=timezone.utc) - mtime
        # For short lookbacks used by the market scanner, refresh every 4 hours.
        # 1-hour TTL was too aggressive and caused constant live downloads.
        if period in ("1w", "2w", "1m", "2m", "3m"):
            return age < timedelta(hours=4)
        return age < timedelta(hours=6)

    def fetch(self, pair: str, timeframe: str = "1h",
              period: str = "6m", force: bool = False) -> pd.DataFrame:
        """
        Retorna DataFrame OHLCV para el par y período dado.
        Usa cache si está disponible.
        """
        cache_path = self._cache_path(pair, timeframe, period)

        if not force and self._is_cache_valid(cache_path, period):
            logger.info(f"Usando cache: {cache_path.name}")
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            return df

        logger.info(f"Descargando {pair} {timeframe} ({period})...")
        df = self._download(pair, timeframe, period)
        df.to_csv(cache_path)
        logger.info(f"Guardado en cache: {cache_path.name} ({len(df)} velas)")
        return df

    def _download(self, pair: str, timeframe: str, period: str) -> pd.DataFrame:
        delta = PERIOD_MAP.get(period, timedelta(days=180))
        since_dt = datetime.now(tz=timezone.utc) - delta
        since_ms = int(since_dt.timestamp() * 1000)

        tf_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        all_candles = []

        while True:
            try:
                candles = self.exchange.fetch_ohlcv(
                    pair, timeframe=timeframe,
                    since=since_ms, limit=1000
                )
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limit, esperando 10s...")
                time.sleep(10)
                continue
            except ccxt.NetworkError as e:
                logger.error(f"Error de red: {e}")
                raise

            if not candles:
                break

            all_candles.extend(candles)
            last_ts = candles[-1][0]

            # Si llegamos al presente, terminar
            if last_ts >= int(datetime.now(tz=timezone.utc).timestamp() * 1000) - tf_ms:
                break

            since_ms = last_ts + tf_ms
            time.sleep(self.exchange.rateLimit / 1000)

        if not all_candles:
            raise ValueError(f"No se obtuvieron datos para {pair} {timeframe}")

        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)
        return df.astype(float)
