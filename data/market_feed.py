"""
Dhan WebSocket live market feed wrapper.

NOT wired into the default data_manager polling loop below -- for a
short-term-hold, few-trades-a-day college project, polling the REST API
every POLL_INTERVAL_SECONDS (config.py) is simpler, easier to debug, and
plenty fast enough. This module is here to match your architecture and
as a documented starting point if you later want tick-level reaction
speed, but treat it as unfinished/unverified -- Dhan's WebSocket message
format needs to be confirmed against a live connection, which this
sandbox can't do.
"""

from utils.logger import get_logger

logger = get_logger(__name__)


class MarketFeed:
    def __init__(self, client_id: str, access_token: str, on_tick_callback=None):
        self.client_id = client_id
        self.access_token = access_token
        self.on_tick_callback = on_tick_callback
        self._ws = None
        self._running = False

    def connect(self, security_ids: list, exchange_segment: str):
        """Subscribes to live ticks for the given security IDs. Uses the
        dhanhq SDK's marketfeed module -- confirm the exact class/method
        names against the installed dhanhq version, these have changed
        across SDK releases."""
        from dhanhq import marketfeed

        instruments = [(exchange_segment, sid, marketfeed.Ticker) for sid in security_ids]
        self._ws = marketfeed.DhanFeed(self.client_id, self.access_token, instruments)
        self._running = True
        logger.info(f"Connecting market feed for {len(security_ids)} instruments")

        try:
            while self._running:
                self._ws.run_forever()
                data = self._ws.get_data()
                if data and self.on_tick_callback:
                    self.on_tick_callback(data)
        except Exception as e:
            logger.error(f"Market feed error: {e}")
            self._running = False

    def disconnect(self):
        self._running = False
        if self._ws is not None:
            try:
                self._ws.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    print("MarketFeed module loaded. Unverified against a live connection -- "
          "see module docstring. Not wired into data_manager's default loop.")
