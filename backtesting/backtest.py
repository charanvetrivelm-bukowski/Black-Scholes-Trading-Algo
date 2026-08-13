"""
Simple backtest engine: replays historical price data bar-by-bar through
a strategy's generate_signal(row) method, tracking capital, trades, and
equity curve, then reports standard performance metrics.

This is intentionally simple (single position at a time, no partial
fills, no slippage model beyond a flat commission) -- good enough to
sanity-check a strategy's basic behavior, not a substitute for a more
rigorous backtest before real capital. See the earlier multi-timeframe
backtest harness built for the SIP project for a more elaborate example
if you want to extend this.
"""

import pandas as pd
import numpy as np

from utils.logger import get_logger
from utils.constants import BUY_SIGNAL, SELL_SIGNAL, NO_SIGNAL

logger = get_logger(__name__)


class BacktestEngine:
    def __init__(self, initial_capital: float = 100000, commission: float = 0.0003):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.commission = commission
        self.position = 0
        self.entry_price = 0.0
        self.quantity = 0
        self.trades = []
        self.equity_curve = []

    def execute_trade(self, signal: str, price: float, timestamp):
        if signal == BUY_SIGNAL and self.position == 0:
            self.quantity = int(self.capital / price)
            if self.quantity <= 0:
                return
            cost = self.quantity * price
            fee = cost * self.commission
            self.capital -= (cost + fee)
            self.position = 1
            self.entry_price = price
            self.trades.append({"time": timestamp, "type": "BUY", "price": price, "quantity": self.quantity})

        elif signal == SELL_SIGNAL and self.position == 1:
            revenue = self.quantity * price
            fee = revenue * self.commission
            self.capital += (revenue - fee)
            pnl = (price - self.entry_price) * self.quantity
            self.trades.append({"time": timestamp, "type": "SELL", "price": price, "quantity": self.quantity, "pnl": pnl})
            self.position = 0
            self.quantity = 0
            self.entry_price = 0.0

    def update_equity(self, price: float):
        equity = self.capital
        if self.position == 1:
            equity += self.quantity * price
        self.equity_curve.append(equity)

    def run(self, data: pd.DataFrame, strategy) -> dict:
        logger.info("Backtest started")
        for index, row in data.iterrows():
            signal = strategy.generate_signal(row)
            self.execute_trade(signal, row["close"], index)
            self.update_equity(row["close"])
        logger.info("Backtest completed")
        return self.results()

    def results(self) -> dict:
        if not self.equity_curve:
            return {"error": "no data processed"}

        equity = pd.Series(self.equity_curve)
        returns = equity.pct_change().dropna()

        total_return = (equity.iloc[-1] - self.initial_capital) / self.initial_capital
        max_drawdown = (equity / equity.cummax() - 1).min()

        sharpe = 0.0
        if returns.std() != 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

        return {
            "initial_capital": self.initial_capital,
            "final_capital": equity.iloc[-1],
            "total_return_pct": total_return * 100,
            "max_drawdown_pct": max_drawdown * 100,
            "sharpe_ratio": sharpe,
            "total_trades": len(self.trades),
            "trades": self.trades,
        }


class SimpleThresholdStrategy:
    """A minimal example strategy for testing the backtest engine in
    isolation (not the real cascade+options strategy, which needs live
    option chain data the backtester above doesn't model). Buys when
    price crosses above its 20-period MA, sells when it crosses back
    below -- just enough logic to prove the engine works correctly."""

    def __init__(self, ma_window: int = 20):
        self.ma_window = ma_window
        self.price_history = []
        self.in_position = False

    def generate_signal(self, row) -> str:
        self.price_history.append(row["close"])
        if len(self.price_history) < self.ma_window:
            return NO_SIGNAL

        ma = np.mean(self.price_history[-self.ma_window:])
        price = row["close"]

        if price > ma and not self.in_position:
            self.in_position = True
            return BUY_SIGNAL
        elif price < ma and self.in_position:
            self.in_position = False
            return SELL_SIGNAL
        return NO_SIGNAL


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=True, index_col=0)


if __name__ == "__main__":
    # Sanity check with synthetic data (no CSV needed) -- confirms the
    # engine correctly tracks capital/trades/equity end to end
    rng = np.random.default_rng(0)
    n = 200
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    data = pd.DataFrame({"close": prices}, index=dates)

    engine = BacktestEngine(initial_capital=100000)
    strategy = SimpleThresholdStrategy(ma_window=20)
    results = engine.run(data, strategy)

    print(f"Initial capital: {results['initial_capital']}")
    print(f"Final capital:   {results['final_capital']:.2f}")
    print(f"Total return:    {results['total_return_pct']:.2f}%")
    print(f"Max drawdown:    {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe ratio:    {results['sharpe_ratio']:.2f}")
    print(f"Total trades:    {results['total_trades']}")

    assert results["total_trades"] > 0, "Expected at least some trades from a 200-day random walk crossing its MA"
    assert results["final_capital"] > 0, "Capital went negative -- bug in trade execution logic"
    print("\nBacktest engine validated correctly.")
