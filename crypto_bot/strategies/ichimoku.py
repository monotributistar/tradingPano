"""
Ichimoku Cloud Strategy
- Complete Japanese trend system widely used by professional traders.
- Components:
    Tenkan-sen (9):  (max_high_9  + min_low_9)  / 2  — conversion line
    Kijun-sen  (26): (max_high_26 + min_low_26) / 2  — base line
    Senkou Span A:   (Tenkan + Kijun) / 2            — cloud boundary (fast)
    Senkou Span B (52): (max_high_52 + min_low_52) / 2 — cloud boundary (slow)
    Chikou span:     current close shifted back 26 bars
- BUY:   TK cross up AND price above cloud AND chikou > close[26 bars ago]
- SHORT: TK cross down AND price below cloud AND chikou < close[26 bars ago]
- Exit LONG:  TK cross down OR price falls into cloud
- Exit SHORT: TK cross up  OR price rises into cloud
- Needs 52+26+5 = 83 warmup bars minimum.

Edge: Ichimoku provides a complete trend-following system in one indicator —
cloud as support/resistance, TK cross as momentum, Chikou as trend confirmation.
"""
from typing import Optional
import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal, TradeSignal


class IchimokuStrategy(BaseStrategy):
    name = "ichimoku"
    description = "Ichimoku Cloud — sistema completo japonés de tendencia"
    ideal_timeframes: list = ["4h","1d","1w"]
    min_period: str = "3m"
    market_type: str = "trending"
    trade_frequency: str = "low"
    min_liquidity: str = "medium"
    suitable_timeframes: list = ['4h', '1d']
    suitable_market_conditions: list = ['trending']
    recommended_leverage: float = 2.0
    max_leverage: float = 8.0
    risk_profile: dict = {
        "stop_loss_pct":     3.0,
        "take_profit_pct":   7.0,
        "position_size_pct": 5.0,
    }


    def initialize(self, config: dict):
        self.tenkan_period = config.get("tenkan_period", 9)
        self.kijun_period = config.get("kijun_period", 26)
        self.senkou_b_period = config.get("senkou_b_period", 52)
        self.amount_per_trade = config.get("amount_per_trade", 10.0)
        self._stop_price: Optional[float] = None

    def reset(self):
        self._stop_price = None

    def _mid(self, high: pd.Series, low: pd.Series, period: int) -> pd.Series:
        """(max_high + min_low) / 2 over rolling period."""
        return (high.rolling(period).max() + low.rolling(period).min()) / 2

    def _compute_ichimoku(self, candles: pd.DataFrame) -> dict:
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]

        tenkan = self._mid(high, low, self.tenkan_period)
        kijun = self._mid(high, low, self.kijun_period)
        span_a = (tenkan + kijun) / 2
        span_b = self._mid(high, low, self.senkou_b_period)
        # Chikou: current close shifted 26 bars back for comparison with close
        chikou_lag = self.kijun_period

        def f(s):
            v = float(s.iloc[-1])
            return v if v == v else 0.0

        return {
            "tenkan": f(tenkan),
            "kijun": f(kijun),
            "span_a": f(span_a),
            "span_b": f(span_b),
            "tenkan_prev": float(tenkan.iloc[-2]) if len(tenkan) > 1 else f(tenkan),
            "kijun_prev": float(kijun.iloc[-2]) if len(kijun) > 1 else f(kijun),
            "close_26ago": float(close.iloc[-chikou_lag - 1]) if len(close) > chikou_lag else float(close.iloc[0]),
            "current_close": float(close.iloc[-1]),
        }

    def on_candle(self, pair: str, candles: pd.DataFrame,
                  position: Optional[dict]) -> TradeSignal:
        # Need senkou_b + kijun + buffer
        needed = self.senkou_b_period + self.kijun_period + 5
        if len(candles) < needed:
            return TradeSignal(Signal.HOLD, pair, float(candles["close"].iloc[-1]), 0, "warmup")

        price = float(candles["close"].iloc[-1])
        ic = self._compute_ichimoku(candles)

        tenkan = ic["tenkan"]
        kijun = ic["kijun"]
        tenkan_prev = ic["tenkan_prev"]
        kijun_prev = ic["kijun_prev"]
        span_a = ic["span_a"]
        span_b = ic["span_b"]
        close_26ago = ic["close_26ago"]
        current_close = ic["current_close"]

        # TK crossovers
        tk_cross_up = tenkan_prev <= kijun_prev and tenkan > kijun      # bullish
        tk_cross_down = tenkan_prev >= kijun_prev and tenkan < kijun    # bearish

        # Cloud boundaries
        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)

        # Price vs cloud
        above_cloud = price > cloud_top
        below_cloud = price < cloud_bottom
        in_cloud = cloud_bottom <= price <= cloud_top

        # Chikou confirmation
        chikou_bullish = current_close > close_26ago
        chikou_bearish = current_close < close_26ago

        current_side = position.get("side") if position else None

        # ── MANAGE LONG ────────────────────────────────────────────────────────
        if current_side == "long":
            # Exit: TK cross down OR price enters/falls into cloud
            if tk_cross_down or in_cloud or below_cloud:
                reason = ("TK cross down" if tk_cross_down
                          else "price in cloud" if in_cloud
                          else "price below cloud")
                self._stop_price = None
                return TradeSignal(
                    Signal.SELL, pair, price, 0,
                    f"long exit: {reason} T={tenkan:.4f} K={kijun:.4f}",
                    metadata={"tenkan": tenkan, "kijun": kijun,
                               "span_a": span_a, "span_b": span_b}
                )
            # Cloud acts as dynamic stop — stop just below cloud bottom
            self._stop_price = cloud_bottom

        # ── MANAGE SHORT ───────────────────────────────────────────────────────
        elif current_side == "short":
            # Cover: TK cross up OR price enters/rises into cloud
            if tk_cross_up or in_cloud or above_cloud:
                reason = ("TK cross up" if tk_cross_up
                          else "price in cloud" if in_cloud
                          else "price above cloud")
                self._stop_price = None
                return TradeSignal(
                    Signal.COVER, pair, price, 0,
                    f"short exit: {reason} T={tenkan:.4f} K={kijun:.4f}",
                    metadata={"tenkan": tenkan, "kijun": kijun,
                               "span_a": span_a, "span_b": span_b}
                )
            # Cloud acts as dynamic stop — stop just above cloud top
            self._stop_price = cloud_top

        # ── NO POSITION: look for entry ────────────────────────────────────────
        else:
            self._stop_price = None

            # LONG: TK cross up + above cloud + chikou bullish
            if tk_cross_up and above_cloud and chikou_bullish:
                self._stop_price = cloud_bottom
                return TradeSignal(
                    Signal.BUY, pair, price, self.amount_per_trade,
                    f"Ichimoku BUY: TK cross T={tenkan:.4f}>K={kijun:.4f} above cloud chikou bull",
                    confidence=min(1.0, (price - cloud_top) / (price * 0.01 + 1e-10)),
                    metadata={"tenkan": tenkan, "kijun": kijun, "span_a": span_a,
                               "span_b": span_b, "cloud_top": cloud_top,
                               "cloud_bottom": cloud_bottom, "stop": self._stop_price}
                )

            # SHORT: TK cross down + below cloud + chikou bearish
            if tk_cross_down and below_cloud and chikou_bearish:
                self._stop_price = cloud_top
                return TradeSignal(
                    Signal.SHORT, pair, price, self.amount_per_trade,
                    f"Ichimoku SHORT: TK cross T={tenkan:.4f}<K={kijun:.4f} below cloud chikou bear",
                    confidence=min(1.0, (cloud_bottom - price) / (price * 0.01 + 1e-10)),
                    metadata={"tenkan": tenkan, "kijun": kijun, "span_a": span_a,
                               "span_b": span_b, "cloud_top": cloud_top,
                               "cloud_bottom": cloud_bottom, "stop": self._stop_price}
                )

        return TradeSignal(Signal.HOLD, pair, price, 0,
                           f"hold T={tenkan:.4f} K={kijun:.4f} above={above_cloud} below={below_cloud}",
                           metadata={"tenkan": tenkan, "kijun": kijun, "span_a": span_a,
                                     "span_b": span_b, "above_cloud": above_cloud,
                                     "below_cloud": below_cloud, "in_cloud": in_cloud})

    def get_params(self) -> dict:
        return {
            "tenkan_period": self.tenkan_period,
            "kijun_period": self.kijun_period,
            "senkou_b_period": self.senkou_b_period,
            "amount_per_trade": self.amount_per_trade,
        }

    def get_param_grid(self) -> dict:
        return {
            "tenkan_period": [7, 9, 13],
            "kijun_period": [20, 26, 30],
            "senkou_b_period": [44, 52, 60],
        }

    def save_state(self) -> dict:
        return {"stop_price": self._stop_price}

    def load_state(self, state: dict):
        self._stop_price = state.get("stop_price")
