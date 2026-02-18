"""Tests for per-user rate limiting."""

import time

from bot.rate_limit import RateLimiter, RATE_LIMIT_MSG, rate_limiter


# ── Singleton ────────────────────────────────────────────────────────

def test_module_singleton_exists():
    """Module exposes a ready-to-use RateLimiter singleton."""
    assert isinstance(rate_limiter, RateLimiter)


# ── Basic allow / deny ───────────────────────────────────────────────

def test_allows_up_to_max_requests():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    user = 1001
    assert rl.is_allowed(user) is True
    assert rl.is_allowed(user) is True
    assert rl.is_allowed(user) is True


def test_denies_after_max_requests():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    user = 1001
    for _ in range(3):
        rl.is_allowed(user)
    assert rl.is_allowed(user) is False


def test_denied_request_not_recorded():
    """Denied calls must NOT push a new timestamp (would delay recovery)."""
    rl = RateLimiter(max_requests=2, window_seconds=0.2)
    user = 42
    assert rl.is_allowed(user) is True
    assert rl.is_allowed(user) is True
    assert rl.is_allowed(user) is False  # denied — no timestamp added

    # After the window elapses only the 2 real timestamps need to expire.
    time.sleep(0.25)
    assert rl.is_allowed(user) is True


# ── Window expiration ────────────────────────────────────────────────

def test_window_expiration_allows_again():
    """After the window elapses the user may send again."""
    rl = RateLimiter(max_requests=2, window_seconds=0.15)
    user = 2002
    assert rl.is_allowed(user) is True
    assert rl.is_allowed(user) is True
    assert rl.is_allowed(user) is False

    time.sleep(0.2)  # wait for window to expire

    assert rl.is_allowed(user) is True


def test_sliding_window_partial_expiration():
    """Old timestamps slide out while newer ones remain."""
    rl = RateLimiter(max_requests=2, window_seconds=0.2)
    user = 3003

    assert rl.is_allowed(user) is True  # t=0
    time.sleep(0.12)
    assert rl.is_allowed(user) is True  # t=0.12 — window full
    assert rl.is_allowed(user) is False  # denied

    # Wait just enough for the first timestamp to expire (~0.10s)
    time.sleep(0.10)
    assert rl.is_allowed(user) is True  # first slot freed up


# ── Multiple users are independent ──────────────────────────────────

def test_users_are_independent():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.is_allowed(100) is True
    assert rl.is_allowed(100) is False  # user 100 exhausted

    assert rl.is_allowed(200) is True   # user 200 unaffected
    assert rl.is_allowed(200) is False

    assert rl.is_allowed(300) is True   # user 300 unaffected


# ── get_wait_time ────────────────────────────────────────────────────

def test_wait_time_zero_when_under_limit():
    rl = RateLimiter(max_requests=5, window_seconds=60)
    assert rl.get_wait_time(999) == 0.0


def test_wait_time_zero_after_some_requests():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    rl.is_allowed(10)
    rl.is_allowed(10)
    assert rl.get_wait_time(10) == 0.0  # still 1 slot left


def test_wait_time_positive_when_limited():
    rl = RateLimiter(max_requests=2, window_seconds=1.0)
    rl.is_allowed(50)
    rl.is_allowed(50)
    wait = rl.get_wait_time(50)
    assert wait > 0.0
    assert wait <= 1.0


def test_wait_time_decreases_over_time():
    rl = RateLimiter(max_requests=1, window_seconds=0.3)
    rl.is_allowed(60)
    w1 = rl.get_wait_time(60)

    time.sleep(0.1)
    w2 = rl.get_wait_time(60)

    assert w2 < w1


def test_wait_time_reaches_zero_after_window():
    rl = RateLimiter(max_requests=1, window_seconds=0.15)
    rl.is_allowed(70)
    assert rl.get_wait_time(70) > 0.0

    time.sleep(0.2)
    assert rl.get_wait_time(70) == 0.0


# ── Cleanup ──────────────────────────────────────────────────────────

def test_cleanup_removes_expired_entries():
    rl = RateLimiter(max_requests=1, window_seconds=0.1, cleanup_interval=1)
    rl.is_allowed(800)
    time.sleep(0.15)

    # Next call triggers cleanup (interval=1 ⇒ every call)
    rl.is_allowed(801)
    assert 800 not in rl._requests


# ── Message template ─────────────────────────────────────────────────

def test_rate_limit_message_formatting():
    msg = RATE_LIMIT_MSG.format(seconds=42.7)
    assert "43 segundos" in msg


def test_rate_limit_message_is_portuguese():
    assert "Calma" in RATE_LIMIT_MSG
    assert "segundos" in RATE_LIMIT_MSG
