"""
engine/__init__.py — Engine factory
=====================================

``create_engine(config, mode)`` is the single entry point for engine
instantiation.  Both the CLI (``main.py``) and the API (``bot_manager.py``)
call this function instead of importing engine classes directly.

Routing table
-------------

  mode    exchange           engine class
  ─────────────────────────────────────────────────────────
  paper   bybit / binance    PaperEngine       (ccxt prices)
  paper   oanda              OandaPaperEngine  (OANDA prices)
  live    bybit / binance    LiveEngine        (ccxt orders)
  live    oanda              OandaEngine       (OANDA v20 orders)

Adding a new broker
-------------------
1. Create ``engine/<broker>.py`` extending ``BaseEngine``.
2. Add an ``elif exchange == "<broker>":`` branch below.
3. Write tests in ``tests/unit/test_engine_factory.py``.
"""

import logging

logger = logging.getLogger(__name__)


def create_engine(config: dict, mode: str = "live"):
    """
    Instantiate and return the appropriate trading engine.

    Parameters
    ----------
    config : dict
        Loaded ``config.yaml`` contents (with env-var overrides applied).
    mode   : str
        ``"paper"`` for simulated trading, ``"live"`` for real orders.

    Returns
    -------
    BaseEngine subclass instance.
    """
    exchange = config.get("exchange", "bybit").lower()

    if mode == "paper":
        if exchange == "oanda":
            from engine.oanda_paper import OandaPaperEngine
            logger.info("[factory] OandaPaperEngine selected")
            return OandaPaperEngine(config)

        from engine.paper import PaperEngine
        logger.info("[factory] PaperEngine selected (exchange=%s)", exchange)
        return PaperEngine(config)

    # ── live ──────────────────────────────────────────────────────────────────
    if exchange == "oanda":
        from engine.oanda import OandaEngine
        logger.info("[factory] OandaEngine selected")
        return OandaEngine(config)

    from engine.live import LiveEngine
    logger.info("[factory] LiveEngine selected (exchange=%s)", exchange)
    return LiveEngine(config)
