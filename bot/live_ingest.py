"""Live ingestion: capture new group messages and ingest into ChromaDB in real-time."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from ingestion.chunker import chunk_messages
from ingestion.parser import TelegramMessage
from rag.embedder import embed_texts

import chromadb

logger = logging.getLogger(__name__)

# Buffer configuration
BATCH_THRESHOLD = int(os.getenv("LIVE_INGEST_BATCH_SIZE", "10"))
FLUSH_INTERVAL_SECONDS = int(os.getenv("LIVE_INGEST_FLUSH_SECONDS", "300"))  # 5 minutes

COLLECTION_NAME = "telegram_messages"

# Brazil timezone offset (UTC-3)
_BR_TZ = timezone(timedelta(hours=-3))


class MessageBuffer:
    """Thread-safe buffer for accumulating messages before ingestion."""

    def __init__(
        self,
        batch_threshold: int = BATCH_THRESHOLD,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
    ):
        self._lock = threading.Lock()
        self._messages: list[TelegramMessage] = []
        self._first_message_time: float | None = None
        self.batch_threshold = batch_threshold
        self.flush_interval = flush_interval

    def add(self, msg: TelegramMessage) -> bool:
        """Add a message to the buffer.

        Returns True if the buffer should be flushed (threshold reached).
        """
        with self._lock:
            if not self._messages:
                self._first_message_time = time.monotonic()
            self._messages.append(msg)
            return len(self._messages) >= self.batch_threshold

    def should_flush_by_time(self) -> bool:
        """Check if enough time has elapsed since the first buffered message."""
        with self._lock:
            if not self._messages or self._first_message_time is None:
                return False
            return (time.monotonic() - self._first_message_time) >= self.flush_interval

    def flush(self) -> list[TelegramMessage]:
        """Return all buffered messages and clear the buffer."""
        with self._lock:
            messages = self._messages.copy()
            self._messages.clear()
            self._first_message_time = None
            return messages

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._messages)

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return len(self._messages) == 0


# Module-level buffer instance
_buffer = MessageBuffer()


def _get_buffer() -> MessageBuffer:
    """Get the global message buffer (allows replacement in tests)."""
    return _buffer


def telegram_message_to_dataclass(message) -> TelegramMessage | None:
    """Convert a python-telegram-bot Message object to our TelegramMessage dataclass.

    Returns None if the message cannot be converted (e.g. no text).
    """
    if message is None or not message.text:
        return None

    # Use the message date, fall back to now in BR timezone
    if message.date:
        timestamp = message.date.astimezone(_BR_TZ).replace(tzinfo=None)
    else:
        timestamp = datetime.now(_BR_TZ).replace(tzinfo=None)

    author = "Unknown"
    if message.from_user:
        author = message.from_user.full_name or message.from_user.first_name or "Unknown"

    reply_to_id = None
    if message.reply_to_message:
        reply_to_id = message.reply_to_message.message_id

    is_forwarded = message.forward_date is not None
    forwarded_from = None
    if is_forwarded and message.forward_from:
        forwarded_from = message.forward_from.full_name or message.forward_from.first_name

    return TelegramMessage(
        id=message.message_id,
        author=author,
        timestamp=timestamp,
        text=message.text,
        reply_to_id=reply_to_id,
        media_type=None,
        media_path=None,
        is_forwarded=is_forwarded,
        forwarded_from=forwarded_from,
    )


def _ingest_batch(messages: list[TelegramMessage]) -> int:
    """Chunk, embed, and insert a batch of messages into ChromaDB.

    Returns the number of chunks inserted.
    """
    if not messages:
        return 0

    # Chunk
    chunks = chunk_messages(messages)
    if not chunks:
        logger.info("Nenhum chunk gerado para o batch de %d mensagens.", len(messages))
        return 0

    # Embed
    texts = [c.text for c in chunks]
    logger.info("Gerando embeddings para %d chunks (live ingestion)...", len(texts))
    embeddings = embed_texts(texts)

    # Insert into ChromaDB
    db_path = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    existing_count = collection.count()
    timestamp_tag = datetime.now().strftime("%Y%m%d%H%M%S")

    ids = []
    metadatas = []
    documents = []
    for i, chunk in enumerate(chunks):
        doc_id = f"live_{timestamp_tag}_{existing_count + i}"
        ids.append(doc_id)
        documents.append(chunk.text)
        metadatas.append({
            "authors": json.dumps(chunk.authors, ensure_ascii=False),
            "start_time": chunk.start_time,
            "end_time": chunk.end_time,
            "message_ids": json.dumps(chunk.message_ids),
            "message_count": chunk.metadata["message_count"],
            "source": "live",
        })

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    logger.info(
        "Live ingestion: %d chunks inseridos (%d mensagens). Total no DB: %d.",
        len(chunks),
        len(messages),
        collection.count(),
    )
    return len(chunks)


async def _flush_buffer() -> None:
    """Flush the buffer: chunk, embed, and store in ChromaDB."""
    buf = _get_buffer()
    messages = buf.flush()
    if not messages:
        return

    logger.info("Flush do buffer: processando %d mensagens...", len(messages))
    try:
        inserted = await asyncio.to_thread(_ingest_batch, messages)
        logger.info("Flush concluído: %d chunks inseridos.", inserted)
    except Exception:
        logger.exception("Erro ao processar batch de live ingestion")


async def handle_new_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture a new group text message and buffer it for ingestion.

    This handler runs at low priority (group=2) so it does not interfere
    with command or mention handlers.
    """
    if update.message is None:
        return

    message = update.message

    # Ignore bot's own messages
    if message.from_user and context.bot and message.from_user.id == context.bot.id:
        return

    # Convert to our dataclass
    tg_msg = telegram_message_to_dataclass(message)
    if tg_msg is None:
        return

    logger.debug(
        "Mensagem capturada para live ingestion: [%d] %s: %s",
        tg_msg.id,
        tg_msg.author,
        tg_msg.text[:80] if tg_msg.text else "(vazio)",
    )

    # Add to buffer and check if we should flush
    buf = _get_buffer()
    should_flush = buf.add(tg_msg)
    if should_flush:
        logger.info("Buffer atingiu threshold (%d mensagens), iniciando flush...", buf.batch_threshold)
        await _flush_buffer()


async def _periodic_flush(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: flush the buffer if enough time has passed."""
    buf = _get_buffer()
    if buf.should_flush_by_time():
        logger.info("Flush periódico: buffer com %d mensagens.", buf.size)
        await _flush_buffer()


def setup_live_ingestion(application: Application) -> None:
    """Register the live ingestion handler and periodic flush job.

    The handler is added in group=2 so it runs after all command/mention handlers
    (which use the default group=0).
    """
    # Register the message handler for text messages (not commands)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_new_message,
        ),
        group=2,
    )

    # Schedule periodic flush check every 60 seconds
    job_queue = application.job_queue
    if job_queue is None:
        logger.warning(
            "JobQueue not available — periodic flush disabled. "
            "Install python-telegram-bot[job-queue] to enable."
        )
    else:
        job_queue.run_repeating(
            _periodic_flush,
            interval=60,
            first=60,
            name="live_ingest_flush",
        )

    logger.info(
        "Live ingestion configurada: batch_threshold=%d, flush_interval=%ds",
        BATCH_THRESHOLD,
        FLUSH_INTERVAL_SECONDS,
    )
