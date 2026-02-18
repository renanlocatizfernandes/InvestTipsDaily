"""Health monitoring and metrics for TipsAI bot."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class Metrics:
    """Singleton that tracks bot performance metrics.

    Thread-safe counters for queries, latency, errors, and uptime.
    """

    _instance: Metrics | None = None
    _lock = threading.Lock()

    def __new__(cls) -> Metrics:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init_metrics()
                    cls._instance = instance
        return cls._instance

    def _init_metrics(self) -> None:
        """Initialize all metric counters."""
        self._start_time: float = time.monotonic()
        self._start_datetime: datetime = datetime.now(timezone.utc)
        self._total_queries: int = 0
        self._total_latency: float = 0.0
        self._error_count: int = 0
        self._last_query_time: float | None = None
        self._metrics_lock = threading.Lock()

    def record_query(self, latency_seconds: float) -> None:
        """Record a successfully processed query with its latency.

        Args:
            latency_seconds: Time in seconds the query took to process.
        """
        with self._metrics_lock:
            self._total_queries += 1
            self._total_latency += latency_seconds
            self._last_query_time = time.monotonic()

    def record_error(self) -> None:
        """Record an error occurrence."""
        with self._metrics_lock:
            self._error_count += 1

    @property
    def uptime_seconds(self) -> float:
        """Return uptime in seconds since metrics were initialized."""
        return time.monotonic() - self._start_time

    def get_status(self) -> dict:
        """Return a snapshot of all current metrics.

        Returns:
            Dict with keys: uptime_seconds, total_queries, avg_latency,
            error_count, last_query_seconds_ago, start_datetime.
        """
        with self._metrics_lock:
            avg_latency = (
                self._total_latency / self._total_queries
                if self._total_queries > 0
                else 0.0
            )
            last_query_ago = (
                time.monotonic() - self._last_query_time
                if self._last_query_time is not None
                else None
            )
            return {
                "uptime_seconds": self.uptime_seconds,
                "total_queries": self._total_queries,
                "avg_latency": round(avg_latency, 2),
                "error_count": self._error_count,
                "last_query_seconds_ago": (
                    round(last_query_ago, 1) if last_query_ago is not None else None
                ),
                "start_datetime": self._start_datetime.isoformat(),
            }

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._init_metrics()


# Module-level singleton instance for easy imports
metrics = Metrics()


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable pt-BR string."""
    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}min")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _get_chromadb_count() -> int | None:
    """Get the number of documents in the ChromaDB collection.

    Returns:
        Document count or None if collection is unavailable.
    """
    try:
        from rag.pipeline import _get_collection

        collection = _get_collection()
        if collection is not None:
            return collection.count()
    except Exception:
        logger.debug("Could not get ChromaDB count", exc_info=True)
    return None


def _get_embedding_status() -> str:
    """Check if the embedding model is loaded.

    Returns:
        Status string in pt-BR.
    """
    try:
        from rag.embedder import _model

        if _model is not None:
            return "carregado"
        return "nao carregado"
    except Exception:
        return "indisponivel"


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health command — display bot health and metrics."""
    status = metrics.get_status()

    uptime_str = _format_uptime(status["uptime_seconds"])
    avg_latency_str = f'{status["avg_latency"]:.1f}s'
    total_queries = status["total_queries"]
    error_count = status["error_count"]

    # Get ChromaDB info
    chroma_count = _get_chromadb_count()
    chroma_str = f"{chroma_count:,} chunks".replace(",", ".") if chroma_count is not None else "indisponivel"

    # Get embedding model status
    model_status = _get_embedding_status()

    text = (
        "\U0001f3e5 *Status do TipsAI*\n\n"
        f"\u23f1 *Uptime:* {uptime_str}\n"
        f"\U0001f4ca *Consultas:* {total_queries}\n"
        f"\u26a1 *Latencia media:* {avg_latency_str}\n"
        f"\u274c *Erros:* {error_count}\n"
        f"\U0001f4be *ChromaDB:* {chroma_str}\n"
        f"\U0001f9e0 *Modelo:* {model_status}"
    )

    await update.message.reply_text(text, parse_mode="Markdown")
