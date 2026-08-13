"""Shared constants."""

# Signal types
BUY_SIGNAL = "BUY"
SELL_SIGNAL = "SELL"
NO_SIGNAL = "NONE"

# Zone kinds (order block engine)
BULLISH = "bullish"   # demand zone
BEARISH = "bearish"   # supply zone

# Exchange segments (Dhan API values)
NSE_EQ = "NSE_EQ"
NSE_FNO = "NSE_FNO"
IDX_I = "IDX_I"   # index segment, used for NIFTY spot

# Instrument types
EQUITY = "EQUITY"
OPTIDX = "OPTIDX"   # index option
INDEX = "INDEX"

# Product types
CNC = "CNC"    # delivery
INTRADAY = "INTRADAY"

# Order types
MARKET = "MARKET"
LIMIT = "LIMIT"

# Risk defaults (override via config.py / environment, not by editing here)
DEFAULT_MAX_RISK_PER_TRADE_PCT = 2.0     # % of capital risked per trade
DEFAULT_MAX_DAILY_LOSS_PCT = 5.0          # % of capital, hard stop for the day
DEFAULT_MAX_OPEN_POSITIONS = 1            # college-project default: one position at a time, keeps risk reasoning simple
