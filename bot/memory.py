"""Per-user conversation memory for TipsAI bot.

Stores recent exchanges (role, message) per user_id so follow-up
questions have context.  Thread-safe, with TTL expiration and
max-size eviction.

When ENABLE_MEMORY_CONDENSATION is true (default), exceeding MAX_HISTORY
triggers condensation: the oldest half of the conversation is summarised
by Claude into 2-3 sentences, and the history is replaced with
[condensed_summary] + [recent_half].  If condensation fails, the code
falls back to simple eviction (drop oldest messages).
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# Max exchanges (user + assistant pairs count as 2 entries each)
MAX_HISTORY = 20  # 10 exchanges = 20 messages (user + assistant)

# Conversations expire after 30 minutes of inactivity
TTL_SECONDS = 30 * 60

_lock = threading.Lock()

# user_id -> {"messages": [(role, text), ...], "last_active": float}
_store: dict[int, dict] = {}

# Condensation prompt (Portuguese)
_CONDENSATION_PROMPT = (
    "Resuma brevemente esta conversa em 2-3 frases, "
    "mantendo os pontos-chave:"
)


def _is_condensation_enabled() -> bool:
    """Check whether memory condensation is enabled via env var."""
    return os.getenv("ENABLE_MEMORY_CONDENSATION", "true").lower() in (
        "true", "1", "yes",
    )


def _condense_history(messages: list[tuple[str, str]]) -> tuple[str, str]:
    """Condense a list of (role, text) messages into a single summary.

    Calls Claude (via rag.llm.generate_response) with a condensation
    prompt and returns a ("assistant", summary_text) tuple suitable for
    prepending to the conversation history.

    Raises on any failure so the caller can fall back to simple eviction.
    """
    # Import here to avoid circular imports (rag.pipeline -> bot.memory)
    from rag.llm import generate_response

    # Format the messages into a readable conversation transcript
    transcript_lines: list[str] = []
    for role, text in messages:
        label = "Usuário" if role == "user" else "Assistente"
        transcript_lines.append(f"{label}: {text}")
    transcript = "\n".join(transcript_lines)

    summary = generate_response(
        system_prompt="Você é um assistente que resume conversas de forma concisa.",
        user_message=f"{_CONDENSATION_PROMPT}\n\n{transcript}",
        max_tokens=256,
    )

    return ("assistant", f"[Resumo da conversa anterior] {summary}")


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
            if _is_condensation_enabled():
                try:
                    mid = len(entry["messages"]) // 2
                    older_half = entry["messages"][:mid]
                    recent_half = entry["messages"][mid:]

                    # Release the lock while calling Claude (may take a few seconds)
                    # We work on local copies so the store is not in an
                    # inconsistent state while the API call runs.
                    _lock.release()
                    try:
                        condensed = _condense_history(older_half)
                    finally:
                        _lock.acquire()

                    # Re-check: the entry may have been cleared while we
                    # released the lock.
                    if user_id in _store:
                        entry = _store[user_id]
                        entry["messages"] = [condensed] + recent_half
                        logger.info(
                            "Condensed %d messages into summary for user %d "
                            "(now %d messages)",
                            len(older_half),
                            user_id,
                            len(entry["messages"]),
                        )
                except Exception:
                    logger.warning(
                        "Memory condensation failed for user %d, "
                        "falling back to simple eviction.",
                        user_id,
                        exc_info=True,
                    )
                    # Re-fetch entry in case it changed during lock release
                    if user_id in _store:
                        entry = _store[user_id]
                        entry["messages"] = entry["messages"][-MAX_HISTORY:]
            else:
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
