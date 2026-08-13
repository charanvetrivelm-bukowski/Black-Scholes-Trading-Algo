"""
Signal generator: combines the demand/supply zone cascade with a
screened option (fairly priced + good Greeks) to produce a final,
executable TradeSignal -- only when BOTH agree.
"""

from dataclasses import dataclass
from datetime import datetime

from strategy.cascade import Cascade
from utils.constants import BUY_SIGNAL, SELL_SIGNAL
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TradeSignal:
    direction: str          # BUY_SIGNAL or SELL_SIGNAL
    option_type: str        # "call" or "put"
    security_id: str
    strike: float
    entry_price: float
    stop_loss: float
    target: float
    confidence: float
    timestamp: datetime


class SignalGenerator:
    def __init__(self, stop_loss_pct: float = 0.30, target_pct: float = 0.60):
        """stop_loss_pct/target_pct: as a fraction of entry premium.
        Defaults (30% stop, 60% target -> 1:2 reward:risk) are a
        reasonable starting point for short-dated option buying but are
        NOT backtested -- tune these against real short-term Nifty option
        price behavior before trusting them."""
        self.cascade = Cascade()
        self.stop_loss_pct = stop_loss_pct
        self.target_pct = target_pct

    def generate(self, screened_option) -> TradeSignal:
        if screened_option is None:
            return None

        cascade_signal = self.cascade.evaluate()
        if cascade_signal is None:
            logger.info("SignalGenerator: cascade returned None (likely insufficient daily/hourly "
                       "history to run the monthly->weekly->daily->hourly detection yet) -- no signal")
            return None
        if cascade_signal.direction is None:
            logger.info(f"SignalGenerator: cascade status is '{cascade_signal.status}' (neither demand "
                       f"nor supply confirmed) -- no directional signal to trade, even though a discounted "
                       f"option was found by the screener")
            return None

        direction = cascade_signal.direction
        expected_option_type = "call" if direction == BUY_SIGNAL else "put"

        if screened_option.option_type.lower() != expected_option_type:
            # e.g. Nifty is at a demand zone (bullish) but the best-screened
            # option was a put -- direction mismatch, no trade
            logger.info(f"Cascade says {direction} ({expected_option_type}) but best screened "
                        f"option is {screened_option.option_type} -- no signal")
            return None

        entry_price = screened_option.market_price
        stop_loss = round(entry_price * (1 - self.stop_loss_pct), 2)
        target = round(entry_price * (1 + self.target_pct), 2)

        confidence = max(0, min(100, round(cascade_signal.confidence - abs(screened_option.deviation_percent), 2)))

        return TradeSignal(
            direction=direction, option_type=screened_option.option_type,
            security_id=screened_option.security_id, strike=screened_option.strike,
            entry_price=entry_price, stop_loss=stop_loss, target=target,
            confidence=confidence, timestamp=datetime.now(),
        )


if __name__ == "__main__":
    print("SignalGenerator module loaded. See strategy/strategy.py for the full pipeline test.")