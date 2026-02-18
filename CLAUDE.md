# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**InvestTipsDaily** is a Telegram bot ("TipsAI") for the "Invest Tips Daily - BR" group. It ingests exported Telegram chat history (HTML files), builds a vector knowledge base, and answers questions via a RAG pipeline powered by Claude Haiku. All content is in **Brazilian Portuguese (pt-BR)**.

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test file / single test
pytest tests/test_parser.py -v
pytest tests/test_chunker.py::test_temporal_grouping -v

# Run ingestion (parse HTML → chunk → embed → store in ChromaDB)
python -m ingestion.ingest                              # local
docker compose run --rm bot python -m ingestion.ingest  # docker

# Run bot
python -m bot.main         # local
docker compose up           # docker

# Install dev dependencies
pip install -e ".[dev]"
```

## Architecture

### Data Flow

```
Telegram HTML exports (messages*.html)
    ↓  ingestion/parser.py     — BeautifulSoup4 extracts TelegramMessage dataclasses
    ↓  ingestion/chunker.py    — Groups messages by conversation (30min gap / reply chains), splits at ~2000 chars
    ↓  rag/embedder.py         — sentence-transformers encodes chunks (multilingual-e5-large, 1024-dim)
    ↓  ingestion/ingest.py     — Stores embeddings + metadata in ChromaDB (PersistentClient)

User question (Telegram)
    ↓  bot/handlers.py         — Routes commands (/tips, /buscar, /resumo) and @mentions
    ↓  rag/pipeline.py         — Embeds query → ChromaDB cosine search (top 8, threshold 0.3)
    ↓  rag/web_search.py       — If question matches realtime keywords (prices, "hoje", crypto tickers), searches web via DuckDuckGo
    ↓  rag/llm.py              — Sends context + question to Claude Haiku, returns response
    ↓  bot/handlers.py         — Sends response back to Telegram (auto-splits messages >4096 chars)
```

### Key Design Patterns

- **E5 prefix convention**: `embed_texts()` prefixes documents with `"passage: "`, `embed_query()` prefixes with `"query: "`. This is required by the multilingual-e5 model — mixing them up breaks retrieval quality.
- **Lazy singletons**: Embedding model, ChromaDB collection, and Anthropic client are all lazy-loaded on first use via module-level `_get_*()` functions. Bot startup calls `_preload_models()` to warm them up.
- **Incremental ingestion**: `processed_ids.json` in the ChromaDB directory tracks which message IDs have been ingested. Re-running ingestion only processes new messages.
- **Joined messages**: Telegram export uses `div.message.default.joined` for consecutive messages by the same author (no author div). Parser inherits author from the previous message via `current_author` state.
- **Async bot, sync RAG**: Bot handlers are async (python-telegram-bot). RAG pipeline is synchronous — handlers use `asyncio.to_thread()` to avoid blocking. Typing indicator stays active via a background task.

### Stack

| Component | Technology |
|-----------|-----------|
| Bot framework | python-telegram-bot (async, polling) |
| Vector DB | ChromaDB (in-process PersistentClient, cosine distance) |
| Embeddings | sentence-transformers/multilingual-e5-large (1024-dim) |
| LLM | Anthropic Claude Haiku 4.5 (claude-haiku-4-5-20251001) |
| Web search | DuckDuckGo via `ddgs` library |
| HTML parsing | BeautifulSoup4 + lxml |
| Container | Docker + docker-compose |

### Environment Variables (`.env`, see `.env.example`)

`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `EMBEDDING_MODEL`, `CHROMA_DB_PATH`, `TELEGRAM_EXPORT_PATH`, `CLAUDE_MODEL`, `LOG_LEVEL`

### Docker Volumes

- `./data/chroma_db:/app/data/chroma_db` — persisted vector database
- `./data/telegram_export:/app/data/telegram_export` — Telegram HTML exports

## Telegram Export HTML Format

Messages live in `messages.html` through `messages20.html`. Key selectors:
- `div.message.default` (with `id="message{N}"`) — regular messages
- `div.message.default.joined` — continuation messages (no author, inherits from previous)
- `div.message.service` — system events (skip these)
- `.from_name` — author (direct child of `.body`, not from `.forwarded.body`)
- `.pull_right.date.details[title]` — timestamp as `DD.MM.YYYY HH:MM:SS UTC-03:00`
- `.reply_to a[onclick="GoToMessage(N)"]` — reply references
- `.media_wrap` — media: `a.photo_wrap`, `a.media_photo`, `a.video_file_wrap`, `a.media_video`, `a.media_voice_message`
- `.forwarded.body > .from_name` — forwarded message original author (may have appended date to strip)

## Gotchas

- **Python version**: Requires 3.10–3.12 (sentence-transformers/ChromaDB compatibility).
- **First run is slow**: Embedding model (~2.3 GB) downloads on first use.
- **Tests are offline**: Tests use fixtures with sample HTML, no API keys or DB needed. `asyncio_mode = "auto"` in pyproject.toml.
- **Two photo CSS classes**: Telegram export uses both `a.photo_wrap` and `a.media_photo` for photos — parser checks both.
