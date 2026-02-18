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
from bot.memory import add_message, get_history

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


def _build_where_clause(
    author: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict | None:
    """Build a ChromaDB ``where`` filter from optional parameters.

    Returns ``None`` when no filters are active.
    """
    conditions: list[dict] = []

    if author:
        # authors is stored as a JSON string (e.g. '["Renan", "Ana"]').
        # ChromaDB $contains does a substring match on string metadata.
        conditions.append({"authors": {"$contains": author}})

    if date_from:
        # start_time is ISO-8601 so lexicographic comparison works.
        conditions.append({"start_time": {"$gte": date_from}})

    if date_to:
        # Include the whole day: compare start_time <= date_to end-of-day
        conditions.append({"start_time": {"$lte": date_to + "T23:59:59"}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def search(
    query_text: str,
    top_k: int = TOP_K,
    author: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Search the vector DB for relevant chunks.

    Parameters
    ----------
    query_text : str
        Semantic search text.
    top_k : int
        Maximum number of results.
    author : str, optional
        Filter by author name (substring match on the authors metadata field).
    date_from : str, optional
        Filter chunks whose start_time >= this ISO date (YYYY-MM-DD).
    date_to : str, optional
        Filter chunks whose start_time <= this ISO date (YYYY-MM-DD, inclusive).

    Returns a list of dicts with 'text', 'authors', 'start_time', 'end_time', 'score'.
    """
    collection = _get_collection()
    if collection is None:
        return []

    query_embedding = embed_query(query_text)

    where_clause = _build_where_clause(author=author, date_from=date_from, date_to=date_to)

    query_kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where_clause is not None:
        query_kwargs["where"] = where_clause

    results = collection.query(**query_kwargs)

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


def query(user_question: str, top_k: int = TOP_K, user_id: int | None = None) -> str:
    """Full RAG pipeline: search + optional web search + generate response.

    Args:
        user_question: The user's question text.
        top_k: Number of RAG results to retrieve.
        user_id: Optional Telegram user ID.  When provided, conversation
                 history is fetched from memory, passed to the LLM, and
                 the new exchange is stored.
    """
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

    # Build conversation history for LLM if user_id is provided
    history: list[dict] | None = None
    if user_id is not None:
        raw_history = get_history(user_id)
        if raw_history:
            history = [{"role": role, "content": text} for role, text in raw_history]

    response = generate_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_question,
        context=context,
        history=history,
    )

    # Store the new exchange in memory
    if user_id is not None:
        add_message(user_id, "user", user_question)
        add_message(user_id, "assistant", response)

    return response


def semantic_search(
    query_text: str,
    top_k: int = 5,
    author: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Public search endpoint for the /buscar command.

    Supports optional metadata filters that are forwarded to :func:`search`.
    """
    return search(
        query_text,
        top_k=top_k,
        author=author,
        date_from=date_from,
        date_to=date_to,
    )
