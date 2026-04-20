"""
Grid search de parámetros sobre estrategias.
Corre backtests en paralelo usando multiprocessing.
"""
import itertools
import logging
import multiprocessing as mp
from copy import deepcopy
from typing import Type

import pandas as pd

from strategies.base import BaseStrategy
from backtester.runner import BacktestRunner

logger = logging.getLogger(__name__)


def _run_single(args: tuple) -> dict:
    """Worker para multiprocessing."""
    strategy_cls, params, pair, period, bt_config, candles_dict = args
    strategy = strategy_cls()
    strategy.initialize(params)

    runner = BacktestRunner(bt_config)
    # Reconstruir DataFrame desde dict serializado
    candles = pd.DataFrame(candles_dict)
    candles.index = pd.to_datetime(candles.index)
    candles.index = candles.index.tz_localize("UTC") if candles.index.tzinfo is None else candles.index

    result = runner.run(strategy, pair, period=period, candles_df=candles)
    return {
        "params": params,
        "metrics": result["metrics"],
    }


class Optimizer:
    def __init__(self, config: dict):
        self.config = config
        self.bt_config = config

    def optimize(self, strategy_cls: Type[BaseStrategy], pair: str,
                 period: str = "6m", metric: str = "sharpe_ratio",
                 max_workers: Optional[int] = None) -> list[dict]:
        """
        Grid search sobre strategy_cls.get_param_grid().

        Args:
            strategy_cls: clase de la estrategia (no instancia)
            pair: par de trading
            period: período de backtest
            metric: métrica para rankear (default: sharpe_ratio)
            max_workers: procesos paralelos (None = CPU count)

        Returns:
            Lista de resultados ordenada de mejor a peor
        """
        # Instancia temporal para obtener la grilla
        temp = strategy_cls()
        base_config = self.config.get("strategies", {}).get(temp.name, {})
        temp.initialize(base_config)
        param_grid = temp.get_param_grid()

        if not param_grid:
            logger.warning(f"{strategy_cls.name} no tiene param_grid definido")
            return []

        # Generar todas las combinaciones
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(itertools.product(*values))
        total = len(combos)
        logger.info(f"Optimizando {strategy_cls.__name__}: {total} combinaciones")

        # Descargar datos una sola vez
        from backtester.data_fetcher import DataFetcher
        bt_cfg = self.config.get("backtest", {})
        fetcher = DataFetcher(exchange_id=bt_cfg.get("data_source", "binance"))
        candles = fetcher.fetch(pair, bt_cfg.get("timeframe", "1h"), period)
        candles_dict = candles.to_dict()

        # Construir lista de argumentos
        args_list = []
        for combo in combos:
            params = dict(zip(keys, combo))
            # Merge con config base
            full_params = {**base_config, **params}
            args_list.append(
                (strategy_cls, full_params, pair, period, self.config, candles_dict)
            )

        # Correr en paralelo
        workers = max_workers or max(1, mp.cpu_count() - 1)
        logger.info(f"Usando {workers} workers...")

        with mp.Pool(workers) as pool:
            results = pool.map(_run_single, args_list)

        # Filtrar errores y ordenar
        valid = [r for r in results if r is not None]
        valid.sort(key=lambda x: x["metrics"].get(metric, -999), reverse=True)

        logger.info(f"Mejor {metric}: {valid[0]['metrics'][metric]:.3f} — {valid[0]['params']}")
        return valid


# Fix missing Optional import
from typing import Optional
