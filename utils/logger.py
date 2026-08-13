"""Centralized logger. Every module does `from utils.logger import get_logger`
and `logger = get_logger(__name__)` -- one consistent format, one place to
change log level/output destination."""

import logging
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_configured = False


def _configure_root():
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(LOG_DIR, "trading_bot.log")),
        ],
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)
