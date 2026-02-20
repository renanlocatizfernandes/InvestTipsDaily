"""Tests for bot.memory — per-user conversation memory."""

import time
from unittest.mock import patch, MagicMock

from bot.memory import (
    MAX_HISTORY,
    TTL_SECONDS,
    _clear_all,
    _condense_history,
    _CONDENSATION_PROMPT,
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


# ── max size (condensation disabled) ─────────────────────────────────

@patch.dict("os.environ", {"ENABLE_MEMORY_CONDENSATION": "false"})
def test_max_size_evicts_oldest():
    """When exceeding MAX_HISTORY messages (condensation off), oldest are dropped."""
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


# ── condensation ─────────────────────────────────────────────────────

@patch.dict("os.environ", {"ENABLE_MEMORY_CONDENSATION": "true"})
@patch("bot.memory._condense_history")
def test_condensation_replaces_older_half_with_summary(mock_condense):
    """When condensation is enabled and history exceeds MAX_HISTORY,
    the older half is condensed into a single summary message."""
    mock_condense.return_value = ("assistant", "[Resumo da conversa anterior] Resumo aqui.")

    # Fill to MAX_HISTORY + 1 to trigger condensation
    for i in range(MAX_HISTORY + 1):
        add_message(1, "user", f"msg {i}")

    history = get_history(1)

    # condensation should have been called once
    mock_condense.assert_called_once()

    # The first message should be the condensed summary
    assert history[0] == ("assistant", "[Resumo da conversa anterior] Resumo aqui.")

    # Total should be: 1 (summary) + recent_half
    mid = (MAX_HISTORY + 1) // 2  # 10
    recent_count = (MAX_HISTORY + 1) - mid  # 11
    assert len(history) == 1 + recent_count


@patch.dict("os.environ", {"ENABLE_MEMORY_CONDENSATION": "true"})
@patch("bot.memory._condense_history")
def test_condensation_passes_older_half_to_condense(mock_condense):
    """Verify that _condense_history receives the correct older half."""
    mock_condense.return_value = ("assistant", "[Resumo da conversa anterior] ...")

    for i in range(MAX_HISTORY + 1):
        add_message(1, "user", f"msg {i}")

    # The older half should be the first 10 messages (indices 0..9)
    called_messages = mock_condense.call_args[0][0]
    mid = (MAX_HISTORY + 1) // 2
    assert len(called_messages) == mid
    assert called_messages[0] == ("user", "msg 0")
    assert called_messages[-1] == ("user", f"msg {mid - 1}")


@patch.dict("os.environ", {"ENABLE_MEMORY_CONDENSATION": "true"})
@patch("bot.memory._condense_history", side_effect=RuntimeError("API error"))
def test_condensation_failure_falls_back_to_eviction(mock_condense):
    """If _condense_history raises, fall back to simple eviction."""
    for i in range(MAX_HISTORY + 4):
        add_message(1, "user", f"msg {i}")

    history = get_history(1)
    assert len(history) == MAX_HISTORY
    # Should have fallen back to keeping the most recent MAX_HISTORY messages
    assert history[-1] == ("user", f"msg {MAX_HISTORY + 3}")


@patch.dict("os.environ", {"ENABLE_MEMORY_CONDENSATION": "false"})
def test_condensation_disabled_uses_simple_eviction():
    """When ENABLE_MEMORY_CONDENSATION is false, use simple eviction."""
    for i in range(MAX_HISTORY + 2):
        add_message(1, "user", f"msg {i}")

    history = get_history(1)
    assert len(history) == MAX_HISTORY
    assert history[0] == ("user", "msg 2")
    assert history[-1] == ("user", f"msg {MAX_HISTORY + 1}")


@patch("rag.llm.generate_response")
def test_condense_history_formats_transcript(mock_generate):
    """_condense_history should format messages and call generate_response."""
    mock_generate.return_value = "O usuario perguntou sobre Bitcoin e staking."

    messages = [
        ("user", "O que e Bitcoin?"),
        ("assistant", "Bitcoin e uma criptomoeda."),
        ("user", "E staking?"),
        ("assistant", "Staking e manter moedas travadas."),
    ]

    result = _condense_history(messages)

    assert result[0] == "assistant"
    assert "[Resumo da conversa anterior]" in result[1]
    assert "O usuario perguntou sobre Bitcoin e staking." in result[1]

    # Check generate_response was called with the condensation prompt
    call_args = mock_generate.call_args
    assert call_args.kwargs["system_prompt"] == "Você é um assistente que resume conversas de forma concisa."
    assert _CONDENSATION_PROMPT in call_args.kwargs["user_message"]
    # Check transcript is included
    assert "Usuário: O que e Bitcoin?" in call_args.kwargs["user_message"]
    assert "Assistente: Bitcoin e uma criptomoeda." in call_args.kwargs["user_message"]
    assert call_args.kwargs["max_tokens"] == 256


@patch.dict("os.environ", {"ENABLE_MEMORY_CONDENSATION": "true"})
@patch("bot.memory._condense_history")
def test_condensation_preserves_recent_messages(mock_condense):
    """After condensation, the recent half of messages must be intact."""
    mock_condense.return_value = ("assistant", "[Resumo da conversa anterior] Resumo.")

    # Add exactly MAX_HISTORY + 1 messages
    total = MAX_HISTORY + 1
    for i in range(total):
        add_message(1, "user", f"msg {i}")

    history = get_history(1)

    mid = total // 2  # 10
    # Recent half starts from message index 10
    recent_messages_in_history = history[1:]  # skip the summary
    for j, (role, text) in enumerate(recent_messages_in_history):
        assert role == "user"
        assert text == f"msg {mid + j}"


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
