"""Parse search queries to extract filters (author, date range) from raw text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedQuery:
    """Result of parsing a search query with optional filters."""

    text: str
    author: str | None = None
    date_from: str | None = None
    date_to: str | None = None


# Patterns for recognised filters (case-insensitive).
# Each filter is a keyword followed by a colon and a value (no spaces in value).
_FILTER_PATTERNS: dict[str, re.Pattern] = {
    "author": re.compile(r"\bautor:(\S+)", re.IGNORECASE),
    "date_from": re.compile(r"\bde:(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    "date_to": re.compile(r"\bate:(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
}


def parse_search_query(raw_query: str) -> dict:
    """Extract filters from a query string and return structured result.

    Supported filters (case-insensitive):
      - autor:Name        -> author filter
      - de:YYYY-MM-DD     -> date range start (inclusive)
      - ate:YYYY-MM-DD    -> date range end (inclusive)

    Everything else becomes the semantic search text.

    Examples:
        >>> parse_search_query("autor:Renan bitcoin de:2024-08-01")
        {"text": "bitcoin", "author": "Renan", "date_from": "2024-08-01", "date_to": None}

        >>> parse_search_query("CoinTech2U rendimento")
        {"text": "CoinTech2U rendimento", "author": None, "date_from": None, "date_to": None}
    """
    remaining = raw_query
    author = None
    date_from = None
    date_to = None

    # Extract author filter
    match = _FILTER_PATTERNS["author"].search(remaining)
    if match:
        author = match.group(1)
        remaining = remaining[: match.start()] + remaining[match.end() :]

    # Extract date_from filter
    match = _FILTER_PATTERNS["date_from"].search(remaining)
    if match:
        date_from = match.group(1)
        remaining = remaining[: match.start()] + remaining[match.end() :]

    # Extract date_to filter
    match = _FILTER_PATTERNS["date_to"].search(remaining)
    if match:
        date_to = match.group(1)
        remaining = remaining[: match.start()] + remaining[match.end() :]

    # Clean up leftover whitespace
    text = " ".join(remaining.split()).strip()

    return {
        "text": text,
        "author": author,
        "date_from": date_from,
        "date_to": date_to,
    }
