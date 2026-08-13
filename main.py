import src.core.env as env
import src.core.supabase as supabase
import src.app as app_telegram_handler

from loguru import logger
from fastapi import FastAPI, Request, Response, status
from contextlib import asynccontextmanager

from src.repository.chat_repository import ChatRepository

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    Defaults,
)
from telegram.constants import ParseMode  # MarkdownV2
from zoneinfo import ZoneInfo  # WIB - Asia/Jakarta

timezone = ZoneInfo("Asia/Jakarta")

bot_config = Defaults(parse_mode=ParseMode.MARKDOWN_V2, tzinfo=timezone)
bot_app = (
    Application.builder().token(env.TELEGRAM_BOT_TOKEN).defaults(bot_config).build()
)

chat_repository = ChatRepository()


# register route handler
bot_app.add_handler(CommandHandler("start", app_telegram_handler.start_command))
bot_app.add_handler(CommandHandler("report", app_telegram_handler.report_command))
bot_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, app_telegram_handler.handle_text)
)
bot_app.add_handler(MessageHandler(filters.VOICE, app_telegram_handler.handle_voice))
bot_app.add_error_handler(app_telegram_handler.error_handler)

supabase_client = supabase.get_supabase_client()


@asynccontextmanager
async def lifespan(app: FastAPI):

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.bot.set_webhook(
        url=f"{env.TELEGRAM_WEBHOOK_URL}",
        secret_token=env.TELEGRAM_SECRET_TOKEN,
        connect_timeout=30,
    )
    yield
    await bot_app.bot.delete_webhook()
    await bot_app.stop()
    await bot_app.shutdown()


app = FastAPI(lifespan=lifespan)


# Telegram webhook
@app.post(f"/webhook/{env.TELEGRAM_BOT_TOKEN}")
async def telegram_webhook(request: Request):
    if (
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        != env.TELEGRAM_SECRET_TOKEN
    ):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        req_body = await request.json()

        # Convert raw JSON dictionary to a formal python-telegram-bot (Update)
        update = Update.de_json(req_body, bot_app.bot)
        await bot_app.process_update(update)

        logger.info(req_body)
        return Response(status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Health-check
@app.get("/health-check")
async def root():
    return {"status": "OK", "message": "Bot is active!"}
