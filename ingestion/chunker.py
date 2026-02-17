"""Chunk parsed Telegram messages into groups for embedding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from ingestion.parser import TelegramMessage

# Maximum gap between messages to consider them part of the same conversation
CONVERSATION_GAP = timedelta(minutes=30)

# Target token count per chunk (rough: 1 token ≈ 4 chars in Portuguese)
TARGET_CHARS = 2000  # ~500 tokens


@dataclass
class MessageChunk:
    """A group of related messages ready for embedding."""

    message_ids: list[int]
    authors: list[str]
    start_time: str  # ISO format
    end_time: str  # ISO format
    text: str  # Combined text for embedding
    metadata: dict = field(default_factory=dict)


def _format_message(msg: TelegramMessage) -> str:
    """Format a single message for inclusion in a chunk."""
    ts = msg.timestamp.strftime("%d/%m/%Y %H:%M")
    prefix = f"[{ts}] {msg.author}"
    if msg.is_forwarded and msg.forwarded_from:
        prefix += f" (encaminhou de {msg.forwarded_from})"
    parts = [f"{prefix}:"]
    if msg.text:
        parts.append(msg.text)
    if msg.media_type and not msg.text:
        media_labels = {
            "photo": "[Foto]",
            "video": "[Vídeo]",
            "voice": "[Áudio]",
            "sticker": "[Sticker]",
            "file": "[Arquivo]",
        }
        parts.append(media_labels.get(msg.media_type, "[Mídia]"))
    return " ".join(parts)


def _build_reply_map(messages: list[TelegramMessage]) -> dict[int, int]:
    """Map message IDs to their reply targets for thread detection."""
    return {m.id: m.reply_to_id for m in messages if m.reply_to_id is not None}


def chunk_messages(messages: list[TelegramMessage]) -> list[MessageChunk]:
    """Split messages into conversational chunks.

    Strategy:
    1. Group messages into threads based on reply chains + temporal proximity.
    2. Break groups that exceed TARGET_CHARS into smaller chunks.
    """
    if not messages:
        return []

    # Filter out messages with no text and no media
    relevant = [m for m in messages if m.text or m.media_type]
    if not relevant:
        return []

    # Phase 1: Group by conversation flow
    groups: list[list[TelegramMessage]] = []
    current_group: list[TelegramMessage] = [relevant[0]]
    reply_targets = {m.id for m in relevant if m.reply_to_id is not None}

    for i in range(1, len(relevant)):
        prev = relevant[i - 1]
        curr = relevant[i]

        # Same conversation if: reply chain, or within time gap
        same_thread = (
            curr.reply_to_id is not None
            and any(m.id == curr.reply_to_id for m in current_group)
        )
        within_gap = (curr.timestamp - prev.timestamp) <= CONVERSATION_GAP

        if same_thread or within_gap:
            current_group.append(curr)
        else:
            groups.append(current_group)
            current_group = [curr]

    groups.append(current_group)

    # Phase 2: Break large groups into sized chunks
    chunks: list[MessageChunk] = []
    for group in groups:
        current_texts: list[str] = []
        current_msgs: list[TelegramMessage] = []
        current_len = 0

        for msg in group:
            formatted = _format_message(msg)
            msg_len = len(formatted)

            if current_len + msg_len > TARGET_CHARS and current_msgs:
                chunks.append(_make_chunk(current_msgs, current_texts))
                current_texts = []
                current_msgs = []
                current_len = 0

            current_texts.append(formatted)
            current_msgs.append(msg)
            current_len += msg_len

        if current_msgs:
            chunks.append(_make_chunk(current_msgs, current_texts))

    return chunks


def _make_chunk(msgs: list[TelegramMessage], texts: list[str]) -> MessageChunk:
    """Create a MessageChunk from a list of messages and their formatted texts."""
    authors = list(dict.fromkeys(m.author for m in msgs))  # unique, ordered
    return MessageChunk(
        message_ids=[m.id for m in msgs],
        authors=authors,
        start_time=msgs[0].timestamp.isoformat(),
        end_time=msgs[-1].timestamp.isoformat(),
        text="\n".join(texts),
        metadata={
            "author_count": len(authors),
            "message_count": len(msgs),
        },
    )
