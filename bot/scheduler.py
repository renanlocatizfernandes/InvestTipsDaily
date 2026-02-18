"""Scheduled daily summary for TipsAI bot."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)

# BRT timezone (UTC-3)
BRT = ZoneInfo("America/Sao_Paulo")

# Summary prompt in Brazilian Portuguese
SUMMARY_PROMPT = (
    "Faça um resumo das conversas mais recentes e relevantes do grupo "
    "Invest Tips Daily, destacando os principais assuntos discutidos hoje."
)

# Telegram message length limit
TG_MSG_LIMIT = 4096


async def _send_long_message(
    bot, chat_id: int | str, text: str, message_thread_id: int | None = None
) -> None:
    """Send a message, splitting if it exceeds Telegram's 4096 char limit."""
    if len(text) <= TG_MSG_LIMIT:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            message_thread_id=message_thread_id,
        )
        return

    # Split on paragraph boundaries, fallback to hard split
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= TG_MSG_LIMIT:
            chunks.append(remaining)
            break
        cut = remaining[:TG_MSG_LIMIT].rfind("\n")
        if cut < TG_MSG_LIMIT // 2:
            cut = TG_MSG_LIMIT
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    for chunk in chunks:
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            message_thread_id=message_thread_id,
        )


async def daily_summary_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: generate and send a daily summary to the configured topic."""
    chat_id = context.job.data["chat_id"]
    thread_id = context.job.data["thread_id"]

    logger.info("Running scheduled daily summary (chat=%s, thread=%s)", chat_id, thread_id)

    try:
        from rag.pipeline import query as rag_query

        response = await asyncio.to_thread(rag_query, SUMMARY_PROMPT)
        await _send_long_message(
            context.bot,
            chat_id=chat_id,
            text=response,
            message_thread_id=thread_id,
        )
        logger.info("Daily summary sent successfully (%d chars)", len(response))
    except Exception:
        logger.exception("Failed to send daily summary")


def setup_scheduler(application: Application) -> None:
    """Register the daily summary job on the application's JobQueue.

    Required environment variables:
        SUMMARY_CHAT_ID   — Telegram chat ID to post in
        SUMMARY_THREAD_ID — Message thread (topic) ID to post in

    Optional:
        SUMMARY_SCHEDULE_HOUR — Hour in BRT (0-23) to run. Default: 20 (8 PM)
    """
    chat_id = os.getenv("SUMMARY_CHAT_ID")
    thread_id = os.getenv("SUMMARY_THREAD_ID")

    if not chat_id or not thread_id:
        logger.warning(
            "Scheduled summary DISABLED: SUMMARY_CHAT_ID and/or SUMMARY_THREAD_ID not set. "
            "Set both environment variables to enable daily summaries."
        )
        return

    # Parse and validate chat_id and thread_id
    try:
        chat_id_int = int(chat_id)
    except ValueError:
        logger.error("SUMMARY_CHAT_ID must be an integer, got: %r", chat_id)
        return

    try:
        thread_id_int = int(thread_id)
    except ValueError:
        logger.error("SUMMARY_THREAD_ID must be an integer, got: %r", thread_id)
        return

    # Parse schedule hour (default 20 = 8 PM BRT)
    hour_str = os.getenv("SUMMARY_SCHEDULE_HOUR", "20")
    try:
        hour = int(hour_str)
        if not 0 <= hour <= 23:
            raise ValueError(f"Hour out of range: {hour}")
    except ValueError:
        logger.error(
            "SUMMARY_SCHEDULE_HOUR must be 0-23, got: %r. Defaulting to 20.", hour_str
        )
        hour = 20

    schedule_time = dt_time(hour=hour, minute=0, second=0, tzinfo=BRT)

    job_queue = application.job_queue
    if job_queue is None:
        logger.error(
            "JobQueue not available. Ensure python-telegram-bot is installed "
            "with job-queue support (pip install 'python-telegram-bot[job-queue]')."
        )
        return

    job_queue.run_daily(
        daily_summary_job,
        time=schedule_time,
        name="daily_summary",
        data={"chat_id": chat_id_int, "thread_id": thread_id_int},
    )

    logger.info(
        "Scheduled daily summary at %02d:00 BRT (chat=%s, thread=%s)",
        hour,
        chat_id_int,
        thread_id_int,
    )
