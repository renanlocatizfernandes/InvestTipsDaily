"""Ingestion script: parse HTML exports → chunk → embed → store in zvec."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import zvec

from ingestion.parser import parse_all_exports
from ingestion.chunker import chunk_messages
from rag.embedder import embed_texts, get_dimension

logger = logging.getLogger(__name__)

VECTOR_FIELD = "embedding"
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


def _build_schema(dim: int) -> zvec.CollectionSchema:
    """Build the zvec collection schema."""
    return zvec.CollectionSchema(
        name="telegram_messages",
        fields=zvec.FieldSchema("metadata", zvec.DataType.STRING, nullable=False),
        vectors=zvec.VectorSchema(
            VECTOR_FIELD,
            zvec.DataType.VECTOR_FP32,
            dimension=dim,
            index_param=zvec.HnswIndexParam(),
        ),
    )


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

    # Step 4: Initialize zvec collection
    dim = get_dimension()

    # Try to open existing collection, or create new one
    try:
        collection = zvec.open(path=db_path)
        logger.info("Opened existing collection at '%s'.", db_path)
    except Exception:
        logger.info("Creating new collection (dim=%d) at '%s'.", dim, db_path)
        schema = _build_schema(dim)
        collection = zvec.create_and_open(path=db_path, schema=schema)

    # Step 5: Embed and insert in batches
    total = len(chunks)
    doc_counter = collection.stats.doc_count if hasattr(collection.stats, 'doc_count') else 0

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

        docs = []
        for i, (chunk, embedding) in enumerate(zip(batch, embeddings)):
            doc_id = f"chunk_{doc_counter + batch_start + i}"
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
            docs.append(
                zvec.Doc(
                    id=doc_id,
                    vectors={VECTOR_FIELD: embedding},
                    fields={"metadata": metadata},
                )
            )

        statuses = collection.insert(docs)
        failed = sum(1 for s in statuses if not s.ok())
        if failed:
            logger.warning("%d documents failed to insert in this batch.", failed)

    collection.flush()

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
