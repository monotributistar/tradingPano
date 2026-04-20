"""
Strategy base classes and shared signal types.

All trading strategies must subclass ``BaseStrategy`` and implement the three
abstract methods: ``initialize``, ``on_candle``, and ``get_params``.

Metadata contract
-----------------
Each strategy declares class-level metadata used by the frontend strategy
selector and the recommendation engine:

- ``ideal_timeframes``  — candle sizes the strategy is tuned for
- ``min_period``        — minimum backtest window for meaningful results
- ``market_type``       — intended market regime (trending / ranging / both)
- ``trade_frequency``   — expected number of round-trips per week
- ``min_liquidity``     — minimum pair liquidity requirement

Signal flow
-----------
``on_candle()`` returns a ``TradeSignal``.  The ``BacktestRunner`` acts on its
``.signal`` field:

- ``BUY``        → open or add to a long position
- ``SELL``       → close long position
- ``SHORT``      → open a short position (simulated futures)
- ``COVER``      → close short position
- ``STOP_LOSS``  → emergency close (respects position side)
- ``TIME_EXIT``  → time-based close (respects position side)
- ``HOLD``       → do nothing this bar
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class Signal(Enum):
    """Action signals produced by a strategy on each candle."""

    BUY = "buy"             # Open long or add to long (DCA)
    SELL = "sell"           # Close long position
    HOLD = "hold"           # No action this bar
    STOP_LOSS = "stop_loss" # Emergency close (honours position side)
    TIME_EXIT = "time_exit" # Time-based close (honours position side)
    SHORT = "short"         # Open short (simulated futures)
    COVER = "cover"         # Close short position


@dataclass
class TradeSignal:
    """Full signal emitted by a strategy on each candle.

    Attributes:
        signal:     The action to take (Signal enum value).
        pair:       Trading pair, e.g. ``"BTC/USDT"``.
        price:      Reference price used for sizing (usually last close).
        amount_usd: Desired position size in USDT before risk adjustment.
        reason:     Human-readable explanation logged on the trade record.
        confidence: Normalised confidence score [0, 1] (informational only).
        metadata:   Extra data for the risk manager, e.g. ``{"atr": 42.0}``.
    """

    signal: Signal
    pair: str
    price: float
    amount_usd: float
    reason: str
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Subclass this, implement the three abstract methods, and populate the
    class-level metadata so the UI can present useful guidance without
    running a backtest first.

    Class attributes
    ----------------
    name : str
        Unique snake_case identifier used in the strategy registry and DB.
    description : str
        One-line English description shown in the strategy selector.

    Metadata (UI + recommendation engine)
    --------------------------------------
    ideal_timeframes : list[str]
        Candle timeframes this strategy is tuned for, e.g. ``["1h", "4h"]``.
    min_period : str
        Minimum recommended backtest window for statistically meaningful
        results, e.g. ``"3m"``.
    market_type : str
        Market regime: ``"trending"``, ``"ranging"``, or ``"both"``.
    trade_frequency : str
        Expected trades per week: ``"high"`` (>5), ``"medium"`` (1–5),
        or ``"low"`` (<1, swing/position).
    min_liquidity : str
        Minimum pair liquidity: ``"high"`` (BTC/ETH only), ``"medium"``
        (top-50 by volume), or ``"any"``.
    """

    name: str = "base"
    description: str = ""

    # ── Strategy metadata — exposed via GET /api/strategies ───────────────────
    ideal_timeframes: list = []
    """Candle timeframes this strategy performs best on, e.g. ['1h', '4h']."""

    min_period: str = "1m"
    """Minimum recommended backtest window for meaningful results."""

    market_type: str = "both"
    """Market regime: 'trending', 'ranging', or 'both'."""

    trade_frequency: str = "medium"
    """Expected trades per week: 'high' (scalping), 'medium', or 'low' (swing)."""

    min_liquidity: str = "any"
    """Minimum pair liquidity: 'high' (BTC/ETH), 'medium' (top-50), or 'any'."""

    # ── Strategy Engine metadata (multi-timeframe + risk engine) ─────────────

    suitable_timeframes: list = []
    """Explicit list of timeframes the strategy works well on.
    Alias for ideal_timeframes with a more descriptive name."""

    suitable_market_conditions: list = []
    """Market condition tags: 'trending', 'ranging', 'high_vol', 'low_vol',
    'bull', 'bear'. Used by the Strategy Engine filter and market scanner."""

    recommended_leverage: float = 1.0
    """Default leverage pre-filled in the Risk Profile form.
    Should be conservative — what a new user should start with."""

    max_leverage: float = 5.0
    """Strategy-level leverage ceiling.  Never exceeds global MAX_LEVERAGE_CAP
    (15x).  Scalping / momentum strategies can tolerate higher; swing strategies
    should keep this low to survive drawdowns."""

    risk_profile: dict = {
        "stop_loss_pct":     2.0,   # % of entry price
        "take_profit_pct":   4.0,   # % of entry price
        "position_size_pct": 5.0,   # % of current equity per trade
    }
    """Default risk parameters for this strategy, pre-filled in the Risk Profile
    form.  Users can override; the RiskManager hard-caps against global limits."""

    @abstractmethod
    def initialize(self, config: dict) -> None:
        """Load strategy parameters from a config dict.

        Args:
            config: Strategy-specific settings from config.yaml, e.g.
                ``{"rsi_period": 14, "bb_std": 2.0}``.
        """

    @abstractmethod
    def on_candle(
        self,
        pair: str,
        candles: pd.DataFrame,
        position: Optional[dict],
    ) -> TradeSignal:
        """Process the latest candle and return a trading signal.

        Args:
            pair:     Trading pair, e.g. ``"BTC/USDT"``.
            candles:  Full OHLCV DataFrame up to and including the current bar.
                      Columns: open, high, low, close, volume.
            position: Currently open position dict, or ``None`` if flat.
                      Keys: side, qty, avg_cost, entry_bar, bars_held, entries.

        Returns:
            TradeSignal with the desired action and sizing.
        """

    @abstractmethod
    def get_params(self) -> dict:
        """Return current parameter values for logging and the UI.

        Returns:
            Dict mapping parameter name → current value.
        """

    def get_param_grid(self) -> dict:
        """Return parameter search space for grid / Bayesian optimisation.

        Override in each strategy to enable the parameter optimizer (Phase 5).

        Returns:
            Dict mapping param_name → list of candidate values, e.g.
            ``{"rsi_period": [7, 14, 21], "bb_std": [1.5, 2.0, 2.5]}``.
        """
        return {}

    def save_state(self) -> dict:
        """Serialise internal state for live-engine persistence.

        Returns:
            JSON-serialisable dict passable to ``load_state``.
        """
        return {}

    def load_state(self, state: dict) -> None:
        """Restore internal state from a previously saved dict.

        Args:
            state: Dict returned by a previous ``save_state()`` call.
        """

    def reset(self) -> None:
        """Reset all internal state between backtest runs.

        Called by ``BacktestRunner`` before each simulation.  Override if your
        strategy accumulates state across bars (indicators, counters, flags).
        """
