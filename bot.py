import os

from fastapi import FastAPI, Request, Header, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import Update, InlineKeyboardMarkup, InlineKeyboardButton


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

balances = {}


def get_balance(user_id):
    if user_id not in balances:
        balances[user_id] = 1000
    return balances[user_id]


@dp.message()
async def message_handler(message):
    user_id = message.from_user.id

    if message.text == "/start":
        balance = get_balance(user_id)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎰 Играть",
                        callback_data="play"
                    )
                ]
            ]
        )

        await message.answer(
            f"🎰 Привет!\n\n"
            f"Добро пожаловать в Emoji Casino!\n\n"
            f"💰 Твой баланс: {balance} монет",
            reply_markup=keyboard
        )


@dp.callback_query()
async def callback_handler(callback):
    user_id = callback.from_user.id

    if callback.data == "play":
        balance = get_balance(user_id)

        await callback.answer()

        await callback.message.answer(
            f"🎰 Игра начинается!\n\n"
            f"💰 Твой баланс: {balance} монет"
        )


@app.on_event("startup")
async def startup():
    webhook_url = f"{RENDER_URL}/webhook/{WEBHOOK_SECRET}"
    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET
    )


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
