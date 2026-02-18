"""Per-user conversation memory for TipsAI bot.

Stores recent exchanges (role, message) per user_id so follow-up
questions have context.  Thread-safe, with TTL expiration and
max-size eviction.
"""

from __future__ import annotations

import threading
import time

# Max exchanges (user + assistant pairs count as 2 entries each)
MAX_HISTORY = 20  # 10 exchanges = 20 messages (user + assistant)

# Conversations expire after 30 minutes of inactivity
TTL_SECONDS = 30 * 60

_lock = threading.Lock()

# user_id -> {"messages": [(role, text), ...], "last_active": float}
_store: dict[int, dict] = {}


def add_message(user_id: int, role: str, text: str) -> None:
    """Append a message to the user's conversation history.

    Args:
        user_id: Telegram user ID.
        role: "user" or "assistant".
        text: Message content.
    """
    with _lock:
        _expire(user_id)
        if user_id not in _store:
            _store[user_id] = {"messages": [], "last_active": time.time()}

        entry = _store[user_id]
        entry["messages"].append((role, text))
        entry["last_active"] = time.time()

        # Evict oldest messages if we exceed the limit
        if len(entry["messages"]) > MAX_HISTORY:
            entry["messages"] = entry["messages"][-MAX_HISTORY:]


def get_history(user_id: int) -> list[tuple[str, str]]:
    """Return the conversation history for a user.

    Returns an empty list if the user has no history or it expired.
    """
    with _lock:
        _expire(user_id)
        entry = _store.get(user_id)
        if entry is None:
            return []
        return list(entry["messages"])


def clear_history(user_id: int) -> None:
    """Clear the conversation history for a user."""
    with _lock:
        _store.pop(user_id, None)


def _expire(user_id: int) -> None:
    """Remove the user's history if TTL has elapsed.  Must be called with _lock held."""
    entry = _store.get(user_id)
    if entry is not None:
        if time.time() - entry["last_active"] > TTL_SECONDS:
            del _store[user_id]


def _clear_all() -> None:
    """Clear all history.  Used only for testing."""
    with _lock:
        _store.clear()
