"""
Position manager: tracks currently open positions (should be at most
config.MAX_OPEN_POSITIONS at a time) and checks whether the current
price has hit a position's stop-loss or target, since this strategy
holds short-term and needs active exit monitoring, not just entries.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Position:
    security_id: str
    option_type: str
    strike: float
    entry_price: float
    quantity: int
    stop_loss: float
    target: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None
    closed: bool = False


class PositionManager:
    def __init__(self):
        self.open_positions: list = []
        self.closed_positions: list = []

    def open_position(self, signal, quantity: int) -> Position:
        position = Position(
            security_id=str(signal.security_id), option_type=signal.option_type,
            strike=signal.strike, entry_price=signal.entry_price, quantity=quantity,
            stop_loss=signal.stop_loss, target=signal.target, entry_time=datetime.now(),
        )
        self.open_positions.append(position)
        logger.info(f"Opened position: {position}")
        return position

    def check_exits(self, current_price_by_security: dict) -> list:
        """Call this on every price update. current_price_by_security:
        {security_id: current_premium}. Returns list of positions closed
        this call."""
        closed_now = []
        for position in list(self.open_positions):
            current_price = current_price_by_security.get(position.security_id)
            if current_price is None:
                continue

            if current_price <= position.stop_loss:
                self._close(position, current_price, "stop_loss")
                closed_now.append(position)
            elif current_price >= position.target:
                self._close(position, current_price, "target")
                closed_now.append(position)

        return closed_now

    def force_close_all(self, current_price_by_security: dict, reason: str = "manual_close"):
        """For end-of-day flatten, or an emergency stop."""
        for position in list(self.open_positions):
            price = current_price_by_security.get(position.security_id, position.entry_price)
            self._close(position, price, reason)

    def _close(self, position: Position, exit_price: float, reason: str):
        position.exit_price = exit_price
        position.exit_time = datetime.now()
        position.exit_reason = reason
        position.closed = True
        self.open_positions.remove(position)
        self.closed_positions.append(position)
        pnl = (exit_price - position.entry_price) * position.quantity
        logger.info(f"Closed position ({reason}): entry={position.entry_price}, exit={exit_price}, pnl={pnl:.2f}")

    def has_open_position(self) -> bool:
        return len(self.open_positions) > 0

    def open_position_count(self) -> int:
        return len(self.open_positions)

    def total_realized_pnl(self) -> float:
        return sum((p.exit_price - p.entry_price) * p.quantity for p in self.closed_positions if p.exit_price is not None)


position_manager = PositionManager()


if __name__ == "__main__":
    from dataclasses import dataclass as _dc

    @_dc
    class _FakeSignal:
        security_id: str
        option_type: str
        strike: float
        entry_price: float
        stop_loss: float
        target: float

    signal = _FakeSignal(security_id="TEST1", option_type="call", strike=24500,
                          entry_price=100.0, stop_loss=70.0, target=160.0)
    position_manager.open_position(signal, quantity=75)
    assert position_manager.has_open_position()

    closed = position_manager.check_exits({"TEST1": 165.0})  # above target
    assert len(closed) == 1 and closed[0].exit_reason == "target"
    assert not position_manager.has_open_position()
    print(f"Realized PnL: {position_manager.total_realized_pnl():.2f}")
    print("\nPosition manager validated correctly.")
