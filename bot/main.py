"""TipsAI Telegram bot entry point."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import (
    cmd_ajuda,
    cmd_buscar,
    cmd_resumo,
    cmd_sobre,
    cmd_start,
    cmd_tips,
    handle_mention,
)

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set. Exiting.")
        raise SystemExit(1)

    app = ApplicationBuilder().token(token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("tips", cmd_tips))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("sobre", cmd_sobre))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))

    # Handle @mentions in group messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Entity("mention"),
            handle_mention,
        )
    )

    logger.info("TipsAI bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
