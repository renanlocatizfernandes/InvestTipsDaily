# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **InvestTipsDaily** project — a Telegram group chat intelligence system for the group "Invest Tips Daily - BR". The project has two phases:

1. **Data ingestion & RAG**: Parse exported Telegram chat history, build a knowledge base using vector embeddings (zvec + Anthropic API), and serve it via a RAG pipeline.
2. **Telegram bot**: Connect the RAG intelligence to an existing Telegram bot in the group (bot access to be provided later).

The entire stack should be containerized with Docker for portability across servers.

## Current State of the Repository

The repository contains the **TipsAI bot** application code and raw Telegram chat export data.

### Application Structure

```
bot/          — Telegram bot (main.py, handlers.py, identity.py)
rag/          — RAG pipeline (pipeline.py, embedder.py, llm.py)
ingestion/    — Data ingestion (parser.py, chunker.py, ingest.py)
tests/        — Test suite (test_parser.py, test_chunker.py, test_bot.py)
docker/       — Dockerfile
```

### Key Commands
- **Run tests**: `pytest tests/ -v`
- **Run ingestion**: `python -m ingestion.ingest`
- **Run bot**: `python -m bot.main`
- **Docker**: `docker-compose up`

### Data Structure

- `messages.html` through `messages10.html` — Telegram chat history split across 10 HTML files (standard Telegram export format). Messages span from **August 2024 to October 2024+** and include topics like "CoinTech2U" and "Papo sobre criptomoedas".
- `photos/` — Exported images (JPG with thumbnails)
- `files/` — Exported file attachments (PNG images)
- `video_files/` — Exported videos (MP4)
- `voice_messages/` — Voice messages (OGG)
- `stickers/` — Animated stickers (TGS)
- `css/style.css`, `js/script.js`, `images/` — Telegram export viewer assets (auto-generated, do not modify)

### Message HTML Format

Each message in the HTML files follows this structure:
- `div.message.default` with `id="message{N}"` — contains the message
- `div.from_name` — sender name
- `div.pull_right.date.details` with `title` attribute — timestamp in format `DD.MM.YYYY HH:MM:SS UTC-03:00`
- `div.text` — message text content
- `div.reply_to` — reply references using `GoToMessage(id)` links
- `div.media_wrap` — attached media (photos, videos, files)
- `div.message.service` — system messages (group creation, member joins, topic creation)

## Architecture

### Stack
| Component | Technology |
|-----------|-----------|
| Bot | python-telegram-bot |
| Vector DB | zvec (alibaba/zvec) — in-process |
| Embeddings | sentence-transformers (multilingual-e5-large) |
| LLM | Anthropic Claude Haiku 4.5 |
| Parser | BeautifulSoup4 + lxml |
| Container | Docker + docker-compose |

### zvec (Vector Database)
- In-process vector database from Alibaba (`pip install zvec`). No server needed.
- Requires Python 3.10-3.12, Linux x86_64 or macOS ARM64 (must run in Docker on Windows).

### Environment Variables (see .env.example)
- `ANTHROPIC_API_KEY` — Claude API key
- `TELEGRAM_BOT_TOKEN` — Bot token from @BotFather
- `EMBEDDING_MODEL` — Embedding model name (default: intfloat/multilingual-e5-large)
- `ZVEC_DB_PATH` — Path to zvec database directory
- `TELEGRAM_EXPORT_PATH` — Path to Telegram HTML exports
- `CLAUDE_MODEL` — Claude model ID

## Key Technical Considerations

- **HTML parsing**: The Telegram export uses a consistent HTML structure. Use BeautifulSoup or similar to extract message text, sender, timestamp, reply chains, and media references from the `messages*.html` files.
- **Language**: Chat messages are primarily in **Brazilian Portuguese (pt-BR)**. Embedding and retrieval models must handle Portuguese well.
- **Media files**: Voice messages (OGG) and videos (MP4) exist but require transcription (e.g., Whisper) to be included in the RAG knowledge base.
- **Incremental exports**: As the user continues exporting chat history, new `messages*.html` files may be added. The ingestion pipeline should handle re-processing gracefully.
- **zvec runs in-process**: Unlike client-server vector DBs, zvec stores data to a local directory and loads it in-process. The Docker volume must persist the zvec data directory.
