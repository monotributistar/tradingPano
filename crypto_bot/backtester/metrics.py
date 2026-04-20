"""
Métricas de performance para backtesting.
"""
import math
from typing import Optional
import numpy as np
import pandas as pd


def compute_metrics(equity_curve: list[float], trades: list[dict],
                    initial_capital: float, timeframe: str = "1h") -> dict:
    """
    Calcula métricas completas de performance.

    Args:
        equity_curve: lista de valores del portfolio en cada barra
        trades: lista de trades cerrados con keys: pnl, pnl_pct, duration_bars
        initial_capital: capital inicial en USDT
        timeframe: timeframe de las velas (para anualización)

    Returns:
        dict con todas las métricas
    """
    if not equity_curve:
        return _empty_metrics()

    equity = np.array(equity_curve, dtype=float)
    final_capital = equity[-1]

    # Total Return
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100

    # Returns por barra
    returns = np.diff(equity) / equity[:-1]
    returns = returns[~np.isnan(returns)]

    # Sharpe Ratio (anualizado)
    bars_per_year = _bars_per_year(timeframe)
    if len(returns) > 1 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * math.sqrt(bars_per_year)
    else:
        sharpe = 0.0

    # Sortino Ratio
    downside = returns[returns < 0]
    if len(downside) > 1 and downside.std() > 0:
        sortino = (returns.mean() / downside.std()) * math.sqrt(bars_per_year)
    else:
        sortino = 0.0

    # Max Drawdown
    max_dd_pct, max_dd_duration = _max_drawdown(equity)

    # Trade stats
    closed = [t for t in trades if t.get("status") == "closed"]
    total_trades = len(closed)

    if total_trades > 0:
        pnls = [t["pnl"] for t in closed]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        win_rate = len(winners) / total_trades * 100
        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy = sum(pnls) / total_trades
        avg_duration = np.mean([t.get("duration_bars", 0) for t in closed])
        avg_win = np.mean(winners) if winners else 0
        avg_loss = np.mean(losers) if losers else 0
    else:
        win_rate = 0.0
        profit_factor = 0.0
        expectancy = 0.0
        avg_duration = 0.0
        avg_win = 0.0
        avg_loss = 0.0

    # Capital Utilization: % del tiempo con posición abierta
    bars_in_position = sum(1 for t in trades if t.get("status") in ("open", "closed"))
    capital_util = bars_in_position / len(equity_curve) * 100 if equity_curve else 0

    return {
        "total_return_pct": round(total_return_pct, 2),
        "final_capital": round(final_capital, 4),
        "initial_capital": round(initial_capital, 4),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_duration_bars": max_dd_duration,
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "total_trades": total_trades,
        "avg_trade_duration_bars": round(avg_duration, 1),
        "expectancy_usd": round(expectancy, 4),
        "capital_utilization_pct": round(capital_util, 1),
        "avg_win_usd": round(avg_win, 4),
        "avg_loss_usd": round(avg_loss, 4),
    }


def _max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    """Retorna (max_drawdown_pct, duración_en_barras)."""
    peak = equity[0]
    max_dd = 0.0
    max_dd_duration = 0
    dd_start = 0

    for i, val in enumerate(equity):
        if val > peak:
            peak = val
            dd_start = i
        dd = (val - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
            max_dd_duration = i - dd_start

    return abs(max_dd), max_dd_duration


def _bars_per_year(timeframe: str) -> int:
    mapping = {
        "1m": 525_600, "5m": 105_120, "15m": 35_040,
        "30m": 17_520, "1h": 8_760, "4h": 2_190, "1d": 365,
    }
    return mapping.get(timeframe, 8_760)


def _empty_metrics() -> dict:
    return {
        "total_return_pct": 0.0, "final_capital": 0.0, "initial_capital": 0.0,
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "max_drawdown_pct": 0.0,
        "max_drawdown_duration_bars": 0, "win_rate_pct": 0.0,
        "profit_factor": 0.0, "total_trades": 0, "avg_trade_duration_bars": 0.0,
        "expectancy_usd": 0.0, "capital_utilization_pct": 0.0,
        "avg_win_usd": 0.0, "avg_loss_usd": 0.0,
    }
