"""Tests for bot.memory — per-user conversation memory."""

import time
from unittest.mock import patch

from bot.memory import (
    MAX_HISTORY,
    TTL_SECONDS,
    _clear_all,
    _store,
    add_message,
    clear_history,
    get_history,
)


def setup_function():
    """Reset the in-memory store before each test."""
    _clear_all()


# ── add / get ────────────────────────────────────────────────────────

def test_add_and_get_single_message():
    add_message(1, "user", "Oi")
    history = get_history(1)
    assert history == [("user", "Oi")]


def test_add_multiple_messages_preserves_order():
    add_message(1, "user", "pergunta 1")
    add_message(1, "assistant", "resposta 1")
    add_message(1, "user", "pergunta 2")
    history = get_history(1)
    assert history == [
        ("user", "pergunta 1"),
        ("assistant", "resposta 1"),
        ("user", "pergunta 2"),
    ]


def test_get_history_returns_copy():
    """Modifying the returned list should not affect the store."""
    add_message(1, "user", "Oi")
    history = get_history(1)
    history.append(("user", "extra"))
    assert get_history(1) == [("user", "Oi")]


def test_get_history_unknown_user_returns_empty():
    assert get_history(999) == []


def test_separate_users():
    add_message(1, "user", "msg de user 1")
    add_message(2, "user", "msg de user 2")
    assert get_history(1) == [("user", "msg de user 1")]
    assert get_history(2) == [("user", "msg de user 2")]


# ── clear ────────────────────────────────────────────────────────────

def test_clear_history():
    add_message(1, "user", "Oi")
    clear_history(1)
    assert get_history(1) == []


def test_clear_history_unknown_user_no_error():
    clear_history(999)  # should not raise


# ── max size ─────────────────────────────────────────────────────────

def test_max_size_evicts_oldest():
    """When exceeding MAX_HISTORY messages, oldest are dropped."""
    for i in range(MAX_HISTORY + 4):
        add_message(1, "user", f"msg {i}")

    history = get_history(1)
    assert len(history) == MAX_HISTORY
    # The oldest messages should have been evicted
    assert history[0] == ("user", "msg 4")
    assert history[-1] == ("user", f"msg {MAX_HISTORY + 3}")


def test_ten_exchanges_fit():
    """10 exchanges (user + assistant) = 20 messages = MAX_HISTORY."""
    for i in range(10):
        add_message(1, "user", f"pergunta {i}")
        add_message(1, "assistant", f"resposta {i}")

    history = get_history(1)
    assert len(history) == 20  # exactly MAX_HISTORY


# ── TTL ──────────────────────────────────────────────────────────────

def test_ttl_expires_history():
    add_message(1, "user", "Oi")

    # Simulate time passing beyond TTL
    with patch("bot.memory.time") as mock_time:
        # First call (add_message) happened at real time.
        # Now simulate get_history being called after TTL.
        mock_time.time.return_value = time.time() + TTL_SECONDS + 1
        history = get_history(1)

    assert history == []


def test_ttl_not_expired_keeps_history():
    add_message(1, "user", "Oi")

    with patch("bot.memory.time") as mock_time:
        mock_time.time.return_value = time.time() + TTL_SECONDS - 60
        history = get_history(1)

    assert history == [("user", "Oi")]


def test_ttl_resets_on_new_message():
    """Adding a message should reset the TTL timer."""
    add_message(1, "user", "msg 1")

    # Simulate time passing close to TTL, then add another message
    future = time.time() + TTL_SECONDS - 60
    with patch("bot.memory.time") as mock_time:
        mock_time.time.return_value = future
        add_message(1, "user", "msg 2")

    # Now check that TTL is measured from the second message, not the first
    with patch("bot.memory.time") as mock_time:
        # 90 seconds after the second message — still within TTL
        mock_time.time.return_value = future + 90
        history = get_history(1)

    assert len(history) == 2
