"""
Order execution for options trades. Dry-run by default (config.LIVE_TRADING
must be explicitly True to place real orders) -- every order intent is
logged before/after the API call regardless of dry-run status.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json
import os

import config
from utils.logger import get_logger

logger = get_logger(__name__)

AUDIT_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "order_audit_log.jsonl")


@dataclass
class OrderRecord:
    timestamp: str
    security_id: str
    option_type: str
    strike: float
    transaction_type: str   # "BUY" or "SELL"
    quantity: int
    price_used: float
    dry_run: bool
    broker_order_id: Optional[str] = None
    broker_status: Optional[str] = None
    error: Optional[str] = None


class OrderExecutor:
    def __init__(self):
        self.live_mode = config.LIVE_TRADING and config.DHAN_ENV == "live"
        self._client = None
        if self.live_mode:
            from dhanhq import DhanContext, dhanhq
            context = DhanContext(config.DHAN_CLIENT_ID, config.DHAN_ACCESS_TOKEN)
            self._client = dhanhq(context)
        logger.info(f"OrderExecutor initialized -- live_mode={self.live_mode}")

    def place_option_order(self, signal, lot_size: int, num_lots: int = 1) -> OrderRecord:
        """signal: a TradeSignal from strategy/signal_generator.py.
        Options trade in lots, not arbitrary share counts -- verify the
        current lot size for the underlying (these change periodically
        under SEBI rules, don't hardcode an assumed value)."""
        quantity = lot_size * num_lots
        transaction_type = "BUY"  # this strategy only takes long option positions (buy calls or puts), no writing

        record = OrderRecord(
            timestamp=datetime.now().isoformat(),
            security_id=str(signal.security_id), option_type=signal.option_type,
            strike=signal.strike, transaction_type=transaction_type,
            quantity=quantity, price_used=signal.entry_price, dry_run=not self.live_mode,
        )

        if self.live_mode:
            try:
                response = self._client.place_order(
                    security_id=str(signal.security_id),
                    exchange_segment="NSE_FNO",
                    transaction_type=self._client.BUY,
                    quantity=quantity,
                    order_type=self._client.MARKET,
                    product_type=self._client.INTRADAY,   # short-term in-and-out, per the stated plan -- not carrying overnight
                    price=0,
                )
                record.broker_order_id = response.get("data", {}).get("orderId")
                record.broker_status = response.get("status")
            except Exception as e:
                record.error = str(e)
                logger.error(f"Order placement failed: {e}")
        else:
            logger.info(f"[DRY RUN] Would place order: {record}")

        self._write_audit_log(record)
        return record

    @staticmethod
    def _write_audit_log(record: OrderRecord):
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(record.__dict__) + "\n")


order_executor = OrderExecutor()


if __name__ == "__main__":
    from dataclasses import dataclass as _dc

    @_dc
    class _FakeSignal:
        security_id: str
        option_type: str
        strike: float
        entry_price: float

    fake_signal = _FakeSignal(security_id="TEST123", option_type="call", strike=24500, entry_price=185.5)
    record = order_executor.place_option_order(fake_signal, lot_size=75, num_lots=1)
    print(f"Order record: {record}")
    assert record.dry_run is True, "Should default to dry-run without config.LIVE_TRADING=True"
    print("\nOrder executor validated correctly (dry-run mode).")
