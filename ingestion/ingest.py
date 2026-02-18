"""Ingestion script: parse HTML exports → chunk → embed → store in ChromaDB."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import chromadb

from ingestion.parser import parse_all_exports
from ingestion.chunker import chunk_messages
from ingestion.transcriber import transcribe_audio
from ingestion.image_analyzer import analyze_image
from rag.embedder import embed_texts

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
    db_path = db_path or os.getenv("CHROMA_DB_PATH", "./data/chroma_db")

    Path(db_path).mkdir(parents=True, exist_ok=True)

    # Step 1: Parse HTML files
    logger.info("Parsing HTML exports from %s ...", export_path)
    all_messages = parse_all_exports(export_path)
    logger.info("Parsed %d messages total.", len(all_messages))

    # Step 1.5: Transcribe voice messages
    voice_messages = [m for m in all_messages if m.media_type == "voice" and m.media_path]
    if voice_messages:
        logger.info("Found %d voice messages to transcribe.", len(voice_messages))
        transcribed_count = 0
        for msg in voice_messages:
            audio_path = os.path.join(export_path, msg.media_path)
            transcription = transcribe_audio(audio_path)
            if transcription:
                prefix = f"{msg.text}\n" if msg.text else ""
                msg.text = f"{prefix}[Transcrição de áudio] {transcription}"
                transcribed_count += 1
        logger.info("Transcribed %d of %d voice messages.", transcribed_count, len(voice_messages))

    # Step 1.6: Analyze images in photo messages
    photo_messages = [m for m in all_messages if m.media_type == "photo" and m.media_path]
    if photo_messages:
        logger.info("Found %d photo messages to analyze.", len(photo_messages))
        analyzed_count = 0
        for msg in photo_messages:
            image_path = os.path.join(export_path, msg.media_path)
            description = analyze_image(image_path)
            if description:
                prefix = f"{msg.text}\n" if msg.text else ""
                msg.text = f"{prefix}[Descrição da imagem] {description}"
                analyzed_count += 1
        logger.info("Analyzed %d of %d photo messages.", analyzed_count, len(photo_messages))

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

    # Step 4: Initialize ChromaDB
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # Step 5: Embed and insert in batches
    total = len(chunks)
    existing_count = collection.count()

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

        ids = []
        metadatas = []
        documents = []
        for i, chunk in enumerate(batch):
            doc_id = f"chunk_{existing_count + batch_start + i}"
            ids.append(doc_id)
            documents.append(chunk.text)
            metadatas.append({
                "authors": json.dumps(chunk.authors, ensure_ascii=False),
                "start_time": chunk.start_time,
                "end_time": chunk.end_time,
                "message_ids": json.dumps(chunk.message_ids),
                "message_count": chunk.metadata["message_count"],
            })

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    # Step 6: Track processed IDs
    new_ids = {m.id for m in new_messages}
    processed_ids.update(new_ids)
    _save_processed_ids(db_path, processed_ids)

    logger.info(
        "Ingestion complete. %d chunks inserted. Total in DB: %d.",
        len(chunks),
        collection.count(),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_ingestion()
