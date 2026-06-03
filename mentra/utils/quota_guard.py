"""Daily request quota guard for Groq API calls."""

import datetime
import threading


class DailyQuotaGuard:
    """Thread-safe daily request counter with automatic date-based reset.

    Every STT and LLM call must pass guard.allow() before firing.
    When the limit is reached, callers should stop sending until the next day.
    """

    def __init__(self, limit: int = 1900):
        self._limit = limit
        self._count = 0
        self._date = datetime.date.today()
        self._lock = threading.Lock()

    def _maybe_reset(self):
        """Reset counter if the date has changed (called under lock)."""
        today = datetime.date.today()
        if today != self._date:
            self._date = today
            self._count = 0

    def allow(self) -> bool:
        """Check if a request is allowed.  Increments the counter on True."""
        with self._lock:
            self._maybe_reset()
            if self._count >= self._limit:
                return False
            self._count += 1
            return True

    @property
    def count(self) -> int:
        """Current request count today (read-only)."""
        with self._lock:
            self._maybe_reset()
            return self._count

    @property
    def remaining(self) -> int:
        """Remaining requests today."""
        with self._lock:
            self._maybe_reset()
            return max(0, self._limit - self._count)

    @property
    def limit(self) -> int:
        return self._limit

    def __repr__(self):
        return f"DailyQuotaGuard(count={self.count}/{self._limit}, remaining={self.remaining})"
