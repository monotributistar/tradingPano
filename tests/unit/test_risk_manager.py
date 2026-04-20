"""
tests/unit/test_risk_manager.py
================================

Unit tests for crypto_bot/risk_manager.py.

All tests are pure (no I/O, no DB, no network).
The RiskManager is instantiated directly with inline config dicts.
"""

import pytest
from datetime import datetime, timezone

from risk_manager import RiskManager, _parse_blackout


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_rm(
    *,
    daily_loss_pct:      float = 10.0,
    max_drawdown_pct:    float = 0.0,
    max_daily_trades:    int   = 0,
    max_consecutive:     int   = 0,
    blackout:            str   = "",
    max_concurrent:      int   = 3,
    leverage:            float = 1.0,
    initial_capital:     float = 100.0,
) -> RiskManager:
    config = {
        "risk": {
            "daily_loss_stop_pct":    daily_loss_pct,
            "max_drawdown_pct":       max_drawdown_pct,
            "max_daily_trades":       max_daily_trades,
            "max_consecutive_losses": max_consecutive,
            "blackout_hours":         blackout,
            "max_concurrent_positions": max_concurrent,
            "leverage":               leverage,
        }
    }
    return RiskManager(config, initial_capital)


NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)  # noon UTC


# ── Basic operation ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_no_halt_when_equity_unchanged():
    rm = make_rm()
    halted, reason = rm.check_all(100.0, NOW)
    assert not halted
    assert reason == ""


@pytest.mark.unit
def test_no_halt_on_first_call_with_gain():
    rm = make_rm()
    halted, reason = rm.check_all(110.0, NOW)
    assert not halted


# ── Daily loss stop ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_daily_loss_halt_triggered():
    rm = make_rm(daily_loss_pct=5.0, initial_capital=100.0)
    # Simulate a day start at 100, then loss to 94 (6 % loss)
    rm.check_all(100.0, NOW)                         # sets day_start_equity=100
    halted, reason = rm.check_all(94.0, NOW)
    assert halted
    assert "daily loss" in reason


@pytest.mark.unit
def test_daily_loss_not_triggered_below_threshold():
    rm = make_rm(daily_loss_pct=5.0, initial_capital=100.0)
    rm.check_all(100.0, NOW)
    halted, _ = rm.check_all(96.0, NOW)              # only 4 % loss
    assert not halted


@pytest.mark.unit
def test_daily_loss_resets_at_midnight():
    """Day-scoped halt should clear when the UTC date rolls over."""
    rm = make_rm(daily_loss_pct=5.0, initial_capital=100.0)
    rm.check_all(100.0, NOW)
    rm.check_all(90.0, NOW)            # triggers halt

    next_day = datetime(2026, 4, 18, 0, 5, 0, tzinfo=timezone.utc)
    halted, reason = rm.check_all(90.0, next_day)
    # Halt should be cleared for a new day
    assert not halted


# ── Max drawdown ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_max_drawdown_halt():
    rm = make_rm(max_drawdown_pct=20.0, initial_capital=100.0)
    rm.check_all(120.0, NOW)           # new peak = 120
    halted, reason = rm.check_all(95.0, NOW)   # 20.8% from peak → halt
    assert halted
    assert "drawdown" in reason


@pytest.mark.unit
def test_max_drawdown_not_triggered():
    rm = make_rm(max_drawdown_pct=20.0, initial_capital=100.0)
    rm.check_all(120.0, NOW)           # peak = 120
    halted, _ = rm.check_all(100.0, NOW)        # 16.7% — below 20%
    assert not halted


@pytest.mark.unit
def test_max_drawdown_zero_means_disabled():
    rm = make_rm(max_drawdown_pct=0.0, initial_capital=100.0)
    halted, _ = rm.check_all(1.0, NOW)          # massive loss — drawdown disabled
    assert not halted


# ── Max daily trades ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_max_daily_trades_halt():
    rm = make_rm(max_daily_trades=3, initial_capital=100.0)
    for _ in range(3):
        rm.check_all(100.0, NOW, trade_type="win")
    halted, reason = rm.check_all(100.0, NOW, trade_type="win")
    assert halted
    assert "daily trades" in reason


@pytest.mark.unit
def test_max_daily_trades_zero_means_disabled():
    rm = make_rm(max_daily_trades=0, initial_capital=100.0)
    for _ in range(100):
        rm.check_all(100.0, NOW, trade_type="win")
    halted, _ = rm.check_all(100.0, NOW)
    assert not halted


@pytest.mark.unit
def test_daily_trades_reset_next_day():
    rm = make_rm(max_daily_trades=2, initial_capital=100.0)
    rm.check_all(100.0, NOW, trade_type="win")
    rm.check_all(100.0, NOW, trade_type="win")
    # Next UTC day
    next_day = datetime(2026, 4, 18, 0, 5, 0, tzinfo=timezone.utc)
    halted, _ = rm.check_all(100.0, next_day, trade_type="win")
    assert not halted   # counter reset


# ── Max consecutive losses ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_consecutive_losses_halt():
    rm = make_rm(max_consecutive=3, initial_capital=100.0)
    for _ in range(3):
        rm.check_all(100.0, NOW, trade_type="loss")
    halted, reason = rm.check_all(100.0, NOW)
    assert halted
    assert "consecutive" in reason


@pytest.mark.unit
def test_consecutive_losses_reset_on_win():
    rm = make_rm(max_consecutive=3, initial_capital=100.0)
    rm.check_all(100.0, NOW, trade_type="loss")
    rm.check_all(100.0, NOW, trade_type="loss")
    rm.check_all(100.0, NOW, trade_type="win")   # resets counter
    # 2 more losses — not yet at threshold
    rm.check_all(100.0, NOW, trade_type="loss")
    rm.check_all(100.0, NOW, trade_type="loss")
    halted, _ = rm.check_all(100.0, NOW)
    assert not halted


@pytest.mark.unit
def test_consecutive_losses_zero_means_disabled():
    rm = make_rm(max_consecutive=0, initial_capital=100.0)
    for _ in range(20):
        rm.check_all(100.0, NOW, trade_type="loss")
    halted, _ = rm.check_all(100.0, NOW)
    assert not halted


# ── Blackout hours ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_blackout_skips_during_window():
    rm = make_rm(blackout="11:00-13:00")   # noon is inside
    halted, reason = rm.check_all(100.0, NOW)
    assert halted
    assert "blackout" in reason
    # Not a permanent halt — self._halted should still be False
    assert not rm._halted


@pytest.mark.unit
def test_blackout_allows_outside_window():
    rm = make_rm(blackout="22:00-06:00")   # noon is outside
    halted, _ = rm.check_all(100.0, NOW)
    assert not halted


@pytest.mark.unit
def test_blackout_midnight_wrapping():
    rm = make_rm(blackout="22:00-06:00")
    midnight_ts = datetime(2026, 4, 17, 23, 30, 0, tzinfo=timezone.utc)
    halted, reason = rm.check_all(100.0, midnight_ts)
    assert halted
    assert "blackout" in reason

    early_morning = datetime(2026, 4, 18, 5, 59, 0, tzinfo=timezone.utc)
    halted2, _ = rm.check_all(100.0, early_morning)
    assert halted2

    morning = datetime(2026, 4, 18, 6, 1, 0, tzinfo=timezone.utc)
    halted3, _ = rm.check_all(100.0, morning)
    assert not halted3


# ── Already halted ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_already_halted_stays_halted():
    rm = make_rm(max_drawdown_pct=5.0, initial_capital=100.0)
    rm.check_all(120.0, NOW)
    rm.check_all(50.0, NOW)   # triggers drawdown halt
    assert rm._halted
    # Even with good equity, stays halted
    halted, reason = rm.check_all(200.0, NOW)
    assert halted
    assert "halted" in reason.lower() or rm._halt_reason in reason


# ── Max concurrent positions ───────────────────────────────────────────────────

@pytest.mark.unit
def test_can_open_new_position_allows():
    rm = make_rm(max_concurrent=3)
    ok, _ = rm.can_open_new_position(2)
    assert ok


@pytest.mark.unit
def test_can_open_new_position_blocks():
    rm = make_rm(max_concurrent=3)
    ok, reason = rm.can_open_new_position(3)
    assert not ok
    assert "max positions" in reason


# ── Position sizing ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_fixed_sizing_returns_base_amount():
    rm = make_rm(leverage=1.0)
    size = rm.compute_position_size(10.0, current_equity=100.0)
    assert size == 10.0


@pytest.mark.unit
def test_leverage_multiplies_size():
    rm = make_rm(leverage=2.0)
    size = rm.compute_position_size(10.0, current_equity=100.0)
    assert size == 20.0


@pytest.mark.unit
def test_leverage_capped_at_3x():
    rm = make_rm(leverage=5.0)   # should be capped at 3x
    assert rm.leverage == 3.0


@pytest.mark.unit
def test_size_capped_at_50_pct_equity():
    rm = make_rm(leverage=1.0)
    # Asking for 80 USDT with 100 equity — should be capped at 50
    size = rm.compute_position_size(80.0, current_equity=100.0)
    assert size == 50.0


# ── _parse_blackout helper ─────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("raw,expected_start,expected_end", [
    ("22:00-06:00", "22:00", "06:00"),
    ("01:30-05:45", "01:30", "05:45"),
    ("",            "",      ""),
    ("invalid",     "",      ""),
    ("25:00-06:00", "",      ""),   # invalid hour
])
def test_parse_blackout(raw, expected_start, expected_end):
    start, end = _parse_blackout(raw)
    assert start == expected_start
    assert end   == expected_end
