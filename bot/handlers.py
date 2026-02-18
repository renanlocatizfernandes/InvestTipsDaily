"""Telegram bot command handlers."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.identity import ABOUT_TEXT, HELP_TEXT, BOT_USERNAME
from rag.pipeline import query as rag_query, semantic_search

logger = logging.getLogger(__name__)

# Telegram message length limit
TG_MSG_LIMIT = 4096

# Cached bot username (populated on first use)
_bot_username: str | None = None


async def _get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Get and cache the bot username."""
    global _bot_username
    if _bot_username is None:
        bot_user = await context.bot.get_me()
        _bot_username = bot_user.username or BOT_USERNAME
    return _bot_username


async def _send_long_message(update: Update, text: str, **kwargs) -> None:
    """Send a message, splitting if it exceeds Telegram's 4096 char limit."""
    if len(text) <= TG_MSG_LIMIT:
        await update.message.reply_text(text, **kwargs)
        return

    # Split on paragraph boundaries, fallback to hard split
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= TG_MSG_LIMIT:
            chunks.append(remaining)
            break
        # Try to split at last newline before limit
        cut = remaining[:TG_MSG_LIMIT].rfind("\n")
        if cut < TG_MSG_LIMIT // 2:
            cut = TG_MSG_LIMIT  # Hard split if no good break point
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    for chunk in chunks:
        await update.message.reply_text(chunk, **kwargs)


async def _run_with_typing(update: Update, coro):
    """Run a coroutine while keeping the typing indicator active."""
    async def keep_typing():
        while True:
            try:
                await update.message.chat.send_action(ChatAction.TYPING)
            except Exception:
                break
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())
    try:
        return await coro
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


def _escape_markdown(text: str) -> str:
    """Escape Markdown special characters in user-generated content."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "Fala! Eu sou o TipsAI, assistente do Invest Tips Daily. "
        "Use /ajuda pra ver o que eu posso fazer."
    )


async def cmd_tips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tips <pergunta> — free-form RAG question."""
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text(
            "Manda a pergunta junto! Exemplo: /tips o que é CoinTech2U?"
        )
        return

    logger.info("User %s asked /tips: %s", update.effective_user.first_name, question)
    start = time.monotonic()

    try:
        response = await _run_with_typing(
            update, asyncio.to_thread(rag_query, question)
        )
        elapsed = time.monotonic() - start
        logger.info("/tips response in %.1fs (%d chars)", elapsed, len(response))
        await _send_long_message(update, response)
    except Exception:
        logger.exception("Error in /tips handler")
        await update.message.reply_text(
            "Deu um erro aqui. Tenta de novo daqui a pouco."
        )


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /buscar <termo> — semantic search in chat history."""
    term = " ".join(context.args) if context.args else ""
    if not term:
        await update.message.reply_text(
            "Falta o termo de busca! Exemplo: /buscar CoinTech2U rendimento"
        )
        return

    logger.info("User %s searched: %s", update.effective_user.first_name, term)

    try:
        results = await _run_with_typing(
            update, asyncio.to_thread(semantic_search, term, 5)
        )
        if not results:
            await update.message.reply_text(
                "Nao encontrei nada sobre isso no historico. "
                "Talvez o assunto nao tenha sido discutido no grupo ainda."
            )
            return

        parts = [f"\U0001f50d Resultados para: {term}\n"]
        for i, doc in enumerate(results, 1):
            authors = ", ".join(doc["authors"]) if isinstance(doc["authors"], list) else doc["authors"]
            text_preview = doc["text"][:200]
            if len(doc["text"]) > 200:
                text_preview += "..."
            score_pct = int(doc.get("score", 0) * 100)
            parts.append(f"{i}. [{score_pct}%] {authors} ({doc['start_time'][:10]}):\n{text_preview}\n")

        await _send_long_message(update, "\n".join(parts))
    except Exception:
        logger.exception("Error in /buscar handler")
        await update.message.reply_text(
            "Deu um erro na busca. Tenta de novo daqui a pouco."
        )


async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resumo — summary of recent relevant conversations."""
    logger.info("User %s requested /resumo", update.effective_user.first_name)

    try:
        response = await _run_with_typing(
            update,
            asyncio.to_thread(
                rag_query,
                "Faca um resumo breve das conversas mais recentes e relevantes do grupo, "
                "destacando os principais assuntos discutidos."
            ),
        )
        await _send_long_message(update, response)
    except Exception:
        logger.exception("Error in /resumo handler")
        await update.message.reply_text(
            "Deu um erro ao gerar o resumo. Tenta de novo daqui a pouco."
        )


async def cmd_sobre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sobre — about the bot."""
    await update.message.reply_text(ABOUT_TEXT, parse_mode="Markdown")


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ajuda — help."""
    username = await _get_bot_username(context)
    text = HELP_TEXT.format(bot_username=username)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages that mention the bot — treat as /tips."""
    if update.message is None or update.message.text is None:
        return

    username = await _get_bot_username(context)
    mention = f"@{username}"

    text = update.message.text
    if mention.lower() not in text.lower():
        return  # Not a mention of us

    # Remove the mention (case-insensitive) to get the question
    question = re.sub(re.escape(mention), "", text, flags=re.IGNORECASE).strip()

    if not question:
        await update.message.reply_text(
            f"Fala! Me marca com uma pergunta que eu respondo. "
            f"Exemplo: {mention} o que é staking?"
        )
        return

    logger.info("User %s mentioned bot: %s", update.effective_user.first_name, question)
    start = time.monotonic()

    try:
        response = await _run_with_typing(
            update, asyncio.to_thread(rag_query, question)
        )
        elapsed = time.monotonic() - start
        logger.info("Mention response in %.1fs (%d chars)", elapsed, len(response))
        await _send_long_message(update, response)
    except Exception:
        logger.exception("Error in mention handler")
        await update.message.reply_text(
            "Deu um erro aqui. Tenta de novo daqui a pouco."
        )


async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle replies to bot messages — continue the conversation."""
    if update.message is None or update.message.text is None:
        return
    if update.message.reply_to_message is None:
        return

    # Only respond if replying to a message from this bot
    bot_id = (await context.bot.get_me()).id
    if update.message.reply_to_message.from_user.id != bot_id:
        return

    question = update.message.text.strip()
    if not question:
        return

    logger.info("User %s replied to bot: %s", update.effective_user.first_name, question)
    start = time.monotonic()

    try:
        response = await _run_with_typing(
            update, asyncio.to_thread(rag_query, question)
        )
        elapsed = time.monotonic() - start
        logger.info("Reply response in %.1fs (%d chars)", elapsed, len(response))
        await _send_long_message(update, response)
    except Exception:
        logger.exception("Error in reply handler")
        await update.message.reply_text(
            "Deu um erro aqui. Tenta de novo daqui a pouco."
        )
