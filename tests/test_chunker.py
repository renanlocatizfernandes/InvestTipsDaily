"""Tests for the message chunker."""

from datetime import datetime, timedelta

import pytest

from ingestion.chunker import MessageChunk, chunk_messages, OVERLAP_CHARS, TARGET_CHARS
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


def test_overlap_between_split_chunks():
    """When a conversation group is split, trailing messages from the previous
    chunk are carried over to the next chunk as overlap (~OVERLAP_CHARS worth).

    We craft messages so that:
    - Each formatted message is ~250 chars (well above OVERLAP_CHARS=200 per
      single message, so at least 1 message overlaps).
    - 10 such messages produce ~2500 chars total, which exceeds TARGET_CHARS
      and forces a split, giving us multiple chunks to verify overlap on.
    """
    # Each message text is 200 chars; formatted adds prefix (~50 chars)
    # so each formatted message is ~250 chars.  TARGET_CHARS=2000 means
    # roughly 8 messages fit per chunk before a split.
    msg_text = "A" * 200
    msgs = [
        _make_msg(i, author=f"User{i}", minutes_offset=i, text=msg_text)
        for i in range(1, 11)
    ]

    chunks = chunk_messages(msgs)

    # Must produce more than 1 chunk (the group is too large for one)
    assert len(chunks) >= 2, f"Expected >=2 chunks, got {len(chunks)}"

    # Verify overlap: for each consecutive pair of chunks, the tail of the
    # first chunk's message_ids should overlap with the head of the next.
    for i in range(len(chunks) - 1):
        prev_ids = chunks[i].message_ids
        next_ids = chunks[i + 1].message_ids

        overlap_ids = set(prev_ids) & set(next_ids)
        assert len(overlap_ids) > 0, (
            f"Chunks {i} and {i+1} share no message IDs — overlap is missing. "
            f"prev_ids={prev_ids}, next_ids={next_ids}"
        )

        # The overlapping IDs should be from the END of the previous chunk
        # and the START of the next chunk.
        for oid in overlap_ids:
            assert oid in prev_ids[-len(overlap_ids) - 1 :]
            assert oid in next_ids[: len(overlap_ids) + 1]

    # Verify metadata is still correct in each chunk
    for chunk in chunks:
        assert chunk.metadata["message_count"] == len(chunk.message_ids)
        assert chunk.metadata["author_count"] == len(chunk.authors)


def test_overlap_does_not_apply_to_small_groups():
    """Groups that fit in a single chunk should produce exactly one chunk
    with no duplication — overlap only applies when splitting occurs."""
    msgs = [
        _make_msg(1, minutes_offset=0, text="Short msg 1"),
        _make_msg(2, minutes_offset=1, text="Short msg 2"),
        _make_msg(3, minutes_offset=2, text="Short msg 3"),
    ]
    chunks = chunk_messages(msgs)
    assert len(chunks) == 1
    assert chunks[0].message_ids == [1, 2, 3]
