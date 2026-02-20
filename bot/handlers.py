"""Telegram bot command handlers."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.identity import ABOUT_TEXT, HELP_TEXT, BOT_USERNAME
from bot.exceptions import (
    RateLimitExceededError,
    RAGError,
    SearchError,
    TipsAIError,
)
from bot.feedback import create_feedback_keyboard, store_query_for_message
from bot.health import metrics
from bot.rate_limit import rate_limiter, RATE_LIMIT_MSG
from rag.pipeline import query as rag_query, semantic_search
from rag.search_parser import parse_search_query

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


def _check_rate_limit(update: Update) -> None:
    """Check rate limit for the user. Raises RateLimitExceededError if over limit."""
    user_id = update.effective_user.id
    if not rate_limiter.is_allowed(user_id):
        wait = rate_limiter.get_wait_time(user_id)
        raise RateLimitExceededError(wait)


async def _send_response_with_feedback(
    update: Update, text: str, question: str
) -> None:
    """Send a RAG response with feedback buttons attached."""
    keyboard = create_feedback_keyboard()
    if len(text) <= TG_MSG_LIMIT:
        sent = await update.message.reply_text(text, reply_markup=keyboard)
        store_query_for_message(sent.message_id, question)
    else:
        # For long messages, only attach buttons to the last chunk
        await _send_long_message(update, text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command with welcome message and quick-action buttons."""
    welcome_text = (
        "Fala! Eu sou o *TipsAI*, o assistente inteligente do "
        "*Invest Tips Daily* \U0001f9e0\n\n"
        "Sou a memória viva do grupo — posso responder perguntas, "
        "buscar conversas antigas, fazer resumos e muito mais.\n\n"
        "Escolhe uma opção abaixo pra começar ou manda /ajuda a qualquer momento:"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Fazer uma pergunta", callback_data="help_tips"),
            InlineKeyboardButton("Buscar no grupo", callback_data="help_buscar"),
        ],
        [
            InlineKeyboardButton("Ver ajuda", callback_data="help_ajuda"),
            InlineKeyboardButton("Status do bot", callback_data="help_status"),
        ],
    ])
    await update.message.reply_text(
        welcome_text, parse_mode="Markdown", reply_markup=keyboard,
    )


async def start_button_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle presses on the /start inline keyboard buttons."""
    query = update.callback_query
    await query.answer()

    responses = {
        "help_tips": (
            "\U0001f4ac *Fazer uma pergunta*\n\n"
            "Use o comando /tips seguido da sua pergunta. Exemplo:\n"
            "`/tips o que é staking?`\n\n"
            "Você também pode me marcar no grupo com @{bot_username} "
            "e a pergunta, ou simplesmente responder a uma mensagem minha."
        ),
        "help_buscar": (
            "\U0001f50d *Buscar no grupo*\n\n"
            "Use o comando /buscar seguido do termo. Exemplo:\n"
            "`/buscar CoinTech2U rendimento`\n\n"
            "Filtros opcionais:\n"
            "• `autor:Nome` — filtra por autor\n"
            "• `de:YYYY-MM-DD` — data inicial\n"
            "• `ate:YYYY-MM-DD` — data final\n\n"
            "Exemplo completo:\n"
            "`/buscar autor:Renan bitcoin de:2024-08-01 ate:2024-09-30`"
        ),
        "help_ajuda": (
            "\U0001f4cb *Comandos disponíveis*\n\n"
            "/tips <pergunta> — Pergunta livre ao bot\n"
            "/buscar <termo> — Busca semântica no histórico\n"
            "/resumo — Resumo das últimas conversas\n"
            "/health — Status e métricas do bot\n"
            "/sobre — Sobre o bot e o canal\n"
            "/ajuda — Lista completa de comandos"
        ),
        "help_status": (
            "\U00002699 *Status do bot*\n\n"
            "Para ver o status atual, métricas de uso e tempo de atividade "
            "do TipsAI, use o comando:\n"
            "`/health`"
        ),
    }

    data = query.data
    text = responses.get(data)
    if text is None:
        return

    username = await _get_bot_username(context)
    text = text.format(bot_username=username)
    await query.edit_message_text(text, parse_mode="Markdown")


async def cmd_tips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tips <pergunta> — free-form RAG question."""
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text(
            "Manda a pergunta junto! Exemplo: /tips o que é CoinTech2U?"
        )
        return

    user_id = update.effective_user.id
    logger.info("User %s asked /tips: %s", update.effective_user.first_name, question)
    start = time.monotonic()

    try:
        _check_rate_limit(update)
        response = await _run_with_typing(
            update, asyncio.to_thread(rag_query, question, user_id=user_id)
        )
        elapsed = time.monotonic() - start
        metrics.record_query(elapsed)
        logger.info("/tips response in %.1fs (%d chars)", elapsed, len(response))
        await _send_response_with_feedback(update, response, question)
    except RateLimitExceededError as exc:
        logger.info("Rate limit hit for user %s: %s", user_id, exc)
        await update.message.reply_text(RATE_LIMIT_MSG.format(seconds=exc.wait_seconds))
    except RAGError as exc:
        metrics.record_error()
        logger.error("%s in /tips handler: %s", type(exc).__name__, exc)
        await update.message.reply_text(
            "Deu um erro ao processar sua pergunta. Tenta de novo daqui a pouco."
        )
    except Exception:
        metrics.record_error()
        logger.exception("Unexpected %s in /tips handler", "error")
        await update.message.reply_text(
            "Deu um erro aqui. Tenta de novo daqui a pouco."
        )


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /buscar <termo> — semantic search in chat history.

    Supports inline filters:
        /buscar autor:Renan bitcoin de:2024-08-01 ate:2024-09-30
    """
    raw_term = " ".join(context.args) if context.args else ""
    if not raw_term:
        await update.message.reply_text(
            "Falta o termo de busca! Exemplo: /buscar CoinTech2U rendimento\n"
            "Filtros opcionais: autor:Nome de:YYYY-MM-DD ate:YYYY-MM-DD"
        )
        return

    parsed = parse_search_query(raw_term)
    search_text = parsed["text"]

    # Need at least some search text or a filter to proceed
    if not search_text and not parsed["author"] and not parsed["date_from"] and not parsed["date_to"]:
        await update.message.reply_text(
            "Falta o termo de busca! Exemplo: /buscar CoinTech2U rendimento"
        )
        return

    # If only filters and no text, use a broad query
    if not search_text:
        search_text = "mensagens do grupo"

    logger.info(
        "User %s searched: text=%r author=%s date_from=%s date_to=%s",
        update.effective_user.first_name,
        search_text,
        parsed["author"],
        parsed["date_from"],
        parsed["date_to"],
    )
    start = time.monotonic()

    try:
        _check_rate_limit(update)
        results = await _run_with_typing(
            update,
            asyncio.to_thread(
                semantic_search,
                search_text,
                5,
                author=parsed["author"],
                date_from=parsed["date_from"],
                date_to=parsed["date_to"],
            ),
        )
        elapsed = time.monotonic() - start
        metrics.record_query(elapsed)
        if not results:
            await update.message.reply_text(
                "Nao encontrei nada sobre isso no historico. "
                "Talvez o assunto nao tenha sido discutido no grupo ainda."
            )
            return

        # Build header showing active filters
        header = f"\U0001f50d Resultados para: {search_text}"
        filter_parts = []
        if parsed["author"]:
            filter_parts.append(f"autor={parsed['author']}")
        if parsed["date_from"]:
            filter_parts.append(f"de={parsed['date_from']}")
        if parsed["date_to"]:
            filter_parts.append(f"ate={parsed['date_to']}")
        if filter_parts:
            header += f" [{', '.join(filter_parts)}]"

        parts = [header + "\n"]
        for i, doc in enumerate(results, 1):
            authors = ", ".join(doc["authors"]) if isinstance(doc["authors"], list) else doc["authors"]
            text_preview = doc["text"][:200]
            if len(doc["text"]) > 200:
                text_preview += "..."
            score_pct = int(doc.get("score", 0) * 100)
            parts.append(f"{i}. [{score_pct}%] {authors} ({doc['start_time'][:10]}):\n{text_preview}\n")

        await _send_long_message(update, "\n".join(parts))
    except RateLimitExceededError as exc:
        logger.info("Rate limit hit for user %s: %s", update.effective_user.id, exc)
        await update.message.reply_text(RATE_LIMIT_MSG.format(seconds=exc.wait_seconds))
    except SearchError as exc:
        metrics.record_error()
        logger.error("%s in /buscar handler: %s", type(exc).__name__, exc)
        await update.message.reply_text(
            "Deu um erro na busca. Tenta de novo daqui a pouco."
        )
    except Exception:
        metrics.record_error()
        logger.exception("Unexpected %s in /buscar handler", "error")
        await update.message.reply_text(
            "Deu um erro na busca. Tenta de novo daqui a pouco."
        )


async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resumo — summary of recent relevant conversations."""
    logger.info("User %s requested /resumo", update.effective_user.first_name)
    start = time.monotonic()

    try:
        _check_rate_limit(update)
        response = await _run_with_typing(
            update,
            asyncio.to_thread(
                rag_query,
                "Faca um resumo breve das conversas mais recentes e relevantes do grupo, "
                "destacando os principais assuntos discutidos."
            ),
        )
        elapsed = time.monotonic() - start
        metrics.record_query(elapsed)
        await _send_long_message(update, response)
    except RateLimitExceededError as exc:
        logger.info("Rate limit hit for user %s: %s", update.effective_user.id, exc)
        await update.message.reply_text(RATE_LIMIT_MSG.format(seconds=exc.wait_seconds))
    except RAGError as exc:
        metrics.record_error()
        logger.error("%s in /resumo handler: %s", type(exc).__name__, exc)
        await update.message.reply_text(
            "Deu um erro ao gerar o resumo. Tenta de novo daqui a pouco."
        )
    except Exception:
        metrics.record_error()
        logger.exception("Unexpected %s in /resumo handler", "error")
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

    user_id = update.effective_user.id
    logger.info("User %s mentioned bot: %s", update.effective_user.first_name, question)
    start = time.monotonic()

    try:
        _check_rate_limit(update)
        response = await _run_with_typing(
            update, asyncio.to_thread(rag_query, question, user_id=user_id)
        )
        elapsed = time.monotonic() - start
        metrics.record_query(elapsed)
        logger.info("Mention response in %.1fs (%d chars)", elapsed, len(response))
        await _send_response_with_feedback(update, response, question)
    except RateLimitExceededError as exc:
        logger.info("Rate limit hit for user %s: %s", user_id, exc)
        await update.message.reply_text(RATE_LIMIT_MSG.format(seconds=exc.wait_seconds))
    except RAGError as exc:
        metrics.record_error()
        logger.error("%s in mention handler: %s", type(exc).__name__, exc)
        await update.message.reply_text(
            "Deu um erro ao processar sua pergunta. Tenta de novo daqui a pouco."
        )
    except Exception:
        metrics.record_error()
        logger.exception("Unexpected %s in mention handler", "error")
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

    user_id = update.effective_user.id
    logger.info("User %s replied to bot: %s", update.effective_user.first_name, question)
    start = time.monotonic()

    try:
        _check_rate_limit(update)
        response = await _run_with_typing(
            update, asyncio.to_thread(rag_query, question, user_id=user_id)
        )
        elapsed = time.monotonic() - start
        metrics.record_query(elapsed)
        logger.info("Reply response in %.1fs (%d chars)", elapsed, len(response))
        await _send_response_with_feedback(update, response, question)
    except RateLimitExceededError as exc:
        logger.info("Rate limit hit for user %s: %s", user_id, exc)
        await update.message.reply_text(RATE_LIMIT_MSG.format(seconds=exc.wait_seconds))
    except RAGError as exc:
        metrics.record_error()
        logger.error("%s in reply handler: %s", type(exc).__name__, exc)
        await update.message.reply_text(
            "Deu um erro ao processar sua pergunta. Tenta de novo daqui a pouco."
        )
    except Exception:
        metrics.record_error()
        logger.exception("Unexpected %s in reply handler", "error")
        await update.message.reply_text(
            "Deu um erro aqui. Tenta de novo daqui a pouco."
        )
