"""Tests for live ingestion: buffering, message conversion, and flush logic."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingestion.parser import TelegramMessage
from bot.live_ingest import (
    MessageBuffer,
    telegram_message_to_dataclass,
    handle_new_message,
    _flush_buffer,
    _ingest_batch,
)


# ---------------------------------------------------------------------------
# MessageBuffer tests
# ---------------------------------------------------------------------------

class TestMessageBuffer:
    """Tests for the thread-safe MessageBuffer."""

    def _make_tg_msg(self, id: int = 1, text: str = "Hello") -> TelegramMessage:
        return TelegramMessage(
            id=id,
            author="User",
            timestamp=datetime(2024, 8, 17, 14, 0, 0),
            text=text,
        )

    def test_empty_buffer(self):
        buf = MessageBuffer(batch_threshold=10)
        assert buf.is_empty
        assert buf.size == 0

    def test_add_message_below_threshold(self):
        buf = MessageBuffer(batch_threshold=5)
        msg = self._make_tg_msg()
        should_flush = buf.add(msg)
        assert not should_flush
        assert buf.size == 1
        assert not buf.is_empty

    def test_add_message_reaches_threshold(self):
        buf = MessageBuffer(batch_threshold=3)
        for i in range(2):
            result = buf.add(self._make_tg_msg(id=i))
            assert not result

        # Third message triggers threshold
        result = buf.add(self._make_tg_msg(id=3))
        assert result

    def test_flush_returns_messages_and_clears(self):
        buf = MessageBuffer(batch_threshold=10)
        msg1 = self._make_tg_msg(id=1, text="Msg 1")
        msg2 = self._make_tg_msg(id=2, text="Msg 2")
        buf.add(msg1)
        buf.add(msg2)

        flushed = buf.flush()
        assert len(flushed) == 2
        assert flushed[0].id == 1
        assert flushed[1].id == 2

        # Buffer should be empty after flush
        assert buf.is_empty
        assert buf.size == 0

    def test_flush_empty_buffer_returns_empty_list(self):
        buf = MessageBuffer()
        flushed = buf.flush()
        assert flushed == []

    def test_should_flush_by_time_false_when_empty(self):
        buf = MessageBuffer(flush_interval=5.0)
        assert not buf.should_flush_by_time()

    def test_should_flush_by_time_false_when_recent(self):
        buf = MessageBuffer(flush_interval=300.0)
        buf.add(self._make_tg_msg())
        assert not buf.should_flush_by_time()

    def test_should_flush_by_time_true_when_elapsed(self):
        buf = MessageBuffer(flush_interval=0.01)  # Very short interval
        buf.add(self._make_tg_msg())
        time.sleep(0.02)
        assert buf.should_flush_by_time()

    def test_flush_resets_timer(self):
        buf = MessageBuffer(flush_interval=0.01)
        buf.add(self._make_tg_msg())
        time.sleep(0.02)
        assert buf.should_flush_by_time()

        buf.flush()
        assert not buf.should_flush_by_time()


# ---------------------------------------------------------------------------
# telegram_message_to_dataclass tests
# ---------------------------------------------------------------------------

class TestTelegramMessageConversion:
    """Tests for converting Telegram Message objects to TelegramMessage dataclass."""

    def _make_telegram_message(
        self,
        message_id: int = 42,
        text: str = "Oi pessoal",
        first_name: str = "Renan",
        last_name: str = "Fernandes",
        user_id: int = 12345,
        date: datetime | None = None,
        reply_to_message: MagicMock | None = None,
        forward_date: datetime | None = None,
        forward_from: MagicMock | None = None,
    ) -> MagicMock:
        """Create a mock telegram.Message object."""
        msg = MagicMock()
        msg.message_id = message_id
        msg.text = text
        msg.date = date or datetime(2024, 10, 15, 18, 30, 0, tzinfo=timezone.utc)
        msg.reply_to_message = reply_to_message
        msg.forward_date = forward_date
        msg.forward_from = forward_from

        user = MagicMock()
        user.id = user_id
        user.first_name = first_name
        user.last_name = last_name
        user.full_name = f"{first_name} {last_name}" if last_name else first_name
        msg.from_user = user

        return msg

    def test_basic_conversion(self):
        msg = self._make_telegram_message()
        result = telegram_message_to_dataclass(msg)

        assert result is not None
        assert result.id == 42
        assert result.author == "Renan Fernandes"
        assert result.text == "Oi pessoal"
        assert result.reply_to_id is None
        assert result.is_forwarded is False
        assert result.media_type is None
        assert result.media_path is None

    def test_none_message_returns_none(self):
        assert telegram_message_to_dataclass(None) is None

    def test_empty_text_returns_none(self):
        msg = self._make_telegram_message(text="")
        msg.text = ""
        assert telegram_message_to_dataclass(msg) is None

    def test_no_text_returns_none(self):
        msg = self._make_telegram_message()
        msg.text = None
        assert telegram_message_to_dataclass(msg) is None

    def test_reply_to_message(self):
        reply_msg = MagicMock()
        reply_msg.message_id = 10
        msg = self._make_telegram_message(reply_to_message=reply_msg)

        result = telegram_message_to_dataclass(msg)
        assert result is not None
        assert result.reply_to_id == 10

    def test_forwarded_message(self):
        fwd_user = MagicMock()
        fwd_user.full_name = "Carlos Silva"
        fwd_user.first_name = "Carlos"
        msg = self._make_telegram_message(
            forward_date=datetime(2024, 10, 10, 12, 0, 0, tzinfo=timezone.utc),
            forward_from=fwd_user,
        )

        result = telegram_message_to_dataclass(msg)
        assert result is not None
        assert result.is_forwarded is True
        assert result.forwarded_from == "Carlos Silva"

    def test_timestamp_converted_to_br_timezone(self):
        utc_date = datetime(2024, 10, 15, 18, 0, 0, tzinfo=timezone.utc)
        msg = self._make_telegram_message(date=utc_date)

        result = telegram_message_to_dataclass(msg)
        assert result is not None
        # UTC 18:00 -> BR (UTC-3) 15:00
        assert result.timestamp.hour == 15
        assert result.timestamp.tzinfo is None  # naive datetime

    def test_user_with_no_last_name(self):
        msg = self._make_telegram_message(first_name="Ana", last_name=None)
        msg.from_user.full_name = "Ana"
        msg.from_user.last_name = None

        result = telegram_message_to_dataclass(msg)
        assert result is not None
        assert result.author == "Ana"

    def test_no_from_user_falls_back_to_unknown(self):
        msg = self._make_telegram_message()
        msg.from_user = None

        result = telegram_message_to_dataclass(msg)
        assert result is not None
        assert result.author == "Unknown"


# ---------------------------------------------------------------------------
# handle_new_message tests
# ---------------------------------------------------------------------------

class TestHandleNewMessage:
    """Tests for the async handler that captures messages."""

    def _make_update_and_context(
        self,
        text: str = "Boa noite",
        user_id: int = 100,
        bot_id: int = 999,
        first_name: str = "User",
    ) -> tuple[MagicMock, MagicMock]:
        """Create mock Update and Context for testing."""
        update = MagicMock(spec=["message"])
        message = MagicMock()
        message.message_id = 1
        message.text = text
        message.date = datetime(2024, 10, 15, 20, 0, 0, tzinfo=timezone.utc)
        message.reply_to_message = None
        message.forward_date = None
        message.forward_from = None

        from_user = MagicMock()
        from_user.id = user_id
        from_user.first_name = first_name
        from_user.last_name = None
        from_user.full_name = first_name
        message.from_user = from_user

        update.message = message

        context = MagicMock()
        bot = MagicMock()
        bot.id = bot_id
        context.bot = bot

        return update, context

    @pytest.mark.asyncio
    async def test_message_added_to_buffer(self):
        """Regular text messages should be added to the buffer."""
        update, context = self._make_update_and_context(text="Boa noite galera")
        buf = MessageBuffer(batch_threshold=100)

        with patch("bot.live_ingest._get_buffer", return_value=buf):
            await handle_new_message(update, context)

        assert buf.size == 1
        flushed = buf.flush()
        assert flushed[0].text == "Boa noite galera"
        assert flushed[0].author == "User"

    @pytest.mark.asyncio
    async def test_bot_own_messages_ignored(self):
        """Messages from the bot itself should be ignored."""
        update, context = self._make_update_and_context(user_id=999, bot_id=999)
        buf = MessageBuffer(batch_threshold=100)

        with patch("bot.live_ingest._get_buffer", return_value=buf):
            await handle_new_message(update, context)

        assert buf.is_empty

    @pytest.mark.asyncio
    async def test_none_message_ignored(self):
        """Update with no message should be silently ignored."""
        update = MagicMock()
        update.message = None
        context = MagicMock()
        buf = MessageBuffer(batch_threshold=100)

        with patch("bot.live_ingest._get_buffer", return_value=buf):
            await handle_new_message(update, context)

        assert buf.is_empty

    @pytest.mark.asyncio
    async def test_threshold_triggers_flush(self):
        """When batch threshold is reached, flush should be called."""
        buf = MessageBuffer(batch_threshold=2)

        with patch("bot.live_ingest._get_buffer", return_value=buf), \
             patch("bot.live_ingest._flush_buffer", new_callable=AsyncMock) as mock_flush:

            # First message: no flush
            update1, ctx1 = self._make_update_and_context(text="Msg 1")
            update1.message.message_id = 1
            await handle_new_message(update1, ctx1)
            mock_flush.assert_not_called()

            # Second message: triggers flush
            update2, ctx2 = self._make_update_and_context(text="Msg 2")
            update2.message.message_id = 2
            await handle_new_message(update2, ctx2)
            mock_flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# _ingest_batch tests
# ---------------------------------------------------------------------------

class TestIngestBatch:
    """Tests for the batch ingestion function."""

    def test_empty_batch_returns_zero(self):
        assert _ingest_batch([]) == 0

    @patch("bot.live_ingest.chromadb")
    @patch("bot.live_ingest.embed_texts")
    def test_ingest_batch_calls_embed_and_chromadb(self, mock_embed, mock_chromadb):
        """Verify that _ingest_batch chunks, embeds, and inserts."""
        # Setup mocks
        mock_embed.return_value = [[0.1] * 1024]  # One embedding vector

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        messages = [
            TelegramMessage(
                id=1,
                author="User",
                timestamp=datetime(2024, 10, 15, 15, 0, 0),
                text="Mensagem de teste para live ingestion",
            ),
        ]

        result = _ingest_batch(messages)

        assert result >= 1
        mock_embed.assert_called_once()
        mock_collection.add.assert_called_once()

        # Verify the inserted data has "source": "live" in metadata
        call_kwargs = mock_collection.add.call_args
        metadatas = call_kwargs.kwargs.get("metadatas") or call_kwargs[1].get("metadatas")
        if metadatas is None and call_kwargs.args:
            # positional fallback
            pass
        else:
            assert any(m.get("source") == "live" for m in metadatas)


# ---------------------------------------------------------------------------
# _flush_buffer tests
# ---------------------------------------------------------------------------

class TestFlushBuffer:
    """Tests for the async flush function."""

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_does_nothing(self):
        """Flushing an empty buffer should not call _ingest_batch."""
        buf = MessageBuffer()

        with patch("bot.live_ingest._get_buffer", return_value=buf), \
             patch("bot.live_ingest._ingest_batch") as mock_ingest:
            await _flush_buffer()
            mock_ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_processes_buffered_messages(self):
        """Flushing a non-empty buffer should call _ingest_batch with messages."""
        buf = MessageBuffer()
        msg = TelegramMessage(
            id=1,
            author="User",
            timestamp=datetime(2024, 10, 15, 15, 0, 0),
            text="Teste",
        )
        buf.add(msg)

        with patch("bot.live_ingest._get_buffer", return_value=buf), \
             patch("bot.live_ingest._ingest_batch", return_value=1) as mock_ingest:
            await _flush_buffer()
            mock_ingest.assert_called_once()
            args = mock_ingest.call_args[0][0]
            assert len(args) == 1
            assert args[0].text == "Teste"

        # Buffer should be empty after flush
        assert buf.is_empty
