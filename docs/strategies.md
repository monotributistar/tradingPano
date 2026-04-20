# Strategy Catalog

19 strategies are available. Each is registered in `api/main.py → get_strategy_registry()`
and implemented in `crypto_bot/strategies/`.

Use `GET /api/strategies` to retrieve this data dynamically (includes current params).

---

## Metadata Legend

| Field | Values | Meaning |
|-------|--------|---------|
| **Timeframes** | 15m / 30m / 1h / 2h / 4h / 6h / 12h / 1d / 1w | Candle sizes the strategy is tuned for |
| **Min Period** | e.g. `2w`, `3m` | Minimum backtest window for meaningful results |
| **Market Type** | `trending` / `ranging` / `both` | Best market regime |
| **Frequency** | `high` / `medium` / `low` | Expected trades per week |
| **Liquidity** | `high` / `medium` / `any` | Minimum pair liquidity needed |

---

## Strategy Table

| Name | Description | Timeframes | Min Period | Market | Frequency | Liquidity |
|------|-------------|------------|------------|--------|-----------|-----------|
| `scalping` | RSI(7) + Bollinger Bands + EMA direction filter — fast mean-reversion | 15m, 30m, 1h | 2w | both | **high** | medium |
| `vwap_bounce` | VWAP mean reversion — bounce from VWAP band extremes | 15m, 30m, 1h | 1m | ranging | **high** | **high** |
| `momentum_burst` | Captures price explosions — long/short in both directions | 15m, 30m, 1h | 2w | trending | **high** | medium |
| `rsi_mean_revert` | Buys RSI oversold, sells RSI overbought | 1h, 4h | 1m | ranging | medium | any |
| `mean_reversion` | Buys when price deviates from mean, exits on reversion | 1h, 4h | 1m | ranging | medium | any |
| `bb_squeeze` | Bollinger Band squeeze — trades the volatility explosion | 1h, 4h | 1m | both | medium | any |
| `macd_rsi` | MACD + RSI confluence — high-quality signals, low noise | 1h, 4h | 1m | trending | medium | any |
| `stoch_rsi` | Stochastic RSI with EMA trend filter | 1h, 4h | 1m | both | medium | any |
| `bollinger_dca` | DCA when price touches lower Bollinger Band | 1h, 4h, 1d | 1m | ranging | **low** | any |
| `ema_crossover` | Momentum: buy golden cross, sell death cross | 1h, 4h, 1d | 2m | trending | **low** | any |
| `breakout` | Donchian channel breakout with volume confirmation | 1h, 4h, 1d | 2m | trending | **low** | medium |
| `grid_dynamic` | Grid trading with volatility-adjusted bands | 1h, 4h | 1m | ranging | **high** | any |
| `supertrend` | ATR-based Supertrend indicator — popular in crypto | 4h, 1d | 2m | trending | **low** | any |
| `supertrend_pro` | Multi-timeframe Supertrend + ADX filter — institutional grade | 4h, 1d | 3m | trending | **low** | any |
| `ichimoku` | Full Ichimoku Cloud system — Japanese trend methodology | 4h, 1d, 1w | 3m | trending | **low** | medium |
| `trend_following` | Follows main trend with ADX filter — avoids sideways markets | 4h, 1d | 3m | trending | **low** | any |
| `trend_following_ls` | Long/short trend following with futures | 4h, 1d, 1w | 6m | trending | **low** | **high** |
| `threshold_rebalance` | Rebalances when allocation drifts from target | 1d, 1w | 6m | both | **low** | **high** |
| `funding_rate_arb` | Delta-neutral funding rate arbitrage — passive income | 1d, 1w | 6m | both | **low** | **high** |

---

## Strategy Selection Guide

### Short-term (15m – 1h)
Best for active traders or strategies designed around quick reversions:
- `scalping` — high frequency, works in any market
- `vwap_bounce` — intraday mean reversion, needs liquid pairs
- `momentum_burst` — catches intraday explosions

### Medium-term (1h – 4h)
The most versatile timeframe for crypto. Enough noise filtering, enough trades:
- `stoch_rsi` — good all-rounder, trending or ranging
- `macd_rsi` — trend-following with noise reduction
- `bb_squeeze` — volatility breakout plays
- `rsi_mean_revert` / `mean_reversion` — countertrend, best in ranging markets

### Long-term (4h – 1d+)
Fewer trades, larger moves captured, less screen time:
- `supertrend_pro` — institutional-grade trend filter (ADX + dual Supertrend)
- `ichimoku` — comprehensive trend system, great on 4h+
- `trend_following_ls` — long/short for directional markets
- `threshold_rebalance` / `funding_rate_arb` — low-frequency, income-oriented

---

## Choosing by Market Regime

| If the market is… | Try these strategies |
|-------------------|---------------------|
| **Trending strongly** (ADX > 25) | supertrend_pro, trend_following_ls, ichimoku, macd_rsi |
| **Ranging / sideways** | vwap_bounce, rsi_mean_revert, bb_squeeze, grid_dynamic |
| **Unknown / mixed** | stoch_rsi, scalping, momentum_burst, ema_crossover |
| **Bear market** | trend_following_ls (short bias), funding_rate_arb |

---

## Strategy Files

All strategies live in `crypto_bot/strategies/`:

```
base.py              — Abstract base class + metadata contract
scalping.py
vwap_bounce.py
momentum_burst.py
rsi_mean_revert.py
mean_reversion.py
bb_squeeze.py
bollinger_dca.py
macd_rsi.py
stoch_rsi.py
ema_crossover.py
breakout.py
grid_dynamic.py
supertrend.py
supertrend_pro.py
ichimoku.py
trend_following.py
trend_following_ls.py
threshold_rebalance.py
funding_rate_arb.py
```
