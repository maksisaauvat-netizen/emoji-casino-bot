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

# Активные игры пользователей.
games = {}


# =========================
# МЕНЮ ИГР
# =========================

def games_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | Кубики",
                    callback_data="game_dice",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎡 | Рулетка",
                    callback_data="game_roulette",
                )
            ],
        ]
    )


# =========================
# КУБИКИ
# =========================

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
                    text="🎡 | Рулетка",
                    callback_data="game_roulette",
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


# =========================
# РУЛЕТКА
# =========================

def roulette_bets():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Красное x2",
                    callback_data="roulette_red",
                ),
                InlineKeyboardButton(
                    text="⚫ Чёрное x2",
                    callback_data="roulette_black",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬆️ 1–18 x2",
                    callback_data="roulette_low",
                ),
                InlineKeyboardButton(
                    text="⬇️ 19–36 x2",
                    callback_data="roulette_high",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚪ Чётное x2",
                    callback_data="roulette_even",
                ),
                InlineKeyboardButton(
                    text="🟣 Нечётное x2",
                    callback_data="roulette_odd",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🟢 Зеро x36",
                    callback_data="roulette_zero",
                )
            ],
        ]
    )


def roulette_again_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎡 | Крутить ещё раз",
                    callback_data="game_roulette",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎲 | Кубики",
                    callback_data="game_dice",
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


# Европейская рулетка.
RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36,
}


def roulette_color(number):
    if number == 0:
        return "🟢"

    if number in RED_NUMBERS:
        return "🔴"

    return "⚫"


def roulette_bet_name(bet):
    names = {
        "red": "🔴 Красное",
        "black": "⚫ Чёрное",
        "low": "⬆️ 1–18",
        "high": "⬇️ 19–36",
        "even": "⚪ Чётное",
        "odd": "🟣 Нечётное",
        "zero": "🟢 Зеро",
    }

    return names.get(bet, "Неизвестная ставка")


# =========================
# НАЧАЛО РУЛЕТКИ
# =========================

async def start_roulette(callback):
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

    # Ставка списывается только после выбора ставки,
    # поэтому здесь пока ничего не списываем.

    await callback.answer()

    await callback.message.answer(
        f"🎡 Рулетка\n\n"
        f"Ставка: 100 💎\n"
        f"💎 Баланс: {balance} 💎\n\n"
        f"Выбери ставку:",
        reply_markup=roulette_bets(),
    )


# =========================
# НАЧАЛО ИГРЫ В КУБИКИ
# =========================

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
        "type": "dice",
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


# =========================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================

@dp.message()
async def message_handler(message):
    user_id = message.from_user.id

    # /start
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

    # =========================
    # НАСТОЯЩИЙ TELEGRAM DICE
    # =========================

    if message.dice is not None:

        dice = message.dice

        if dice.emoji != "🎲":
            return

        game = games.get(user_id)

        if not game:
            return

        if game.get("type") != "dice":
            return

        if game["mode"] is None:
            return

        if game["prediction"] is None:
            return

        result = dice.value

        # =========================
        # 1 КУБИК
        # =========================

        if game["mode"] == 1:

            if game["completed"]:
                return

            game["completed"] = True

            prediction = game["prediction"]

            if prediction == "less":
                win = result < 3
            else:
                win = result > 3

            coefficient = 1.85
            payout = 185 if win else 0

            if payout > 0:
                balance = change_balance(
                    user_id,
                    payout,
                )
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

            if "first_dice" not in game:

                game["first_dice"] = result

                await message.answer(
                    f"🎲 Первый кубик: {result}\n\n"
                    f"Отправь 🎲 ещё раз — "
                    f"это будет второй кубик."
                )

                return

            first = game["first_dice"]
            second = result
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

            payout = 500 if win and coefficient == 5.00 else (
                185 if win else 0
            )

            if payout > 0:
                balance = change_balance(
                    user_id,
                    payout,
                )
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


# =========================
# CALLBACK-КНОПКИ
# =========================

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
    # РУЛЕТКА
    # =========================

    if callback.data == "game_roulette":
        await start_roulette(callback)
        return

    # =========================
    # СТАВКИ РУЛЕТКИ
    # =========================

    roulette_callbacks = {
        "roulette_red": "red",
        "roulette_black": "black",
        "roulette_low": "low",
        "roulette_high": "high",
        "roulette_even": "even",
        "roulette_odd": "odd",
        "roulette_zero": "zero",
    }

    if callback.data in roulette_callbacks:

        # Нельзя начать рулетку поверх другой игры.
        if user_id in games:
            await callback.answer(
                "🎡 У тебя уже есть активная игра.",
                show_alert=True,
            )
            return

        bet = roulette_callbacks[callback.data]

        balance = get_balance(user_id)

        if balance < 100:
            await callback.answer(
                "❌ Недостаточно монет.",
                show_alert=True,
            )
            return

        # Списываем ставку.
        success = subtract_balance(
            user_id,
            100,
        )

        if not success:
            await callback.answer(
                "❌ Недостаточно монет.",
                show_alert=True,
            )
            return

        # Сохраняем раунд.
        games[user_id] = {
            "type": "roulette",
            "stake": 100,
            "bet": bet,
            "completed": False,
        }

        await callback.answer()

        # Генерируем результат.
        number = random.randint(0, 36)

        color = roulette_color(number)

        win = False

        if bet == "red":
            win = number in RED_NUMBERS

        elif bet == "black":
            win = number != 0 and number not in RED_NUMBERS

        elif bet == "low":
            win = 1 <= number <= 18

        elif bet == "high":
            win = 19 <= number <= 36

        elif bet == "even":
            win = number != 0 and number % 2 == 0

        elif bet == "odd":
            win = number != 0 and number % 2 == 1

        elif bet == "zero":
            win = number == 0

        if bet == "zero":
            coefficient = 36.0
        else:
            coefficient = 2.0

        payout = (
            int(100 * coefficient)
            if win
            else 0
        )

        if payout > 0:
            balance = change_balance(
                user_id,
                payout,
            )
        else:
            balance = get_balance(user_id)

        games.pop(user_id, None)

        result_text = (
            "🎉 ПОБЕДА!"
            if win
            else "❌ Проигрыш"
        )

        await callback.message.answer(
            f"🎡 РУЛЕТКА\n\n"
            f"Выпало: {number} {color}\n\n"
            f"Твоя ставка: "
            f"{roulette_bet_name(bet)}\n"
            f"Ставка: 100 💎\n"
            f"Коэффициент: x{coefficient:.0f}\n\n"
            f"{result_text}\n"
            f"Выплата: {payout} 💎\n\n"
            f"💎 Баланс: {balance} 💎",
            reply_markup=roulette_again_keyboard(),
        )

        return

    # =========================
    # 1 БРОСОК
    # =========================

    if callback.data == "dice_mode_1":

        game = games.get(user_id)

        if not game or game.get("type") != "dice":
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

        if not game or game.get("type") != "dice":
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
    # ПРОГНОЗ КУБИКОВ
    # =========================

    if callback.data in (
        "dice_one_less",
        "dice_one_more",
        "dice_two_less",
        "dice_two_equal",
        "dice_two_more",
    ):

        game = games.get(user_id)

        if not game or game.get("type") != "dice":
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

        game.pop("first_dice", None)

        await callback.answer()

        if game["mode"] == 1:
            await callback.message.answer(
                "🎲 Отправь эмодзи 🎲, "
                "чтобы бросить кубик."
            )
        else:
            await callback.message.answer(
                "🎲 Отправь эмодзи 🎲, "
                "чтобы бросить первый кубик."
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


# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def startup():

    init_db()

    webhook_url = (
        f"{RENDER_URL}/webhook/{WEBHOOK_SECRET}"
    )

    print(
        "SETTING WEBHOOK:",
        webhook_url,
    )

    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=False,
        allowed_updates=[
            "message",
            "callback_query",
        ],
    )

    info = await bot.get_webhook_info()

    print(
        "WEBHOOK URL:",
        info.url,
    )

    print(
        "PENDING UPDATES:",
        info.pending_update_count,
    )

    print(
        "LAST ERROR:",
        info.last_error_message,
    )


# =========================
# SHUTDOWN
# =========================

@app.on_event("shutdown")
async def shutdown():

    # Webhook НЕ удаляем.
    await bot.session.close()


# =========================
# HEALTH CHECK
# =========================

@app.get("/")
async def home():
    return {
        "status": "ok"
    }


# =========================
# TELEGRAM WEBHOOK
# =========================

@app.post("/webhook/{secret}")
async def webhook(
    secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None
    ),
):

    print("=== WEBHOOK ===")

    if secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=403
        )

    if (
        x_telegram_bot_api_secret_token
        != WEBHOOK_SECRET
    ):
        raise HTTPException(
            status_code=403
        )

    data = await request.json()

    print(
        "UPDATE RECEIVED:",
        data,
    )

    update = Update.model_validate(
        data,
        context={
            "bot": bot
        },
    )

    await dp.feed_update(
        bot,
        update,
    )

    return {
        "ok": True
    }
