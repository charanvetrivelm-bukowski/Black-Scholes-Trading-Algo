"""
Security master: resolves a human-readable symbol (e.g. "NIFTY", or an
option's tradingsymbol) to the securityId Dhan's API actually requires.

Dhan publishes a downloadable CSV instrument master (URL/format can
change -- check developer.dhanhq.co for the current link). This module
caches it locally after first download so you're not re-fetching a large
CSV on every startup.
"""

import os
import csv
from utils.logger import get_logger

logger = get_logger(__name__)

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instrument_master_cache.csv")

# Verify this URL against current Dhan documentation before relying on it --
# instrument master download links have changed before and aren't guaranteed
# stable long-term.
INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


class SecurityMaster:
    def __init__(self):
        self._by_symbol = {}
        self._loaded = False

    def load(self, force_refresh: bool = False):
        if self._loaded and not force_refresh:
            return

        if force_refresh or not os.path.exists(CACHE_PATH):
            self._download()

        with open(CACHE_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Column names per Dhan's documented instrument master --
                # verify these exact header names against the real downloaded
                # file, they're a common source of KeyErrors if Dhan renames columns
                symbol = row.get("SEM_TRADING_SYMBOL") or row.get("SYMBOL_NAME")
                security_id = row.get("SEM_SMST_SECURITY_ID") or row.get("SECURITY_ID")
                if symbol and security_id:
                    self._by_symbol[symbol.strip().upper()] = row

        self._loaded = True
        logger.info(f"Security master loaded: {len(self._by_symbol)} instruments")

    def _download(self):
        import urllib.request
        logger.info(f"Downloading instrument master from {INSTRUMENT_MASTER_URL}")
        try:
            urllib.request.urlretrieve(INSTRUMENT_MASTER_URL, CACHE_PATH)
        except Exception as e:
            raise RuntimeError(
                f"Could not download Dhan instrument master ({e}). "
                "Check the URL is current, or manually download it from the "
                f"Dhan developer portal and place it at {CACHE_PATH}"
            )

    def get_security_id(self, symbol: str) -> str:
        self.load()
        row = self._by_symbol.get(symbol.strip().upper())
        if row is None:
            raise KeyError(f"Symbol '{symbol}' not found in instrument master -- "
                            "check spelling, or that the master file downloaded correctly")
        return row.get("SEM_SMST_SECURITY_ID") or row.get("SECURITY_ID")

    def get_row(self, symbol: str) -> dict:
        self.load()
        return self._by_symbol.get(symbol.strip().upper())


security_master = SecurityMaster()


if __name__ == "__main__":
    print("SecurityMaster module loaded. Call security_master.load() and "
          ".get_security_id('SYMBOL') once you have network access to Dhan's "
          "instrument master URL -- not runnable from this sandbox (network restricted).")
