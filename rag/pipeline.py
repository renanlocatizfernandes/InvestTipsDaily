"""RAG pipeline: query → embedding → ChromaDB search → Claude response."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

import chromadb

from rag.embedder import embed_query
from rag.llm import generate_response, _get_client
from rag.web_search import needs_realtime_data, web_search
from bot.identity import SYSTEM_PROMPT
from bot.memory import add_message, get_history

logger = logging.getLogger(__name__)

COLLECTION_NAME = "telegram_messages"
TOP_K = 8
MIN_RELEVANCE_SCORE = 0.3  # Filter out low-relevance results

_collection = None

# In-memory TTL cache for RAG responses: {normalized_query: (response, timestamp)}
_response_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 300  # 5 minutes


def _normalize_query(query: str) -> str:
    """Normalize a query string for cache key matching.

    Lowercases, strips whitespace, and collapses internal whitespace.
    """
    return " ".join(query.lower().strip().split())


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


def _rerank(query: str, documents: list[dict]) -> list[dict]:
    """Rerank retrieved documents using Claude as a lightweight relevance scorer.

    Sends each chunk's text to Claude and asks for a 0-10 relevance score.
    Returns documents sorted by descending relevance score.

    Falls back to original order on any error.
    """
    if not documents:
        return documents

    # Build a compact numbered list of chunk previews (first 200 chars each)
    chunk_summaries = []
    for i, doc in enumerate(documents):
        preview = doc["text"][:200].replace("\n", " ")
        chunk_summaries.append(f"{i}: {preview}")
    chunks_text = "\n".join(chunk_summaries)

    prompt = (
        f"Query: {query}\n\n"
        f"Rate each chunk's relevance to the query (0=irrelevant, 10=perfect match). "
        f"Reply with ONLY comma-separated integers, one per chunk, in order.\n\n"
        f"{chunks_text}"
    )

    try:
        client = _get_client()
        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

        response = client.messages.create(
            model=model,
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )

        scores_text = response.content[0].text.strip()
        scores = [int(s.strip()) for s in scores_text.split(",")]

        if len(scores) != len(documents):
            logger.warning(
                "Reranking score count mismatch: got %d, expected %d. Using original order.",
                len(scores), len(documents),
            )
            return documents

        # Attach scores and sort descending
        for doc, score in zip(documents, scores):
            doc["rerank_score"] = score

        reranked = sorted(documents, key=lambda d: d["rerank_score"], reverse=True)

        logger.info(
            "Reranked %d chunks. Scores: %s",
            len(reranked),
            ", ".join(str(d["rerank_score"]) for d in reranked),
        )
        return reranked

    except Exception:
        logger.warning("Reranking failed, using original order.", exc_info=True)
        return documents


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

    # LLM-based reranking (opt-in via ENABLE_RERANKING=true)
    reranking_enabled = os.getenv("ENABLE_RERANKING", "false").lower() in ("true", "1", "yes")
    if reranking_enabled and len(documents) >= 3:
        logger.info("Reranking %d results with LLM...", len(documents))
        documents = _rerank(query_text, documents)

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
    request_id = uuid.uuid4().hex[:8]
    pipeline_start = time.monotonic()

    logger.info("[%s] Pipeline started for query: %.80s", request_id, user_question)

    # Check response cache
    cache_key = _normalize_query(user_question)
    now = time.monotonic()
    if cache_key in _response_cache:
        cached_response, cached_at = _response_cache[cache_key]
        if now - cached_at < CACHE_TTL:
            logger.info("[%s] Cache hit for query: '%s' (age=%.1fs)", request_id, cache_key[:80], now - cached_at)
            # Still store in memory so conversation history is consistent
            if user_id is not None:
                add_message(user_id, "user", user_question)
                add_message(user_id, "assistant", cached_response)
            return cached_response
        else:
            # Expired entry — remove it
            del _response_cache[cache_key]

    # --- Search stage ---
    logger.info("[%s] Search start", request_id)
    search_start = time.monotonic()
    documents = search(user_question, top_k=top_k)
    search_elapsed = time.monotonic() - search_start
    logger.info("[%s] Search completed: %d results in %.2fs", request_id, len(documents), search_elapsed)

    # Filter low-relevance results
    relevant_docs = [d for d in documents if d["score"] >= MIN_RELEVANCE_SCORE]
    logger.info(
        "[%s] RAG search: %d/%d results above threshold (%.2f)",
        request_id, len(relevant_docs), len(documents), MIN_RELEVANCE_SCORE,
    )

    # Check if we need real-time data
    web_results = ""
    if needs_realtime_data(user_question):
        logger.info("[%s] Question needs real-time data, searching web...", request_id)
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

    # --- LLM stage ---
    logger.info("[%s] LLM call start", request_id)
    llm_start = time.monotonic()
    response = generate_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_question,
        context=context,
        history=history,
    )
    llm_elapsed = time.monotonic() - llm_start
    logger.info("[%s] LLM call completed in %.2fs", request_id, llm_elapsed)

    # Store response in cache
    _response_cache[cache_key] = (response, time.monotonic())
    logger.info("[%s] Cached response for query: '%s'", request_id, cache_key[:80])

    # Store the new exchange in memory
    if user_id is not None:
        add_message(user_id, "user", user_question)
        add_message(user_id, "assistant", response)

    pipeline_elapsed = time.monotonic() - pipeline_start
    logger.info("[%s] Pipeline completed in %.2fs (search=%.2fs, llm=%.2fs)", request_id, pipeline_elapsed, search_elapsed, llm_elapsed)

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
