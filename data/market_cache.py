"""
In-memory market data cache. Thread-safe via a single lock -- simple and
correct beats clever here, since this bot isn't high-frequency enough to
need lock-free structures. ONLY data_manager.py should write to this;
everything else reads through data_manager's getters (see architecture:
"data_manager.py # ONLY writer to cache").
"""

import threading


class MarketCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._spot = None
        self._option_chain = None
        self._option_chain_expiry = None
        self._daily_ohlc = None
        self._hourly_ohlc = None
        self._current_signal = None

    # --- spot ---
    def set_spot(self, price: float):
        with self._lock:
            self._spot = price

    def get_spot(self):
        with self._lock:
            return self._spot

    # --- option chain ---
    def set_option_chain(self, chain: dict, expiry: str = None):
        with self._lock:
            self._option_chain = chain
            self._option_chain_expiry = expiry

    def get_option_chain(self):
        with self._lock:
            return self._option_chain

    def get_option_chain_expiry(self):
        with self._lock:
            return self._option_chain_expiry

    # --- OHLC ---
    def set_daily_ohlc(self, df):
        with self._lock:
            self._daily_ohlc = df

    def get_daily_ohlc(self):
        with self._lock:
            return self._daily_ohlc

    def set_hourly_ohlc(self, df):
        with self._lock:
            self._hourly_ohlc = df

    def get_hourly_ohlc(self):
        with self._lock:
            return self._hourly_ohlc

    # --- signal ---
    def set_signal(self, signal):
        with self._lock:
            self._current_signal = signal

    def get_signal(self):
        with self._lock:
            return self._current_signal


market_cache = MarketCache()
