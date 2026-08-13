"""
Risk manager: the last gate before a signal becomes an order. Checks
position limits, per-trade risk sizing, and a daily loss cap -- if any
of these fail, the signal is rejected regardless of how good the
underlying analysis looked.
"""

from datetime import date

import config
from execution.position_manager import position_manager
from utils.logger import get_logger

logger = get_logger(__name__)


class RiskManager:
    def __init__(self):
        self.capital = config.INITIAL_CAPITAL
        self.daily_loss_limit = config.INITIAL_CAPITAL * (config.MAX_DAILY_LOSS_PCT / 100)
        self.max_risk_per_trade = config.INITIAL_CAPITAL * (config.MAX_RISK_PER_TRADE_PCT / 100)
        self._current_day = date.today()
        self._daily_realized_pnl = 0.0

    def _roll_day_if_needed(self):
        today = date.today()
        if today != self._current_day:
            self._current_day = today
            self._daily_realized_pnl = 0.0
            logger.info("New trading day -- daily loss counter reset")

    def record_realized_pnl(self, pnl: float):
        self._roll_day_if_needed()
        self._daily_realized_pnl += pnl

    def validate_signal(self, signal) -> bool:
        self._roll_day_if_needed()

        if position_manager.open_position_count() >= config.MAX_OPEN_POSITIONS:
            logger.info(f"Signal rejected: already at max open positions ({config.MAX_OPEN_POSITIONS})")
            return False

        if self._daily_realized_pnl <= -self.daily_loss_limit:
            logger.warning(f"Signal rejected: daily loss limit hit ({self._daily_realized_pnl:.2f} <= -{self.daily_loss_limit:.2f})")
            return False

        risk_per_unit = signal.entry_price - signal.stop_loss
        if risk_per_unit <= 0:
            logger.warning("Signal rejected: stop_loss is not below entry_price, risk calc invalid")
            return False

        max_quantity = int(self.max_risk_per_trade / risk_per_unit)
        if max_quantity <= 0:
            logger.warning("Signal rejected: max_risk_per_trade too small to buy even 1 unit at this risk-per-unit")
            return False

        return True

    def position_size(self, signal, lot_size: int) -> int:
        """Returns number of LOTS (not raw quantity) to trade, sized to
        respect max_risk_per_trade, rounded down to whole lots."""
        risk_per_unit = signal.entry_price - signal.stop_loss
        if risk_per_unit <= 0:
            return 0
        max_units = int(self.max_risk_per_trade / risk_per_unit)
        max_lots = max_units // lot_size
        return max(max_lots, 0)

    def current_status(self) -> dict:
        self._roll_day_if_needed()
        return {
            "capital": self.capital,
            "daily_realized_pnl": round(self._daily_realized_pnl, 2),
            "daily_loss_limit": round(self.daily_loss_limit, 2),
            "daily_loss_limit_hit": self._daily_realized_pnl <= -self.daily_loss_limit,
            "open_positions": position_manager.open_position_count(),
            "max_open_positions": config.MAX_OPEN_POSITIONS,
        }


risk_manager = RiskManager()


if __name__ == "__main__":
    from dataclasses import dataclass as _dc

    @_dc
    class _FakeSignal:
        entry_price: float
        stop_loss: float

    signal = _FakeSignal(entry_price=100.0, stop_loss=70.0)
    assert risk_manager.validate_signal(signal) is True
    lots = risk_manager.position_size(signal, lot_size=75)
    print(f"Position size at current risk settings: {lots} lots")
    print(f"Risk status: {risk_manager.current_status()}")

    risk_manager.record_realized_pnl(-risk_manager.daily_loss_limit - 1)
    assert risk_manager.validate_signal(signal) is False, "Should reject after daily loss limit breached"
    print("\nRisk manager validated correctly (rejects after daily loss limit hit).")
