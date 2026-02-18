# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**InvestTipsDaily** is a Telegram bot ("TipsAI") for the "Invest Tips Daily - BR" group. It ingests exported Telegram chat history (HTML files), builds a vector knowledge base, and answers questions via a RAG pipeline powered by Claude Haiku. All content is in **Brazilian Portuguese (pt-BR)**.

## Commands

```bash
# Run all tests (186 tests)
pytest tests/ -v

# Run a single test file / single test
pytest tests/test_parser.py -v
pytest tests/test_chunker.py::test_temporal_grouping -v

# Run ingestion (parse HTML → transcribe audio → analyze images → chunk → embed → store)
python -m ingestion.ingest                              # local
docker compose run --rm bot python -m ingestion.ingest  # docker

# Run bot
python -m bot.main         # local
docker compose up           # docker
docker compose up --build   # rebuild after code changes

# Install dev dependencies
pip install -e ".[dev]"
```

## Architecture

### Data Flow

```
Telegram HTML exports (messages*.html)
    ↓  ingestion/parser.py        — BeautifulSoup4 extracts TelegramMessage dataclasses
    ↓  ingestion/transcriber.py   — Whisper transcribes voice messages (OGG → text)
    ↓  ingestion/image_analyzer.py — Claude Vision describes photos (JPG/PNG → text)
    ↓  ingestion/chunker.py       — Groups messages by conversation (30min gap / reply chains), splits at ~2000 chars
    ↓  rag/embedder.py            — sentence-transformers encodes chunks (multilingual-e5-large, 1024-dim)
    ↓  ingestion/ingest.py        — Stores embeddings + metadata in ChromaDB (PersistentClient)

User question (Telegram)
    ↓  bot/handlers.py         — Routes commands, @mentions, replies; applies rate limiting
    ↓  bot/memory.py           — Fetches per-user conversation history (10 exchanges, 30min TTL)
    ↓  rag/search_parser.py    — Parses filters (autor:, de:, ate:) from /buscar queries
    ↓  rag/pipeline.py         — Embeds query → ChromaDB cosine search (top 8, threshold 0.3, optional filters)
    ↓  rag/web_search.py       — If question matches realtime keywords, searches web via DuckDuckGo
    ↓  rag/llm.py              — Sends context + history + question to Claude Haiku
    ↓  bot/feedback.py         — Attaches thumbs up/down buttons, logs feedback to JSON
    ↓  bot/handlers.py         — Sends response back to Telegram (auto-splits >4096 chars)

Background services
    ↓  bot/live_ingest.py      — Captures new group messages → buffers → chunks → embeds → ChromaDB
    ↓  bot/scheduler.py        — Daily summary posted to "Teste Bot" topic at configured hour
    ↓  bot/health.py           — Tracks query count, latency, errors, uptime
```

### Bot Commands

| Command | Access | Description |
|---------|--------|-------------|
| `/tips <pergunta>` | All | Pergunta livre ao bot (RAG + web search) |
| `/buscar <termo>` | All | Busca semântica com filtros: `autor:Nome de:YYYY-MM-DD ate:YYYY-MM-DD` |
| `/resumo` | All | Resumo das conversas recentes |
| `/health` | All | Status: uptime, consultas, latência, erros, ChromaDB size |
| `/sobre` | All | Informações sobre o bot |
| `/ajuda` | All | Lista de comandos |
| `/reindex` | Admin | Re-ingesta todas as mensagens do zero |
| `/stats` | Admin | Estatísticas: chunks, mensagens, tamanho do DB, top autores |
| `/config` | Admin | Configuração atual (API keys mascaradas) |

### Key Design Patterns

- **E5 prefix convention**: `embed_texts()` prefixes with `"passage: "`, `embed_query()` with `"query: "`. Required by multilingual-e5 — mixing breaks retrieval.
- **Lazy singletons**: Embedding model, ChromaDB collection, Anthropic client, Whisper model — all lazy-loaded via `_get_*()`. Bot startup calls `_preload_models()`.
- **Incremental ingestion**: `processed_ids.json` tracks ingested message IDs. Re-running only processes new messages.
- **Async bot, sync RAG**: Handlers are async (python-telegram-bot), RAG is sync — bridged via `asyncio.to_thread()`. Typing indicator via background task.
- **Conversation memory**: Per-user in-memory store (`bot/memory.py`) with 10-exchange max and 30min TTL. History is passed to Claude as prior messages.
- **Rate limiting**: Sliding window (5 req/60s per user) in `bot/rate_limit.py`. Applied to all RAG-calling handlers.
- **Live ingestion**: `bot/live_ingest.py` buffers new group messages (threshold: 10 msgs or 5min), then chunks+embeds+stores in background. Handler runs at group=2 (lower priority than commands).
- **Feedback loop**: Bot responses include inline thumbs up/down buttons. Clicks are logged to `data/feedback.json` with user, query, and timestamp.
- **Hybrid search**: `/buscar` supports `autor:`, `de:`, `ate:` filters parsed by `rag/search_parser.py`. Filters are translated to ChromaDB `where` clauses ($contains, $gte, $lte).

### Stack

| Component | Technology |
|-----------|-----------|
| Bot framework | python-telegram-bot (async, polling, JobQueue) |
| Vector DB | ChromaDB (in-process PersistentClient, cosine distance) |
| Embeddings | sentence-transformers/multilingual-e5-large (1024-dim) |
| LLM | Anthropic Claude Haiku 4.5 (claude-haiku-4-5-20251001) |
| Vision | Anthropic Claude Vision (image analysis during ingestion) |
| Audio transcription | OpenAI Whisper (local, base model) |
| Web search | DuckDuckGo via `ddgs` library |
| HTML parsing | BeautifulSoup4 + lxml |
| Container | Docker + docker-compose |

### Environment Variables (`.env`, see `.env.example`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `EMBEDDING_MODEL` | No | `intfloat/multilingual-e5-large` | Embedding model |
| `CHROMA_DB_PATH` | No | `./data/chroma_db` | ChromaDB directory |
| `TELEGRAM_EXPORT_PATH` | No | `./data/telegram_export` | HTML exports directory |
| `CLAUDE_MODEL` | No | `claude-haiku-4-5-20251001` | Claude model ID |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `WHISPER_MODEL` | No | `base` | Whisper model size |
| `SUMMARY_CHAT_ID` | No | — | Chat ID for scheduled summaries |
| `SUMMARY_THREAD_ID` | No | — | Topic ID ("Teste Bot") for summaries |
| `SUMMARY_SCHEDULE_HOUR` | No | `20` | Hour (BRT) for daily summary |
| `LIVE_INGEST_BATCH_SIZE` | No | `10` | Messages before live flush |
| `LIVE_INGEST_FLUSH_SECONDS` | No | `300` | Max seconds before live flush |
| `FEEDBACK_DATA_DIR` | No | `data` | Directory for feedback.json |

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
- **First run is slow**: Embedding model (~2.3 GB) and Whisper model download on first use.
- **Tests are offline**: 186 tests use fixtures/mocks, no API keys or DB needed. `asyncio_mode = "auto"` in pyproject.toml.
- **Two photo CSS classes**: Telegram export uses both `a.photo_wrap` and `a.media_photo` — parser checks both.
- **Whisper needs ffmpeg**: Dockerfile installs ffmpeg. For local dev: `apt install ffmpeg` or `brew install ffmpeg`.
- **Scheduled summary requires env vars**: Set both `SUMMARY_CHAT_ID` and `SUMMARY_THREAD_ID` or the scheduler silently disables.
- **Live ingestion handler group**: Runs at `group=2` so it doesn't interfere with command handlers (group 0).
- **Feedback data**: Stored in `data/feedback.json`. The query→message_id mapping is in-memory only (lost on restart).
