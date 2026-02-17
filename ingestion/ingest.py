"""Ingestion script: parse HTML exports → chunk → embed → store in zvec."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import zvec

from ingestion.parser import parse_all_exports
from ingestion.chunker import chunk_messages
from rag.embedder import embed_texts, get_dimension

logger = logging.getLogger(__name__)

COLLECTION_NAME = "telegram_messages"
PROCESSED_IDS_FILE = "processed_ids.json"
BATCH_SIZE = 32


def _load_processed_ids(db_path: str) -> set[int]:
    """Load set of already-processed message IDs."""
    filepath = Path(db_path) / PROCESSED_IDS_FILE
    if filepath.exists():
        return set(json.loads(filepath.read_text()))
    return set()


def _save_processed_ids(db_path: str, ids: set[int]) -> None:
    """Persist set of processed message IDs."""
    filepath = Path(db_path) / PROCESSED_IDS_FILE
    filepath.write_text(json.dumps(sorted(ids)))


def run_ingestion(export_path: str | None = None, db_path: str | None = None) -> None:
    """Run the full ingestion pipeline."""
    export_path = export_path or os.getenv("TELEGRAM_EXPORT_PATH", "./data/telegram_export")
    db_path = db_path or os.getenv("ZVEC_DB_PATH", "./data/zvec_db")

    Path(db_path).mkdir(parents=True, exist_ok=True)

    # Step 1: Parse HTML files
    logger.info("Parsing HTML exports from %s ...", export_path)
    all_messages = parse_all_exports(export_path)
    logger.info("Parsed %d messages total.", len(all_messages))

    # Step 2: Filter out already-processed messages
    processed_ids = _load_processed_ids(db_path)
    new_messages = [m for m in all_messages if m.id not in processed_ids]
    if not new_messages:
        logger.info("No new messages to process.")
        return
    logger.info("%d new messages to process.", len(new_messages))

    # Step 3: Chunk messages
    logger.info("Chunking messages...")
    chunks = chunk_messages(new_messages)
    logger.info("Created %d chunks.", len(chunks))

    # Step 4: Initialize zvec
    db = zvec.Database(db_path)
    dim = get_dimension()

    try:
        collection = db.get_collection(COLLECTION_NAME)
        logger.info("Using existing collection '%s'.", COLLECTION_NAME)
    except Exception:
        logger.info("Creating new collection '%s' (dim=%d).", COLLECTION_NAME, dim)
        collection = db.create_collection(COLLECTION_NAME, dimension=dim)

    # Step 5: Embed and insert in batches
    total = len(chunks)
    for batch_start in range(0, total, BATCH_SIZE):
        batch = chunks[batch_start : batch_start + BATCH_SIZE]
        texts = [c.text for c in batch]

        logger.info(
            "Embedding batch %d-%d of %d...",
            batch_start + 1,
            min(batch_start + BATCH_SIZE, total),
            total,
        )
        embeddings = embed_texts(texts)

        for chunk, embedding in zip(batch, embeddings):
            metadata = json.dumps(
                {
                    "text": chunk.text,
                    "authors": chunk.authors,
                    "start_time": chunk.start_time,
                    "end_time": chunk.end_time,
                    "message_ids": chunk.message_ids,
                    "message_count": chunk.metadata["message_count"],
                },
                ensure_ascii=False,
            )
            collection.insert(embedding, metadata=metadata)

    # Step 6: Track processed IDs
    new_ids = {m.id for m in new_messages}
    processed_ids.update(new_ids)
    _save_processed_ids(db_path, processed_ids)

    logger.info("Ingestion complete. %d chunks inserted.", len(chunks))


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_ingestion()
