# Black-Scholes-Trading-Algo
Rule-based Nifty options trading bot combining Black-Scholes fair-value screening with multi-timeframe demand/supply zone detection, built on the Dhan API.
# Nifty Options Trading Bot

A rule-based, short-term options trading system for Nifty 50, built on the Dhan API. Combines a Black-Scholes fair-value screener with a multi-timeframe demand/supply zone detector to identify and (optionally) execute short-duration option-buying opportunities.

Built as a college project exploring algorithmic trading, options pricing theory, and live market data integration.

## How it works

1. **Zone detection** — a custom order-block engine (ported from a Pine Script indicator, see Attribution below) scans monthly → weekly → daily → hourly candles to determine whether Nifty is currently sitting in a demand or supply zone.
2. **Black-Scholes screening** — every strike within an ATM ± N window is priced using Black-Scholes with a reference volatility derived from the live chain's own near-ATM implied volatilities. Options trading below their computed fair value are flagged as discounted.
3. **Signal generation** — a trade is only proposed when the zone direction and a discounted, liquid option agree. If nothing is genuinely discounted, the system falls back to the option closest to fair value rather than sitting idle.
4. **Risk management** — every signal passes through position sizing, per-trade risk caps, a daily loss circuit breaker, and a max-open-positions limit before it's ever eligible for execution.
5. **Execution** — dry-run by default. Real order placement requires an explicit `LIVE_TRADING=true` environment variable; every order intent (dry-run or live) is written to an audit log.

## Architecture

```
main.py              # entrypoint - live polling loop or mock demo
config.py             # environment-driven configuration

data/                 # market data layer (Dhan REST wrapper, caching, single-writer pattern)
models/               # Black-Scholes pricing, implied volatility, option screening
strategy/              # order block detection, multi-timeframe cascade, signal generation
execution/             # order placement, position tracking, risk management
backtesting/           # historical zone/chain replay tools
utils/                 # logging, shared constants
```

## Tech stack

Python 3, [dhanhq](https://pypi.org/project/dhanhq/) (official Dhan API SDK), pandas, NumPy, SciPy.

## Setup

```bash
pip install -r requirements.txt
```

Set the following as environment variables (or a local `.env` file):

```
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
LIVE_TRADING=false        # keep false until you've tested thoroughly
```

Run:
```bash
python main.py
```

Without valid Dhan credentials, `main.py` automatically runs a self-contained mock demo using synthetic data, so the full pipeline can be verified with no live connection at all.

## Status

This project has been iteratively debugged against **live Dhan market data**, including real fixes for API response-shape mismatches, authentication handling, and timezone/expiry edge cases. It has **not** been through a rigorous historical backtest — the included backtesting tools support that next step but haven't yet been used to validate the strategy's actual edge over time. Treat this as a working research/learning platform, not a validated trading system.

## Disclaimer

This is a personal/educational project. It is not financial advice, and options trading carries substantial risk of loss. `LIVE_TRADING` defaults to `false` for a reason — anyone running this with real capital does so entirely at their own risk and should understand the code fully before enabling live execution.

## Attribution

The order block / demand-supply zone detection logic in `strategy/order_block_engine.py` is ported from the ["Sonarlab - Order Blocks"](https://www.tradingview.com/) Pine Script indicator by ClayeWeight, licensed under [MPL 2.0](https://mozilla.org/MPL/2.0/).
