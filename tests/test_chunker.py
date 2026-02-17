"""Tests for the message chunker."""

from datetime import datetime, timedelta

import pytest

from ingestion.chunker import MessageChunk, chunk_messages
from ingestion.parser import TelegramMessage


def _make_msg(
    id: int,
    author: str = "User",
    minutes_offset: int = 0,
    text: str = "Hello",
    reply_to: int | None = None,
    media_type: str | None = None,
) -> TelegramMessage:
    base = datetime(2024, 8, 17, 14, 0, 0)
    return TelegramMessage(
        id=id,
        author=author,
        timestamp=base + timedelta(minutes=minutes_offset),
        text=text,
        reply_to_id=reply_to,
        media_type=media_type,
    )


def test_empty_input():
    """Empty list produces no chunks."""
    assert chunk_messages([]) == []


def test_single_message():
    """Single message becomes one chunk."""
    msgs = [_make_msg(1, text="Oi")]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 1
    assert chunks[0].message_ids == [1]
    assert "Oi" in chunks[0].text


def test_temporal_grouping():
    """Messages close in time are grouped together."""
    msgs = [
        _make_msg(1, minutes_offset=0, text="Msg 1"),
        _make_msg(2, minutes_offset=5, text="Msg 2"),
        _make_msg(3, minutes_offset=10, text="Msg 3"),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 1
    assert chunks[0].message_ids == [1, 2, 3]


def test_time_gap_splits():
    """Messages with >30min gap are split into separate chunks."""
    msgs = [
        _make_msg(1, minutes_offset=0, text="Msg 1"),
        _make_msg(2, minutes_offset=60, text="Msg 2"),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 2


def test_reply_chain_grouping():
    """Reply chains keep messages in the same chunk even across time gaps."""
    msgs = [
        _make_msg(1, minutes_offset=0, text="Pergunta?"),
        _make_msg(2, minutes_offset=5, text="Resposta"),
        _make_msg(3, minutes_offset=60, text="Complemento", reply_to=1),
    ]
    chunks = chunk_messages(msgs)
    # Message 3 replies to 1 which is in current_group, so stays grouped
    assert len(chunks) == 1


def test_large_chunk_splits():
    """Chunks exceeding target size get split."""
    long_text = "X" * 1500
    msgs = [
        _make_msg(1, minutes_offset=0, text=long_text),
        _make_msg(2, minutes_offset=1, text=long_text),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 2


def test_metadata():
    """Chunks include correct metadata."""
    msgs = [
        _make_msg(1, author="Alice", minutes_offset=0, text="Oi"),
        _make_msg(2, author="Bob", minutes_offset=1, text="Oi!"),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 1
    assert set(chunks[0].authors) == {"Alice", "Bob"}
    assert chunks[0].metadata["message_count"] == 2


def test_media_only_messages():
    """Messages with only media (no text) are included."""
    msgs = [
        _make_msg(1, text="", media_type="photo"),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 1
    assert "[Foto]" in chunks[0].text


def test_empty_messages_filtered():
    """Messages with no text and no media are filtered out."""
    msgs = [
        _make_msg(1, text="", media_type=None),
        _make_msg(2, text="Real message"),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 1
    assert chunks[0].message_ids == [2]
