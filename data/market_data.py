"""
Dhan REST API wrapper: historical OHLC (daily + intraday/hourly), option
chain, expiry list, and LTP. Thin wrapper around the `dhanhq` SDK.

Every fix in this file was confirmed against REAL live responses during
testing this session, not guessed from documentation alone:
- The SDK requires credentials wrapped in a DhanContext object, not
  passed directly as (client_id, access_token).
- security_id must be passed as an int, not a string, across every
  endpoint (confirmed via get_ltp, then applied consistently everywhere).
- The SDK wraps responses in an envelope that has been observed to
  nest ONE layer for some endpoints and TWO layers for others,
  inconsistently -- so unwrapping now adaptively searches for the
  expected key rather than assuming a fixed depth.
"""

import pandas as pd
from datetime import datetime, timedelta

import config
from utils.logger import get_logger

logger = get_logger(__name__)


class MarketDataClient:
    def __init__(self, client_id: str = None, access_token: str = None):
        self.client_id = client_id or config.DHAN_CLIENT_ID
        self.access_token = access_token or config.DHAN_ACCESS_TOKEN
        self._client = None

    def _get_client(self):
        if self._client is None:
            from dhanhq import DhanContext, dhanhq
            context = DhanContext(self.client_id, self.access_token)
            self._client = dhanhq(context)
        return self._client

    # -----------------------------------------------------------------
    # Historical OHLC
    # -----------------------------------------------------------------

    def get_daily_ohlc(self, security_id: str, exchange_segment: str, instrument: str,
                        from_date: str = None, to_date: str = None) -> pd.DataFrame:
        client = self._get_client()
        to_date = to_date or datetime.now().strftime("%Y-%m-%d")
        from_date = from_date or (datetime.now() - timedelta(days=1000)).strftime("%Y-%m-%d")

        response = client.historical_daily_data(
            security_id=int(security_id), exchange_segment=exchange_segment,
            instrument_type=instrument, expiry_code=0,
            from_date=from_date, to_date=to_date,
        )
        return self._response_to_df(response)

    def get_intraday_ohlc(self, security_id: str, exchange_segment: str, instrument: str,
                           interval: str = "60", from_date: str = None, to_date: str = None) -> pd.DataFrame:
        client = self._get_client()
        to_date = to_date or datetime.now().strftime("%Y-%m-%d")
        from_date = from_date or (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")

        response = client.intraday_minute_data(
            security_id=int(security_id), exchange_segment=exchange_segment,
            instrument_type=instrument, interval=interval,
            from_date=from_date, to_date=to_date,
        )
        return self._response_to_df(response)

    @staticmethod
    def _response_to_df(response: dict) -> pd.DataFrame:
        # historical endpoints' raw payload is flat arrays directly, with
        # no further nested "data" key beyond the SDK's own one layer --
        # confirmed different from option_chain/expiry_list, which nest deeper
        data = response.get("data", response)
        df = pd.DataFrame({
            "open": data["open"], "high": data["high"],
            "low": data["low"], "close": data["close"],
        })
        if "timestamp" in data:
            df.index = pd.to_datetime(data["timestamp"], unit="s")
        elif "start_Time" in data:
            df.index = pd.to_datetime(data["start_Time"])
        return df

    # -----------------------------------------------------------------
    # Expiry list
    # -----------------------------------------------------------------

    def get_expiry_list(self, underlying_security_id: str, underlying_segment: str) -> list:
        """Returns the real list of available expiry dates for the
        underlying -- use instead of guessing/hardcoding a date."""
        client = self._get_client()
        response = client.expiry_list(
            under_security_id=int(underlying_security_id),
            under_exchange_segment=underlying_segment,
        )
        logger.info(f"get_expiry_list raw response: {response!r}")

        current = response
        if isinstance(current, dict) and "remarks" in current and "data" in current:
            current = current["data"]
        if isinstance(current, dict) and "status" in current and "data" in current:
            current = current["data"]

        if isinstance(current, list):
            if not current:
                logger.error(f"get_expiry_list: Dhan returned a genuinely EMPTY expiry list for "
                             f"security_id={underlying_security_id}, segment={underlying_segment}.")
            return current

        logger.error(f"get_expiry_list: unexpected shape after unwrap: {current!r}. Full raw response above.")
        return []

    # -----------------------------------------------------------------
    # Option chain
    # -----------------------------------------------------------------

    def get_option_chain(self, underlying_security_id: str, underlying_segment: str, expiry: str) -> dict:
        """Returns the raw Dhan option-chain response dict (after
        stripping the SDK's outer envelope(s)), expected shape documented
        in models/volatility.py."""
        client = self._get_client()
        response = client.option_chain(
            under_security_id=int(underlying_security_id),
            under_exchange_segment=underlying_segment,
            expiry=expiry,
        )
        logger.info(f"get_option_chain raw response (first 500 chars): {str(response)[:500]}")

        current = response
        for depth in range(5):
            if isinstance(current, dict) and "oc" in current:
                if depth > 0:
                    logger.info(f"get_option_chain: found 'oc' after unwrapping {depth} layer(s)")
                return current
            if isinstance(current, dict) and "data" in current and isinstance(current["data"], dict):
                current = current["data"]
            else:
                break

        logger.error(f"get_option_chain: could not find 'oc' key at any depth. Full raw response: {response!r}")
        return {}

    # -----------------------------------------------------------------
    # LTP / quotes
    # -----------------------------------------------------------------

    @staticmethod
    def _unwrap_sdk_envelope(response: dict, target_key: str = None, max_depth: int = 5) -> dict:
        current = response
        for _ in range(max_depth):
            if not isinstance(current, dict):
                break
            if target_key is not None and target_key in current:
                break
            if "data" in current and isinstance(current["data"], dict):
                current = current["data"]
            else:
                break
        return current

    def get_ltp(self, security_id: str, exchange_segment: str) -> float:
        client = self._get_client()
        raw = client.quote_data(securities={exchange_segment: [int(security_id)]})
        quote = self._unwrap_sdk_envelope(raw, target_key=exchange_segment)

        try:
            return quote[exchange_segment][str(security_id)]["last_price"]
        except (KeyError, TypeError) as e:
            logger.error(f"get_ltp: could not parse response as expected ({e}). Raw response: {raw}")
            raise


market_data_client = MarketDataClient()


if __name__ == "__main__":
    print("MarketDataClient module loaded. Requires DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN "
          "env vars and network access to Dhan's API -- not runnable from this sandbox.")
    required_methods = ["get_daily_ohlc", "get_intraday_ohlc", "get_expiry_list", "get_option_chain", "get_ltp"]
    missing = [m for m in required_methods if not hasattr(MarketDataClient, m)]
    if missing:
        print(f"ERROR: missing methods: {missing}")
    else:
        print(f"All {len(required_methods)} expected methods present: {required_methods}")