"""Response quality feedback with inline buttons.

Provides thumbs up/down buttons for bot responses and logs feedback
to a JSON file for quality tracking.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Default feedback file path
FEEDBACK_DIR = Path(os.getenv("FEEDBACK_DATA_DIR", "data"))
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.json"

# Thread-safe lock for file writes
_file_lock = threading.Lock()

# In-memory mapping of message_id -> query text.
# Callback data has a 64-byte limit so we cannot store the query there.
_message_query_map: dict[int, str] = {}


def create_feedback_keyboard() -> InlineKeyboardMarkup:
    """Return an InlineKeyboardMarkup with thumbs up/down buttons."""
    buttons = [
        [
            InlineKeyboardButton("\U0001f44d", callback_data="feedback_positive"),
            InlineKeyboardButton("\U0001f44e", callback_data="feedback_negative"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def store_query_for_message(message_id: int, query: str) -> None:
    """Store the original query text for a bot response message.

    This allows the feedback handler to look up which query a
    feedback button press corresponds to, since callback_data
    has a 64-byte limit and cannot hold arbitrary query text.
    """
    _message_query_map[message_id] = query


async def handle_feedback_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle feedback button presses (callback queries).

    Acknowledges the callback, removes the buttons, and logs
    the feedback entry to the JSON file.
    """
    query = update.callback_query
    if query is None:
        return

    callback_data = query.data
    if callback_data not in ("feedback_positive", "feedback_negative"):
        return

    feedback_value = (
        "positive" if callback_data == "feedback_positive" else "negative"
    )

    # Acknowledge the button press
    ack_text = (
        "Valeu pelo feedback! \U0001f44d"
        if feedback_value == "positive"
        else "Obrigado pelo feedback! Vou melhorar \U0001f4aa"
    )
    await query.answer(ack_text)

    # Remove the inline keyboard so the user can't click again
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("Could not remove feedback keyboard", exc_info=True)

    # Build the feedback entry
    user = update.effective_user
    message = query.message

    # Look up the original query from our in-memory map
    original_query = _message_query_map.pop(message.message_id, "") if message else ""

    # Preview of the bot response (first 120 chars)
    response_text = message.text if message and message.text else ""
    response_preview = response_text[:120]

    entry: dict[str, Any] = {
        "user_id": user.id if user else 0,
        "user_name": user.first_name if user else "unknown",
        "query": original_query,
        "response_preview": response_preview,
        "feedback": feedback_value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Feedback from %s: %s (query=%r)",
        entry["user_name"],
        feedback_value,
        original_query[:50],
    )

    _save_feedback(entry)


def _save_feedback(entry: dict[str, Any], filepath: Path | None = None) -> None:
    """Append a feedback entry to the JSON file (thread-safe)."""
    target = filepath or FEEDBACK_FILE

    with _file_lock:
        # Ensure directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        # Read existing entries
        entries: list[dict[str, Any]] = []
        if target.exists():
            try:
                raw = target.read_text(encoding="utf-8")
                entries = json.loads(raw) if raw.strip() else []
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not read feedback file, starting fresh")
                entries = []

        entries.append(entry)

        # Write atomically (overwrite with full list)
        target.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def get_feedback_stats(filepath: Path | None = None) -> dict[str, int]:
    """Return counts of positive and negative feedback.

    Returns:
        dict with keys "positive", "negative", and "total".
    """
    target = filepath or FEEDBACK_FILE

    with _file_lock:
        if not target.exists():
            return {"positive": 0, "negative": 0, "total": 0}

        try:
            raw = target.read_text(encoding="utf-8")
            entries = json.loads(raw) if raw.strip() else []
        except (json.JSONDecodeError, OSError):
            return {"positive": 0, "negative": 0, "total": 0}

    positive = sum(1 for e in entries if e.get("feedback") == "positive")
    negative = sum(1 for e in entries if e.get("feedback") == "negative")

    return {
        "positive": positive,
        "negative": negative,
        "total": positive + negative,
    }
