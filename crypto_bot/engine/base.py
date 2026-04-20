from abc import ABC, abstractmethod
import pandas as pd


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
