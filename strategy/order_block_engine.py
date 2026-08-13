"""
Order Block detection, ported from the Sonarlab Order Blocks Pine Script
(MPL-2.0) and validated earlier in this project against known test cases.
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class OrderBlock:
    kind: str            # "bullish" (demand) or "bearish" (supply)
    top: float
    bottom: float
    origin_index: int
    created_index: int
    active: bool = True
    triggered: bool = False


class OrderBlockEngine:
    def __init__(
        self,
        sensitivity: float = 28,
        lookback_min: int = 4,
        lookback_max: int = 15,
        min_bar_gap: int = 5,
        mitigation_type: str = "close",
    ):
        self.sens = sensitivity / 100.0
        self.lookback_min = lookback_min
        self.lookback_max = lookback_max
        self.min_bar_gap = min_bar_gap
        self.mitigation_type = mitigation_type

    def detect(self, df: pd.DataFrame) -> list:
        o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
        n = len(df)

        pc = np.full(n, np.nan)
        for i in range(4, n):
            pc[i] = (o[i] - o[i - 4]) / o[i - 4] * 100

        blocks = []
        last_cross_index = None

        for i in range(5, n):
            if np.isnan(pc[i]) or np.isnan(pc[i - 1]):
                continue

            crossed_under = pc[i - 1] > -self.sens and pc[i] <= -self.sens
            crossed_over = pc[i - 1] < self.sens and pc[i] >= self.sens

            if not (crossed_under or crossed_over):
                continue
            if last_cross_index is not None and i - last_cross_index <= self.min_bar_gap:
                last_cross_index = i
                continue
            last_cross_index = i

            if crossed_under:
                origin = self._find_origin(o, c, i, want_bullish_candle=True)
                if origin is not None:
                    blocks.append(OrderBlock(kind="bearish", top=h[origin], bottom=l[origin],
                                              origin_index=origin, created_index=i))

            if crossed_over:
                origin = self._find_origin(o, c, i, want_bullish_candle=False)
                if origin is not None:
                    blocks.append(OrderBlock(kind="bullish", top=h[origin], bottom=l[origin],
                                              origin_index=origin, created_index=i))

        return blocks

    def _find_origin(self, o, c, current_i, want_bullish_candle: bool) -> Optional[int]:
        for offset in range(self.lookback_min, self.lookback_max + 1):
            idx = current_i - offset
            if idx < 0:
                break
            is_bullish_candle = c[idx] > o[idx]
            if is_bullish_candle == want_bullish_candle:
                return idx
        return None

    def update_mitigation(self, blocks: list, df: pd.DataFrame, upto_index: int):
        h, l, c = df["high"].values, df["low"].values, df["close"].values
        for ob in blocks:
            if not ob.active:
                continue
            ref_bull = c[upto_index - 1] if self.mitigation_type == "close" else l[upto_index]
            ref_bear = c[upto_index - 1] if self.mitigation_type == "close" else h[upto_index]
            if ob.kind == "bullish" and ref_bull < ob.bottom:
                ob.active = False
            if ob.kind == "bearish" and ref_bear > ob.top:
                ob.active = False


if __name__ == "__main__":
    print("Order Block Engine module loaded (see strategy/cascade.py for the end-to-end test).")
