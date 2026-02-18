"""Tests for bot feedback module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.feedback import (
    _save_feedback,
    create_feedback_keyboard,
    get_feedback_stats,
    handle_feedback_callback,
    store_query_for_message,
    _message_query_map,
)


# ── Keyboard creation ────────────────────────────────────────────────

def test_create_feedback_keyboard_returns_markup():
    """Keyboard has the correct type."""
    from telegram import InlineKeyboardMarkup

    kb = create_feedback_keyboard()
    assert isinstance(kb, InlineKeyboardMarkup)


def test_create_feedback_keyboard_has_two_buttons():
    """Keyboard has exactly two buttons in a single row."""
    kb = create_feedback_keyboard()
    rows = kb.inline_keyboard
    assert len(rows) == 1
    assert len(rows[0]) == 2


def test_create_feedback_keyboard_callback_data():
    """Buttons have the correct callback_data values."""
    kb = create_feedback_keyboard()
    buttons = kb.inline_keyboard[0]
    data_values = {btn.callback_data for btn in buttons}
    assert data_values == {"feedback_positive", "feedback_negative"}


def test_create_feedback_keyboard_button_labels():
    """Buttons have thumbs up and thumbs down emoji labels."""
    kb = create_feedback_keyboard()
    buttons = kb.inline_keyboard[0]
    labels = {btn.text for btn in buttons}
    assert "\U0001f44d" in labels  # thumbs up
    assert "\U0001f44e" in labels  # thumbs down


# ── Feedback storage ─────────────────────────────────────────────────

def test_save_feedback_creates_file(tmp_path: Path):
    """Saving feedback creates the JSON file if it doesn't exist."""
    filepath = tmp_path / "feedback.json"
    entry = {
        "user_id": 123,
        "user_name": "TestUser",
        "query": "o que e staking?",
        "response_preview": "Staking eh...",
        "feedback": "positive",
        "timestamp": "2025-01-01T00:00:00+00:00",
    }
    _save_feedback(entry, filepath=filepath)

    assert filepath.exists()
    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["feedback"] == "positive"


def test_save_feedback_appends(tmp_path: Path):
    """Multiple saves append to the same list."""
    filepath = tmp_path / "feedback.json"
    for i in range(3):
        _save_feedback(
            {
                "user_id": i,
                "user_name": f"User{i}",
                "query": f"query {i}",
                "response_preview": "resp",
                "feedback": "positive" if i % 2 == 0 else "negative",
                "timestamp": "2025-01-01T00:00:00+00:00",
            },
            filepath=filepath,
        )

    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert len(data) == 3


def test_save_feedback_handles_corrupt_file(tmp_path: Path):
    """If the JSON file is corrupt, start fresh instead of crashing."""
    filepath = tmp_path / "feedback.json"
    filepath.write_text("NOT VALID JSON", encoding="utf-8")

    _save_feedback(
        {
            "user_id": 1,
            "user_name": "User",
            "query": "q",
            "response_preview": "r",
            "feedback": "negative",
            "timestamp": "2025-01-01T00:00:00+00:00",
        },
        filepath=filepath,
    )

    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["feedback"] == "negative"


def test_save_feedback_creates_parent_dirs(tmp_path: Path):
    """Parent directories are created automatically."""
    filepath = tmp_path / "nested" / "deep" / "feedback.json"
    _save_feedback(
        {
            "user_id": 1,
            "user_name": "User",
            "query": "q",
            "response_preview": "r",
            "feedback": "positive",
            "timestamp": "2025-01-01T00:00:00+00:00",
        },
        filepath=filepath,
    )
    assert filepath.exists()


# ── Feedback stats ───────────────────────────────────────────────────

def test_get_feedback_stats_empty(tmp_path: Path):
    """Stats for a non-existent file return all zeros."""
    filepath = tmp_path / "nonexistent.json"
    stats = get_feedback_stats(filepath=filepath)
    assert stats == {"positive": 0, "negative": 0, "total": 0}


def test_get_feedback_stats_counts(tmp_path: Path):
    """Stats correctly count positive and negative feedback."""
    filepath = tmp_path / "feedback.json"
    entries = [
        {"feedback": "positive"},
        {"feedback": "positive"},
        {"feedback": "positive"},
        {"feedback": "negative"},
        {"feedback": "negative"},
    ]
    filepath.write_text(json.dumps(entries), encoding="utf-8")

    stats = get_feedback_stats(filepath=filepath)
    assert stats["positive"] == 3
    assert stats["negative"] == 2
    assert stats["total"] == 5


def test_get_feedback_stats_corrupt_file(tmp_path: Path):
    """Stats return zeros if the file is corrupt."""
    filepath = tmp_path / "feedback.json"
    filepath.write_text("{invalid", encoding="utf-8")

    stats = get_feedback_stats(filepath=filepath)
    assert stats == {"positive": 0, "negative": 0, "total": 0}


def test_get_feedback_stats_empty_file(tmp_path: Path):
    """Stats return zeros for an empty file."""
    filepath = tmp_path / "feedback.json"
    filepath.write_text("", encoding="utf-8")

    stats = get_feedback_stats(filepath=filepath)
    assert stats == {"positive": 0, "negative": 0, "total": 0}


# ── Query mapping ────────────────────────────────────────────────────

def test_store_query_for_message():
    """store_query_for_message saves to the in-memory map."""
    # Clean up after ourselves
    original = dict(_message_query_map)
    try:
        store_query_for_message(999, "minha pergunta")
        assert _message_query_map[999] == "minha pergunta"
    finally:
        _message_query_map.clear()
        _message_query_map.update(original)


# ── Callback handler ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_feedback_callback_positive(tmp_path: Path):
    """Handler processes positive feedback and saves it."""
    filepath = tmp_path / "feedback.json"

    # Build mock update
    callback_query = AsyncMock()
    callback_query.data = "feedback_positive"
    callback_query.message = MagicMock()
    callback_query.message.message_id = 42
    callback_query.message.text = "Staking eh o processo de..."

    user = MagicMock()
    user.id = 123
    user.first_name = "Renan"

    update = MagicMock(spec=["callback_query", "effective_user"])
    update.callback_query = callback_query
    update.effective_user = user

    context = MagicMock()

    # Store a query for this message
    store_query_for_message(42, "o que e staking?")

    with patch("bot.feedback.FEEDBACK_FILE", filepath):
        await handle_feedback_callback(update, context)

    # Verify callback was answered
    callback_query.answer.assert_awaited_once()
    answer_text = callback_query.answer.call_args[0][0]
    assert "\U0001f44d" in answer_text

    # Verify keyboard was removed
    callback_query.edit_message_reply_markup.assert_awaited_once_with(
        reply_markup=None
    )

    # Verify feedback was saved
    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["feedback"] == "positive"
    assert data[0]["user_id"] == 123
    assert data[0]["user_name"] == "Renan"
    assert data[0]["query"] == "o que e staking?"
    assert data[0]["response_preview"] == "Staking eh o processo de..."


@pytest.mark.asyncio
async def test_handle_feedback_callback_negative(tmp_path: Path):
    """Handler processes negative feedback and saves it."""
    filepath = tmp_path / "feedback.json"

    callback_query = AsyncMock()
    callback_query.data = "feedback_negative"
    callback_query.message = MagicMock()
    callback_query.message.message_id = 43
    callback_query.message.text = "Nao encontrei informacao..."

    user = MagicMock()
    user.id = 456
    user.first_name = "Maria"

    update = MagicMock(spec=["callback_query", "effective_user"])
    update.callback_query = callback_query
    update.effective_user = user

    context = MagicMock()

    with patch("bot.feedback.FEEDBACK_FILE", filepath):
        await handle_feedback_callback(update, context)

    # Verify negative acknowledgement text
    answer_text = callback_query.answer.call_args[0][0]
    assert "\U0001f4aa" in answer_text

    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["feedback"] == "negative"
    assert data[0]["user_name"] == "Maria"


@pytest.mark.asyncio
async def test_handle_feedback_callback_ignores_unknown_data(tmp_path: Path):
    """Handler ignores callback queries with unknown data."""
    filepath = tmp_path / "feedback.json"

    callback_query = AsyncMock()
    callback_query.data = "some_other_action"

    update = MagicMock(spec=["callback_query", "effective_user"])
    update.callback_query = callback_query

    context = MagicMock()

    with patch("bot.feedback.FEEDBACK_FILE", filepath):
        await handle_feedback_callback(update, context)

    # Should not have answered or saved anything
    callback_query.answer.assert_not_awaited()
    assert not filepath.exists()


@pytest.mark.asyncio
async def test_handle_feedback_callback_no_query():
    """Handler returns early when there is no callback query."""
    update = MagicMock(spec=["callback_query", "effective_user"])
    update.callback_query = None

    context = MagicMock()

    # Should not raise
    await handle_feedback_callback(update, context)


@pytest.mark.asyncio
async def test_handle_feedback_consumes_query_mapping(tmp_path: Path):
    """After feedback, the query mapping entry is removed."""
    filepath = tmp_path / "feedback.json"

    callback_query = AsyncMock()
    callback_query.data = "feedback_positive"
    callback_query.message = MagicMock()
    callback_query.message.message_id = 77
    callback_query.message.text = "Resp"

    user = MagicMock()
    user.id = 1
    user.first_name = "Test"

    update = MagicMock(spec=["callback_query", "effective_user"])
    update.callback_query = callback_query
    update.effective_user = user

    context = MagicMock()

    store_query_for_message(77, "minha pergunta")

    with patch("bot.feedback.FEEDBACK_FILE", filepath):
        await handle_feedback_callback(update, context)

    # The mapping entry should have been consumed (removed)
    assert 77 not in _message_query_map
