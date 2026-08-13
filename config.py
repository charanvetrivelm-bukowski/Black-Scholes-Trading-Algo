"""
Central configuration. Reads secrets from environment variables --
NEVER hardcode your access token here. Set these in your Dhan Cloud
environment/secrets panel, or a local .env (loaded via python-dotenv)
when running locally.
"""

import os

# --- Dhan credentials ---
DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")

# --- Environment ---
# IMPORTANT: the official dhanhq SDK has NO way to point at Dhan's sandbox
# (https://sandbox.dhan.co/v2) -- its base URL is a hardcoded constant
# inside the SDK itself (confirmed by reading the installed package's
# source directly). This means data_manager.py and orders.py, which go
# through the dhanhq SDK, ALWAYS talk to the real production API,
# regardless of any setting here. There is no live-money risk from this
# for data reads (historical/quotes are read-only), but order placement
# through this SDK is real the moment LIVE_TRADING=True, even if you
# intended to test against sandbox. Genuine sandbox testing of ORDER
# PLACEMENT specifically requires raw HTTP requests against
# https://sandbox.dhan.co/v2 instead of this SDK -- not implemented here.
DHAN_ENV = os.environ.get("DHAN_ENV", "live")  # kept for future use; does not currently affect the SDK's base URL

# --- Safety switch ---
# This must be explicitly set to "true" (string) to allow real order placement.
# Given the sandbox limitation above, this is your ONLY real safety net
# against accidental live orders -- treat it accordingly.
LIVE_TRADING = os.environ.get("LIVE_TRADING", "false").lower() == "true"

# --- Underlying instrument ---
UNDERLYING_SYMBOL = os.environ.get("UNDERLYING_SYMBOL", "NIFTY")
UNDERLYING_SECURITY_ID = os.environ.get("UNDERLYING_SECURITY_ID", "13")  # Nifty 50 index, verify against Dhan's instrument master
UNDERLYING_EXCHANGE_SEGMENT = "IDX_I"

# --- Risk-free rate for Black-Scholes (approx. India short-term G-sec / repo proxy) ---
RISK_FREE_RATE = float(os.environ.get("RISK_FREE_RATE", "0.065"))

# --- Screener thresholds ---
FAIR_PRICE_TOLERANCE_PCT = float(os.environ.get("FAIR_PRICE_TOLERANCE_PCT", "8.0"))
ATM_STRIKE_WINDOW = int(os.environ.get("ATM_STRIKE_WINDOW", "4"))  # only consider ATM-N..ATM+N strikes --
                                                                     # keeps the universe to liquid, tradeable
                                                                     # strikes and avoids far-OTM noise
MIN_DELTA = float(os.environ.get("MIN_DELTA", "0.30"))
MAX_DELTA = float(os.environ.get("MAX_DELTA", "0.65"))
MAX_THETA_PCT_OF_PREMIUM = float(os.environ.get("MAX_THETA_PCT_OF_PREMIUM", "8.0"))
MIN_OPEN_INTEREST = float(os.environ.get("MIN_OPEN_INTEREST", "1000"))
MAX_BID_ASK_SPREAD_PCT = float(os.environ.get("MAX_BID_ASK_SPREAD_PCT", "6.0"))

# --- Risk management ---
INITIAL_CAPITAL = float(os.environ.get("INITIAL_CAPITAL", "100000"))
MAX_RISK_PER_TRADE_PCT = float(os.environ.get("MAX_RISK_PER_TRADE_PCT", "2.0"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "5.0"))
MAX_OPEN_POSITIONS = int(os.environ.get("MAX_OPEN_POSITIONS", "1"))

# --- Strategy loop ---
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))