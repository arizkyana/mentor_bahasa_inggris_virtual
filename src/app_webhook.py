from loguru import logger
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

import src.core.env as env


async def start(update: Update, context: ContextTypes):

    await update.message.reply_text("Hello!, Webhook is working here")


def run():
    application = Application.builder().token(env.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    logger.info(
        f"python telegram bot webhook is running on: {env.TELEGRAM_WEBHOOK_URL}/{env.TELEGRAM_BOT_TOKEN}"
    )

    # Start webhook
    application.run_webhook(
        listen=env.BOT_HOST,
        port=env.BOT_PORT,
        url_path=env.TELEGRAM_BOT_TOKEN,
        webhook_url=f"{env.TELEGRAM_WEBHOOK_URL}/{env.TELEGRAM_BOT_TOKEN}",
    )
