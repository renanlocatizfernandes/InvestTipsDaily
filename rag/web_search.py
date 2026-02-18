"""Web search for real-time data (prices, news, market info)."""

from __future__ import annotations

import logging
import re

from ddgs import DDGS

logger = logging.getLogger(__name__)

# Keywords that suggest the question needs current/real-time data
_REALTIME_KEYWORDS = [
    # Price/value
    r"\bpreço\b", r"\bcotação\b", r"\bcotacao\b", r"\bvale\b",
    r"\bquanto\s+(tá|está|custa|vale)\b",
    # Temporal
    r"\bhoje\b", r"\bagora\b", r"\batual\b", r"\batualmente\b",
    r"\besta\s+semana\b", r"\beste\s+mês\b",
    # Market movements
    r"\bmercado\b", r"\balta\b", r"\bqueda\b", r"\bcaiu\b", r"\bsubiu\b",
    r"\bbull\b", r"\bbear\b", r"\brally\b", r"\bcrash\b", r"\bdump\b", r"\bpump\b",
    # News
    r"\bnotícia\b", r"\bnoticia\b", r"\bnews\b", r"\bnovidade\b",
    # Market metrics
    r"\bmarket\s?cap\b", r"\bvolume\b", r"\bliquidez\b",
    r"\bdominância\b", r"\bdominancia\b",
    # Predictions
    r"\bprevisão\b", r"\bprevisao\b", r"\bperspectiva\b",
    # Crypto tickers
    r"\bbtc\b", r"\beth\b", r"\bsol\b", r"\bada\b", r"\bxrp\b",
    r"\bbnb\b", r"\bdoge\b", r"\bmatic\b", r"\bdot\b", r"\bavax\b",
    r"\bbitcoin\b", r"\bethereum\b", r"\bsolana\b", r"\bcardano\b", r"\bripple\b",
    # Regulation/events
    r"\bregulação\b", r"\bregulamentação\b", r"\bsec\b", r"\betf\b",
    r"\bhalving\b", r"\bfed\b", r"\bselic\b",
]

_REALTIME_PATTERN = re.compile("|".join(_REALTIME_KEYWORDS), re.IGNORECASE)


def needs_realtime_data(question: str) -> bool:
    """Check if a question likely needs current/real-time information."""
    return bool(_REALTIME_PATTERN.search(question))


def _optimize_query(question: str) -> str:
    """Optimize search query for better crypto/finance results."""
    # Add context if not already crypto-specific
    lower = question.lower()
    has_crypto_term = any(t in lower for t in [
        "bitcoin", "ethereum", "cripto", "crypto", "btc", "eth", "defi",
        "blockchain", "token", "moeda", "coin",
    ])
    if has_crypto_term:
        return f"{question} preço cotação hoje"
    return f"{question} cripto investimento"


def web_search(query: str, max_results: int = 3) -> str:
    """Search the web and return formatted results.

    Returns a formatted string with search results, or empty string on failure.
    """
    optimized = _optimize_query(query)
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(optimized, region="br-pt", max_results=max_results))

        if not results:
            return ""

        parts = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            parts.append(f"- {title}: {body}")

        return "\n".join(parts)
    except Exception:
        logger.exception("Web search failed for query: %s", optimized)
        return ""
