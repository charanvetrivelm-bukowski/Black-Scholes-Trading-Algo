"""
Strategy orchestrator: pulls fresh data, screens the option chain,
generates a signal from the zone cascade + screening, validates it
against risk limits, and returns a signal ready for execution (or None
if any stage didn't produce a valid trade).
"""

from datetime import datetime

from data.data_manager import data_manager
from models.option_screener import OptionScreener
from strategy.signal_generator import SignalGenerator
from execution.risk_manager import risk_manager
from utils.logger import get_logger

logger = get_logger(__name__)


class Strategy:
    def __init__(self):
        self.screener = OptionScreener()
        self.signal_generator = SignalGenerator()
        self.current_signal = None

    def run(self):
        option_chain = data_manager.get_option_chain()
        if option_chain is None:
            logger.info("Strategy.run(): no option chain data yet")
            return None

        spot = data_manager.get_spot()
        if spot is None:
            logger.info("Strategy.run(): no spot price yet")
            return None

        time_to_expiry = self.calculate_time_to_expiry(data_manager.get_option_chain_expiry())
        if time_to_expiry <= 0:
            logger.info("Strategy.run(): option has expired or no expiry tracked, skipping")
            return None

        screened = self.screener.screen(option_chain, spot, time_to_expiry)
        if not screened:
            return None

        candidates = self.screener.passed_only(screened)

        if candidates:
            best_option = self.screener.best_trade(candidates)
            logger.info(
                f"Strategy.run(): {len(candidates)} discounted candidate(s) found (of {len(screened)} screened "
                f"in the ATM window). Selecting highest fair-value discount: strike={best_option.strike} "
                f"{best_option.option_type} | LTP={best_option.market_price} | fair_value={best_option.fair_value} | "
                f"discount={abs(best_option.deviation_percent):.1f}% below fair value | "
                f"delta={best_option.greeks.delta:.2f} | security_id={best_option.security_id}"
            )
        else:
            best_option = self.screener.closest_to_fair(screened)
            if best_option is None:
                logger.info(f"Strategy.run(): {len(screened)} strikes screened in the ATM window, none had a "
                           f"usable price to fall back on -- no candidate this cycle")
                return None
            logger.info(
                f"Strategy.run(): no discounted strikes in the ATM window (of {len(screened)} screened). "
                f"Falling back to closest-to-fair-value: strike={best_option.strike} {best_option.option_type} | "
                f"LTP={best_option.market_price} | fair_value={best_option.fair_value} | "
                f"deviation={best_option.deviation_percent:+.1f}% from fair value | "
                f"delta={best_option.greeks.delta:.2f} | security_id={best_option.security_id}"
            )

        signal = self.signal_generator.generate(best_option)
        if signal is None:
            return None

        if not risk_manager.validate_signal(signal):
            return None

        data_manager.update_signal(signal)
        self.current_signal = signal
        logger.info(f"Signal generated: {signal}")
        return signal

    @staticmethod
    def calculate_time_to_expiry(expiry: str) -> float:
        """Takes the expiry string we ourselves requested the chain for
        (tracked in market_cache alongside the chain) -- confirmed from a
        real response that Dhan's option_chain endpoint does NOT echo the
        expiry back in its response body (only 'last_price' and 'oc'),
        so extracting it from the response was never going to work.

        IMPORTANT: uses NSE market close (15:30) as the cutoff for the
        expiry date, NOT midnight -- confirmed as a real bug from a live
        run: options trade normally all day on their own expiry date
        right up until market close, so parsing the expiry as midnight
        made the code treat the entire expiry day (including trading
        hours) as already expired, which is exactly backwards -- expiry
        day is often the most active day for a short-term strategy like
        this one, not a day to skip."""
        if not expiry:
            logger.warning("calculate_time_to_expiry: no expiry was tracked for the current option chain")
            return 0.0
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").replace(hour=15, minute=30)
        remaining_seconds = max((expiry_date - datetime.now()).total_seconds(), 0)
        return remaining_seconds / (365 * 24 * 60 * 60)

    def latest_signal(self):
        return self.current_signal

    def clear_signal(self):
        self.current_signal = None
        data_manager.update_signal(None)


if __name__ == "__main__":
    print("Strategy module loaded. See main.py for the full mock end-to-end run.")