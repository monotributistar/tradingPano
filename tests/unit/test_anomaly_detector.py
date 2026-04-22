"""
tests/unit/test_anomaly_detector.py
=====================================

Unit tests for api/anomaly_detector.py.

All tests are pure (no I/O, no network, no DB).
The notifier is replaced by a simple spy that records sent messages.
"""

import pytest
from typing import Optional
from api.anomaly_detector import AnomalyDetector


# ── Spy notifier ───────────────────────────────────────────────────────────────

class _SpyNotifier:
    """Captures calls to send() instead of actually sending Telegram messages."""
    def __init__(self):
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)

    @property
    def last(self) -> Optional[str]:
        return self.messages[-1] if self.messages else None

    def reset(self):
        self.messages.clear()


def make_detector(
    *,
    slippage_pct:    float = 0.5,
    balance_gap_pct: float = 5.0,
    stale_candles:   int   = 3,
) -> tuple[AnomalyDetector, _SpyNotifier]:
    config = {
        "risk": {
            "slippage_alert_pct":    slippage_pct,
            "balance_gap_pct":       balance_gap_pct,
            "stale_price_candles":   stale_candles,
        }
    }
    detector = AnomalyDetector(config)
    spy = _SpyNotifier()
    detector.set_notifier(spy)
    return detector, spy


# ── Slippage ───────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_slippage_within_threshold_no_alert():
    d, spy = make_detector(slippage_pct=0.5)
    ok = d.check_slippage("BTC/USDT", expected_price=100.0, actual_price=100.4)
    assert ok
    assert len(spy.messages) == 0


@pytest.mark.unit
def test_slippage_over_threshold_alerts():
    d, spy = make_detector(slippage_pct=0.5)
    ok = d.check_slippage("BTC/USDT", expected_price=100.0, actual_price=101.0)
    assert not ok
    assert len(spy.messages) == 1
    assert "SLIPPAGE" in spy.last
    assert "BTC/USDT" in spy.last


@pytest.mark.unit
def test_slippage_exact_threshold_no_alert():
    """Exactly at threshold should NOT trigger (> not >=)."""
    d, spy = make_detector(slippage_pct=0.5)
    ok = d.check_slippage("BTC/USDT", expected_price=100.0, actual_price=100.5)
    assert ok
    assert len(spy.messages) == 0


@pytest.mark.unit
def test_slippage_zero_expected_price_skipped():
    """If expected_price is 0 or negative, slippage can't be computed — skip."""
    d, spy = make_detector()
    ok = d.check_slippage("BTC/USDT", expected_price=0.0, actual_price=100.0)
    assert ok
    assert len(spy.messages) == 0


@pytest.mark.unit
def test_slippage_negative_direction_also_detected():
    """Slippage in either direction triggers the alert."""
    d, spy = make_detector(slippage_pct=0.5)
    ok = d.check_slippage("ETH/USDT", expected_price=100.0, actual_price=99.0)
    assert not ok
    assert "SLIPPAGE" in spy.last


# ── Balance integrity ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_balance_gap_within_threshold_no_alert():
    d, spy = make_detector(balance_gap_pct=5.0)
    ok = d.check_balance(recorded_equity=100.0, live_equity=103.0)
    assert ok
    assert len(spy.messages) == 0


@pytest.mark.unit
def test_balance_gap_over_threshold_alerts():
    d, spy = make_detector(balance_gap_pct=5.0)
    ok = d.check_balance(recorded_equity=100.0, live_equity=94.0)
    assert not ok
    assert "BALANCE GAP" in spy.last


@pytest.mark.unit
def test_balance_gap_zero_recorded_skips():
    """First run (no DB baseline) — should not alert."""
    d, spy = make_detector()
    ok = d.check_balance(recorded_equity=0.0, live_equity=100.0)
    assert ok
    assert len(spy.messages) == 0


@pytest.mark.unit
def test_balance_gap_symmetric():
    """Gap is absolute — positive gap also alerts."""
    d, spy = make_detector(balance_gap_pct=5.0)
    ok = d.check_balance(recorded_equity=100.0, live_equity=107.0)
    assert not ok
    assert "BALANCE GAP" in spy.last


# ── Stale price ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_price_fresh_on_change():
    d, spy = make_detector(stale_candles=3)
    assert d.check_price_freshness("BTC/USDT", 100.0)
    assert d.check_price_freshness("BTC/USDT", 101.0)  # price changed
    assert len(spy.messages) == 0


@pytest.mark.unit
def test_stale_price_triggers_after_n_unchanged_candles():
    d, spy = make_detector(stale_candles=3)
    d.check_price_freshness("BTC/USDT", 100.0)     # candle 1 — sets baseline
    d.check_price_freshness("BTC/USDT", 100.0)     # candle 2 — stale_count=1
    d.check_price_freshness("BTC/USDT", 100.0)     # candle 3 — stale_count=2
    result = d.check_price_freshness("BTC/USDT", 100.0)  # candle 4 — fires alert
    assert not result
    assert "STALE" in spy.last
    assert "BTC/USDT" in spy.last


@pytest.mark.unit
def test_stale_counter_resets_after_alert():
    """After an alert fires, the counter resets so we don't spam every candle."""
    d, spy = make_detector(stale_candles=2)
    d.check_price_freshness("BTC/USDT", 100.0)
    d.check_price_freshness("BTC/USDT", 100.0)
    d.check_price_freshness("BTC/USDT", 100.0)  # alert fires, counter resets
    assert len(spy.messages) == 1
    # Two more unchanged candles — counter started from 0 again
    d.check_price_freshness("BTC/USDT", 100.0)
    d.check_price_freshness("BTC/USDT", 100.0)
    assert len(spy.messages) == 1   # no second alert yet


@pytest.mark.unit
def test_stale_counter_resets_on_price_change():
    d, spy = make_detector(stale_candles=3)
    d.check_price_freshness("BTC/USDT", 100.0)
    d.check_price_freshness("BTC/USDT", 100.0)   # stale_count=1
    d.check_price_freshness("BTC/USDT", 101.0)   # price changed — reset
    d.check_price_freshness("BTC/USDT", 101.0)   # stale_count=1 again
    d.check_price_freshness("BTC/USDT", 101.0)   # stale_count=2
    result = d.check_price_freshness("BTC/USDT", 101.0)  # fires at 3
    assert not result


@pytest.mark.unit
def test_stale_independent_per_pair():
    """Staleness counters are tracked per pair independently."""
    d, spy = make_detector(stale_candles=2)
    d.check_price_freshness("BTC/USDT", 100.0)
    d.check_price_freshness("BTC/USDT", 100.0)
    d.check_price_freshness("ETH/USDT", 50.0)   # different pair, fresh
    result_btc = d.check_price_freshness("BTC/USDT", 100.0)  # BTC stale
    result_eth = d.check_price_freshness("ETH/USDT", 50.0)   # ETH — stale_count=1
    assert not result_btc
    assert result_eth


# ── Notifier not set ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_no_notifier_does_not_crash():
    """If no notifier is set, anomalies are still detected but don't crash."""
    config = {"risk": {
        "slippage_alert_pct": 0.1,
        "balance_gap_pct": 1.0,
        "stale_price_candles": 1,
    }}
    d = AnomalyDetector(config)
    # _notifier is None — should not raise
    ok = d.check_slippage("X/Y", 100.0, 102.0)
    assert not ok   # still detects
