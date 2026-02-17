"""RAG pipeline: query → embedding → zvec search → Claude response."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import zvec

from rag.embedder import embed_query
from rag.llm import generate_response
from bot.identity import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

COLLECTION_NAME = "telegram_messages"
TOP_K = 10

_db: zvec.Database | None = None


def _get_db() -> zvec.Database:
    """Get or initialize the zvec database."""
    global _db
    if _db is None:
        db_path = os.getenv("ZVEC_DB_PATH", "./data/zvec_db")
        Path(db_path).mkdir(parents=True, exist_ok=True)
        _db = zvec.Database(db_path)
    return _db


def search(query: str, top_k: int = TOP_K) -> list[dict]:
    """Search the vector DB for relevant chunks.

    Returns a list of dicts with 'text', 'authors', 'start_time', 'end_time', 'score'.
    """
    db = _get_db()

    try:
        collection = db.get_collection(COLLECTION_NAME)
    except Exception:
        logger.warning("Collection '%s' not found. Run ingestion first.", COLLECTION_NAME)
        return []

    query_embedding = embed_query(query)
    results = collection.search(query_embedding, top_k=top_k)

    documents = []
    for result in results:
        metadata = json.loads(result.metadata) if isinstance(result.metadata, str) else result.metadata
        documents.append({
            "text": metadata.get("text", ""),
            "authors": metadata.get("authors", []),
            "start_time": metadata.get("start_time", ""),
            "end_time": metadata.get("end_time", ""),
            "score": result.score,
        })

    return documents


def _format_context(documents: list[dict]) -> str:
    """Format retrieved documents into a context string for the LLM."""
    if not documents:
        return ""

    parts = []
    for i, doc in enumerate(documents, 1):
        authors = ", ".join(doc["authors"]) if isinstance(doc["authors"], list) else doc["authors"]
        header = f"[Trecho {i}] Autores: {authors} | Período: {doc['start_time']} — {doc['end_time']}"
        parts.append(f"{header}\n{doc['text']}")

    return "\n\n".join(parts)


def query(user_question: str, top_k: int = TOP_K) -> str:
    """Full RAG pipeline: search + generate response."""
    documents = search(user_question, top_k=top_k)
    context = _format_context(documents)

    if not context:
        context_note = (
            "Nenhuma mensagem relevante foi encontrada no histórico do grupo. "
            "Responda com base no seu conhecimento geral, mas deixe claro que "
            "não encontrou referências específicas do grupo."
        )
    else:
        context_note = context

    return generate_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_question,
        context=context_note,
    )


def semantic_search(query_text: str, top_k: int = 5) -> list[dict]:
    """Public search endpoint for the /buscar command."""
    return search(query_text, top_k=top_k)
