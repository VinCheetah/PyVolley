"""
Simple in-memory TTL cache for heavy database statistics and queries.
"""

import time
from typing import Any, Callable, Dict, Optional, Tuple


class TTLCache:
    """In-memory key-value store with Time-To-Live expiration."""

    def __init__(self, default_ttl: int = 300):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            expires_at, value = self._cache[key]
            if time.time() < expires_at:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        duration = ttl if ttl is not None else self.default_ttl
        self._cache[key] = (time.time() + duration, value)

    def clear(self) -> None:
        self._cache.clear()

    def get_or_compute(
        self, key: str, compute_fn: Callable[[], Any], ttl: Optional[int] = None
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        result = compute_fn()
        self.set(key, result, ttl=ttl)
        return result


# Global singleton instance for web stats caching (5 minutes TTL by default)
stats_cache = TTLCache(default_ttl=300)
