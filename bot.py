import os

from fastapi import FastAPI, Request, Header, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import Update


TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is not set")

if not RENDER_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL is not set")


bot = Bot(TOKEN)
dp = Dispatcher()
app = FastAPI()


@dp.message()
async def message_handler(message):
    if message.text == "/start":
        await message.answer(
            "🎰 Привет!\n\n"
            "Добро пожаловать в Emoji Casino!"
        )


@app.on_event("startup")
async def startup():
    webhook_url = f"{RENDER_URL}/webhook/{WEBHOOK_SECRET}"
    await bot.set_webhook(webhook_url)


@app.on_event("shutdown")
async def shutdown():
    await bot.delete_webhook()
    await bot.session.close()


@app.get("/")
async def home():
    return {"status": "ok"}


@app.post("/webhook/{secret}")
async def webhook(
    secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    data = await request.json()

    update = Update.model_validate(
        data,
        context={"bot": bot}
    )

    await dp.feed_update(bot, update)

    return {"ok": True}
