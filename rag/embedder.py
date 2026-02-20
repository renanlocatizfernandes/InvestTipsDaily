"""Embedding wrapper using sentence-transformers."""

from __future__ import annotations

import logging
import os
import time

import numpy as np

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
        logger.info("Loading embedding model: %s", model_name)
        _model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded (dim=%d)", _model.get_sentence_embedding_dimension())
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts.

    multilingual-e5 expects the prefix "query: " for queries and
    "passage: " for documents. We add "passage: " here since this is
    used for indexing. Use embed_query() for search queries.
    """
    model = _get_model()
    prefixed = [f"passage: {t}" for t in texts]
    start = time.monotonic()
    embeddings = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=True)
    elapsed = time.monotonic() - start
    logger.info("Embedded %d texts in %.2fs", len(texts), elapsed)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Generate embedding for a search query."""
    model = _get_model()
    embedding = model.encode(f"query: {query}", normalize_embeddings=True)
    return embedding.tolist()


def get_dimension() -> int:
    """Return the embedding dimension of the loaded model."""
    return _get_model().get_sentence_embedding_dimension()
