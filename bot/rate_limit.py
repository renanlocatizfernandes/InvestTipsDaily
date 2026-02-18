"""Per-user rate limiting with sliding window."""

from __future__ import annotations

import threading
import time
from collections import deque

# Rate-limit exceeded message template (pt-BR)
RATE_LIMIT_MSG = (
    "Calma! Você está enviando muitas mensagens. "
    "Tente novamente em {seconds:.0f} segundos."
)


class RateLimiter:
    """Sliding-window rate limiter keyed by user ID.

    Parameters
    ----------
    max_requests : int
        Maximum number of requests allowed inside the window (default 5).
    window_seconds : float
        Length of the sliding window in seconds (default 60).
    cleanup_interval : int
        Run automatic cleanup of expired entries every *cleanup_interval*
        calls to :meth:`is_allowed` (default 100).
    """

    def __init__(
        self,
        max_requests: int = 5,
        window_seconds: float = 60,
        cleanup_interval: int = 100,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._cleanup_interval = cleanup_interval

        # user_id -> deque of timestamps (most recent at the right)
        self._requests: dict[int, deque[float]] = {}
        self._lock = threading.Lock()
        self._call_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_allowed(self, user_id: int) -> bool:
        """Return ``True`` if *user_id* is below the rate limit.

        If the request is allowed, the current timestamp is recorded.
        If denied, no timestamp is recorded.
        """
        now = time.monotonic()

        with self._lock:
            self._call_count += 1
            if self._call_count % self._cleanup_interval == 0:
                self._cleanup(now)

            dq = self._requests.get(user_id)
            if dq is None:
                dq = deque()
                self._requests[user_id] = dq

            # Evict timestamps outside the window
            cutoff = now - self.window_seconds
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) < self.max_requests:
                dq.append(now)
                return True

            return False

    def get_wait_time(self, user_id: int) -> float:
        """Seconds until *user_id* can make the next request.

        Returns ``0.0`` when the user is not rate-limited.
        """
        now = time.monotonic()

        with self._lock:
            dq = self._requests.get(user_id)
            if dq is None:
                return 0.0

            # Evict expired entries
            cutoff = now - self.window_seconds
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) < self.max_requests:
                return 0.0

            # The oldest timestamp inside the window determines when the
            # next slot opens up.
            oldest = dq[0]
            wait = (oldest + self.window_seconds) - now
            return max(wait, 0.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup(self, now: float) -> None:
        """Remove user entries whose timestamps are all expired.

        Must be called while holding ``self._lock``.
        """
        cutoff = now - self.window_seconds
        expired_users = [
            uid
            for uid, dq in self._requests.items()
            if not dq or dq[-1] <= cutoff
        ]
        for uid in expired_users:
            del self._requests[uid]


# Module-level singleton for easy import:
#   from bot.rate_limit import rate_limiter
rate_limiter = RateLimiter()
