"""
Minimal in-process pub/sub event bus. Lets data_manager announce
"spot updated", "option chain updated", etc. without importing the
strategy layer directly (avoids circular imports and keeps data/ and
strategy/ decoupled, matching the architecture's intent).
"""

from collections import defaultdict
from utils.logger import get_logger

logger = get_logger(__name__)


class EventBus:
    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_name: str, callback):
        self._subscribers[event_name].append(callback)

    def publish(self, event_name: str, payload=None):
        for callback in self._subscribers.get(event_name, []):
            try:
                callback(payload)
            except Exception as e:
                logger.error(f"Event subscriber for '{event_name}' raised: {e}")


event_bus = EventBus()
