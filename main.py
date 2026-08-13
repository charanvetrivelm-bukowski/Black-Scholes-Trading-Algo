"""
Main entrypoint.

If DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN are set (as they will be when
deployed on Dhan Cloud, or loaded from a local .env file), runs the live
polling loop: refresh data -> run strategy -> execute signal -> monitor
exits, repeating every config.POLL_INTERVAL_SECONDS.

If no credentials are set, runs a mock demo instead -- populates the
data layer with synthetic data and runs one full pass through the
pipeline, so you can verify the whole system wires together correctly
before ever touching a real (or even sandbox) Dhan connection.
"""

import time
import sys

from dotenv import load_dotenv
load_dotenv()  # must run BEFORE `import config`, since config.py reads
                 # environment variables at import time

import config
from data.data_manager import data_manager
from strategy.strategy import Strategy
from execution.orders import order_executor
from execution.position_manager import position_manager
from execution.risk_manager import risk_manager
from utils.logger import get_logger

logger = get_logger(__name__)

NIFTY_LOT_SIZE = 75  # VERIFY this against the current NSE-published lot size before trading --
                       # F&O lot sizes are revised periodically and this WILL go stale


def run_live_loop():
    logger.info("Starting live polling loop")
    strategy = Strategy()

    expiry_list = data_manager.client.get_expiry_list(config.UNDERLYING_SECURITY_ID, config.UNDERLYING_EXCHANGE_SEGMENT)
    if not expiry_list:
        logger.error("Could not fetch a real expiry list from Dhan -- check get_expiry_list's logged raw "
                     "response above and fix its parsing before continuing. Stopping rather than guessing a date.")
        return
    expiry = expiry_list[0]  # nearest expiry -- verify this is actually sorted ascending once you see real data
    logger.info(f"Using nearest expiry: {expiry} (from {len(expiry_list)} available: {expiry_list})")

    while True:
        try:
            data_manager.refresh_all(expiry)

            spot = data_manager.get_spot()
            if spot is not None and position_manager.has_open_position():
                open_prices = {p.security_id: spot for p in position_manager.open_positions}  # placeholder: should be each option's own LTP, not spot
                closed = position_manager.check_exits(open_prices)
                for position in closed:
                    pnl = (position.exit_price - position.entry_price) * position.quantity
                    risk_manager.record_realized_pnl(pnl)

            if not position_manager.has_open_position():
                signal = strategy.run()
                if signal is not None:
                    lots = risk_manager.position_size(signal, lot_size=NIFTY_LOT_SIZE)
                    if lots > 0:
                        record = order_executor.place_option_order(signal, lot_size=NIFTY_LOT_SIZE, num_lots=lots)
                        if record.error is None:
                            position_manager.open_position(signal, quantity=NIFTY_LOT_SIZE * lots)

            logger.info(f"Risk status: {risk_manager.current_status()}")

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)

        time.sleep(config.POLL_INTERVAL_SECONDS)


def run_mock_demo():
    """No live credentials needed -- exercises the full pipeline with
    synthetic data so you can confirm everything wires together."""
    import numpy as np
    import pandas as pd
    from datetime import datetime
    from models.black_scholes import bs_price, bs_greeks

    logger.info("No Dhan credentials found -- running mock demo instead of the live loop")

    rng = np.random.default_rng(42)
    days = 300
    dates = pd.bdate_range("2025-06-01", periods=days)
    returns = rng.normal(0.0004, 0.011, days)
    close = 24000 * np.cumprod(1 + returns)
    open_ = np.roll(close, 1); open_[0] = 24000
    high = np.maximum(open_, close) * 1.003
    low = np.minimum(open_, close) * 0.997
    daily_df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=dates)

    hourly_index = pd.date_range("2026-07-01 09:15", periods=15 * 6, freq="1h")
    hourly_returns = rng.normal(0.0003, 0.004, len(hourly_index))
    hourly_close = daily_df["close"].iloc[-1] * np.cumprod(1 + hourly_returns)
    hourly_open = np.roll(hourly_close, 1); hourly_open[0] = daily_df["close"].iloc[-1]
    hourly_df = pd.DataFrame({
        "open": hourly_open, "high": np.maximum(hourly_open, hourly_close) * 1.001,
        "low": np.minimum(hourly_open, hourly_close) * 0.999, "close": hourly_close,
    }, index=hourly_index)

    spot = float(daily_df["close"].iloc[-1])
    r, T = config.RISK_FREE_RATE, 7 / 365
    true_iv = 0.13
    strikes = [round(spot / 100) * 100 + step for step in range(-600, 700, 100)]
    oc = {}
    for K in strikes:
        oc[str(float(K))] = {}
        for opt_key, opt_type in (("ce", "call"), ("pe", "put")):
            price = bs_price(spot, K, r, T, true_iv, opt_type)
            g = bs_greeks(spot, K, r, T, true_iv, opt_type)
            oc[str(float(K))][opt_key] = {
                "last_price": round(price, 2), "oi": 20000, "security_id": f"{opt_key.upper()}{K}",
                "implied_volatility": true_iv * 100,
                "greeks": {"delta": g.delta, "gamma": g.gamma, "theta": g.theta, "vega": g.vega},
            }
    option_chain = {"last_price": spot, "oc": oc}
    mock_expiry = (datetime.now() + pd.Timedelta(days=7)).strftime("%Y-%m-%d")  # matches T=7/365 used above for pricing

    data_manager.load_mock_data(spot, daily_df, hourly_df, option_chain, expiry=mock_expiry)

    strategy = Strategy()
    signal = strategy.run()

    print(f"\nSpot: {spot:.2f}")
    if signal is None:
        print("No trade signal this pass (expected often -- both the zone AND a fairly-priced, "
              "well-behaved-Greeks option have to line up; try re-running with a different seed "
              "to see a populated signal).")
    else:
        print(f"Signal generated: {signal}")
        lots = risk_manager.position_size(signal, lot_size=NIFTY_LOT_SIZE)
        print(f"Position size at current risk settings: {lots} lots")
        if lots > 0:
            record = order_executor.place_option_order(signal, lot_size=NIFTY_LOT_SIZE, num_lots=lots)
            print(f"Order record (dry-run): {record}")

    print(f"\nRisk status: {risk_manager.current_status()}")


if __name__ == "__main__":
    if config.DHAN_CLIENT_ID and config.DHAN_ACCESS_TOKEN:
        run_live_loop()
    else:
        run_mock_demo()