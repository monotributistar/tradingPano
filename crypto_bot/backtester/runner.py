"""
Backtest Engine — bar-by-bar trading simulation.

Simulates a trading session by replaying historical OHLCV candles and calling
``strategy.on_candle()`` on each bar.

Features
--------
- Long and short (simulated futures) positions
- Fee and slippage simulation
- ATR-based risk-managed position sizing via RiskManager
- Daily loss halt to prevent runaway drawdowns
- End-of-period mark-to-market close for open positions
- Equity curve and trade log output

Usage
-----
::

    runner = BacktestRunner(config)
    result = runner.run(strategy, pair="BTC/USDT", period="6m", timeframe="4h")
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, TradeSignal
from backtester.data_fetcher import DataFetcher
from backtester.metrics import compute_metrics
from risk_manager import RiskManager

logger = logging.getLogger(__name__)


class BacktestRunner:
    def __init__(self, config: dict):
        bt_cfg = config.get("backtest", {})
        self.initial_capital = bt_cfg.get("initial_capital", 20.0)
        self.fee_pct = bt_cfg.get("fee_pct", 0.1) / 100
        self.slippage_pct = bt_cfg.get("slippage_pct", 0.05) / 100
        self.timeframe = bt_cfg.get("timeframe", "1h")
        self.data_source = bt_cfg.get("data_source", "kucoin")
        # Daily overnight financing cost as a fraction of position value.
        # Divided by bars_per_day to get per-bar cost.
        # 0.0 disables the feature (default, backward-compatible).
        self.swap_cost_daily_pct = float(bt_cfg.get("swap_cost_daily_pct", 0.0)) / 100
        self.config = config  # keep full config for risk manager
        self.results_dir = Path("data/backtest_results")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.fetcher = DataFetcher(exchange_id=self.data_source)

    def run(
        self,
        strategy: BaseStrategy,
        pair: str,
        period: str = "6m",
        timeframe: Optional[str] = None,
        candles_df: Optional[pd.DataFrame] = None,
        warmup_bars: int = 50,
    ) -> dict:
        """Run a full backtest simulation bar-by-bar.

        Args:
            strategy: Initialised strategy instance implementing BaseStrategy.
            pair: Trading pair in BASE/QUOTE format, e.g. ``"BTC/USDT"``.
            period: Historical window to fetch, e.g. ``"6m"`` or ``"1y"``.
            timeframe: Candle size override, e.g. ``"4h"``. Defaults to the
                value set in ``config["backtest"]["timeframe"]`` (usually ``"1h"``).
            candles_df: Pre-fetched OHLCV DataFrame. When provided, skips the
                DataFetcher call entirely — useful for walk-forward slicing.
            warmup_bars: Bars skipped at the start to allow indicators to warm up.

        Returns:
            dict with keys: strategy, pair, period, timeframe, params, metrics,
            trades, equity_curve, equity_timestamps, halt_events, risk_info, run_at.

        Position dict schema::

            {
                "side": "long" | "short",
                "qty": float,
                "avg_cost": float,
                "entry_bar": int,
                "bars_held": int,
                "entries": list[dict],
                # short-only:
                "collateral": float,
            }
        """
        active_timeframe = timeframe or self.timeframe
        strategy.reset()

        if candles_df is None:
            candles_df = self.fetcher.fetch(pair, active_timeframe, period)

        balance_usdt = self.initial_capital
        position: Optional[dict] = None
        trades = []
        equity_curve = []
        equity_timestamps = []
        halt_events = []  # track when the risk manager halted
        total_swap_cost = 0.0  # accumulated overnight financing charges

        # Bars-per-day mapping used to amortise the daily swap rate.
        _bars_per_day: dict[str, float] = {
            "M1": 1440, "M5": 288, "M15": 96, "M30": 48,
            "H1": 24,   "H4": 6,   "H12": 2,  "D": 1,
            "1m": 1440, "5m": 288, "15m": 96, "30m": 48,
            "1h": 24,   "4h": 6,   "12h": 2,  "1d": 1,
            "1w": 1/7,
        }
        bars_per_day = _bars_per_day.get(active_timeframe, 24)

        # Risk manager enforces leverage, daily loss stop, position sizing
        risk_mgr = RiskManager(self.config, self.initial_capital)

        min_bars = max(warmup_bars, 50)

        for i in range(min_bars, len(candles_df)):
            candles = candles_df.iloc[:i + 1]
            price = float(candles["close"].iloc[-1])
            timestamp = candles.index[-1]

            if position is not None:
                position["bars_held"] += 1

            # ── OVERNIGHT FINANCING (SWAP) COST ────────────────────────────────
            # Deduct per-bar swap cost from balance while a position is open.
            # cost_per_bar = (swap_cost_daily_pct / bars_per_day) * position_value
            if position is not None and self.swap_cost_daily_pct > 0.0:
                if position["side"] == "long":
                    pos_value = position["qty"] * price
                else:  # short
                    pos_value = position["collateral"]
                swap_cost = (self.swap_cost_daily_pct / bars_per_day) * pos_value
                balance_usdt -= swap_cost
                total_swap_cost += swap_cost

            signal_obj: TradeSignal = strategy.on_candle(pair, candles, position)
            sig = signal_obj.signal

            # Compute current equity for risk checks
            if position is None:
                current_equity = balance_usdt
            elif position["side"] == "long":
                current_equity = balance_usdt + position["qty"] * price
            else:
                unrealized = (position["avg_cost"] - price) * position["qty"]
                current_equity = balance_usdt + position["collateral"] + unrealized

            # Daily loss check — only blocks NEW trades, doesn't force close
            halted, halt_reason = risk_mgr.check_daily_loss(current_equity, timestamp)
            if halted and sig in (Signal.BUY, Signal.SHORT):
                if not halt_events or halt_events[-1]["bar"] != i:
                    halt_events.append({"bar": i, "timestamp": str(timestamp), "reason": halt_reason})
                sig = Signal.HOLD

            # Apply risk-managed position sizing for new entries
            atr_val = signal_obj.metadata.get("atr") if signal_obj.metadata else None
            if sig in (Signal.BUY, Signal.SHORT) and signal_obj.amount_usd > 0:
                adj_amount = risk_mgr.compute_position_size(
                    signal_obj.amount_usd, current_equity,
                    atr=atr_val, price=price,
                )
                signal_obj = TradeSignal(
                    sig, pair, price, adj_amount, signal_obj.reason,
                    confidence=signal_obj.confidence,
                    metadata=signal_obj.metadata,
                )

            # ── LONG OPEN ──────────────────────────────────────────────────────
            if sig == Signal.BUY and signal_obj.amount_usd > 0 and (
                position is None or position["side"] == "long"
            ):
                fill_price = price * (1 + self.slippage_pct)
                fee = signal_obj.amount_usd * self.fee_pct
                cost = signal_obj.amount_usd + fee

                if balance_usdt >= cost:
                    qty = signal_obj.amount_usd / fill_price
                    balance_usdt -= cost

                    if position is None:
                        position = {
                            "side": "long",
                            "qty": qty,
                            "avg_cost": fill_price,
                            "entry_bar": i,
                            "bars_held": 0,
                            "entries": [{"price": fill_price, "qty": qty, "fee": fee}],
                        }
                    else:
                        # DCA into existing long
                        total_qty = position["qty"] + qty
                        position["avg_cost"] = (
                            position["avg_cost"] * position["qty"] + fill_price * qty
                        ) / total_qty
                        position["qty"] = total_qty
                        position["entries"].append({"price": fill_price, "qty": qty, "fee": fee})

                    trades.append({
                        "type": "buy", "side": "long", "pair": pair,
                        "price": fill_price, "qty": qty, "fee": fee, "bar": i,
                        "timestamp": str(timestamp), "reason": signal_obj.reason,
                        "status": "open",
                    })

            # ── LONG CLOSE ─────────────────────────────────────────────────────
            elif sig in (Signal.SELL, Signal.STOP_LOSS, Signal.TIME_EXIT) and (
                position is not None and position["side"] == "long"
            ):
                fill_price = price * (1 - self.slippage_pct)
                qty = position["qty"]
                gross = qty * fill_price
                fee = gross * self.fee_pct
                net = gross - fee
                balance_usdt += net

                total_cost = position["avg_cost"] * qty
                pnl = net - total_cost
                pnl_pct = pnl / total_cost * 100 if total_cost else 0

                trades.append({
                    "type": "sell", "side": "long", "pair": pair,
                    "price": fill_price, "qty": qty, "fee": fee, "bar": i,
                    "timestamp": str(timestamp), "reason": signal_obj.reason,
                    "pnl": round(pnl, 6), "pnl_pct": round(pnl_pct, 3),
                    "duration_bars": i - position["entry_bar"],
                    "avg_cost": position["avg_cost"], "status": "closed",
                })
                position = None

            # ── SHORT OPEN ─────────────────────────────────────────────────────
            elif sig == Signal.SHORT and signal_obj.amount_usd > 0 and position is None:
                fill_price = price * (1 - self.slippage_pct)
                collateral = signal_obj.amount_usd
                fee = collateral * self.fee_pct
                total_required = collateral + fee

                if balance_usdt >= total_required:
                    qty = collateral / fill_price
                    # Deduct both collateral AND fee from balance
                    balance_usdt -= total_required

                    position = {
                        "side": "short",
                        "qty": qty,
                        "avg_cost": fill_price,
                        "entry_bar": i,
                        "bars_held": 0,
                        "collateral": collateral,
                        "entries": [{"price": fill_price, "qty": qty, "fee": fee}],
                    }

                    trades.append({
                        "type": "short", "side": "short", "pair": pair,
                        "price": fill_price, "qty": qty, "fee": fee, "bar": i,
                        "timestamp": str(timestamp), "reason": signal_obj.reason,
                        "status": "open",
                    })

            # ── SHORT CLOSE (COVER) ────────────────────────────────────────────
            elif sig in (Signal.COVER, Signal.STOP_LOSS, Signal.TIME_EXIT) and (
                position is not None and position["side"] == "short"
            ):
                fill_price = price * (1 + self.slippage_pct)  # buy back at slightly higher
                qty = position["qty"]
                fee = qty * fill_price * self.fee_pct

                # PnL for short: (entry_price - exit_price) * qty - fees
                short_entry = position["avg_cost"]
                pnl = (short_entry - fill_price) * qty - fee
                pnl_pct = pnl / (short_entry * qty) * 100 if short_entry * qty else 0

                # Return collateral +/- pnl
                balance_usdt += position["collateral"] + pnl

                trades.append({
                    "type": "cover", "side": "short", "pair": pair,
                    "price": fill_price, "qty": qty, "fee": fee, "bar": i,
                    "timestamp": str(timestamp), "reason": signal_obj.reason,
                    "pnl": round(pnl, 6), "pnl_pct": round(pnl_pct, 3),
                    "duration_bars": i - position["entry_bar"],
                    "avg_cost": short_entry, "status": "closed",
                })
                position = None

            # ── EQUITY CALCULATION ─────────────────────────────────────────────
            if position is None:
                equity_curve.append(balance_usdt)
            elif position["side"] == "long":
                equity_curve.append(balance_usdt + position["qty"] * price)
            else:  # short: equity = balance + collateral + unrealized PnL
                unrealized = (position["avg_cost"] - price) * position["qty"]
                equity_curve.append(balance_usdt + position["collateral"] + unrealized)

            equity_timestamps.append(str(timestamp))

        # ── CLOSE OPEN POSITION AT END (mark-to-market) ────────────────────────
        if position is not None:
            last_price = float(candles_df["close"].iloc[-1])
            qty = position["qty"]
            if position["side"] == "long":
                pnl = qty * last_price - position["avg_cost"] * qty
                trade_type = "sell_eod"
            else:
                pnl = (position["avg_cost"] - last_price) * qty
                balance_usdt += position["collateral"]
                trade_type = "cover_eod"

            avg_cost = position["avg_cost"]
            trades.append({
                "type": trade_type, "side": position["side"], "pair": pair,
                "price": last_price, "qty": qty, "fee": 0,
                "bar": len(candles_df) - 1,
                "timestamp": str(candles_df.index[-1]),
                "reason": "end of backtest",
                "pnl": round(pnl, 6),
                "pnl_pct": round(pnl / (avg_cost * qty) * 100, 3) if avg_cost * qty else 0,
                "duration_bars": len(candles_df) - 1 - position["entry_bar"],
                "avg_cost": avg_cost, "status": "closed",
            })

        metrics = compute_metrics(
            equity_curve, trades, self.initial_capital, active_timeframe
        )

        return {
            "strategy": strategy.name,
            "pair": pair,
            "period": period,
            "timeframe": active_timeframe,
            "params": strategy.get_params(),
            "metrics": metrics,
            "trades": trades,
            "equity_curve": equity_curve,
            "equity_timestamps": equity_timestamps,
            "halt_events": halt_events,
            "risk_info": risk_mgr.info(),
            "run_at": datetime.now(tz=timezone.utc).isoformat(),
            "total_swap_cost": round(total_swap_cost, 6),
        }

    def save_result(self, result: dict) -> Path:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"{result['strategy']}_{result['pair'].replace('/', '_')}_{ts}.json"
        path = self.results_dir / fname
        with open(path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"Resultado guardado: {path}")
        return path
