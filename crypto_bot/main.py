#!/usr/bin/env python3
"""
Crypto Trading Bot — CLI principal.

Usage:
  python main.py backtest --strategy mean_reversion --pair BTC/USDT --period 6m
  python main.py backtest --strategy all --pair BTC/USDT --period 1y
  python main.py backtest --strategy bollinger_dca --pair ETH/USDT --optimize
  python main.py paper --strategy mean_reversion --pairs BTC/USDT,ETH/USDT
  python main.py live --strategy mean_reversion --pairs BTC/USDT
  python main.py compare --strategies mean_reversion,ema_crossover --pair BTC/USDT --period 6m
  python main.py status
"""
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.logging import RichHandler

console = Console()

# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging(config: dict):
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO"))
    log_file = log_cfg.get("file", "data/bot.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    handlers = [
        logging.FileHandler(log_file),
    ]
    if log_cfg.get("rich_console", True):
        handlers.append(RichHandler(console=console, show_time=False, show_path=False))

    logging.basicConfig(level=level, handlers=handlers,
                        format="%(message)s", datefmt="[%X]")


# ── Config loader ──────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Strategy registry ──────────────────────────────────────────────────────────

def get_strategy_registry():
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.ema_crossover import EMACrossoverStrategy
    from strategies.bollinger_dca import BollingerDCAStrategy
    from strategies.rsi_mean_revert import RSIMeanRevertStrategy
    from strategies.grid_dynamic import GridDynamicStrategy
    from strategies.threshold_rebalance import ThresholdRebalanceStrategy

    return {
        "mean_reversion": MeanReversionStrategy,
        "ema_crossover": EMACrossoverStrategy,
        "bollinger_dca": BollingerDCAStrategy,
        "rsi_mean_revert": RSIMeanRevertStrategy,
        "grid_dynamic": GridDynamicStrategy,
        "threshold_rebalance": ThresholdRebalanceStrategy,
    }


def load_strategy(name: str, config: dict):
    registry = get_strategy_registry()
    if name not in registry:
        console.print(f"[red]Estrategia desconocida: {name}[/red]")
        console.print(f"Disponibles: {', '.join(registry.keys())}")
        sys.exit(1)
    strategy = registry[name]()
    strategy_cfg = config.get("strategies", {}).get(name, {})
    strategy.initialize(strategy_cfg)
    return strategy


# ── Rich output helpers ────────────────────────────────────────────────────────

def print_backtest_result(result: dict):
    m = result["metrics"]
    strategy = result["strategy"]
    pair = result["pair"]
    period = result["period"]

    ret_color = "green" if m["total_return_pct"] >= 0 else "red"
    dd_color = "red" if m["max_drawdown_pct"] > 5 else "yellow"

    # Mini equity curve using block characters
    curve = result.get("equity_curve", [])
    if curve:
        mn, mx = min(curve), max(curve)
        rng = mx - mn if mx != mn else 1
        chars = "▁▂▃▄▅▆▇█"
        mini = "".join(chars[int((v - mn) / rng * 7)] for v in curve[::max(1, len(curve)//40)])
    else:
        mini = ""

    panel_content = (
        f"  [bold]Total Return:[/bold]   [{ret_color}]{m['total_return_pct']:+.1f}%[/{ret_color}]"
        f"     [bold]Sharpe Ratio:[/bold]   {m['sharpe_ratio']:.2f}\n"
        f"  [bold]Max Drawdown:[/bold]   [{dd_color}]-{m['max_drawdown_pct']:.1f}%[/{dd_color}]"
        f"     [bold]Win Rate:[/bold]       {m['win_rate_pct']:.1f}%\n"
        f"  [bold]Total Trades:[/bold]   {m['total_trades']}"
        f"           [bold]Profit Factor:[/bold]  {m['profit_factor']:.2f}\n"
        f"  [bold]Avg Duration:[/bold]   {m['avg_trade_duration_bars']:.1f}h"
        f"        [bold]Sortino:[/bold]        {m['sortino_ratio']:.2f}\n"
        f"  [bold]Expectancy:[/bold]     ${m['expectancy_usd']:.4f}"
        f"      [bold]Capital Used:[/bold]   {m['capital_utilization_pct']:.1f}%\n\n"
        f"  [dim]{mini}[/dim]"
    )

    console.print(Panel(
        panel_content,
        title=f"[bold cyan]Backtest: {strategy} on {pair} ({period})[/bold cyan]",
        border_style="cyan",
        expand=False,
    ))


def print_compare_table(results: list[dict]):
    table = Table(title="Strategy Comparison", box=box.ROUNDED,
                  show_header=True, header_style="bold magenta")
    table.add_column("Strategy", style="cyan", no_wrap=True)
    table.add_column("Return", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Sortino", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("WinRate", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("PF", justify="right")

    results_sorted = sorted(results, key=lambda r: r["metrics"]["sharpe_ratio"], reverse=True)

    for r in results_sorted:
        m = r["metrics"]
        ret = m["total_return_pct"]
        ret_str = f"[green]+{ret:.1f}%[/green]" if ret >= 0 else f"[red]{ret:.1f}%[/red]"
        table.add_row(
            r["strategy"],
            ret_str,
            f"{m['sharpe_ratio']:.2f}",
            f"{m['sortino_ratio']:.2f}",
            f"[red]-{m['max_drawdown_pct']:.1f}%[/red]",
            f"{m['win_rate_pct']:.1f}%",
            str(m["total_trades"]),
            f"{m['profit_factor']:.2f}",
        )

    console.print(table)


# ── Bot runner (paper / live) ──────────────────────────────────────────────────

class BotRunner:
    def __init__(self, engine, strategy, pairs: list[str],
                 config: dict, mode: str = "paper"):
        self.engine = engine
        self.strategy = strategy
        self.pairs = pairs
        self.config = config
        self.mode = mode
        self.running = True
        self.state_path = Path("data/bot_state.json")

        from tracker.trade_logger import TradeLogger
        from tracker.portfolio import Portfolio
        self.logger = TradeLogger()
        bt_cfg = config.get(mode, config.get("paper", {}))
        self.portfolio = Portfolio(initial_balance=bt_cfg.get("initial_balance", 20.0))
        self._positions: dict = {}  # pair -> {qty, avg_cost, entry_time, bars_held}
        self._load_state()

    def _load_state(self):
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    state = json.load(f)
                self._positions = state.get("positions", {})
                strategy_state = state.get("strategy_state", {})
                if strategy_state:
                    self.strategy.load_state(strategy_state)
                console.print("[dim]Estado restaurado desde bot_state.json[/dim]")
            except Exception as e:
                console.print(f"[yellow]No se pudo restaurar estado: {e}[/yellow]")

    def _save_state(self):
        state = {
            "positions": self._positions,
            "strategy_state": self.strategy.save_state(),
            "mode": self.mode,
            "strategy": self.strategy.name,
            "pairs": self.pairs,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

    def _handle_signal_obj(self, signal_obj, pair: str):
        from strategies.base import Signal

        if signal_obj.signal == Signal.BUY and signal_obj.amount_usd > 0:
            order = self.engine.market_buy(pair, signal_obj.amount_usd)
            if order.get("status") == "rejected":
                return

            qty = order.get("qty", signal_obj.amount_usd / signal_obj.price)
            fill_price = order.get("price", signal_obj.price)
            fee = order.get("fee", 0)

            if pair in self._positions:
                pos = self._positions[pair]
                total_qty = pos["qty"] + qty
                pos["avg_cost"] = (pos["avg_cost"] * pos["qty"] + fill_price * qty) / total_qty
                pos["qty"] = total_qty
            else:
                self._positions[pair] = {
                    "qty": qty, "avg_cost": fill_price,
                    "entry_time": time.time(), "bars_held": 0
                }

            self.logger.log_buy(
                pair, fill_price, qty, fee,
                self.strategy.name, signal_obj.reason, self.mode
            )
            console.print(f"[green]BUY[/green] {qty:.6f} {pair.split('/')[0]} @ {fill_price:.2f} | {signal_obj.reason}")

        elif signal_obj.signal.name in ("SELL", "STOP_LOSS", "TIME_EXIT"):
            pos = self._positions.get(pair)
            if not pos:
                return

            order = self.engine.market_sell(pair, pos["qty"])
            if order.get("status") == "rejected":
                return

            qty = order.get("qty", pos["qty"])
            fill_price = order.get("price", signal_obj.price)
            fee = order.get("fee", 0)
            gross = qty * fill_price
            cost = pos["qty"] * pos["avg_cost"]
            pnl = gross - fee - cost
            pnl_pct = pnl / cost * 100

            self.logger.log_sell(
                pair, fill_price, qty, fee, pnl, pnl_pct,
                self.strategy.name, signal_obj.reason, self.mode
            )

            pnl_color = "green" if pnl >= 0 else "red"
            console.print(
                f"[red]SELL[/red] {qty:.6f} {pair.split('/')[0]} @ {fill_price:.2f} | "
                f"PnL: [{pnl_color}]{pnl:+.4f} USDT ({pnl_pct:+.2f}%)[/{pnl_color}] | {signal_obj.reason}"
            )
            del self._positions[pair]

        elif signal_obj.signal.name == "SHORT" and signal_obj.amount_usd > 0:
            if pair in self._positions:
                return   # already have a position on this pair
            if not hasattr(self.engine, "short_open"):
                return
            order = self.engine.short_open(pair, signal_obj.amount_usd)
            if order.get("status") in ("rejected", "unsupported", "error"):
                return

            qty = order.get("qty", signal_obj.amount_usd / max(signal_obj.price, 1e-10))
            fill_price = order.get("price", signal_obj.price)
            fee = order.get("fee", 0)
            self._positions[pair] = {
                "qty": qty, "avg_cost": fill_price, "side": "short",
                "entry_time": time.time(), "bars_held": 0
            }
            self.logger.log_buy(
                pair, fill_price, qty, fee,
                self.strategy.name, signal_obj.reason, self.mode
            )
            console.print(
                f"[magenta]SHORT[/magenta] {qty:.6f} {pair.split('/')[0]} "
                f"@ {fill_price:.4f} | {signal_obj.reason}"
            )

        elif signal_obj.signal.name in ("COVER",) or (
            signal_obj.signal.name in ("SELL", "STOP_LOSS", "TIME_EXIT")
            and self._positions.get(pair, {}).get("side") == "short"
        ):
            pos = self._positions.get(pair)
            if not pos or pos.get("side") != "short":
                return
            if not hasattr(self.engine, "short_cover"):
                return
            order = self.engine.short_cover(pair, pos["qty"])
            if order.get("status") in ("rejected", "unsupported", "error"):
                return

            qty = order.get("qty", pos["qty"])
            fill_price = order.get("price", signal_obj.price)
            fee = order.get("fee", 0)
            cost = pos["qty"] * pos["avg_cost"]
            pnl = (pos["avg_cost"] - fill_price) * qty - fee   # short P&L
            pnl_pct = pnl / cost * 100 if cost else 0

            self.logger.log_sell(
                pair, fill_price, qty, fee, pnl, pnl_pct,
                self.strategy.name, signal_obj.reason, self.mode
            )
            pnl_color = "green" if pnl >= 0 else "red"
            console.print(
                f"[cyan]COVER[/cyan] {qty:.6f} {pair.split('/')[0]} @ {fill_price:.4f} | "
                f"PnL: [{pnl_color}]{pnl:+.4f} USDT ({pnl_pct:+.2f}%)[/{pnl_color}] | {signal_obj.reason}"
            )
            del self._positions[pair]

    def run(self, timeframe: str = "1h"):
        console.print(f"[bold]Bot iniciado[/bold] — modo=[cyan]{self.mode}[/cyan] "
                      f"estrategia=[cyan]{self.strategy.name}[/cyan] "
                      f"pares={self.pairs}")

        tf_seconds = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                      "1h": 3600, "4h": 14400}.get(timeframe, 3600)

        def graceful_exit(sig, frame):
            console.print("\n[yellow]Shutdown signal recibido. Guardando estado...[/yellow]")
            self.running = False
            self._save_state()
            console.print("[green]Estado guardado. Bye![/green]")
            sys.exit(0)

        signal.signal(signal.SIGINT, graceful_exit)
        signal.signal(signal.SIGTERM, graceful_exit)

        while self.running:
            for pair in self.pairs:
                try:
                    candles = self.engine.fetch_ohlcv(pair, timeframe, limit=200)
                    pos = self._positions.get(pair)
                    if pos:
                        pos["bars_held"] = pos.get("bars_held", 0) + 1

                    signal_obj = self.strategy.on_candle(pair, candles, pos)
                    self._handle_signal_obj(signal_obj, pair)

                    # Portfolio snapshot
                    prices = {}
                    for p in self.pairs:
                        try:
                            prices[p] = self.engine.get_price(p)
                        except Exception:
                            pass
                    bal = self.engine.get_balance()
                    usdt = bal.get("USDT", 0)
                    snap = self.portfolio.snapshot(usdt, prices)
                    console.print(
                        f"[dim]{pair} @ {float(candles['close'].iloc[-1]):.2f} | "
                        f"Portfolio: ${snap['total']:.2f} "
                        f"({snap['pnl_pct']:+.2f}%)[/dim]"
                    )

                except Exception as e:
                    logging.error(f"Error procesando {pair}: {e}", exc_info=True)

            self._save_state()
            time.sleep(tf_seconds)


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.group()
@click.option("--config", default="config.yaml", show_default=True,
              help="Path al archivo de configuración")
@click.pass_context
def cli(ctx, config):
    """Crypto Trading Bot — backtesting y trading multi-estrategia."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    cfg = load_config(config)
    ctx.obj["config"] = cfg
    setup_logging(cfg)


@cli.command()
@click.option("--strategy", required=True,
              help="Estrategia a backtestar. Usar 'all' para comparar todas.")
@click.option("--pair", default="BTC/USDT", show_default=True, help="Par de trading")
@click.option("--period", default=None, help="Período: 1m, 3m, 6m, 1y, 2y")
@click.option("--optimize", is_flag=True, help="Optimizar hiperparámetros")
@click.option("--save/--no-save", default=True, help="Guardar resultado en disco")
@click.pass_context
def backtest(ctx, strategy, pair, period, optimize, save):
    """Correr backtest de una estrategia contra datos históricos."""
    config = ctx.obj["config"]
    if period is None:
        period = config.get("backtest", {}).get("default_period", "6m")

    from backtester.runner import BacktestRunner
    runner = BacktestRunner(config)

    if strategy == "all":
        registry = get_strategy_registry()
        results = []
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      BarColumn(), console=console) as progress:
            task = progress.add_task("Backtesting strategies...", total=len(registry))
            for name, cls in registry.items():
                progress.update(task, description=f"[cyan]{name}[/cyan]")
                s = cls()
                s.initialize(config.get("strategies", {}).get(name, {}))
                try:
                    result = runner.run(s, pair, period)
                    results.append(result)
                    if save:
                        runner.save_result(result)
                except Exception as e:
                    console.print(f"[red]Error en {name}: {e}[/red]")
                progress.advance(task)
        print_compare_table(results)

    elif optimize:
        from backtester.optimizer import Optimizer
        registry = get_strategy_registry()
        if strategy not in registry:
            console.print(f"[red]Estrategia desconocida: {strategy}[/red]")
            return
        opt = Optimizer(config)
        console.print(f"[cyan]Optimizando {strategy} en {pair} ({period})...[/cyan]")
        results = opt.optimize(registry[strategy], pair, period)
        if results:
            console.print(f"\n[bold green]Top 5 configuraciones:[/bold green]")
            table = Table(box=box.SIMPLE)
            table.add_column("Rank")
            table.add_column("Sharpe", justify="right")
            table.add_column("Return", justify="right")
            table.add_column("Params")
            for i, r in enumerate(results[:5], 1):
                m = r["metrics"]
                table.add_row(
                    str(i),
                    f"{m['sharpe_ratio']:.3f}",
                    f"{m['total_return_pct']:+.1f}%",
                    str(r["params"])
                )
            console.print(table)

    else:
        s = load_strategy(strategy, config)
        with console.status(f"[cyan]Backtesting {strategy} en {pair} ({period})...[/cyan]"):
            result = runner.run(s, pair, period)
        print_backtest_result(result)
        if save:
            path = runner.save_result(result)
            console.print(f"[dim]Guardado: {path}[/dim]")


@cli.command()
@click.option("--strategy", default=None, help="Estrategia (default: config.yaml active_strategy)")
@click.option("--pairs", default=None, help="Pares separados por coma: BTC/USDT,ETH/USDT")
@click.pass_context
def paper(ctx, strategy, pairs):
    """Paper trading con precios reales y trades simulados."""
    config = ctx.obj["config"]
    strategy_name = strategy or config.get("active_strategy", "mean_reversion")
    pair_list = pairs.split(",") if pairs else config.get("pairs", ["BTC/USDT"])

    from engine import create_engine
    engine = create_engine(config, mode="paper")
    s = load_strategy(strategy_name, config)
    timeframe = config.get("backtest", {}).get("timeframe", "1h")

    bot = BotRunner(engine, s, pair_list, config, mode="paper")
    bot.run(timeframe=timeframe)


@cli.command()
@click.option("--strategy", default=None, help="Estrategia a usar")
@click.option("--pairs", default=None, help="Pares separados por coma")
@click.pass_context
def live(ctx, strategy, pairs):
    """Live trading real. ¡Usar con precaución!"""
    config = ctx.obj["config"]
    strategy_name = strategy or config.get("active_strategy", "mean_reversion")
    pair_list = pairs.split(",") if pairs else config.get("pairs", ["BTC/USDT"])

    console.print(
        Panel(
            "[bold red]⚠ LIVE TRADING[/bold red]\n"
            f"Estrategia: [cyan]{strategy_name}[/cyan]\n"
            f"Pares: [cyan]{pair_list}[/cyan]\n"
            f"Exchange: [cyan]{config.get('exchange', 'bybit')}[/cyan] "
            f"{'(TESTNET)' if config.get('testnet') else '[bold red](MAINNET)[/bold red]'}\n\n"
            "Presiona [bold]Enter[/bold] para continuar o [bold]Ctrl+C[/bold] para cancelar.",
            border_style="red"
        )
    )
    input()

    from engine import create_engine
    engine = create_engine(config, mode="live")
    s = load_strategy(strategy_name, config)
    timeframe = config.get("backtest", {}).get("timeframe", "1h")

    bot = BotRunner(engine, s, pair_list, config, mode="live")
    bot.run(timeframe=timeframe)


@cli.command()
@click.option("--strategies", required=True,
              help="Estrategias a comparar separadas por coma")
@click.option("--pair", default="BTC/USDT", show_default=True)
@click.option("--period", default=None)
@click.pass_context
def compare(ctx, strategies, pair, period):
    """Comparar múltiples estrategias en el mismo período y par."""
    config = ctx.obj["config"]
    if period is None:
        period = config.get("backtest", {}).get("default_period", "6m")

    strategy_names = [s.strip() for s in strategies.split(",")]
    from backtester.runner import BacktestRunner
    runner = BacktestRunner(config)

    # Pre-descargar datos una sola vez
    console.print(f"[cyan]Descargando datos {pair} {period}...[/cyan]")
    candles = runner.fetcher.fetch(pair,
                                   config.get("backtest", {}).get("timeframe", "1h"),
                                   period)

    results = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console) as progress:
        task = progress.add_task("Comparando...", total=len(strategy_names))
        for name in strategy_names:
            progress.update(task, description=f"[cyan]{name}[/cyan]")
            try:
                s = load_strategy(name, config)
                result = runner.run(s, pair, period, candles_df=candles)
                results.append(result)
            except Exception as e:
                console.print(f"[red]Error en {name}: {e}[/red]")
            progress.advance(task)

    print_compare_table(results)


@cli.command()
@click.pass_context
def status(ctx):
    """Ver estado actual del bot (posiciones, PnL, trades recientes)."""
    from tracker.trade_logger import TradeLogger
    logger = TradeLogger()
    stats = logger.get_stats()

    state_path = Path("data/bot_state.json")
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
        console.print(Panel(
            f"  [bold]Modo:[/bold]       {state.get('mode', 'N/A')}\n"
            f"  [bold]Estrategia:[/bold] {state.get('strategy', 'N/A')}\n"
            f"  [bold]Pares:[/bold]      {state.get('pairs', [])}\n"
            f"  [bold]Guardado:[/bold]   {state.get('saved_at', 'N/A')}\n"
            f"  [bold]Posiciones:[/bold] {list(state.get('positions', {}).keys())}",
            title="[bold]Bot State[/bold]", border_style="blue"
        ))
    else:
        console.print("[yellow]No hay estado guardado (bot nunca corrió)[/yellow]")

    # Trade stats
    if stats["total_trades"] > 0:
        pnl_color = "green" if stats["total_pnl"] >= 0 else "red"
        console.print(Panel(
            f"  [bold]Total trades:[/bold]  {stats['total_trades']}\n"
            f"  [bold]Win rate:[/bold]      {stats['win_rate']:.1f}%\n"
            f"  [bold]Total PnL:[/bold]     [{pnl_color}]{stats['total_pnl']:+.4f} USDT[/{pnl_color}]\n"
            f"  [bold]Avg PnL:[/bold]       {stats['avg_pnl']:+.4f} USDT",
            title="[bold]Trade Statistics[/bold]", border_style="green"
        ))
    else:
        console.print("[dim]Sin trades registrados todavía.[/dim]")


if __name__ == "__main__":
    cli()
