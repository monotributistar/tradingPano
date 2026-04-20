"""
MACD + RSI Confluence Strategy
- Combina dos señales independientes para entradas de alta calidad
- BUY: MACD cruza señal hacia arriba + RSI sale de zona oversold (< 40)
- SELL: MACD cruza señal hacia abajo + RSI sale de overbought (> 60)
- Stop loss con ATR, take profit dinámico

Edge: La confluencia de MACD y RSI filtra señales falsas. Una sola señal
no es suficiente — ambos indicadores deben confirmar. Genera menos trades
pero de mayor calidad, reduciendo fees y whipsaws.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    rsi[avg_loss == 0] = 100
    return rsi


class MACDRSIStrategy(BaseStrategy):
    name = "macd_rsi"
    description = "Confluencia MACD + RSI — señales de alta calidad con menos ruido"
    ideal_timeframes: list = ["1h","4h"]
    min_period: str = "1m"
    market_type: str = "trending"
    trade_frequency: str = "medium"
    min_liquidity: str = "any"
    suitable_timeframes: list = ['1h', '4h']
    suitable_market_conditions: list = ['trending', 'both']
    recommended_leverage: float = 2.5
    max_leverage: float = 10.0
    risk_profile: dict = {
        "stop_loss_pct":     2.0,
        "take_profit_pct":   5.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_buy_level = config.get("rsi_buy_level", 40)    # RSI debe estar por debajo
        self.rsi_sell_level = config.get("rsi_sell_level", 60)  # RSI debe estar por encima
        self.atr_period = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 2.0)
        self.tp_atr_mult = config.get("tp_atr_mult", 3.0)       # risk/reward 1:1.5
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self.trend_filter = config.get("trend_filter", True)
        self.trend_ema = config.get("trend_ema", 100)
        self._stop_price: Optional[float] = None
        self._tp_price: Optional[float] = None

    def reset(self):
        self._stop_price = None
        self._tp_price = None

    def _atr(self, candles: pd.DataFrame, period: int) -> float:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    def _macd(self, close: pd.Series):
        ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        needed = self.macd_slow + self.macd_signal + self.rsi_period + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        close = candles["close"]
        price = float(close.iloc[-1])

        macd_line, signal_line, histogram = self._macd(close)
        rsi = _rsi(close, self.rsi_period)
        atr = self._atr(candles, self.atr_period)

        macd_now = float(macd_line.iloc[-1])
        macd_prev = float(macd_line.iloc[-2])
        sig_now = float(signal_line.iloc[-1])
        sig_prev = float(signal_line.iloc[-2])
        hist_now = float(histogram.iloc[-1])
        rsi_now = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-2])

        # MACD crosses
        macd_crossed_up = macd_prev < sig_prev and macd_now > sig_now
        macd_crossed_down = macd_prev > sig_prev and macd_now < sig_now

        # RSI confirmation
        rsi_was_oversold = rsi_prev < self.rsi_buy_level
        rsi_was_overbought = rsi_prev > self.rsi_sell_level
        rsi_recovering = rsi_now > rsi_prev  # RSI rising
        rsi_falling = rsi_now < rsi_prev     # RSI falling

        # Trend filter
        in_uptrend = True
        if self.trend_filter and len(close) >= self.trend_ema:
            trend_ema_val = float(close.ewm(span=self.trend_ema, adjust=False).mean().iloc[-1])
            in_uptrend = price > trend_ema_val

        # ── EXIT logic ──
        if position is not None:
            avg_cost = position.get("avg_cost", price)

            # Hard stop
            if self._stop_price is not None and price <= self._stop_price:
                stop_hit = self._stop_price
                self._stop_price = None
                self._tp_price = None
                return TradeSignal(
                    Signal.STOP_LOSS, pair, price, 0,
                    f"stop loss at {stop_hit:.2f} (ATR stop)",
                    metadata={"rsi": rsi_now, "macd": macd_now, "atr": atr}
                )

            # Take profit
            if self._tp_price is not None and price >= self._tp_price:
                tp_hit = self._tp_price
                self._stop_price = None
                self._tp_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"take profit at {tp_hit:.2f}",
                    metadata={"rsi": rsi_now, "macd": macd_now}
                )

            # MACD death cross + RSI falling from overbought
            if macd_crossed_down and (rsi_was_overbought or rsi_falling):
                self._stop_price = None
                self._tp_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"MACD death cross + RSI={rsi_now:.1f}",
                    confidence=min(1.0, abs(hist_now) / (atr * 0.01 + 1e-10)),
                    metadata={"rsi": rsi_now, "macd": macd_now, "signal": sig_now}
                )

        # ── ENTRY logic ──
        else:
            self._stop_price = None
            self._tp_price = None

            # MACD golden cross + RSI confirming upward momentum
            buy_signal = (
                macd_crossed_up
                and (rsi_was_oversold or rsi_now < self.rsi_buy_level + 10)
                and rsi_recovering
                and in_uptrend
            )

            if buy_signal:
                stop = price - self.stop_atr_mult * atr
                tp = price + self.tp_atr_mult * atr
                self._stop_price = stop
                self._tp_price = tp
                confluence_score = min(1.0, (
                    abs(macd_now - sig_now) / (atr * 0.01 + 1e-10) * 0.5 +
                    (self.rsi_buy_level - rsi_now) / self.rsi_buy_level * 0.5
                ))
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"MACD cross up + RSI={rsi_now:.1f} recovering",
                    confidence=max(0.3, min(1.0, confluence_score)),
                    metadata={
                        "rsi": rsi_now, "macd": macd_now, "signal": sig_now,
                        "histogram": hist_now, "atr": atr,
                        "stop": stop, "tp": tp,
                    }
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold macd={macd_now:.4f} rsi={rsi_now:.1f}",
                           metadata={"rsi": rsi_now, "macd": macd_now,
                                     "signal": sig_now, "hist": hist_now})

    def get_params(self) -> dict:
        return {
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "rsi_period": self.rsi_period,
            "rsi_buy_level": self.rsi_buy_level,
            "rsi_sell_level": self.rsi_sell_level,
            "atr_period": self.atr_period,
            "stop_atr_mult": self.stop_atr_mult,
            "tp_atr_mult": self.tp_atr_mult,
            "amount_per_trade": self.amount_per_trade,
            "trend_filter": self.trend_filter,
            "trend_ema": self.trend_ema,
        }

    def get_param_grid(self) -> dict:
        return {
            "macd_fast": [8, 12, 15],
            "macd_slow": [21, 26, 34],
            "rsi_buy_level": [35, 40, 45],
            "rsi_sell_level": [55, 60, 65],
            "stop_atr_mult": [1.5, 2.0, 2.5],
            "tp_atr_mult": [2.5, 3.0, 4.0],
            "trend_ema": [50, 100, 200],
        }

    def save_state(self) -> dict:
        return {"stop_price": self._stop_price, "tp_price": self._tp_price}

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
        self._tp_price = state.get("tp_price")
