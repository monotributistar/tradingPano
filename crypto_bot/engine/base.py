from abc import ABC, abstractmethod
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class BaseEngine(ABC):
    @abstractmethod
    def get_price(self, pair: str) -> float: ...

    @abstractmethod
    def get_balance(self) -> dict: ...

    @abstractmethod
    def market_buy(self, pair: str, usdt_amount: float) -> dict: ...

    @abstractmethod
    def market_sell(self, pair: str, qty: float) -> dict: ...

    @abstractmethod
    def fetch_ohlcv(self, pair: str, timeframe: str,
                    limit: int = 100) -> pd.DataFrame: ...

    # ── Optional CFD / futures methods ─────────────────────────────────────────
    # Default implementations return "unsupported" so spot-only engines
    # (PaperEngine for crypto) don't need to override them.  CFD engines
    # (OandaEngine) override all four with real implementations.

    def short_open(self, pair: str, usdt_amount: float) -> dict:
        """Open a short position.  Default: no-op for spot-only engines."""
        logger.warning(
            f"[{type(self).__name__}] short_open not supported — "
            "enable futures / CFD mode or use a CFD engine."
        )
        return {"status": "unsupported"}

    def short_cover(self, pair: str, qty: float) -> dict:
        """Close a short position.  Default: no-op for spot-only engines."""
        logger.warning(
            f"[{type(self).__name__}] short_cover not supported."
        )
        return {"status": "unsupported"}

    def get_margin_info(self) -> dict:
        """Return margin level, used margin, available margin.  CFD-only."""
        return {}

    def get_financing_cost(self) -> float:
        """Return total accrued overnight financing cost (USDT).  CFD-only."""
        return 0.0
