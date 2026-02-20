---
name: llm-app-patterns
description: "Production-ready patterns for building LLM applications. Covers RAG pipelines, agent architectures, prompt IDEs, and LLMOps monitoring. Use when designing AI applications, implementing RAG, building agents, or setting up LLM observability."
---

# LLM Application Patterns

> Production-ready patterns for building LLM applications.

## When to Use This Skill

Use this skill when:

- Designing LLM-powered applications
- Implementing RAG (Retrieval-Augmented Generation)
- Building AI agents with tools
- Setting up LLMOps monitoring
- Choosing between agent architectures

---

## 1. RAG Pipeline Architecture

### Overview

RAG (Retrieval-Augmented Generation) grounds LLM responses in your data.

```
Ingest → Retrieve → Generate
  │          │          │
  ▼          ▼          ▼
Chunking   Vector    LLM
Embedding  Search    + Context
```

### 1.1 Document Ingestion

```python
# Chunking strategies
class ChunkingStrategy:
    FIXED_SIZE = "fixed_size"      # e.g., 512 tokens
    SEMANTIC = "semantic"          # Split on paragraphs/sections
    RECURSIVE = "recursive"        # ["\\n\\n", "\\n", " ", ""]
    DOCUMENT_AWARE = "document_aware"  # Headers, lists, etc.

CHUNK_CONFIG = {
    "chunk_size": 512,
    "chunk_overlap": 50,
    "separators": ["\\n\\n", "\\n", ". ", " "],
}
```

### 1.2 Embedding & Storage

```python
VECTOR_DB_OPTIONS = {
    "pinecone": {"use_case": "Production, managed service", "scale": "Billions"},
    "weaviate": {"use_case": "Self-hosted, multi-modal", "scale": "Millions"},
    "chromadb": {"use_case": "Development, prototyping", "scale": "Thousands"},
    "pgvector": {"use_case": "Existing Postgres", "scale": "Millions"},
}
```

### 1.3 Retrieval Strategies

```python
# Basic semantic search
def semantic_search(query: str, top_k: int = 5):
    query_embedding = embed(query)
    return vector_db.similarity_search(query_embedding, top_k=top_k)

# Hybrid search (semantic + keyword)
def hybrid_search(query: str, top_k: int = 5, alpha: float = 0.5):
    semantic_results = vector_db.similarity_search(query)
    keyword_results = bm25_search(query)
    return rrf_merge(semantic_results, keyword_results, alpha)

# Multi-query retrieval
def multi_query_retrieval(query: str):
    queries = llm.generate_query_variations(query, n=3)
    all_results = []
    for q in queries:
        all_results.extend(semantic_search(q))
    return deduplicate(all_results)
```

### 1.4 Generation with Context

```python
RAG_PROMPT_TEMPLATE = """
Answer the user's question based ONLY on the following context.
If the context doesn't contain enough information, say so.

Context:
{context}

Question: {question}

Answer:"""
```

---

## 2. Agent Architectures

### 2.1 ReAct Pattern (Reasoning + Acting)

```
Thought → Action → Observation → (repeat) → Final Answer
```

### 2.2 Function Calling Pattern

LLM decides which tools to call based on user query.

### 2.3 Plan-and-Execute Pattern

1. Create a plan (list of steps)
2. Execute each step
3. Replan if needed

### 2.4 Multi-Agent Collaboration

Specialized agents collaborating on complex tasks with a coordinator.

---

## 3. LLMOps & Observability

### Metrics to Track

| Category | Metrics |
|----------|---------|
| Performance | latency_p50, latency_p99, tokens_per_second |
| Quality | user_satisfaction, task_completion, hallucination_rate |
| Cost | cost_per_request, tokens_per_request, cache_hit_rate |
| Reliability | error_rate, timeout_rate, retry_rate |

---

## 4. Production Patterns

### 4.1 Caching Strategy

Cache deterministic outputs (temperature=0) with content-based keys.

### 4.2 Rate Limiting & Retry

Exponential backoff with jitter. Track timestamps for rate limiting.

### 4.3 Fallback Strategy

Primary model → fallback models. Log failures and switch automatically.

---

## Architecture Decision Matrix

| Pattern | Use When | Complexity | Cost |
|:--------|:---------|:-----------|:-----|
| **Simple RAG** | FAQ, docs search | Low | Low |
| **Hybrid RAG** | Mixed queries | Medium | Medium |
| **ReAct Agent** | Multi-step tasks | Medium | Medium |
| **Function Calling** | Structured tools | Low | Low |
| **Plan-Execute** | Complex tasks | High | High |
| **Multi-Agent** | Research tasks | Very High | Very High |
