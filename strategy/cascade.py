"""
Multi-timeframe zone cascade: monthly -> weekly -> daily -> hourly,
narrowing from a macro demand/supply zone down to a precise entry
trigger. Validated earlier in this project against synthetic data.

Cascade.evaluate() is the interface strategy/signal_generator.py calls --
it pulls OHLC from data_manager, runs the cascade for both zone kinds,
and returns a CascadeSignal with a direction ("BUY"/"SELL"/None) and a
rough confidence score.
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

from strategy.order_block_engine import OrderBlockEngine, OrderBlock
from data.data_manager import data_manager
from utils.constants import BUY_SIGNAL, SELL_SIGNAL
from utils.logger import get_logger

logger = get_logger(__name__)


def resample_ohlc(daily_df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return daily_df.resample(rule).agg(agg).dropna()


@dataclass
class CascadeResult:
    monthly_zone: Optional[OrderBlock]
    weekly_zone: Optional[OrderBlock]
    daily_zone: Optional[OrderBlock]
    final_zone: Optional[OrderBlock]
    reasoning: list = field(default_factory=list)


@dataclass
class CascadeSignal:
    direction: Optional[str]     # BUY_SIGNAL, SELL_SIGNAL, or None
    confidence: float            # 0-100, rough heuristic based on how many timeframes confirmed
    status: str                  # "demand", "supply", "neutral", "conflicting"
    demand_result: CascadeResult
    supply_result: CascadeResult


def _nearest_active(blocks: list, price: float, kind: str) -> Optional[OrderBlock]:
    if kind == "bullish":
        candidates = [b for b in blocks if b.kind == "bullish" and b.active and b.bottom <= price * 1.15]
    else:
        candidates = [b for b in blocks if b.kind == "bearish" and b.active and b.top >= price * 0.85]
    if not candidates:
        return None
    return min(candidates, key=lambda b: abs(price - (b.top + b.bottom) / 2))


def find_cascading_zone(daily_df, kind="bullish", sens_monthly=20, sens_weekly=24, sens_daily=28, current_price=None) -> CascadeResult:
    reasoning = []
    if current_price is None:
        current_price = daily_df["close"].iloc[-1]

    monthly_df = resample_ohlc(daily_df, "ME")
    weekly_df = resample_ohlc(daily_df, "W")

    monthly_engine = OrderBlockEngine(sensitivity=sens_monthly)
    monthly_blocks = monthly_engine.detect(monthly_df)
    monthly_engine.update_mitigation(monthly_blocks, monthly_df, len(monthly_df) - 1)
    monthly_zone = _nearest_active(monthly_blocks, current_price, kind)

    if monthly_zone is None:
        reasoning.append(f"no active monthly {kind} zone -- proceeding to weekly on full history")
        weekly_search_df = weekly_df
    else:
        reasoning.append(f"monthly zone: {monthly_zone.bottom:.2f}-{monthly_zone.top:.2f}")
        zone_start = monthly_df.index[monthly_zone.origin_index]
        weekly_search_df = weekly_df[weekly_df.index >= zone_start - pd.Timedelta(days=45)]

    weekly_engine = OrderBlockEngine(sensitivity=sens_weekly)
    weekly_blocks = weekly_engine.detect(weekly_search_df) if len(weekly_search_df) > 20 else []
    if weekly_blocks:
        weekly_engine.update_mitigation(weekly_blocks, weekly_search_df, len(weekly_search_df) - 1)

    if monthly_zone is not None:
        weekly_candidates = [b for b in weekly_blocks if b.kind == kind and b.active
                              and b.bottom >= monthly_zone.bottom * 0.98 and b.top <= monthly_zone.top * 1.02]
    else:
        weekly_candidates = [b for b in weekly_blocks if b.kind == kind and b.active]
    weekly_zone = _nearest_active(weekly_candidates, current_price, kind)

    if weekly_zone is None:
        reasoning.append(f"no weekly {kind} zone confirming -- proceeding to daily on full history")
        daily_search_df = daily_df
    else:
        reasoning.append(f"weekly zone: {weekly_zone.bottom:.2f}-{weekly_zone.top:.2f}")
        zone_start = weekly_search_df.index[weekly_zone.origin_index]
        daily_search_df = daily_df[daily_df.index >= zone_start - pd.Timedelta(days=10)]

    daily_engine = OrderBlockEngine(sensitivity=sens_daily)
    daily_blocks = daily_engine.detect(daily_search_df) if len(daily_search_df) > 20 else []
    if daily_blocks:
        daily_engine.update_mitigation(daily_blocks, daily_search_df, len(daily_search_df) - 1)

    if weekly_zone is not None:
        daily_candidates = [b for b in daily_blocks if b.kind == kind and b.active
                             and b.bottom >= weekly_zone.bottom * 0.99 and b.top <= weekly_zone.top * 1.01]
    else:
        daily_candidates = [b for b in daily_blocks if b.kind == kind and b.active]
    daily_zone = _nearest_active(daily_candidates, current_price, kind)

    if daily_zone is not None:
        reasoning.append(f"daily zone: {daily_zone.bottom:.2f}-{daily_zone.top:.2f}")
    else:
        reasoning.append(f"no daily confirmation within the higher-timeframe {kind} zone yet")

    final_zone = daily_zone or weekly_zone or monthly_zone
    return CascadeResult(monthly_zone, weekly_zone, daily_zone, final_zone, reasoning)


def find_cascading_zone_with_hourly(daily_df, hourly_df, kind="bullish", sens_hourly=30, current_price=None, **kwargs) -> CascadeResult:
    result = find_cascading_zone(daily_df, kind=kind, current_price=current_price, **kwargs)
    if current_price is None:
        current_price = daily_df["close"].iloc[-1]

    base_zone = result.final_zone

    if hourly_df is None or len(hourly_df) < 20:
        result.reasoning.append("insufficient hourly data -- skipping hourly refinement entirely")
        return result

    hourly_search_df = hourly_df[hourly_df.index >= hourly_df.index[-1] - pd.Timedelta(days=15)]
    hourly_engine = OrderBlockEngine(sensitivity=sens_hourly)
    hourly_blocks = hourly_engine.detect(hourly_search_df) if len(hourly_search_df) > 20 else []
    if hourly_blocks:
        hourly_engine.update_mitigation(hourly_blocks, hourly_search_df, len(hourly_search_df) - 1)

    hourly_zone = None

    # Preferred: hourly zone that nests inside the higher-timeframe zone
    # (our own "macro coherence" design choice, not part of the original
    # single-timeframe indicator)
    if base_zone is not None:
        constrained_candidates = [b for b in hourly_blocks if b.kind == kind and b.active
                                   and b.bottom >= base_zone.bottom * 0.99 and b.top <= base_zone.top * 1.01]
        hourly_zone = _nearest_active(constrained_candidates, current_price, kind)
        if hourly_zone is not None:
            result.reasoning.append(f"hourly zone (nested in higher-timeframe zone): {hourly_zone.bottom:.2f}-{hourly_zone.top:.2f}")

    # Fallback: plain, UNCONSTRAINED hourly zone -- this is what the
    # TradingView indicator actually shows on an hourly chart viewed
    # alone, with no cross-timeframe filtering. Runs whenever the
    # constrained search found nothing, OR there was no higher-timeframe
    # zone to constrain against in the first place.
    if hourly_zone is None:
        unconstrained_candidates = [b for b in hourly_blocks if b.kind == kind and b.active]
        hourly_zone = _nearest_active(unconstrained_candidates, current_price, kind)
        if hourly_zone is not None:
            result.reasoning.append(f"hourly zone (unconstrained fallback, matches single-timeframe "
                                   f"indicator behavior): {hourly_zone.bottom:.2f}-{hourly_zone.top:.2f}")
        else:
            result.reasoning.append(f"no hourly {kind} zone found even unconstrained")

    if hourly_zone is not None:
        result.final_zone = hourly_zone

    return result


class Cascade:
    def evaluate(self) -> Optional[CascadeSignal]:
        """Pulls daily + hourly OHLC from data_manager and runs the full
        cascade for both demand and supply. Returns None if there isn't
        enough data yet to evaluate (e.g. still warming up)."""
        daily_df = data_manager.get_daily_ohlc()
        hourly_df = data_manager.get_hourly_ohlc()

        if daily_df is None or len(daily_df) < 60:
            logger.info(f"Cascade.evaluate(): insufficient daily history yet "
                       f"(have {0 if daily_df is None else len(daily_df)} bars, need 60+)")
            return None

        current_price = data_manager.get_spot()
        if current_price is None:
            current_price = daily_df["close"].iloc[-1]

        logger.info(f"Cascade.evaluate(): current_price={current_price}, "
                   f"daily_bars={len(daily_df)}, hourly_bars={0 if hourly_df is None else len(hourly_df)}")

        demand = find_cascading_zone_with_hourly(daily_df, hourly_df, kind="bullish", current_price=current_price)
        supply = find_cascading_zone_with_hourly(daily_df, hourly_df, kind="bearish", current_price=current_price)

        def zone_str(z):
            if z is None:
                return "none"
            return f"{z.bottom:.2f}-{z.top:.2f} (active={z.active})"

        logger.info(
            f"Cascade.evaluate() DEMAND detail: monthly={zone_str(demand.monthly_zone)} | "
            f"weekly={zone_str(demand.weekly_zone)} | daily={zone_str(demand.daily_zone)} | "
            f"final={zone_str(demand.final_zone)} | reasoning={demand.reasoning}"
        )
        logger.info(
            f"Cascade.evaluate() SUPPLY detail: monthly={zone_str(supply.monthly_zone)} | "
            f"weekly={zone_str(supply.weekly_zone)} | daily={zone_str(supply.daily_zone)} | "
            f"final={zone_str(supply.final_zone)} | reasoning={supply.reasoning}"
        )

        # ZONE_TOLERANCE was previously 1% (0.01) -- on Nifty at ~24,400,
        # that's roughly 244 points of slop on EACH side of a zone, wide
        # enough that two genuinely separate zones only 60 points apart
        # could both claim the same current price simultaneously,
        # producing a false "conflicting" status. 0.1% (~24 points) is
        # still a reasonable buffer for near-zone entries without being
        # wide enough to overlap adjacent zones.
        ZONE_TOLERANCE = 0.001
        in_demand = demand.final_zone is not None and demand.final_zone.bottom <= current_price <= demand.final_zone.top * (1 + ZONE_TOLERANCE)
        in_supply = supply.final_zone is not None and supply.final_zone.bottom * (1 - ZONE_TOLERANCE) <= current_price <= supply.final_zone.top

        # confidence heuristic: which timeframes confirmed for the winning zone
        def confirmed_count(result):
            return sum(z is not None for z in (result.monthly_zone, result.weekly_zone, result.daily_zone))

        if in_demand and in_supply:
            return CascadeSignal(direction=None, confidence=0, status="conflicting", demand_result=demand, supply_result=supply)
        elif in_demand:
            confidence = 40 + confirmed_count(demand) * 20  # 40 base + up to 60 for 3 confirming timeframes
            return CascadeSignal(direction=BUY_SIGNAL, confidence=min(confidence, 100), status="demand", demand_result=demand, supply_result=supply)
        elif in_supply:
            confidence = 40 + confirmed_count(supply) * 20
            return CascadeSignal(direction=SELL_SIGNAL, confidence=min(confidence, 100), status="supply", demand_result=demand, supply_result=supply)
        else:
            return CascadeSignal(direction=None, confidence=0, status="neutral", demand_result=demand, supply_result=supply)


if __name__ == "__main__":
    print("Cascade module loaded. See tests/ or run main.py with mock data for an end-to-end check.")