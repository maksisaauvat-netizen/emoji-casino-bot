import os
import random

from fastapi import FastAPI, Request, Header, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


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

# Активные игры пользователей
games = {}


def games_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | Кубики",
                    callback_data="game_dice",
                )
            ]
        ]
    )


def dice_modes():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 1 бросок",
                    callback_data="dice_mode_1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎲 2 броска",
                    callback_data="dice_mode_2",
                )
            ],
        ]
    )


def dice_one_predictions():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="x1.85 | Меньше 3",
                    callback_data="dice_one_less",
                )
            ],
            [
                InlineKeyboardButton(
                    text="x1.85 | Больше 3",
                    callback_data="dice_one_more",
                )
            ],
        ]
    )


def dice_two_predictions():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="x1.85 | Меньше 7",
                    callback_data="dice_two_less",
                )
            ],
            [
                InlineKeyboardButton(
                    text="x5.00 | Равно 7",
                    callback_data="dice_two_equal",
                )
            ],
            [
                InlineKeyboardButton(
                    text="x1.85 | Больше 7",
                    callback_data="dice_two_more",
                )
            ],
        ]
    )


def after_game_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | Бросить ещё раз",
                    callback_data="dice_again",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ | К играм",
                    callback_data="games_menu",
                )
            ],
        ]
    )


async def start_dice_game(callback):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "🎲 У тебя уже есть активная игра.",
            show_alert=True,
        )
        return

    balance = get_balance(user_id)

    if balance < 100:
        await callback.answer(
            "❌ Недостаточно монет.",
            show_alert=True,
        )
        return

    success = subtract_balance(user_id, 100)

    if not success:
        await callback.answer(
            "❌ Недостаточно монет.",
            show_alert=True,
        )
        return

    games[user_id] = {
        "stake": 100,
        "mode": None,
        "prediction": None,
        "completed": False,
    }

    new_balance = get_balance(user_id)

    await callback.answer()

    await callback.message.answer(
        f"🎲 Кубики\n\n"
        f"Ставка: 100 💎\n"
        f"💎 Баланс: {new_balance} 💎\n\n"
        f"Выбери режим:",
        reply_markup=dice_modes(),
    )


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
                        callback_data="play",
                    )
                ]
            ]
        )

        await message.answer(
            f"🎰 Привет!\n\n"
            f"Добро пожаловать в Emoji Casino!\n\n"
            f"💰 Твой баланс: {balance} монет",
            reply_markup=keyboard,
        )
        return

    # Распознаём сообщение с эмодзи кубика.
    # Используем поиск по тексту, а не строгое сравнение.
    if message.text and "🎲" in message.text:
        game = games.get(user_id)

        if not game:
            return

        if game["completed"]:
            return

        if game["mode"] is None or game["prediction"] is None:
            return

        # Сразу закрываем раунд,
        # чтобы повторное сообщение не дало вторую выплату.
        game["completed"] = True

        # =========================
        # 1 КУБИК
        # =========================
        if game["mode"] == 1:
            result = random.randint(1, 6)

            prediction = game["prediction"]

            if prediction == "less":
                win = result in (1, 2)
            else:
                win = result in (4, 5, 6)

            coefficient = 1.85
            payout = 185 if win else 0

            if payout > 0:
                balance = change_balance(user_id, payout)
            else:
                balance = get_balance(user_id)

            games.pop(user_id, None)

            await message.answer(
                f"🎲 Результат: {result}\n\n"
                f"Ставка: 100 💎\n"
                f"Коэффициент: x{coefficient:.2f}\n"
                f"Выплата: {payout} 💎\n\n"
                f"💎 Баланс: {balance} 💎",
                reply_markup=after_game_keyboard(),
            )
            return

        # =========================
        # 2 КУБИКА
        # =========================
        if game["mode"] == 2:
            first = random.randint(1, 6)
            second = random.randint(1, 6)
            total = first + second

            prediction = game["prediction"]

            if prediction == "less":
                win = total < 7
                coefficient = 1.85

            elif prediction == "equal":
                win = total == 7
                coefficient = 5.00

            else:
                win = total > 7
                coefficient = 1.85

            if win:
                if coefficient == 5.00:
                    payout = 500
                else:
                    payout = 185
            else:
                payout = 0

            if payout > 0:
                balance = change_balance(user_id, payout)
            else:
                balance = get_balance(user_id)

            games.pop(user_id, None)

            await message.answer(
                f"🎲 Результат: {first} + {second} = {total}\n\n"
                f"Ставка: 100 💎\n"
                f"Коэффициент: x{coefficient:.2f}\n"
                f"Выплата: {payout} 💎\n\n"
                f"💎 Баланс: {balance} 💎",
                reply_markup=after_game_keyboard(),
            )
            return


@dp.callback_query()
async def callback_handler(callback):
    print("CALLBACK RECEIVED:", callback.data)

    user_id = callback.from_user.id

    # =========================
    # ИГРАТЬ
    # =========================
    if callback.data == "play":
        balance = get_balance(user_id)

        await callback.answer()

        await callback.message.answer(
            f"🎰 Игры\n\n"
            f"💎 Баланс: {balance} 💎\n\n"
            f"Выбери игру:",
            reply_markup=games_menu(),
        )
        return

    # =========================
    # КУБИКИ
    # =========================
    if callback.data == "game_dice":
        await start_dice_game(callback)
        return

    # =========================
    # 1 БРОСОК
    # =========================
    if callback.data == "dice_mode_1":
        game = games.get(user_id)

        if not game:
            await callback.answer(
                "❌ Игра не найдена.",
                show_alert=True,
            )
            return

        game["mode"] = 1

        await callback.answer()

        await callback.message.answer(
            "🎲 1 бросок\n\n"
            "Выбери прогноз:",
            reply_markup=dice_one_predictions(),
        )
        return

    # =========================
    # 2 БРОСКА
    # =========================
    if callback.data == "dice_mode_2":
        game = games.get(user_id)

        if not game:
            await callback.answer(
                "❌ Игра не найдена.",
                show_alert=True,
            )
            return

        game["mode"] = 2

        await callback.answer()

        await callback.message.answer(
            "🎲 2 броска\n\n"
            "Выбери прогноз:",
            reply_markup=dice_two_predictions(),
        )
        return

    # =========================
    # ПРОГНОЗ
    # =========================
    if callback.data in (
        "dice_one_less",
        "dice_one_more",
        "dice_two_less",
        "dice_two_equal",
        "dice_two_more",
    ):
        game = games.get(user_id)

        if not game:
            await callback.answer(
                "❌ Игра не найдена.",
                show_alert=True,
            )
            return

        if game["mode"] == 1:
            if callback.data == "dice_one_less":
                game["prediction"] = "less"
            else:
                game["prediction"] = "more"

        elif game["mode"] == 2:
            if callback.data == "dice_two_less":
                game["prediction"] = "less"

            elif callback.data == "dice_two_equal":
                game["prediction"] = "equal"

            else:
                game["prediction"] = "more"

        await callback.answer()

        if game["mode"] == 1:
            await callback.message.answer(
                "🎲 Отправь эмодзи 🎲, чтобы бросить кубик."
            )
        else:
            await callback.message.answer(
                "🎲 Отправь эмодзи 🎲, чтобы бросить кубики."
            )

        return

    # =========================
    # БРОСИТЬ ЕЩЁ РАЗ
    # =========================
    if callback.data == "dice_again":
        await start_dice_game(callback)
        return

    # =========================
    # К ИГРАМ
    # =========================
    if callback.data == "games_menu":
        games.pop(user_id, None)

        balance = get_balance(user_id)

        await callback.answer()

        await callback.message.answer(
            f"🎰 Игры\n\n"
            f"💎 Баланс: {balance} 💎\n\n"
            f"Выбери игру:",
            reply_markup=games_menu(),
        )
        return

    await callback.answer()


@app.on_event("startup")
async def startup():
    init_db()

    webhook_url = f"{RENDER_URL}/webhook/{WEBHOOK_SECRET}"

    print("SETTING WEBHOOK:", webhook_url)

    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=False,
        allowed_updates=["message", "callback_query"],
    )

    info = await bot.get_webhook_info()

    print("WEBHOOK URL:", info.url)
    print("PENDING UPDATES:", info.pending_update_count)
    print("LAST ERROR:", info.last_error_message)


@app.on_event("shutdown")
async def shutdown():
    # НЕ удаляем webhook при перезапуске Render.
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
    print("=== WEBHOOK ===")

    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    data = await request.json()

    print("UPDATE RECEIVED:", data)

    update = Update.model_validate(
        data,
        context={"bot": bot},
    )

    await dp.feed_update(bot, update)

    return {"ok": True}
