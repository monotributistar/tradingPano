"""
Monte Carlo trade-order analysis.

Shuffles the order in which a strategy's realised trade PnLs occur, re-plays
the equity curve for each permutation, and reports the distribution of
outcomes.  This distinguishes "the strategy is genuinely profitable" from
"a couple of lucky trades landed in the right order".
"""
from __future__ import annotations

import math
import logging
import random
from typing import Iterable, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe(x, default: float = 0.0) -> float:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _extract_pnls(trades: Iterable[dict]) -> list[float]:
    """Only closed trades with a non-null pnl field."""
    out: list[float] = []
    for t in trades or []:
        pnl = t.get("pnl") if isinstance(t, dict) else None
        if pnl is None:
            continue
        if isinstance(t, dict) and t.get("status") and t["status"] != "closed":
            continue
        try:
            v = float(pnl)
        except (TypeError, ValueError):
            continue
        if math.isnan(v) or math.isinf(v):
            continue
        out.append(v)
    return out


def _max_drawdown_pct(equity: np.ndarray) -> float:
    """Max drawdown of an equity array as a positive percentage."""
    if equity.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    # avoid division-by-zero on dead accounts
    safe_peaks = np.where(peaks <= 0, np.nan, peaks)
    dd = (equity - safe_peaks) / safe_peaks
    dd = np.nan_to_num(dd, nan=0.0)
    return float(abs(dd.min()) * 100.0) if dd.size else 0.0


# ── public API ───────────────────────────────────────────────────────────────

def run_monte_carlo(
    trades: list,
    initial_capital: float,
    n_runs: int = 1000,
    seed: Optional[int] = None,
) -> dict:
    """
    Parameters
    ----------
    trades : list of dict
        Typically the ``trades`` field of a BacktestRunner result.  Only
        entries with a numeric ``pnl`` and (if present) ``status='closed'``
        are used.
    initial_capital : float
        Starting balance for each shuffled replay.
    n_runs : int
        Number of random permutations to draw (default 1000).
    seed : int | None
        Optional RNG seed for reproducibility.

    Returns
    -------
    dict
        JSON-serialisable summary — see module docstring.
    """
    n_runs = max(1, int(n_runs))
    initial_capital = _safe(initial_capital, 1.0)
    if initial_capital <= 0:
        initial_capital = 1.0

    pnls = _extract_pnls(trades)
    if not pnls:
        return {
            "n_runs": 0,
            "n_trades": 0,
            "initial_capital": round(initial_capital, 6),
            "original_return_pct": 0.0,
            "mean_return_pct": 0.0,
            "median_return_pct": 0.0,
            "std_return_pct": 0.0,
            "percentile_5_pct": 0.0,
            "percentile_95_pct": 0.0,
            "max_drawdown_distribution": {
                "mean": 0.0, "median": 0.0, "percentile_95": 0.0,
            },
            "probability_profit": 0.0,
            "histogram": [],
            "note": "no closed trades with pnl — nothing to simulate",
        }

    pnl_arr = np.asarray(pnls, dtype=float)
    original_final = initial_capital + pnl_arr.sum()
    original_return_pct = (original_final - initial_capital) / initial_capital * 100.0

    rng = np.random.default_rng(seed)
    n_trades = len(pnl_arr)

    final_returns = np.empty(n_runs, dtype=float)
    max_dds = np.empty(n_runs, dtype=float)

    for r in range(n_runs):
        perm = rng.permutation(n_trades)
        shuffled = pnl_arr[perm]
        equity = initial_capital + np.cumsum(shuffled)
        # Include the initial capital at t=0 for realistic DD baseline.
        full = np.concatenate(([initial_capital], equity))
        final_returns[r] = (equity[-1] - initial_capital) / initial_capital * 100.0
        max_dds[r] = _max_drawdown_pct(full)

    # sanitise (shouldn't happen, but be safe for JSON)
    final_returns = np.nan_to_num(final_returns, nan=0.0, posinf=0.0, neginf=0.0)
    max_dds = np.nan_to_num(max_dds, nan=0.0, posinf=0.0, neginf=0.0)

    mean_ret = float(final_returns.mean())
    median_ret = float(np.median(final_returns))
    std_ret = float(final_returns.std(ddof=0))
    p5 = float(np.percentile(final_returns, 5))
    p95 = float(np.percentile(final_returns, 95))
    prob_profit = float((final_returns > 0).mean()) * 100.0

    dd_mean = float(max_dds.mean())
    dd_median = float(np.median(max_dds))
    dd_p95 = float(np.percentile(max_dds, 95))

    # ── histogram (20 buckets) ──────────────────────────────────────────────
    lo = float(final_returns.min())
    hi = float(final_returns.max())
    if math.isclose(lo, hi):
        # all runs produced the same return (degenerate)
        histogram = [{"bucket_pct": round(lo, 3), "count": int(n_runs)}]
    else:
        n_buckets = 20
        edges = np.linspace(lo, hi, n_buckets + 1)
        counts, _ = np.histogram(final_returns, bins=edges)
        histogram = [
            {
                "bucket_pct": round(float((edges[i] + edges[i + 1]) / 2.0), 3),
                "bucket_low": round(float(edges[i]), 3),
                "bucket_high": round(float(edges[i + 1]), 3),
                "count": int(counts[i]),
            }
            for i in range(n_buckets)
        ]

    return {
        "n_runs": int(n_runs),
        "n_trades": int(n_trades),
        "initial_capital": round(initial_capital, 6),
        "original_return_pct": round(_safe(original_return_pct), 3),
        "mean_return_pct": round(_safe(mean_ret), 3),
        "median_return_pct": round(_safe(median_ret), 3),
        "std_return_pct": round(_safe(std_ret), 3),
        "percentile_5_pct": round(_safe(p5), 3),
        "percentile_95_pct": round(_safe(p95), 3),
        "max_drawdown_distribution": {
            "mean":          round(_safe(dd_mean), 3),
            "median":        round(_safe(dd_median), 3),
            "percentile_95": round(_safe(dd_p95), 3),
        },
        "probability_profit": round(_safe(prob_profit), 2),
        "histogram": histogram,
    }


# ── quick self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Synthetic Monte Carlo check with a known positive-expectancy PnL list.
    """
    import logging as _lg
    _lg.basicConfig(level=_lg.INFO, format="%(levelname)s %(name)s %(message)s")

    random.seed(0)
    rng = np.random.default_rng(0)

    # 50 winners + 30 small losers + 5 open (no pnl) + a couple of NaNs
    winners = rng.normal(1.2, 0.6, size=50).round(4).tolist()
    losers = (-rng.normal(0.5, 0.3, size=30)).round(4).tolist()
    trades = []
    for w in winners:
        trades.append({"status": "closed", "pnl": w})
    for l in losers:
        trades.append({"status": "closed", "pnl": l})
    # Edge cases
    trades.append({"status": "open",   "pnl": None})
    trades.append({"status": "closed", "pnl": None})
    trades.append({"status": "closed", "pnl": float("nan")})

    result = run_monte_carlo(trades, initial_capital=100.0, n_runs=1000, seed=7)

    print("Monte Carlo self-test")
    print(f"  n_runs             : {result['n_runs']}")
    print(f"  n_trades           : {result['n_trades']}")
    print(f"  original return %  : {result['original_return_pct']}")
    print(f"  mean / median %    : {result['mean_return_pct']} / {result['median_return_pct']}")
    print(f"  std %              : {result['std_return_pct']}")
    print(f"  P5 / P95 %         : {result['percentile_5_pct']} / {result['percentile_95_pct']}")
    print(f"  P(profit)          : {result['probability_profit']}%")
    print(f"  DD distribution    : {result['max_drawdown_distribution']}")
    print(f"  histogram buckets  : {len(result['histogram'])} "
          f"(first={result['histogram'][0] if result['histogram'] else None})")

    # Empty case
    empty = run_monte_carlo([], initial_capital=100.0, n_runs=500)
    print(f"  empty-case note    : {empty.get('note')}")
