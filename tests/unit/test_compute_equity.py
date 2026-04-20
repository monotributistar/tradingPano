"""
tests/unit/test_compute_equity.py
===================================

Unit tests for api/bot_manager._compute_equity.
This helper is the backbone of equity tracking for both the RiskManager
integration and the balance integrity check.
"""

import pytest
import sys
from pathlib import Path

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.bot_manager import _compute_equity


@pytest.mark.unit
def test_no_positions_returns_initial_balance():
    equity = _compute_equity({}, {}, initial_balance=100.0)
    assert equity == 100.0


@pytest.mark.unit
def test_single_long_position_at_cost():
    """When market price == avg_cost there's no P&L."""
    positions = {"BTC/USDT": {"qty": 0.01, "avg_cost": 50_000.0}}
    prices    = {"BTC/USDT": 50_000.0}
    equity    = _compute_equity(positions, prices, initial_balance=1_000.0)
    # cost_basis = 500, balance_usdt = 500, pos_value = 500
    assert equity == 1_000.0


@pytest.mark.unit
def test_single_long_position_with_gain():
    positions = {"BTC/USDT": {"qty": 0.01, "avg_cost": 50_000.0}}
    prices    = {"BTC/USDT": 60_000.0}   # +20%
    equity    = _compute_equity(positions, prices, initial_balance=1_000.0)
    # cost_basis = 500, balance_usdt = 500, pos_value = 600
    assert equity == 1_100.0


@pytest.mark.unit
def test_single_long_position_with_loss():
    positions = {"BTC/USDT": {"qty": 0.01, "avg_cost": 50_000.0}}
    prices    = {"BTC/USDT": 40_000.0}   # -20%
    equity    = _compute_equity(positions, prices, initial_balance=1_000.0)
    # cost_basis = 500, balance_usdt = 500, pos_value = 400
    assert equity == 900.0


@pytest.mark.unit
def test_multiple_positions():
    positions = {
        "BTC/USDT": {"qty": 0.01, "avg_cost": 50_000.0},
        "ETH/USDT": {"qty": 0.1,  "avg_cost":  2_000.0},
    }
    prices = {
        "BTC/USDT": 50_000.0,   # flat
        "ETH/USDT":  2_500.0,   # +25%
    }
    equity = _compute_equity(positions, prices, initial_balance=1_000.0)
    # cost_basis = 500 + 200 = 700
    # balance_usdt = 1000 - 700 = 300
    # pos_value = 500 + 250 = 750
    # total = 300 + 750 = 1050
    assert equity == 1_050.0


@pytest.mark.unit
def test_falls_back_to_avg_cost_when_price_missing():
    """If a pair has no entry in current_prices, uses avg_cost as price."""
    positions = {"BTC/USDT": {"qty": 0.01, "avg_cost": 50_000.0}}
    equity    = _compute_equity(positions, {}, initial_balance=1_000.0)
    # No price → uses avg_cost → same as no gain/loss
    assert equity == 1_000.0


@pytest.mark.unit
def test_balance_usdt_floored_at_zero():
    """Guard: balance_usdt never goes negative (over-leveraged paper positions)."""
    # cost_basis > initial_balance (simulates leverage / over-investment)
    positions = {"BTC/USDT": {"qty": 1.0, "avg_cost": 5_000.0}}
    prices    = {"BTC/USDT": 6_000.0}
    equity    = _compute_equity(positions, prices, initial_balance=100.0)
    # cost_basis = 5000, balance_usdt = max(0, 100 - 5000) = 0
    # pos_value = 6000 → total = 6000
    assert equity == 6_000.0


@pytest.mark.unit
def test_equity_is_rounded_to_4_decimal_places():
    positions = {"BTC/USDT": {"qty": 0.00001, "avg_cost": 50_000.0}}
    prices    = {"BTC/USDT": 50_001.11111}
    equity    = _compute_equity(positions, prices, initial_balance=100.0)
    assert len(str(equity).split(".")[-1]) <= 4
