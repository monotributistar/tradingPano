"""
Walk-forward analysis.

Splits the dataset into N segments, runs the strategy on each segment as
out-of-sample (OOS), and reports per-segment plus aggregate stats.

The first 80 percent of the available candles is used as the walk-forward
window (split into ``n_segments`` equal slices).  The final 20 percent is
intentionally NOT consumed here — it is preserved for a later, independent
hold-out validation (optimizer, final sanity check, etc.).

Every segment is run with the same (default) strategy parameters.  The
intent of walk-forward is NOT parameter optimization here; it is to measure
consistency across different time slices / market regimes.
"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Allow running as a script (`python backtester/walk_forward.py`) as well as
# being imported by the API layer where crypto_bot is already on sys.path.
_BOT_DIR = Path(__file__).resolve().parent.parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

from backtester.runner import BacktestRunner  # noqa: E402
from backtester.data_fetcher import DataFetcher  # noqa: E402

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_float(x, default: float = 0.0) -> float:
    """Convert numpy / pandas numeric into a JSON-safe float."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _date_str(ts) -> str:
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


# ── public API ───────────────────────────────────────────────────────────────

def run_walk_forward(
    strategy,
    pair: str,
    config: dict,
    period: str = "1y",
    n_segments: int = 5,
    candles_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Run walk-forward analysis.

    For every segment ``i`` in ``0 .. n_segments-1``:
      - segments ``[0..i-1]`` conceptually act as in-sample (context only —
        we don't optimize here, we use the strategy's current defaults)
      - segment ``[i]`` is the out-of-sample test window

    Only the first 80% of the dataset is consumed; the last 20% is reserved
    for later independent validation.

    Returns a JSON-serialisable dict; see module docstring for shape.
    """
    n_segments = max(2, int(n_segments))

    bt_cfg = config.get("backtest", {})
    timeframe = bt_cfg.get("timeframe", "1h")
    data_source = bt_cfg.get("data_source", "kucoin")

    if candles_df is None:
        fetcher = DataFetcher(exchange_id=data_source)
        candles_df = fetcher.fetch(pair, timeframe, period)

    if candles_df is None or len(candles_df) == 0:
        return {
            "pair": pair,
            "strategy": getattr(strategy, "name", "unknown"),
            "n_segments": n_segments,
            "period": period,
            "error": "no data",
            "segments": [],
            "aggregate": _empty_aggregate(),
        }

    total_bars = len(candles_df)

    # Reserve last 20% for later validation — only operate on first 80%.
    wf_end = int(total_bars * 0.80)
    wf_df = candles_df.iloc[:wf_end]

    # Need at least ~60 bars per segment for the runner's min warm-up of 50.
    min_required_per_segment = 60
    seg_len = len(wf_df) // n_segments
    if seg_len < min_required_per_segment:
        logger.warning(
            "Walk-forward: segments too small (%d bars each); "
            "reducing n_segments", seg_len,
        )
        n_segments = max(2, len(wf_df) // min_required_per_segment)
        if n_segments < 2:
            return {
                "pair": pair,
                "strategy": getattr(strategy, "name", "unknown"),
                "n_segments": 0,
                "period": period,
                "error": f"insufficient data for walk-forward "
                         f"({len(wf_df)} bars available)",
                "segments": [],
                "aggregate": _empty_aggregate(),
            }
        seg_len = len(wf_df) // n_segments

    runner = BacktestRunner(config)

    segments_out: list[dict] = []
    seg_returns: list[float] = []
    seg_sharpes: list[float] = []
    seg_drawdowns: list[float] = []

    for i in range(n_segments):
        start = i * seg_len
        end = (i + 1) * seg_len if i < n_segments - 1 else len(wf_df)
        seg_df = wf_df.iloc[start:end]

        if len(seg_df) < min_required_per_segment:
            logger.warning("Skipping too-small segment %d (%d bars)", i, len(seg_df))
            continue

        # Fresh strategy state for every OOS slice
        if hasattr(strategy, "reset"):
            try:
                strategy.reset()
            except Exception as e:  # noqa: BLE001
                logger.warning("strategy.reset() failed: %s", e)

        try:
            result = runner.run(strategy, pair, candles_df=seg_df)
        except Exception as e:  # noqa: BLE001
            logger.exception("Segment %d failed", i)
            segments_out.append({
                "index": i,
                "start": _date_str(seg_df.index[0]),
                "end":   _date_str(seg_df.index[-1]),
                "bars": len(seg_df),
                "error": str(e),
                "metrics": {},
                "trades": 0,
                "return_pct": 0.0,
            })
            continue

        metrics = result.get("metrics", {}) or {}
        ret_pct = _safe_float(metrics.get("total_return_pct"))
        sharpe = _safe_float(metrics.get("sharpe_ratio"))
        max_dd = _safe_float(metrics.get("max_drawdown_pct"))

        seg_returns.append(ret_pct)
        seg_sharpes.append(sharpe)
        seg_drawdowns.append(max_dd)

        closed_trades = sum(
            1 for t in result.get("trades", []) if t.get("status") == "closed"
        )

        segments_out.append({
            "index": i,
            "start": _date_str(seg_df.index[0]),
            "end":   _date_str(seg_df.index[-1]),
            "bars":  len(seg_df),
            "metrics": {k: _safe_float(v) if isinstance(v, (int, float, np.integer, np.floating))
                        else v for k, v in metrics.items()},
            "trades": closed_trades,
            "return_pct": round(ret_pct, 3),
        })

    aggregate = _aggregate(seg_returns, seg_sharpes, seg_drawdowns)

    return {
        "pair": pair,
        "strategy": getattr(strategy, "name", "unknown"),
        "n_segments": n_segments,
        "period": period,
        "timeframe": timeframe,
        "total_bars": int(total_bars),
        "walk_forward_bars": int(len(wf_df)),
        "holdout_bars": int(total_bars - len(wf_df)),
        "segments": segments_out,
        "aggregate": aggregate,
    }


# ── internals ────────────────────────────────────────────────────────────────

def _aggregate(returns: list[float], sharpes: list[float],
               drawdowns: list[float]) -> dict:
    if not returns:
        return _empty_aggregate()

    arr = np.asarray(returns, dtype=float)
    sh = np.asarray(sharpes, dtype=float)
    dd = np.asarray(drawdowns, dtype=float)

    positive = int((arr > 0).sum())
    consistency = (positive / len(arr)) * 100.0 if len(arr) else 0.0

    std_return = float(arr.std(ddof=0)) if len(arr) > 1 else 0.0

    return {
        "avg_return_pct":        round(_safe_float(arr.mean()), 3),
        "std_return_pct":        round(_safe_float(std_return), 3),
        "median_return_pct":     round(_safe_float(np.median(arr)), 3),
        "consistency_score":     round(_safe_float(consistency), 2),
        "positive_segments":     positive,
        "avg_sharpe":            round(_safe_float(sh.mean()), 3),
        "avg_max_drawdown_pct":  round(_safe_float(dd.mean()), 3),
        "worst_segment_return":  round(_safe_float(arr.min()), 3),
        "best_segment_return":   round(_safe_float(arr.max()), 3),
    }


def _empty_aggregate() -> dict:
    return {
        "avg_return_pct": 0.0,
        "std_return_pct": 0.0,
        "median_return_pct": 0.0,
        "consistency_score": 0.0,
        "positive_segments": 0,
        "avg_sharpe": 0.0,
        "avg_max_drawdown_pct": 0.0,
        "worst_segment_return": 0.0,
        "best_segment_return": 0.0,
    }


# ── quick self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Synthetic walk-forward sanity check — uses a deterministic random-walk
    dataframe + a naive "buy every N bars, sell K bars later" strategy so we
    don't need network access.
    """
    import logging as _lg
    _lg.basicConfig(level=_lg.INFO, format="%(levelname)s %(name)s %(message)s")

    from strategies.base import BaseStrategy, Signal, TradeSignal

    class _ToyStrategy(BaseStrategy):
        name = "toy_wf"

        def __init__(self):
            self._bars = 0

        def initialize(self, config: dict):
            self._bars = 0

        def reset(self):
            self._bars = 0

        def on_candle(self, pair, candles, position):
            self._bars += 1
            price = float(candles["close"].iloc[-1])
            if position is None and self._bars % 25 == 0:
                return TradeSignal(Signal.BUY, pair, price, 5.0, "buy_every_25")
            if position is not None and (self._bars % 25 == 12):
                return TradeSignal(Signal.SELL, pair, price, 0.0, "sell_after_12")
            return TradeSignal(Signal.HOLD, pair, price, 0.0, "hold")

        def get_params(self):
            return {}

    # Build synthetic OHLCV: 1200 bars, 1h, random walk
    rng = np.random.default_rng(42)
    n = 1200
    rets = rng.normal(0, 0.01, size=n)
    close = 100 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame({
        "open": close, "high": close * 1.002, "low": close * 0.998,
        "close": close, "volume": rng.uniform(10, 100, size=n),
    }, index=idx)

    cfg = {
        "backtest": {
            "initial_capital": 100.0,
            "fee_pct": 0.1,
            "slippage_pct": 0.05,
            "timeframe": "1h",
        },
        "strategies": {},
    }

    result = run_walk_forward(_ToyStrategy(), "BTC/USDT", cfg,
                              n_segments=4, candles_df=df)
    print("Walk-forward self-test")
    print(f"  pair            : {result['pair']}")
    print(f"  strategy        : {result['strategy']}")
    print(f"  n_segments      : {result['n_segments']}")
    print(f"  walk_fwd bars   : {result.get('walk_forward_bars')}")
    print(f"  hold-out bars   : {result.get('holdout_bars')}")
    for s in result["segments"]:
        print(f"   seg {s['index']}: {s['start']} -> {s['end']} "
              f"trades={s['trades']} return={s['return_pct']}%")
    print(f"  aggregate       : {result['aggregate']}")
