"""
Data manager: the ONLY module that writes to market_cache (per the
architecture). Polls Dhan's REST API on a schedule and refreshes the
cache; everything else (strategy, execution) reads through this module's
getters, never touches market_cache or market_data directly.
"""

from datetime import datetime, timedelta

import config
from data.market_cache import market_cache
from data.market_data import market_data_client
from data.event_bus import event_bus
from utils.logger import get_logger

logger = get_logger(__name__)


class DataManager:
    def __init__(self):
        self.client = market_data_client
        self.underlying_security_id = config.UNDERLYING_SECURITY_ID
        self.underlying_segment = config.UNDERLYING_EXCHANGE_SEGMENT

    # -----------------------------------------------------------------
    # Refresh methods -- call these on a schedule (see main.py's loop)
    # -----------------------------------------------------------------

    def refresh_spot(self):
        try:
            price = self.client.get_ltp(self.underlying_security_id, self.underlying_segment)
            market_cache.set_spot(price)
            event_bus.publish("spot_updated", price)
        except Exception as e:
            logger.error(f"refresh_spot failed: {e}")

    def refresh_daily_ohlc(self):
        try:
            df = self.client.get_daily_ohlc(
                self.underlying_security_id, self.underlying_segment, "INDEX",
            )
            market_cache.set_daily_ohlc(df)
            event_bus.publish("daily_ohlc_updated", df)
        except Exception as e:
            logger.error(f"refresh_daily_ohlc failed: {e}")

    def refresh_hourly_ohlc(self):
        try:
            df = self.client.get_intraday_ohlc(
                self.underlying_security_id, self.underlying_segment, "INDEX", interval="60",
            )
            market_cache.set_hourly_ohlc(df)
            event_bus.publish("hourly_ohlc_updated", df)
        except Exception as e:
            logger.error(f"refresh_hourly_ohlc failed: {e}")

    def refresh_option_chain(self, expiry: str):
        try:
            chain = self.client.get_option_chain(self.underlying_security_id, self.underlying_segment, expiry)
            market_cache.set_option_chain(chain, expiry=expiry)
            event_bus.publish("option_chain_updated", chain)
        except Exception as e:
            logger.error(f"refresh_option_chain failed: {e}")

    def refresh_all(self, expiry: str):
        self.refresh_spot()
        self.refresh_daily_ohlc()
        self.refresh_hourly_ohlc()
        self.refresh_option_chain(expiry)

    # -----------------------------------------------------------------
    # Getters -- everything else in the codebase reads through these
    # -----------------------------------------------------------------

    def get_spot(self):
        return market_cache.get_spot()

    def get_option_chain(self):
        return market_cache.get_option_chain()

    def get_option_chain_expiry(self):
        return market_cache.get_option_chain_expiry()

    def get_daily_ohlc(self):
        return market_cache.get_daily_ohlc()

    def get_hourly_ohlc(self):
        return market_cache.get_hourly_ohlc()

    def update_signal(self, signal):
        market_cache.set_signal(signal)
        event_bus.publish("signal_updated", signal)

    def get_signal(self):
        return market_cache.get_signal()

    # -----------------------------------------------------------------
    # Testing / mock support
    # -----------------------------------------------------------------

    def load_mock_data(self, spot: float, daily_df, hourly_df, option_chain: dict, expiry: str = None):
        """Bypasses the Dhan API entirely -- populates the cache directly
        with synthetic/test data, for local testing without live credentials."""
        market_cache.set_spot(spot)
        market_cache.set_daily_ohlc(daily_df)
        market_cache.set_hourly_ohlc(hourly_df)
        market_cache.set_option_chain(option_chain, expiry=expiry)
        logger.info("Mock data loaded into cache")


data_manager = DataManager()


if __name__ == "__main__":
    print("DataManager module loaded. Use load_mock_data() for local testing without live Dhan credentials.")
