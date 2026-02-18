"""RAG pipeline: query → embedding → ChromaDB search → Claude response."""

from __future__ import annotations

import json
import logging
import os

import chromadb

from rag.embedder import embed_query
from rag.llm import generate_response
from rag.web_search import needs_realtime_data, web_search
from bot.identity import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

COLLECTION_NAME = "telegram_messages"
TOP_K = 8
MIN_RELEVANCE_SCORE = 0.3  # Filter out low-relevance results

_collection = None


def _get_collection():
    """Get or open the ChromaDB collection."""
    global _collection
    if _collection is None:
        db_path = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")
        client = chromadb.PersistentClient(path=db_path)
        try:
            _collection = client.get_collection(COLLECTION_NAME)
            logger.info("Opened ChromaDB collection '%s' (%d docs)", COLLECTION_NAME, _collection.count())
        except Exception:
            logger.warning("Collection '%s' not found. Run ingestion first.", COLLECTION_NAME)
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
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = []
    if results["documents"] and results["documents"][0]:
        for i, doc_text in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i] if results["distances"] else None
            authors = json.loads(meta.get("authors", "[]"))
            documents.append({
                "text": doc_text,
                "authors": authors,
                "start_time": meta.get("start_time", ""),
                "end_time": meta.get("end_time", ""),
                "score": 1 - distance if distance is not None else 0,
            })

    return documents


def _format_context(documents: list[dict], web_results: str = "") -> str:
    """Format retrieved documents and web results into a context string."""
    parts = []

    if documents:
        for i, doc in enumerate(documents, 1):
            authors = ", ".join(doc["authors"]) if isinstance(doc["authors"], list) else doc["authors"]
            header = f"[Trecho {i}] Autores: {authors} | Período: {doc['start_time']} — {doc['end_time']}"
            parts.append(f"{header}\n{doc['text']}")

    if web_results:
        parts.append(f"[Dados atuais da web]\n{web_results}")

    return "\n\n".join(parts)


def query(user_question: str, top_k: int = TOP_K) -> str:
    """Full RAG pipeline: search + optional web search + generate response."""
    documents = search(user_question, top_k=top_k)

    # Filter low-relevance results
    relevant_docs = [d for d in documents if d["score"] >= MIN_RELEVANCE_SCORE]
    logger.info(
        "RAG search: %d/%d results above threshold (%.2f)",
        len(relevant_docs), len(documents), MIN_RELEVANCE_SCORE,
    )

    # Check if we need real-time data
    web_results = ""
    if needs_realtime_data(user_question):
        logger.info("Question needs real-time data, searching web...")
        web_results = web_search(user_question)

    context = _format_context(relevant_docs, web_results)

    if not context:
        context = (
            "Nenhuma mensagem relevante foi encontrada no histórico do grupo. "
            "Responda com base no seu conhecimento geral, mas deixe claro que "
            "não encontrou referências específicas do grupo."
        )

    return generate_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_question,
        context=context,
    )


def semantic_search(query_text: str, top_k: int = 5) -> list[dict]:
    """Public search endpoint for the /buscar command."""
    return search(query_text, top_k=top_k)
