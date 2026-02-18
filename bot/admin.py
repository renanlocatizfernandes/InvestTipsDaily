"""Admin-restricted bot commands (/reindex, /stats, /config)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import functools
from pathlib import Path

try:
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Admin check decorator
# ---------------------------------------------------------------------------

def admin_only(func):
    """Decorator that restricts a handler to group admins only.

    Uses update.effective_chat.get_member(user_id) to verify admin status.
    Works for group owner, administrators, and in private chats (always allowed).
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        chat = update.effective_chat

        if user is None or chat is None or update.message is None:
            return

        # Private chats — allow (useful for testing)
        if chat.type == "private":
            return await func(update, context, *args, **kwargs)

        # Group/supergroup — check admin status
        try:
            member = await chat.get_member(user.id)
        except Exception:
            logger.exception("Failed to check admin status for user %s", user.id)
            await update.message.reply_text(
                "Nao consegui verificar suas permissoes. Tenta de novo."
            )
            return

        if member.status not in ("creator", "administrator"):
            await update.message.reply_text(
                "Apenas administradores podem usar este comando."
            )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# /reindex command
# ---------------------------------------------------------------------------

@admin_only
async def cmd_reindex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reindex — re-run ingestion from scratch (admin only).

    Clears processed_ids.json and runs the ingestion pipeline in a background
    thread so the bot stays responsive.
    """
    db_path = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")
    processed_ids_file = Path(db_path) / "processed_ids.json"

    await update.message.reply_text(
        "Iniciando reindexacao... Isso pode levar alguns minutos."
    )

    def _run_reindex() -> str:
        """Run reindexation in a thread."""
        # Clear processed IDs so all messages are re-processed
        if processed_ids_file.exists():
            processed_ids_file.unlink()
            logger.info("Cleared processed_ids.json for reindex.")

        from ingestion.ingest import run_ingestion
        try:
            run_ingestion()
            return "Reindexacao concluida com sucesso!"
        except Exception as exc:
            logger.exception("Reindex failed")
            return f"Erro na reindexacao: {exc}"

    try:
        result = await asyncio.to_thread(_run_reindex)
        await update.message.reply_text(result)
    except Exception:
        logger.exception("Error in /reindex handler")
        await update.message.reply_text(
            "Deu um erro ao executar a reindexacao. Verifique os logs."
        )


# ---------------------------------------------------------------------------
# /stats command
# ---------------------------------------------------------------------------

def _get_dir_size_bytes(path: str) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    dir_path = Path(path)
    if dir_path.exists():
        for f in dir_path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    return total


def _format_size(size_bytes: int) -> str:
    """Format bytes into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


COLLECTION_NAME = "telegram_messages"
PROCESSED_IDS_FILE = "processed_ids.json"


def get_stats() -> str:
    """Gather stats from ChromaDB and return a formatted string."""
    db_path = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")

    # Number of processed messages
    processed_ids_path = Path(db_path) / PROCESSED_IDS_FILE
    processed_count = 0
    if processed_ids_path.exists():
        try:
            ids = json.loads(processed_ids_path.read_text())
            processed_count = len(ids)
        except Exception:
            pass

    # ChromaDB stats
    chunk_count = 0
    top_authors: list[tuple[str, int]] = []
    try:
        client = chromadb.PersistentClient(path=db_path)
        collection = client.get_collection(COLLECTION_NAME)
        chunk_count = collection.count()

        # Get all metadata to compute top authors
        if chunk_count > 0:
            all_meta = collection.get(include=["metadatas"])
            author_counts: dict[str, int] = {}
            for meta in all_meta["metadatas"]:
                authors_json = meta.get("authors", "[]")
                try:
                    authors = json.loads(authors_json)
                except (json.JSONDecodeError, TypeError):
                    authors = []
                msg_count = meta.get("message_count", 0)
                for author in authors:
                    author_counts[author] = author_counts.get(author, 0) + msg_count

            # Sort by count descending, take top 5
            sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
            top_authors = sorted_authors[:5]
    except Exception:
        logger.exception("Error reading ChromaDB stats")

    # DB size on disk
    db_size = _get_dir_size_bytes(db_path)

    # Build output
    lines = [
        "Estatisticas do TipsAI",
        "",
        f"Chunks no ChromaDB: {chunk_count}",
        f"Mensagens processadas: {processed_count}",
        f"Tamanho do banco: {_format_size(db_size)}",
    ]

    if top_authors:
        lines.append("")
        lines.append("Top 5 autores por mensagens:")
        for i, (author, count) in enumerate(top_authors, 1):
            lines.append(f"  {i}. {author} — {count} msgs")

    return "\n".join(lines)


@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats — show bot and database statistics (admin only)."""
    try:
        stats_text = await asyncio.to_thread(get_stats)
        await update.message.reply_text(stats_text)
    except Exception:
        logger.exception("Error in /stats handler")
        await update.message.reply_text(
            "Deu um erro ao buscar as estatisticas. Verifique os logs."
        )


# ---------------------------------------------------------------------------
# /config command
# ---------------------------------------------------------------------------

def _mask_key(value: str) -> str:
    """Mask a sensitive string, showing only first 8 and last 4 chars."""
    if len(value) <= 16:
        return "****"
    return value[:8] + "..." + value[-4:]


def get_config() -> str:
    """Gather current bot configuration from environment variables.

    Masks sensitive values (API keys, tokens).
    """
    claude_model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    embedding_model = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    db_path = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")
    export_path = os.getenv("TELEGRAM_EXPORT_PATH", "./data/telegram_export")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # Sensitive — mask
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    lines = [
        "Configuracao atual do TipsAI",
        "",
        f"Modelo LLM: {claude_model}",
        f"Modelo de embeddings: {embedding_model}",
        f"Caminho do ChromaDB: {db_path}",
        f"Caminho dos exports: {export_path}",
        f"Nivel de log: {log_level}",
        f"API Key Anthropic: {_mask_key(api_key) if api_key else '(nao configurada)'}",
        f"Token do bot: {_mask_key(bot_token) if bot_token else '(nao configurado)'}",
    ]

    return "\n".join(lines)


@admin_only
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /config — show current configuration (admin only)."""
    config_text = get_config()
    await update.message.reply_text(config_text)
