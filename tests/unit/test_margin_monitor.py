"""
tests/unit/test_margin_monitor.py
==================================

Unit tests for MarginMonitor (crypto_bot/margin_monitor.py).

All tests are pure — no network I/O, no real threads.
The engine and bot_manager are replaced by simple fakes.
The monitor's `check_once()` method is called directly so that
tests run synchronously without sleeping.
"""

import pytest
from unittest.mock import MagicMock, call


# ── Fakes ──────────────────────────────────────────────────────────────────────

def _make_engine(margin_level: float = 300.0) -> MagicMock:
    engine = MagicMock()
    engine.get_margin_info.return_value = {
        "margin_level":     margin_level,
        "margin_used":      500.0,
        "margin_available": 9500.0,
        "nav":              10_000.0,
    }
    return engine


def _make_bot_manager() -> MagicMock:
    return MagicMock()


def _make_notifier() -> MagicMock:
    n = MagicMock()
    n.send = MagicMock()
    return n


def _make_monitor(margin_level: float = 300.0, interval_s: int = 30):
    from margin_monitor import MarginMonitor
    engine      = _make_engine(margin_level)
    bot_manager = _make_bot_manager()
    notifier    = _make_notifier()
    monitor = MarginMonitor(engine, bot_manager, notifier=notifier, interval_s=interval_s)
    return monitor, engine, bot_manager, notifier


# ── Constructor ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_constructor_stores_params():
    from margin_monitor import MarginMonitor
    engine      = _make_engine()
    bot_manager = _make_bot_manager()
    notifier    = _make_notifier()
    m = MarginMonitor(engine, bot_manager, notifier=notifier, interval_s=60)
    assert m._engine      is engine
    assert m._bot_manager is bot_manager
    assert m._notifier    is notifier
    assert m._interval    == 60


@pytest.mark.unit
def test_constructor_notifier_optional():
    from margin_monitor import MarginMonitor
    engine      = _make_engine()
    bot_manager = _make_bot_manager()
    m = MarginMonitor(engine, bot_manager)  # no notifier
    assert m._notifier is None


@pytest.mark.unit
def test_not_running_initially():
    monitor, *_ = _make_monitor()
    assert monitor._running is False


# ── check_once — healthy (above all thresholds) ────────────────────────────────

@pytest.mark.unit
def test_healthy_level_no_action():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=500.0)
    result = monitor.check_once()
    assert result["level"] == 500.0
    assert result["action"] == "ok"
    bot_manager.stop.assert_not_called()
    notifier.send.assert_not_called()


@pytest.mark.unit
def test_check_once_returns_dict_with_level():
    monitor, engine, *_ = _make_monitor(margin_level=350.0)
    result = monitor.check_once()
    assert "level" in result
    assert result["level"] == 350.0


# ── WARN threshold (≤ 200%) ────────────────────────────────────────────────────

@pytest.mark.unit
def test_warn_level_no_notification_sent():
    """At WARN level (200%), we log but don't notify via Telegram."""
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=200.0)
    result = monitor.check_once()
    assert result["action"] == "warn"
    notifier.send.assert_not_called()
    bot_manager.stop.assert_not_called()


@pytest.mark.unit
def test_just_above_warn_level_is_ok():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=200.1)
    result = monitor.check_once()
    assert result["action"] == "ok"


@pytest.mark.unit
def test_exactly_at_warn_level_warns():
    monitor, *_ = _make_monitor(margin_level=200.0)
    result = monitor.check_once()
    assert result["action"] == "warn"


# ── ALERT threshold (≤ 150%) ──────────────────────────────────────────────────

@pytest.mark.unit
def test_alert_level_sends_notification():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=150.0)
    result = monitor.check_once()
    assert result["action"] == "alert"
    notifier.send.assert_called_once()
    bot_manager.stop.assert_not_called()


@pytest.mark.unit
def test_alert_message_contains_level():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=140.0)
    monitor.check_once()
    msg = notifier.send.call_args[0][0]
    assert "140" in msg or "140.0" in msg


@pytest.mark.unit
def test_alert_message_contains_margin_keyword():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=130.0)
    monitor.check_once()
    msg = notifier.send.call_args[0][0].upper()
    assert "MARGIN" in msg


@pytest.mark.unit
def test_exactly_at_alert_level_alerts():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=150.0)
    result = monitor.check_once()
    assert result["action"] == "alert"
    notifier.send.assert_called_once()


# ── STOP threshold (≤ 110%) ───────────────────────────────────────────────────

@pytest.mark.unit
def test_stop_level_calls_bot_stop():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=110.0)
    result = monitor.check_once()
    assert result["action"] == "stop"
    bot_manager.stop.assert_called_once()


@pytest.mark.unit
def test_stop_level_also_notifies():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=105.0)
    monitor.check_once()
    notifier.send.assert_called_once()


@pytest.mark.unit
def test_stop_message_contains_stop_keyword():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=100.0)
    monitor.check_once()
    msg = notifier.send.call_args[0][0].upper()
    assert "STOP" in msg or "MARGIN" in msg


@pytest.mark.unit
def test_below_stop_level_still_stops():
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=90.0)
    result = monitor.check_once()
    assert result["action"] == "stop"
    bot_manager.stop.assert_called_once()


# ── no_positions special case ─────────────────────────────────────────────────

@pytest.mark.unit
def test_no_positions_returns_ok():
    """When margin_level is 9999.0 (no open positions), action should be 'ok'."""
    monitor, engine, bot_manager, notifier = _make_monitor(margin_level=9999.0)
    result = monitor.check_once()
    assert result["action"] == "ok"
    notifier.send.assert_not_called()
    bot_manager.stop.assert_not_called()


# ── Engine errors ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_engine_error_returns_error_status():
    """If get_margin_info raises, check_once returns action='error' without crashing."""
    from margin_monitor import MarginMonitor
    engine = MagicMock()
    engine.get_margin_info.side_effect = RuntimeError("Connection refused")
    bot_manager = _make_bot_manager()
    notifier    = _make_notifier()
    monitor = MarginMonitor(engine, bot_manager, notifier=notifier)
    result = monitor.check_once()
    assert result["action"] == "error"
    assert "error" in result
    bot_manager.stop.assert_not_called()


@pytest.mark.unit
def test_engine_error_does_not_call_notifier():
    """On engine error, we don't send spurious Telegram messages."""
    from margin_monitor import MarginMonitor
    engine = MagicMock()
    engine.get_margin_info.side_effect = ConnectionError("timeout")
    monitor = MarginMonitor(engine, _make_bot_manager(), notifier=_make_notifier())
    monitor.check_once()
    monitor._notifier.send.assert_not_called()


# ── Notifier absent ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_no_notifier_alert_does_not_crash():
    """Alert-level margin with no notifier set — should not raise."""
    from margin_monitor import MarginMonitor
    engine = _make_engine(margin_level=130.0)
    monitor = MarginMonitor(engine, _make_bot_manager(), notifier=None)
    result = monitor.check_once()  # should not raise
    assert result["action"] == "alert"


@pytest.mark.unit
def test_no_notifier_stop_does_not_crash():
    """Stop-level margin with no notifier set — bot stops, no crash."""
    from margin_monitor import MarginMonitor
    engine      = _make_engine(margin_level=100.0)
    bot_manager = _make_bot_manager()
    monitor = MarginMonitor(engine, bot_manager, notifier=None)
    result = monitor.check_once()
    assert result["action"] == "stop"
    bot_manager.stop.assert_called_once()


# ── Start / stop lifecycle ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_start_sets_running_true():
    import threading
    monitor, *_ = _make_monitor()
    # Patch _loop to do nothing so the thread doesn't run indefinitely
    monitor._loop = lambda: None
    monitor.start()
    assert monitor._running is True
    # Clean up
    monitor.stop()


@pytest.mark.unit
def test_stop_sets_running_false():
    import threading
    monitor, *_ = _make_monitor()
    monitor._loop = lambda: None
    monitor.start()
    monitor.stop()
    assert monitor._running is False


@pytest.mark.unit
def test_start_spawns_daemon_thread():
    import threading
    monitor, *_ = _make_monitor()
    monitor._loop = lambda: None  # no-op so thread exits immediately
    monitor.start()
    assert isinstance(monitor._thread, threading.Thread)
    assert monitor._thread.daemon is True
    monitor.stop()


# ── Class constants ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_class_constants_are_defined():
    from margin_monitor import MarginMonitor
    assert MarginMonitor.WARN_LEVEL  == 200.0
    assert MarginMonitor.ALERT_LEVEL == 150.0
    assert MarginMonitor.STOP_LEVEL  == 110.0


@pytest.mark.unit
def test_interval_default_is_30_seconds():
    from margin_monitor import MarginMonitor
    engine = _make_engine()
    m = MarginMonitor(engine, _make_bot_manager())
    assert m._interval == 30
