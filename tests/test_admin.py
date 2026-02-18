"""Tests for admin commands (admin check, stats formatting, config masking)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.admin import (
    admin_only,
    _mask_key,
    _format_size,
    get_config,
    get_stats,
)


# ---------------------------------------------------------------------------
# Helpers to build fake Telegram objects
# ---------------------------------------------------------------------------

def _make_update(chat_type: str = "supergroup", member_status: str = "administrator"):
    """Create a mock Update with configurable chat type and member status."""
    update = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 123
    update.effective_user.first_name = "TestUser"
    update.effective_chat = AsyncMock()
    update.effective_chat.type = chat_type
    update.message = AsyncMock()

    member = MagicMock()
    member.status = member_status
    update.effective_chat.get_member = AsyncMock(return_value=member)

    return update


def _make_context():
    """Create a mock context."""
    return AsyncMock()


# ---------------------------------------------------------------------------
# Tests for admin_only decorator
# ---------------------------------------------------------------------------

class TestAdminOnly:
    """Tests for the admin_only decorator."""

    @pytest.mark.asyncio
    async def test_allows_group_admin(self):
        """Admin users can execute the command."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update(chat_type="supergroup", member_status="administrator")
        context = _make_context()
        await dummy_handler(update, context)
        assert handler_called

    @pytest.mark.asyncio
    async def test_allows_group_creator(self):
        """Group creator (owner) can execute the command."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update(chat_type="supergroup", member_status="creator")
        context = _make_context()
        await dummy_handler(update, context)
        assert handler_called

    @pytest.mark.asyncio
    async def test_blocks_regular_member(self):
        """Regular members are blocked with a Portuguese message."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update(chat_type="supergroup", member_status="member")
        context = _make_context()
        await dummy_handler(update, context)
        assert not handler_called
        update.message.reply_text.assert_called_once_with(
            "Apenas administradores podem usar este comando."
        )

    @pytest.mark.asyncio
    async def test_blocks_restricted_user(self):
        """Restricted users are blocked."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update(chat_type="supergroup", member_status="restricted")
        context = _make_context()
        await dummy_handler(update, context)
        assert not handler_called

    @pytest.mark.asyncio
    async def test_allows_private_chat(self):
        """Private chats always pass (for testing convenience)."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update(chat_type="private")
        context = _make_context()
        await dummy_handler(update, context)
        assert handler_called

    @pytest.mark.asyncio
    async def test_handles_get_member_failure(self):
        """Gracefully handles failure to check admin status."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update(chat_type="supergroup")
        update.effective_chat.get_member = AsyncMock(side_effect=Exception("API error"))
        context = _make_context()
        await dummy_handler(update, context)
        assert not handler_called
        update.message.reply_text.assert_called_once_with(
            "Nao consegui verificar suas permissoes. Tenta de novo."
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_message(self):
        """Does nothing when update.message is None."""
        handler_called = False

        @admin_only
        async def dummy_handler(update, context):
            nonlocal handler_called
            handler_called = True

        update = _make_update()
        update.message = None
        context = _make_context()
        await dummy_handler(update, context)
        assert not handler_called


# ---------------------------------------------------------------------------
# Tests for _mask_key
# ---------------------------------------------------------------------------

class TestMaskKey:
    """Tests for API key masking."""

    def test_mask_long_key(self):
        result = _mask_key("sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890")
        assert result.startswith("sk-ant-a")
        assert result.endswith("7890")
        assert "..." in result
        # Must not contain the full key
        assert "abcdefghijklmnopqrstuvwxyz" not in result

    def test_mask_short_key(self):
        result = _mask_key("shortkey")
        assert result == "****"

    def test_mask_exactly_16_chars(self):
        result = _mask_key("1234567890123456")
        assert result == "****"

    def test_mask_17_chars(self):
        result = _mask_key("12345678901234567")
        assert result == "12345678...4567"


# ---------------------------------------------------------------------------
# Tests for _format_size
# ---------------------------------------------------------------------------

class TestFormatSize:
    """Tests for human-readable size formatting."""

    def test_bytes(self):
        assert _format_size(512) == "512 B"

    def test_kilobytes(self):
        assert _format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert _format_size(2 * 1024 * 1024 * 1024) == "2.0 GB"

    def test_zero(self):
        assert _format_size(0) == "0 B"


# ---------------------------------------------------------------------------
# Tests for get_config
# ---------------------------------------------------------------------------

class TestGetConfig:
    """Tests for configuration display."""

    def test_shows_model_info(self):
        with patch.dict(os.environ, {
            "CLAUDE_MODEL": "claude-haiku-4-5-20251001",
            "EMBEDDING_MODEL": "intfloat/multilingual-e5-large",
            "CHROMA_DB_PATH": "/data/chroma_db",
            "TELEGRAM_EXPORT_PATH": "/data/exports",
            "LOG_LEVEL": "INFO",
            "ANTHROPIC_API_KEY": "",
            "TELEGRAM_BOT_TOKEN": "",
        }):
            config = get_config()
            assert "claude-haiku-4-5-20251001" in config
            assert "intfloat/multilingual-e5-large" in config
            assert "/data/chroma_db" in config

    def test_masks_api_key(self):
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-ant-api03-verylongsecretkeythatmustbemasked",
            "TELEGRAM_BOT_TOKEN": "1234567890:ABCDefghIJKLmnopQRSTuvwxyz1234567",
        }):
            config = get_config()
            # Full key must NOT be present
            assert "verylongsecretkeythatmustbemasked" not in config
            assert "ABCDefghIJKLmnopQRSTuvwxyz1234567" not in config
            # But masked version should be there
            assert "..." in config

    def test_handles_missing_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()
            assert "(nao configurada)" in config
            assert "(nao configurado)" in config


# ---------------------------------------------------------------------------
# Tests for get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    """Tests for stats formatting."""

    def test_stats_with_data(self, tmp_path):
        """Stats correctly reports chunk count, processed msgs, and top authors."""
        # Create a fake processed_ids.json
        processed_ids = list(range(100))
        ids_file = tmp_path / "processed_ids.json"
        ids_file.write_text(json.dumps(processed_ids))

        # Mock ChromaDB
        mock_collection = MagicMock()
        mock_collection.count.return_value = 50
        mock_collection.get.return_value = {
            "metadatas": [
                {"authors": '["Alice"]', "message_count": 30},
                {"authors": '["Bob"]', "message_count": 20},
                {"authors": '["Alice", "Charlie"]', "message_count": 10},
            ]
        }

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection

        with patch.dict(os.environ, {"CHROMA_DB_PATH": str(tmp_path)}), \
             patch("bot.admin.chromadb") as mock_chromadb:
            mock_chromadb.PersistentClient.return_value = mock_client

            stats = get_stats()

        assert "Chunks no ChromaDB: 50" in stats
        assert "Mensagens processadas: 100" in stats
        assert "Alice" in stats
        assert "Bob" in stats

    def test_stats_empty_db(self, tmp_path):
        """Stats handles an empty database gracefully."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_collection

        with patch.dict(os.environ, {"CHROMA_DB_PATH": str(tmp_path)}), \
             patch("bot.admin.chromadb") as mock_chromadb:
            mock_chromadb.PersistentClient.return_value = mock_client

            stats = get_stats()

        assert "Chunks no ChromaDB: 0" in stats
        assert "Mensagens processadas: 0" in stats

    def test_stats_db_error(self, tmp_path):
        """Stats handles ChromaDB errors gracefully."""
        with patch.dict(os.environ, {"CHROMA_DB_PATH": str(tmp_path)}), \
             patch("bot.admin.chromadb") as mock_chromadb:
            mock_chromadb.PersistentClient.side_effect = Exception("DB error")

            stats = get_stats()

        # Should still produce output (with 0 chunks)
        assert "Chunks no ChromaDB: 0" in stats
