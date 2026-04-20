"""
api/anomaly_detector.py — Runtime anomaly detection for live trading
=====================================================================

Detects three classes of anomaly that should immediately alert the trader:

Slippage
--------
After each trade, compare the expected fill price (signal price at decision
time) with the actual exchange fill price.  If the deviation exceeds the
configured threshold, fire a Telegram alert.

Balance integrity
-----------------
After each candle cycle, compare the DB-recorded equity with the live
exchange balance.  A large unexpected gap indicates an out-of-band trade,
fee surprise, or DB corruption.

Stale price
-----------
If the exchange price for a pair has not changed across N consecutive candles
(or hasn't been fetched for > T seconds), the data feed may be frozen.
Skip signal generation and alert.

Usage
-----
    from api.anomaly_detector import AnomalyDetector

    detector = AnomalyDetector(config)

    # After each trade execution:
    detector.check_slippage(pair, expected_price, actual_price, trade_type)

    # After each candle + DB wallet snapshot:
    detector.check_balance(recorded_equity, live_equity)

    # On each candle fetch:
    alive = detector.check_price_freshness(pair, new_price)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Lightweight anomaly detector.

    Parameters (all read from ``config["risk"]`` sub-dict)
    -------------------------------------------------------
    slippage_alert_pct  float   Fire alert if |fill - signal| / signal > X%  (default 0.5)
    balance_gap_pct     float   Fire alert if |live - db| / db > X%          (default 5.0)
    stale_price_candles int     Flag pair as stale after N unchanged candles  (default 5)
    """

    def __init__(self, config: dict):
        risk = config.get("risk", {})
        self._slippage_threshold = float(risk.get("slippage_alert_pct", 0.5))
        self._balance_gap_pct    = float(risk.get("balance_gap_pct",    5.0))
        self._stale_candles      = int(risk.get("stale_price_candles",   5))

        # Per-pair price staleness tracking
        self._last_prices: dict[str, float]  = {}
        self._stale_count: dict[str, int]    = defaultdict(int)
        self._last_fetch_ts: dict[str, float] = {}

        # Injected lazily (set by bot_manager after init)
        self._notifier = None  # TelegramNotifier | None

    def set_notifier(self, notifier) -> None:
        """Attach a TelegramNotifier so anomalies fire phone alerts."""
        self._notifier = notifier

    # ── Slippage ───────────────────────────────────────────────────────────────

    def check_slippage(
        self,
        pair: str,
        expected_price: float,
        actual_price: float,
        trade_type: str = "buy",
    ) -> bool:
        """
        Check whether fill slippage exceeds the threshold.

        Returns True if slippage is acceptable, False if anomaly was detected.
        """
        if expected_price <= 0:
            return True  # can't compute — skip

        slippage_pct = abs(actual_price - expected_price) / expected_price * 100.0

        if slippage_pct > self._slippage_threshold:
            msg = (
                f"⚠️ SLIPPAGE ALERT: {trade_type.upper()} {pair} — "
                f"expected {expected_price:.4f}, filled {actual_price:.4f} "
                f"({slippage_pct:+.2f}% > {self._slippage_threshold}% threshold)"
            )
            logger.warning(msg)
            self._send_alert(msg)
            return False

        return True

    # ── Balance integrity ──────────────────────────────────────────────────────

    def check_balance(
        self,
        recorded_equity: float,
        live_equity: float,
        label: str = "equity",
    ) -> bool:
        """
        Compare DB-recorded equity vs live exchange equity.

        Returns True if values are consistent, False if gap is too large.
        """
        if recorded_equity <= 0:
            return True  # first run — no baseline

        gap_pct = abs(live_equity - recorded_equity) / recorded_equity * 100.0

        if gap_pct > self._balance_gap_pct:
            msg = (
                f"⚠️ BALANCE GAP: {label} in DB={recorded_equity:.2f} USDT, "
                f"live={live_equity:.2f} USDT (gap={gap_pct:.1f}% > "
                f"{self._balance_gap_pct}% threshold). "
                f"Possible out-of-band trade or fee spike."
            )
            logger.error(msg)
            self._send_alert(msg)
            return False

        return True

    # ── Stale price ────────────────────────────────────────────────────────────

    def check_price_freshness(self, pair: str, price: float) -> bool:
        """
        Track price changes across candles.  Returns False (stale) when the
        price has been identical for ``stale_price_candles`` consecutive bars.
        """
        now = time.time()
        self._last_fetch_ts[pair] = now

        prev = self._last_prices.get(pair)
        if prev is None or price != prev:
            self._last_prices[pair] = price
            self._stale_count[pair] = 0
            return True

        self._stale_count[pair] += 1

        if self._stale_count[pair] >= self._stale_candles:
            msg = (
                f"⚠️ STALE PRICE: {pair} price unchanged at {price:.4f} "
                f"for {self._stale_count[pair]} consecutive candles. "
                f"Possible exchange data freeze — skipping signal."
            )
            logger.warning(msg)
            self._send_alert(msg)
            # Reset so we don't spam every candle
            self._stale_count[pair] = 0
            return False

        return True

    # ── Internal ───────────────────────────────────────────────────────────────

    def _send_alert(self, text: str) -> None:
        if self._notifier is not None:
            try:
                self._notifier.send(text)
            except Exception as exc:
                logger.error(f"AnomalyDetector: failed to send Telegram alert: {exc}")
