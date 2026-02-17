"""RAG pipeline: query → embedding → zvec search → Claude response."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import zvec

from rag.embedder import embed_query, get_dimension
from rag.llm import generate_response
from bot.identity import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

VECTOR_FIELD = "embedding"
TOP_K = 10

_collection = None


def _get_collection():
    """Get or open the zvec collection."""
    global _collection
    if _collection is None:
        db_path = os.getenv("ZVEC_DB_PATH", "./data/zvec_db")
        try:
            _collection = zvec.open(path=db_path)
            logger.info("Opened zvec collection at %s", db_path)
        except Exception:
            logger.warning("Could not open zvec collection at %s. Run ingestion first.", db_path)
            return None
    return _collection


def search(query_text: str, top_k: int = TOP_K) -> list[dict]:
    """Search the vector DB for relevant chunks.

    Returns a list of dicts with 'text', 'authors', 'start_time', 'end_time', 'score'.
    """
    collection = _get_collection()
    if collection is None:
        return []

    query_embedding = embed_query(query_text)

    results = collection.query(
        vectors=zvec.VectorQuery(VECTOR_FIELD, vector=query_embedding),
        topk=top_k,
    )

    documents = []
    for doc in results:
        # Metadata stored as JSON in the 'metadata' field
        raw = doc.field("metadata")
        if raw is None:
            continue
        metadata = json.loads(raw) if isinstance(raw, str) else raw
        documents.append({
            "text": metadata.get("text", ""),
            "authors": metadata.get("authors", []),
            "start_time": metadata.get("start_time", ""),
            "end_time": metadata.get("end_time", ""),
            "score": doc.score,
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
