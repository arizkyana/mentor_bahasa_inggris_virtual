import src.core.env as env

import os
import random

from zoneinfo import ZoneInfo  # WIB - Asia/Jakarta

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    Application,
    CommandHandler,  # /start /report
    MessageHandler,  # text atau suara (voice note)
    Defaults,
    filters,
)

from telegram.constants import ParseMode  # MarkdownV2
from loguru import logger
from datetime import time, date, timedelta  # generate - per 1 minggu / 7 hari

from src.agents import LeadAgent
from src.repository.chat_repository import ChatRepository
from src.core.format import to_telegram_markdown
from src.core.artifacts import Artifact

timezone = ZoneInfo("Asia/Jakarta")

chat_repository = ChatRepository()
lead_agent = LeadAgent()

# python-telegram-bot config
bot_config = Defaults(parse_mode=ParseMode.MARKDOWN_V2, tzinfo=timezone)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass


def run():
    app = (
        Application.builder().token(env.TELEGRAM_BOT_TOKEN).defaults(bot_config).build()
    )

    # register route handler
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("report", report_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("Mentor Bahasa Inggris Virtual berhasil di jalankan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)
