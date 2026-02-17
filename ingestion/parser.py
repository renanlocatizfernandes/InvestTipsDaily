"""Parser for Telegram Desktop HTML chat exports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag


@dataclass
class TelegramMessage:
    """A single parsed Telegram message."""

    id: int
    author: str
    timestamp: datetime
    text: str
    reply_to_id: int | None = None
    media_type: str | None = None  # "photo", "video", "voice", "sticker", "file"
    media_path: str | None = None
    is_forwarded: bool = False
    forwarded_from: str | None = None


def _extract_message_id(div: Tag) -> int | None:
    """Extract numeric message ID from the div's id attribute."""
    raw = div.get("id", "")
    match = re.search(r"message(-?\d+)", raw)
    return int(match.group(1)) if match else None


def _parse_timestamp(div: Tag) -> datetime | None:
    """Parse timestamp from the date details div's title attribute."""
    date_div = div.select_one(".pull_right.date.details")
    if date_div is None:
        return None
    title = date_div.get("title", "")
    # Format: "17.08.2024 14:34:09 UTC-03:00"
    match = re.match(r"(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2})", title)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d.%m.%Y %H:%M:%S")


def _parse_author(div: Tag) -> str | None:
    """Extract author name from .from_name div (direct child of .body, not forwarded)."""
    body = div.select_one(":scope > .body")
    if body is None:
        return None
    from_name = body.select_one(":scope > .from_name")
    if from_name is None:
        return None
    return from_name.get_text(strip=True)


def _parse_text(div: Tag) -> str:
    """Extract text content from the message."""
    # Get text from main body, not from forwarded body
    body = div.select_one(":scope > .body")
    if body is None:
        return ""
    # Check for forwarded content
    forwarded_body = body.select_one(".forwarded.body")
    text_div = body.select_one(":scope > .text")
    if text_div is None and forwarded_body:
        text_div = forwarded_body.select_one(".text")
    if text_div is None:
        return ""
    return text_div.get_text(strip=True)


def _parse_reply_to(div: Tag) -> int | None:
    """Extract reply-to message ID from reply_to div."""
    reply_div = div.select_one(".reply_to")
    if reply_div is None:
        return None
    link = reply_div.select_one("a")
    if link is None:
        return None
    onclick = link.get("onclick", "")
    match = re.search(r"GoToMessage\((\d+)\)", onclick)
    if match:
        return int(match.group(1))
    # Also check href for cross-file references: messages2.html#go_to_message123
    href = link.get("href", "")
    match = re.search(r"go_to_message(\d+)", href)
    return int(match.group(1)) if match else None


def _parse_media(div: Tag) -> tuple[str | None, str | None]:
    """Extract media type and path."""
    media_wrap = div.select_one(".media_wrap")
    if media_wrap is None:
        return None, None

    # Photo
    photo = media_wrap.select_one("a.photo_wrap")
    if photo:
        return "photo", photo.get("href")

    # Video
    video = media_wrap.select_one("a.video_file_wrap")
    if video:
        return "video", video.get("href")

    # Voice message
    voice = media_wrap.select_one("a.media_voice_message")
    if voice:
        return "voice", voice.get("href")

    # Sticker
    sticker = media_wrap.select_one(".sticker_wrap")
    if sticker:
        return "sticker", None

    # Generic file/document
    doc = media_wrap.select_one("a.media_file")
    if doc:
        return "file", doc.get("href")

    return None, None


def _is_forwarded(div: Tag) -> tuple[bool, str | None]:
    """Check if message is forwarded and extract original author."""
    forwarded_body = div.select_one(".forwarded.body")
    if forwarded_body is None:
        return False, None
    from_name = forwarded_body.select_one(".from_name")
    if from_name:
        # Remove the date span if present
        name_text = from_name.get_text(strip=True)
        # Strip appended date like "22.08.2024 08:53:42"
        name_text = re.sub(r"\s*\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}$", "", name_text)
        return True, name_text.strip() or None
    return True, None


def parse_html_file(filepath: str | Path) -> list[TelegramMessage]:
    """Parse a single Telegram export HTML file and return messages."""
    filepath = Path(filepath)
    html = filepath.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    messages: list[TelegramMessage] = []
    current_author: str | None = None

    for div in soup.select("div.message.default"):
        msg_id = _extract_message_id(div)
        if msg_id is None:
            continue

        # "joined" messages inherit author from previous non-joined message
        author = _parse_author(div)
        is_joined = "joined" in div.get("class", [])
        if author:
            current_author = author
        elif is_joined and current_author:
            author = current_author
        else:
            author = "Unknown"

        timestamp = _parse_timestamp(div)
        if timestamp is None:
            continue

        text = _parse_text(div)
        reply_to = _parse_reply_to(div)
        media_type, media_path = _parse_media(div)
        is_fwd, fwd_from = _is_forwarded(div)

        messages.append(
            TelegramMessage(
                id=msg_id,
                author=author,
                timestamp=timestamp,
                text=text,
                reply_to_id=reply_to,
                media_type=media_type,
                media_path=media_path,
                is_forwarded=is_fwd,
                forwarded_from=fwd_from,
            )
        )

    return messages


def parse_all_exports(export_dir: str | Path) -> list[TelegramMessage]:
    """Parse all messages*.html files in a directory, sorted by message ID."""
    export_dir = Path(export_dir)
    html_files = sorted(export_dir.glob("messages*.html"))
    all_messages: list[TelegramMessage] = []
    for f in html_files:
        all_messages.extend(parse_html_file(f))
    all_messages.sort(key=lambda m: m.id)
    return all_messages
