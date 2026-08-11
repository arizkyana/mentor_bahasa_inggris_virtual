import src.core.env as env

from loguru import logger
from fastapi import FastAPI, Request, Response, status
from contextlib import asynccontextmanager

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

bot_app = Application.builder().token(env.TELEGRAM_BOT_TOKEN).build()


async def start(update: Update, context: ContextTypes):
    logger.info("masuk start")
    await update.message.reply_text("Hello!, webhook is working here with FastAPI")


bot_app.add_handler(CommandHandler("start", start))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.debug(f"Telegram Bot Token: {env.TELEGRAM_BOT_TOKEN}")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.bot.set_webhook(
        url=f"{env.TELEGRAM_WEBHOOK_URL}/webhook/{env.TELEGRAM_BOT_TOKEN}",
        secret_token="secret123",
    )
    yield
    await bot_app.bot.delete_webhook()
    await bot_app.stop()
    await bot_app.shutdown()


app = FastAPI(lifespan=lifespan)


# Telegram webhook
@app.post(f"/webhook/{env.TELEGRAM_BOT_TOKEN}")
async def telegram_webhook(request: Request):
    logger.debug(request.headers.get("X-Telegram-Bot-Api-Secret-Token"))
    # if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != env.TELEGRAM_BOT_TOKEN:
    #     return Response(status_code=status.HTTP_403_FORBIDDEN)
    try:
        req_body = await request.json()

        # Convert raw JSON dictionary to a formal python-telegram-bot (Update)
        update = Update.de_json(req_body, bot_app.bot)
        await bot_app.process_update(update)

        logger.info(f"telegram_webhook: {req_body}")
        return Response(status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Health-check
@app.get("/health-check")
async def root():
    return {"status": "OK", "message": "Bot is active!"}
