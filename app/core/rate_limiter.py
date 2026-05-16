"""
app/core/rate_limiter.py — Rate limiter em memória reutilizável.

Extraído de auth_login.py para ser compartilhado entre routers.
"""
from __future__ import annotations
import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    """Limita chamadas por chave (ex: IP) dentro de uma janela de tempo."""

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self._max = max_calls
        self._period = period_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            calls = self._calls[key]
            calls[:] = [t for t in calls if now - t < self._period]
            if len(calls) >= self._max:
                return False
            calls.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._calls.pop(key, None)


# Instâncias compartilhadas
login_limiter      = RateLimiter(max_calls=10, period_seconds=60)
activation_limiter = RateLimiter(max_calls=5,  period_seconds=3600)
erp_limiter        = RateLimiter(max_calls=60, period_seconds=60)
