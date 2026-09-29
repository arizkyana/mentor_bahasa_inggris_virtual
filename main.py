# 1 import semua package yang diperlukan

import src.core.env as env
import src.core.supabase as supabase
import src.app as app_telegram_bot


from loguru import logger
from fastapi import FastAPI, Request, Response, status
from contextlib import asynccontextmanager

from src.repository.chat_repository import ChatRepository

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, Defaults

from telegram.constants import ParseMode
from zoneinfo import ZoneInfo

from datetime import time

# 2. setup app_bot
timezone = ZoneInfo("Asia/Jakarta")

bot_config = Defaults(parse_mode=ParseMode.MARKDOWN_V2, tzinfo=timezone)
app_bot = (
    Application.builder().token(env.TELEGRAM_BOT_TOKEN).defaults(bot_config).build()
)

# register telegram bot handler
app_bot.add_handler(CommandHandler("start", app_telegram_bot.start_command))
app_bot.add_handler(CommandHandler("report", app_telegram_bot.report_command))

app_bot.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, app_telegram_bot.handle_text)
)
app_bot.add_handler(MessageHandler(filters.VOICE, app_telegram_bot.handle_voice))

# reminder
target_time = time(hour=8, minute=0, second=0, tzinfo=timezone)
app_bot.job_queue.run_daily(
    callback=app_telegram_bot.task_reminder, time=target_time, name="task_reminder"
)

app_bot.add_error_handler(app_telegram_bot.error_handler)

chat_repository = ChatRepository()
supabase_client = supabase.get_supabase_client()


# Expensive startup
# server API ini perlu untuk menjalankan service telegram bot sebelum server API dapat membuka layanan endpoint-endpoint API nya
# perlu di gambarin di excalidraw
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. executed once before the application starts receiving request
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.bot.set_webhook(
        url=f"{env.TELEGRAM_WEBHOOK_URL}",
        secret_token=env.TELEGRAM_SECRET_TOKEN,
        connect_timeout=30,  # seconds
    )
    yield
    # 2. executed once after the application finishes handling requests
    await app_bot.bot.delete_webhook()
    await app_bot.stop()
    await app_bot.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ini dari root"}  # json


@app.get("/get")
async def endpoint_get():
    return {"http_method": "get"}


# http request -> get dan post
@app.post("/post")
async def endpoint_post():
    return {"http_method": "post"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    # checking value of secret token
    api_secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if api_secret_token != env.TELEGRAM_SECRET_TOKEN:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        req_body = await request.json()

        # Convert server telegram's data into a formal python-telegram-bot
        telegram_bot_data = Update.de_json(req_body, app_bot.bot)
        await app_bot.process_update(telegram_bot_data)

        return Response(
            status_code=status.HTTP_200_OK
        )  # Telegram Bot Server is letting know Telegram Server that the response is OK (200) without any data
    except Exception as e:
        # Once error happen, tell to Telegram Server that our server is error
        # meanwhile, we can log the error too
        logger.error(f"Error processing telegram bot data: {e}")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
