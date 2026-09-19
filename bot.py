import os
import random
import asyncio

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

BASE_URL = "https://emoji-casino-bot.onrender.com"

STAKE = 100

SLOT_TWO_MULTIPLIER = 1.85
SLOT_THREE_MULTIPLIER = 3.5

ROULETTE_MULTIPLIER = 1.95
ROULETTE_ZERO_MULTIPLIER = 36


# =========================
# BOT / DISPATCHER
# =========================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()
app = FastAPI()

games = {}


# =========================
# КЛАВИАТУРЫ
# =========================

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Кубики",
                    callback_data="game_dice"
                ),
                InlineKeyboardButton(
                    text="🎡 Рулетка",
                    callback_data="game_roulette"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎰 Слоты",
                    callback_data="game_slots"
                ),
            ],
        ]
    )


def dice_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Бросить кубики",
                    callback_data="dice_start"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                )
            ],
        ]
    )


def roulette_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Красное x1.95",
                    callback_data="roulette_red"
                ),
                InlineKeyboardButton(
                    text="⚫ Чёрное x1.95",
                    callback_data="roulette_black"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬆️ 1–18 x1.95",
                    callback_data="roulette_low"
                ),
                InlineKeyboardButton(
                    text="⬇️ 19–36 x1.95",
                    callback_data="roulette_high"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚪ Чётное x1.95",
                    callback_data="roulette_even"
                ),
                InlineKeyboardButton(
                    text="🟣 Нечётное x1.95",
                    callback_data="roulette_odd"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🟢 Зеро x36",
                    callback_data="roulette_zero"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                )
            ],
        ]
    )


def slots_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎰 Крутить",
                    callback_data="slots_spin"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                )
            ],
        ]
    )


def after_game_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Играть снова",
                    callback_data="play_again"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                )
            ],
        ]
    )


# =========================
# /START
# =========================

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id

    balance = get_balance(user_id)

    await message.answer(
        "🎰 <b>Добро пожаловать в Emoji Casino!</b>\n\n"
        f"💰 Ваш баланс: <b>{balance}</b>\n\n"
        "Выберите игру:",
        reply_markup=main_menu()
    )


# =========================
# ИГРЫ
# =========================

@dp.callback_query(F.data == "games")
async def games_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎮 <b>Игры</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выберите игру:",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# КУБИКИ
# =========================

@dp.callback_query(F.data == "game_dice")
async def game_dice_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎲 <b>Кубики</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        f"Ставка: <b>{STAKE}</b>\n\n"
        "Нажмите «Бросить кубики».",
        reply_markup=dice_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_start")
async def dice_start_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств!",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice",
        "first_dice": None,
    }

    await callback.message.answer(
        "🎲 <b>Бросьте первый кубик!</b>"
    )

    await callback.answer()


# =========================
# РУЛЕТКА
# =========================

@dp.callback_query(F.data == "game_roulette")
async def game_roulette_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎡 <b>Рулетка</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"
        "Выберите ставку:",
        reply_markup=roulette_menu()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "roulette_red",
        "roulette_black",
        "roulette_low",
        "roulette_high",
        "roulette_even",
        "roulette_odd",
        "roulette_zero",
    })
)
async def roulette_bet_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    bet = callback.data

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств!",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "roulette",
        "bet": bet,
    }

    await callback.message.answer(
        "🎡 <b>Рулетка запускается...</b>"
    )

    await asyncio.sleep(0.5)

    number = random.randint(0, 36)

    red_numbers = {
        1, 3, 5, 7, 9,
        12, 14, 16, 18,
        19, 21, 23, 25, 27,
        30, 32, 34, 36
    }

    if number == 0:
        color = "🟢 Зеро"
    elif number in red_numbers:
        color = "🔴 Красное"
    else:
        color = "⚫ Чёрное"

    won = False

    if bet == "roulette_red":
        won = number in red_numbers

    elif bet == "roulette_black":
        won = number != 0 and number not in red_numbers

    elif bet == "roulette_low":
        won = 1 <= number <= 18

    elif bet == "roulette_high":
        won = 19 <= number <= 36

    elif bet == "roulette_even":
        won = number != 0 and number % 2 == 0

    elif bet == "roulette_odd":
        won = number != 0 and number % 2 == 1

    elif bet == "roulette_zero":
        won = number == 0

    if won:

        if bet == "roulette_zero":
            multiplier = ROULETTE_ZERO_MULTIPLIER
            payout = int(STAKE * multiplier)

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                f"📈 Коэффициент: <b>x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>+{payout}</b>"
            )

        else:
            multiplier = ROULETTE_MULTIPLIER
            payout = int(STAKE * multiplier)

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                f"📈 Коэффициент: <b>x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>+{payout}</b>"
            )

        new_balance = change_balance(
            user_id,
            payout
        )

    else:

        new_balance = get_balance(user_id)

        result_text = (
            "😔 <b>Проигрыш</b>\n"
            "💰 Ставка сгорела."
        )

    games.pop(user_id, None)

    await callback.message.answer(
        "🎡 <b>Результат рулетки</b>\n\n"
        f"🎯 Выпало: <b>{number}</b>\n"
        f"{color}\n\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"
        f"{result_text}\n\n"
        f"💳 Баланс: <b>{new_balance}</b>",
        reply_markup=after_game_menu()
    )

    await callback.answer()


# =========================
# СЛОТЫ
# =========================

@dp.callback_query(F.data == "game_slots")
async def game_slots_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"
        "🎰 Нажмите «Крутить».\n\n"
        "📊 <b>Выигрыш:</b>\n"
        "2 одинаковых — <b>x1.85</b>\n"
        "3 одинаковых — <b>x3.5</b>",
        reply_markup=slots_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "slots_spin")
async def slots_spin_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств!",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "slots"
    }

    await callback.message.answer(
        "🎰 <b>Крутите слот!</b>\n\n"
        "Отправьте эмодзи 🎰"
    )

    await callback.answer()


# =========================
# РЕЗУЛЬТАТ СЛОТОВ
# =========================

def slot_result(value):

    if value == 64:
        return (
            ["7️⃣", "7️⃣", "7️⃣"],
            3.5
        )

    n = value - 1

    first = n & 3
    second = (n >> 2) & 3
    third = (n >> 4) & 3

    telegram_map = {
        0: "🍸",
        1: "🍇",
        2: "🍋",
        3: "7️⃣"
    }

    result = [
        telegram_map[first],
        telegram_map[second],
        telegram_map[third]
    ]

    # 3 из 3
    if result[0] == result[1] == result[2]:
        return (
            result,
            SLOT_THREE_MULTIPLIER
        )

    # 2 из 3
    if (
        result[0] == result[1]
        or result[0] == result[2]
        or result[1] == result[2]
    ):
        return (
            result,
            SLOT_TWO_MULTIPLIER
        )

    # Проигрыш
    return (
        result,
        0
    )


# =========================
# DICE / SLOTS
# =========================

@dp.message(F.dice)
async def dice_handler(message: Message):

    user_id = message.from_user.id

    if user_id not in games:
        return

    game = games[user_id]

    emoji = message.dice.emoji
    value = message.dice.value

    # =========================
    # СЛОТЫ
    # =========================

    if game["type"] == "slots":

        if emoji != "🎰":
            return

        del games[user_id]

        symbols, multiplier = slot_result(value)

        if multiplier == SLOT_TWO_MULTIPLIER:

            payout = int(
                STAKE * SLOT_TWO_MULTIPLIER
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                "✨ 2 из 3 одинаковых\n"
                "📈 Коэффициент: <b>x1.85</b>\n"
                f"💰 Выигрыш: <b>+{payout}</b>"
            )

        elif multiplier == SLOT_THREE_MULTIPLIER:

            payout = int(
                STAKE * SLOT_THREE_MULTIPLIER
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>ДЖЕКПОТ!</b>\n"
                "🔥 3 из 3 одинаковых\n"
                "📈 Коэффициент: <b>x3.5</b>\n"
                f"💰 Выигрыш: <b>+{payout}</b>"
            )

        else:

            new_balance = get_balance(user_id)

            result_text = (
                "😔 <b>Проигрыш</b>\n"
                "Нет совпадений."
            )

        await message.answer(
            "🎰 <b>Результат слотов</b>\n\n"
            f"{symbols[0]} | {symbols[1]} | {symbols[2]}\n\n"
            f"{result_text}\n\n"
            f"💳 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu()
        )

        return

    # =========================
    # КУБИКИ
    # =========================

    if game["type"] == "dice":

        if emoji != "🎲":
            return

        first_dice = game["first_dice"]

        if first_dice is None:

            game["first_dice"] = value

            await message.answer(
                "🎲 <b>Первый кубик:</b> "
                f"<b>{value}</b>\n\n"
                "🎲 Теперь бросьте второй кубик!"
            )

            return

        second_dice = value

        del games[user_id]

        total = first_dice + second_dice

        if total >= 10:
            multiplier = 3
        elif total >= 7:
            multiplier = 2
        else:
            multiplier = 0

        if multiplier > 0:

            payout = STAKE * multiplier

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                f"📈 Коэффициент: <b>x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>+{payout}</b>"
            )

        else:

            new_balance = get_balance(user_id)

            result_text = (
                "😔 <b>Проигрыш</b>"
            )

        await message.answer(
            "🎲 <b>Результат кубиков</b>\n\n"
            f"Первый: <b>{first_dice}</b>\n"
            f"Второй: <b>{second_dice}</b>\n"
            f"Сумма: <b>{total}</b>\n\n"
            f"{result_text}\n\n"
            f"💳 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu()
        )


# =========================
# ИГРАТЬ СНОВА
# =========================

@dp.callback_query(F.data == "play_again")
async def play_again_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    await callback.message.edit_text(
        "🎮 <b>Выберите игру</b>\n\n"
        f"💰 Баланс: <b>{get_balance(user_id)}</b>",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# WEBHOOK
# =========================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "Emoji Casino"
    }


@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):

    data = await request.json()

    update = __import__(
        "aiogram.types",
        fromlist=["Update"]
    ).Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def startup():

    init_db()

    webhook_url = (
        f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
    )

    print(
        f"SETTING WEBHOOK: {webhook_url}"
    )

    await bot.set_webhook(
        webhook_url,
        allowed_updates=[
            "message",
            "callback_query"
        ]
    )

    info = await bot.get_webhook_info()

    print(
        f"WEBHOOK URL: {info.url}"
    )

    print(
        f"PENDING UPDATES: {info.pending_update_count}"
    )

    print(
        f"LAST ERROR: {info.last_error_message}"
    )


# =========================
# SHUTDOWN
# =========================

@app.on_event("shutdown")
async def shutdown():

    await bot.session.close()
