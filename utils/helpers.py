"""Small shared helpers."""

from datetime import datetime


def timestamp() -> str:
    return datetime.now().isoformat()


def round2(x: float) -> float:
    return round(x, 2)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator
