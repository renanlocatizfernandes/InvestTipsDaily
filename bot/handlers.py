"""Telegram bot command handlers."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.identity import ABOUT_TEXT, HELP_TEXT, BOT_USERNAME
from rag.pipeline import query as rag_query, semantic_search

logger = logging.getLogger(__name__)


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

    await update.message.chat.send_action("typing")

    try:
        response = rag_query(question)
        await update.message.reply_text(response)
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

    await update.message.chat.send_action("typing")

    try:
        results = semantic_search(term, top_k=5)
        if not results:
            await update.message.reply_text(
                "Não encontrei nada sobre isso no histórico. "
                "Talvez o assunto não tenha sido discutido no grupo ainda."
            )
            return

        parts = [f"\U0001f50d *Resultados para:* _{term}_\n"]
        for i, doc in enumerate(results, 1):
            authors = ", ".join(doc["authors"]) if isinstance(doc["authors"], list) else doc["authors"]
            # Truncate text for readability
            text_preview = doc["text"][:300]
            if len(doc["text"]) > 300:
                text_preview += "..."
            parts.append(f"*{i}.* {authors} ({doc['start_time'][:10]}):\n{text_preview}\n")

        await update.message.reply_text(
            "\n".join(parts),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Error in /buscar handler")
        await update.message.reply_text(
            "Deu um erro na busca. Tenta de novo daqui a pouco."
        )


async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resumo — summary of recent relevant conversations."""
    await update.message.chat.send_action("typing")

    try:
        response = rag_query(
            "Faça um resumo breve das conversas mais recentes e relevantes do grupo, "
            "destacando os principais assuntos discutidos."
        )
        await update.message.reply_text(response)
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
    bot_user = await context.bot.get_me()
    text = HELP_TEXT.format(bot_username=bot_user.username or BOT_USERNAME)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages that mention the bot — treat as /tips."""
    if update.message is None or update.message.text is None:
        return

    bot_user = await context.bot.get_me()
    bot_mention = f"@{bot_user.username}" if bot_user.username else None

    text = update.message.text
    # Remove the mention to get the question
    if bot_mention and bot_mention.lower() in text.lower():
        question = text.replace(bot_mention, "").replace(f"@{bot_user.username}", "").strip()
    else:
        return  # Not actually a mention of us

    if not question:
        await update.message.reply_text(
            "Fala! Me marca com uma pergunta que eu respondo. "
            "Exemplo: @{} o que é staking?".format(bot_user.username)
        )
        return

    await update.message.chat.send_action("typing")

    try:
        response = rag_query(question)
        await update.message.reply_text(response)
    except Exception:
        logger.exception("Error in mention handler")
        await update.message.reply_text(
            "Deu um erro aqui. Tenta de novo daqui a pouco."
        )
