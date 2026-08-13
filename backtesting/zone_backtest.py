"""
Phase 1 backtest: tests the zone cascade ALONE, walking forward day by
day so the cascade only ever sees data that would have been available
at that point in time (no lookahead bias -- this is the single most
important correctness property of any backtest).

Question this answers: when the cascade says "demand zone," does price
actually tend to go up afterward, more than on a random day? This needs
ONLY Nifty's own OHLC history -- no option chain, no Data API
subscription required -- which is why it's the cheap first step before
building the full options backtest (Phase 2).

Run this file directly: `python zone_backtest.py` (flat layout) or
`python -m backtesting.zone_backtest` (nested layout).
"""

import numpy as np
import pandas as pd

from strategy.cascade import find_cascading_zone
from utils.logger import get_logger

logger = get_logger(__name__)


def walk_forward_zone_backtest(daily_df: pd.DataFrame, warmup_days: int = 120, holding_days: int = 5,
                                sensitivity_kwargs: dict = None) -> dict:
    """
    For each day after `warmup_days`, runs the cascade using ONLY data up
    to and including that day, checks the zone status, and if it's
    demand/supply, records the forward return over the next
    `holding_days` trading days. Compares against the unconditional
    (baseline) forward return distribution to see if the signal carries
    real information.
    """
    sensitivity_kwargs = sensitivity_kwargs or {}
    n = len(daily_df)
    demand_signals = []
    supply_signals = []
    all_forward_returns = []

    for i in range(warmup_days, n - holding_days):
        # CRITICAL: truncate to only data known as of day i -- this is
        # what prevents the backtest from cheating with future candles
        known_data = daily_df.iloc[: i + 1]
        current_price = known_data["close"].iloc[-1]

        future_price = daily_df["close"].iloc[i + holding_days]
        forward_return_pct = (future_price - current_price) / current_price * 100
        all_forward_returns.append(forward_return_pct)

        # only re-run the (expensive) full cascade periodically to keep this
        # runnable in reasonable time -- every 3 trading days is frequent
        # enough to catch zone formation without re-detecting on every bar
        if (i - warmup_days) % 3 != 0:
            continue

        demand_result = find_cascading_zone(known_data, kind="bullish", current_price=current_price, **sensitivity_kwargs)
        supply_result = find_cascading_zone(known_data, kind="bearish", current_price=current_price, **sensitivity_kwargs)

        in_demand = demand_result.final_zone is not None and demand_result.final_zone.bottom <= current_price <= demand_result.final_zone.top * 1.01
        in_supply = supply_result.final_zone is not None and supply_result.final_zone.bottom * 0.99 <= current_price <= supply_result.final_zone.top

        if in_demand and not in_supply:
            demand_signals.append({"date": daily_df.index[i], "price": current_price, "forward_return_pct": forward_return_pct})
        elif in_supply and not in_demand:
            supply_signals.append({"date": daily_df.index[i], "price": current_price, "forward_return_pct": forward_return_pct})

    return summarize_results(demand_signals, supply_signals, all_forward_returns, holding_days)


def summarize_results(demand_signals, supply_signals, all_forward_returns, holding_days) -> dict:
    baseline_mean = float(np.mean(all_forward_returns)) if all_forward_returns else float("nan")
    baseline_std = float(np.std(all_forward_returns)) if all_forward_returns else float("nan")

    def signal_stats(signals, label):
        if not signals:
            return {"label": label, "count": 0}
        returns = [s["forward_return_pct"] for s in signals]
        hit_rate = sum(1 for r in returns if (r > 0 if label == "demand" else r < 0)) / len(returns) * 100
        return {
            "label": label,
            "count": len(signals),
            "mean_forward_return_pct": round(float(np.mean(returns)), 3),
            "hit_rate_pct": round(hit_rate, 1),   # % of signals where price moved in the expected direction
            "vs_baseline_pct": round(float(np.mean(returns)) - baseline_mean, 3),
        }

    return {
        "holding_days": holding_days,
        "total_days_tested": len(all_forward_returns),
        "baseline_mean_forward_return_pct": round(baseline_mean, 3),
        "baseline_std_pct": round(baseline_std, 3),
        "demand": signal_stats(demand_signals, "demand"),
        "supply": signal_stats(supply_signals, "supply"),
    }


def print_report(results: dict):
    print(f"\n{'='*60}\nZONE CASCADE BACKTEST (Phase 1 -- no options data)\n{'='*60}")
    print(f"Days tested: {results['total_days_tested']}, holding period: {results['holding_days']} trading days")
    print(f"Baseline (unconditional) forward return: {results['baseline_mean_forward_return_pct']}% "
          f"(std: {results['baseline_std_pct']}%)")

    for key in ("demand", "supply"):
        s = results[key]
        print(f"\n--- {key.upper()} zone signals ---")
        if s["count"] == 0:
            print("  No signals found in this window -- try more history, lower sensitivity, or a longer warmup.")
            continue
        print(f"  Signal count:          {s['count']}")
        print(f"  Mean forward return:   {s['mean_forward_return_pct']}%")
        print(f"  vs baseline:           {'+' if s['vs_baseline_pct'] >= 0 else ''}{s['vs_baseline_pct']}%")
        direction = "up" if key == "demand" else "down"
        print(f"  Hit rate (moved {direction}):  {s['hit_rate_pct']}%")

    print(f"\n{'='*60}")
    print("How to read this: if 'vs baseline' is meaningfully positive for demand")
    print("(and meaningfully negative for supply), the zone signal is adding real")
    print("information beyond random chance. If it's close to zero or reversed,")
    print("the signal isn't doing what it's supposed to on this data/timeframe --")
    print("that's a real finding, not a failure of the backtest itself.")


if __name__ == "__main__":
    # Synthetic data for demonstration -- replace with real Nifty daily
    # history pulled via market_data.get_daily_ohlc() once running with
    # live Dhan credentials. The output format below is exactly what
    # you'll see with real data, just with different numbers.
    rng = np.random.default_rng(7)
    days = 600
    dates = pd.bdate_range("2024-01-01", periods=days)
    returns = rng.normal(0.0003, 0.011, days)
    # inject periodic pullbacks so zones actually form, same technique
    # used in the earlier synthetic generator for this project
    i = 0
    while i < days:
        i += rng.integers(15, 25)
        if i < days:
            for j in range(rng.integers(2, 4)):
                if i + j < days:
                    returns[i + j] -= rng.uniform(0.015, 0.03)

    close = 24000 * np.cumprod(1 + returns)
    open_ = np.roll(close, 1); open_[0] = 24000
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    daily_df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=dates)

    results = walk_forward_zone_backtest(daily_df, warmup_days=120, holding_days=5)
    print_report(results)
