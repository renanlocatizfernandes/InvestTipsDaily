"""Tests for the scheduled daily summary."""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from bot.scheduler import (
    BRT,
    SUMMARY_PROMPT,
    TG_MSG_LIMIT,
    daily_summary_job,
    setup_scheduler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_application():
    """Create a mock Application with a mock JobQueue."""
    app = MagicMock()
    app.job_queue = MagicMock()
    app.job_queue.run_daily = MagicMock()
    return app


def _ensure_rag_pipeline_mock():
    """Ensure rag.pipeline is importable even without chromadb.

    Injects a mock module into sys.modules so that the lazy
    ``from rag.pipeline import query`` inside daily_summary_job works.
    Returns the mock module so callers can configure ``query``.
    """
    mock_pipeline = types.ModuleType("rag.pipeline")
    mock_pipeline.query = MagicMock(return_value="mock response")

    # Ensure parent package exists too
    if "rag" not in sys.modules:
        mock_rag = types.ModuleType("rag")
        sys.modules["rag"] = mock_rag
    sys.modules["rag.pipeline"] = mock_pipeline
    return mock_pipeline


# ---------------------------------------------------------------------------
# setup_scheduler tests
# ---------------------------------------------------------------------------


class TestSetupScheduler:
    """Tests for setup_scheduler configuration logic."""

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "-1001234567890",
        "SUMMARY_THREAD_ID": "42",
    }, clear=False)
    def test_registers_job_with_defaults(self):
        """With valid env vars, scheduler registers a daily job at 20:00 BRT."""
        app = _make_application()
        setup_scheduler(app)

        app.job_queue.run_daily.assert_called_once()
        call_kwargs = app.job_queue.run_daily.call_args
        assert call_kwargs.kwargs["name"] == "daily_summary"

        scheduled_time = call_kwargs.kwargs["time"]
        assert scheduled_time.hour == 20
        assert scheduled_time.minute == 0
        assert scheduled_time.tzinfo == BRT

        data = call_kwargs.kwargs["data"]
        assert data["chat_id"] == -1001234567890
        assert data["thread_id"] == 42

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "-1001234567890",
        "SUMMARY_THREAD_ID": "42",
        "SUMMARY_SCHEDULE_HOUR": "9",
    }, clear=False)
    def test_custom_hour(self):
        """SUMMARY_SCHEDULE_HOUR overrides the default 20:00."""
        app = _make_application()
        setup_scheduler(app)

        scheduled_time = app.job_queue.run_daily.call_args.kwargs["time"]
        assert scheduled_time.hour == 9

    @patch.dict("os.environ", {}, clear=True)
    def test_disabled_when_no_env_vars(self):
        """Scheduler is not registered when env vars are missing."""
        app = _make_application()
        setup_scheduler(app)
        app.job_queue.run_daily.assert_not_called()

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "-1001234567890",
    }, clear=True)
    def test_disabled_when_thread_id_missing(self):
        """Scheduler is not registered when SUMMARY_THREAD_ID is missing."""
        app = _make_application()
        setup_scheduler(app)
        app.job_queue.run_daily.assert_not_called()

    @patch.dict("os.environ", {
        "SUMMARY_THREAD_ID": "42",
    }, clear=True)
    def test_disabled_when_chat_id_missing(self):
        """Scheduler is not registered when SUMMARY_CHAT_ID is missing."""
        app = _make_application()
        setup_scheduler(app)
        app.job_queue.run_daily.assert_not_called()

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "not-a-number",
        "SUMMARY_THREAD_ID": "42",
    }, clear=False)
    def test_invalid_chat_id(self):
        """Non-integer SUMMARY_CHAT_ID prevents registration."""
        app = _make_application()
        setup_scheduler(app)
        app.job_queue.run_daily.assert_not_called()

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "-1001234567890",
        "SUMMARY_THREAD_ID": "abc",
    }, clear=False)
    def test_invalid_thread_id(self):
        """Non-integer SUMMARY_THREAD_ID prevents registration."""
        app = _make_application()
        setup_scheduler(app)
        app.job_queue.run_daily.assert_not_called()

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "-1001234567890",
        "SUMMARY_THREAD_ID": "42",
        "SUMMARY_SCHEDULE_HOUR": "25",
    }, clear=False)
    def test_invalid_hour_falls_back_to_default(self):
        """Invalid hour value falls back to 20."""
        app = _make_application()
        setup_scheduler(app)

        scheduled_time = app.job_queue.run_daily.call_args.kwargs["time"]
        assert scheduled_time.hour == 20

    @patch.dict("os.environ", {
        "SUMMARY_CHAT_ID": "-1001234567890",
        "SUMMARY_THREAD_ID": "42",
    }, clear=False)
    def test_no_job_queue(self):
        """Handles gracefully when job_queue is None."""
        app = MagicMock()
        app.job_queue = None
        # Should not raise
        setup_scheduler(app)


# ---------------------------------------------------------------------------
# daily_summary_job tests
# ---------------------------------------------------------------------------


class TestDailySummaryJob:
    """Tests for the daily_summary_job callback."""

    @pytest.mark.asyncio
    async def test_sends_summary(self):
        """Job generates and sends summary to the configured chat/topic."""
        mock_pipeline = _ensure_rag_pipeline_mock()
        mock_pipeline.query = MagicMock(return_value="Resumo do dia.")

        context = MagicMock()
        context.bot = AsyncMock()
        context.job = MagicMock()
        context.job.data = {"chat_id": -100123, "thread_id": 7}

        await daily_summary_job(context)

        context.bot.send_message.assert_called_once_with(
            chat_id=-100123,
            text="Resumo do dia.",
            message_thread_id=7,
        )

    @pytest.mark.asyncio
    async def test_handles_rag_error(self):
        """Job catches exceptions from RAG pipeline and does not crash."""
        mock_pipeline = _ensure_rag_pipeline_mock()
        mock_pipeline.query = MagicMock(side_effect=RuntimeError("model error"))

        context = MagicMock()
        context.bot = AsyncMock()
        context.job = MagicMock()
        context.job.data = {"chat_id": -100123, "thread_id": 7}

        # Should not raise
        await daily_summary_job(context)

        # No message should be sent on error
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_splits_long_message(self):
        """Job splits messages that exceed Telegram's 4096 char limit."""
        long_text = "A" * (TG_MSG_LIMIT + 100)
        mock_pipeline = _ensure_rag_pipeline_mock()
        mock_pipeline.query = MagicMock(return_value=long_text)

        context = MagicMock()
        context.bot = AsyncMock()
        context.job = MagicMock()
        context.job.data = {"chat_id": -100123, "thread_id": 7}

        await daily_summary_job(context)

        assert context.bot.send_message.call_count == 2


# ---------------------------------------------------------------------------
# SUMMARY_PROMPT content test
# ---------------------------------------------------------------------------


def test_summary_prompt_is_portuguese():
    """The summary prompt must be in Portuguese."""
    assert "resumo" in SUMMARY_PROMPT.lower()
    assert "Invest Tips Daily" in SUMMARY_PROMPT
