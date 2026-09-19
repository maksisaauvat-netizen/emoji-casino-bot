import os
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "emoji_casino_secret_2026_x7k9"
)

WEBHOOK_URL = (
    f"https://emoji-casino-bot.onrender.com/webhook/{WEBHOOK_SECRET}"
)

STAKE = 100


# =========================================================
# BOT
# =========================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

games = {}


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

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
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 Слоты",
                    callback_data="game_slots"
                )
            ]
        ]
    )


def after_game_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Ещё раз",
                    callback_data="play_again"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                )
            ]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_command(message: types.Message):

    user_id = message.from_user.id
    balance = get_balance(user_id)

    await message.answer(
        "🎰 <b>Emoji Casino</b>\n\n"
        "Добро пожаловать!\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выбери игру:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# ИГРЫ
# =========================================================

@dp.callback_query(lambda c: c.data == "games")
async def games_callback(callback: types.CallbackQuery):

    await callback.answer()

    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "🎮 <b>Игры</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выбери игру:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# КУБИКИ
# =========================================================

def dice_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Бросить 2 кубика",
                    callback_data="dice_two"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                )
            ]
        ]
    )


@dp.callback_query(lambda c: c.data == "game_dice")
async def dice_game_callback(callback: types.CallbackQuery):

    await callback.answer()

    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "🎲 <b>Кубики</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Ставка: <b>100</b>\n\n"
        "Нажми кнопку ниже.",
        reply_markup=dice_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data == "dice_two")
async def dice_two_callback(callback: types.CallbackQuery):

    user_id = callback.from_user.id

    await callback.answer()

    if not subtract_balance(user_id, STAKE):

        await callback.message.edit_text(
            "❌ Недостаточно монет.\n\n"
            f"💰 Баланс: <b>{get_balance(user_id)}</b>",
            reply_markup=after_game_menu(),
            parse_mode="HTML"
        )

        return

    games[user_id] = {
        "type": "dice",
        "first_dice": None
    }

    await callback.message.edit_text(
        "🎲 <b>Кубики</b>\n\n"
        "Ставка <b>100</b> списана.\n\n"
        "Отправь настоящий эмодзи 🎲",
        parse_mode="HTML"
    )


# =========================================================
# РУЛЕТКА
# =========================================================

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}


def roulette_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Красное x2",
                    callback_data="roulette_red"
                ),
                InlineKeyboardButton(
                    text="⚫ Чёрное x2",
                    callback_data="roulette_black"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬆️ 1–18 x2",
                    callback_data="roulette_low"
                ),
                InlineKeyboardButton(
                    text="⬇️ 19–36 x2",
                    callback_data="roulette_high"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚪ Чётное x2",
                    callback_data="roulette_even"
                ),
                InlineKeyboardButton(
                    text="🟣 Нечётное x2",
                    callback_data="roulette_odd"
                )
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
            ]
        ]
    )


def roulette_color(number):

    if number == 0:
        return "🟢 Зеро"

    if number in RED_NUMBERS:
        return "🔴 Красное"

    return "⚫ Чёрное"


@dp.callback_query(lambda c: c.data == "game_roulette")
async def roulette_callback(callback: types.CallbackQuery):

    await callback.answer()

    user_id = callback.from_user.id
    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎡 <b>Рулетка</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Ставка: <b>100</b>\n\n"
        "Выбери ставку:",
        reply_markup=roulette_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(
    lambda c: c.data in {
        "roulette_red",
        "roulette_black",
        "roulette_low",
        "roulette_high",
        "roulette_even",
        "roulette_odd",
        "roulette_zero"
    }
)
async def roulette_bet_callback(callback: types.CallbackQuery):

    user_id = callback.from_user.id
    bet = callback.data

    await callback.answer()

    if not subtract_balance(user_id, STAKE):

        await callback.message.edit_text(
            "❌ Недостаточно монет.\n\n"
            f"💰 Баланс: <b>{get_balance(user_id)}</b>",
            reply_markup=after_game_menu(),
            parse_mode="HTML"
        )

        return

    number = random.randint(0, 36)

    color = roulette_color(number)

    multiplier = 2
    win = False

    if bet == "roulette_red":
        win = number in RED_NUMBERS

    elif bet == "roulette_black":
        win = number != 0 and number not in RED_NUMBERS

    elif bet == "roulette_low":
        win = 1 <= number <= 18

    elif bet == "roulette_high":
        win = 19 <= number <= 36

    elif bet == "roulette_even":
        win = number != 0 and number % 2 == 0

    elif bet == "roulette_odd":
        win = number != 0 and number % 2 == 1

    elif bet == "roulette_zero":
        win = number == 0
        multiplier = 36

    if win:

        payout = STAKE * multiplier

        new_balance = change_balance(
            user_id,
            payout
        )

        result = (
            f"🎉 <b>Выигрыш +{payout}</b>"
        )

    else:

        payout = 0
        new_balance = get_balance(user_id)

        result = "😔 <b>Проигрыш</b>"

    bet_names = {
        "roulette_red": "🔴 Красное",
        "roulette_black": "⚫ Чёрное",
        "roulette_low": "⬆️ 1–18",
        "roulette_high": "⬇️ 19–36",
        "roulette_even": "⚪ Чётное",
        "roulette_odd": "🟣 Нечётное",
        "roulette_zero": "🟢 Зеро"
    }

    await callback.message.edit_text(
        "🎡 <b>Результат рулетки</b>\n\n"
        f"🎯 Выпало: <b>{number}</b>\n"
        f"🎨 {color}\n\n"
        f"🎲 Ставка: <b>{bet_names[bet]}</b>\n"
        f"💰 Ставка: <b>{STAKE}</b>\n"
        f"📈 Коэффициент: <b>x{multiplier}</b>\n\n"
        f"{result}\n\n"
        f"💰 Баланс: <b>{new_balance}</b>",
        reply_markup=after_game_menu(),
        parse_mode="HTML"
    )


# =========================================================
# СЛОТЫ
# =========================================================

SLOT_SYMBOLS = [
    "🍒",
    "🍋",
    "🍉",
    "⭐",
    "7️⃣"
]


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
            ]
        ]
    )


@dp.callback_query(lambda c: c.data == "game_slots")
async def slots_callback(callback: types.CallbackQuery):

    await callback.answer()

    user_id = callback.from_user.id
    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Ставка: <b>100</b>\n\n"
        "Нажми «🎰 Крутить».",
        reply_markup=slots_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data == "slots_spin")
async def slots_spin_callback(callback: types.CallbackQuery):

    user_id = callback.from_user.id

    await callback.answer()

    if not subtract_balance(user_id, STAKE):

        await callback.message.edit_text(
            "❌ Недостаточно монет.\n\n"
            f"💰 Баланс: <b>{get_balance(user_id)}</b>",
            reply_markup=after_game_menu(),
            parse_mode="HTML"
        )

        return

    games[user_id] = {
        "type": "slots"
    }

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        "Ставка <b>100</b> списана.\n\n"
        "Теперь отправь настоящий эмодзи 🎰",
        parse_mode="HTML"
    )


def slot_result(value):

    # Telegram для 🎰 возвращает значение 1–64.
    # На его основе определяем комбинацию.

    if value <= 2:

        return ["7️⃣", "7️⃣", "7️⃣"], 50

    elif value <= 5:

        return ["⭐", "⭐", "⭐"], 20

    elif value <= 9:

        return ["🍉", "🍉", "🍉"], 10

    elif value <= 15:

        return ["🍋", "🍋", "🍋"], 8

    elif value <= 23:

        return ["🍒", "🍒", "🍒"], 5

    else:

        index = (value - 24) % len(SLOT_SYMBOLS)

        symbol = SLOT_SYMBOLS[index]

        other = SLOT_SYMBOLS[
            (index + 1) % len(SLOT_SYMBOLS)
        ]

        return [symbol, symbol, other], 2


# =========================================================
# ОБРАБОТКА TELEGRAM DICE
# =========================================================

@dp.message()
async def dice_handler(message: types.Message):

    user_id = message.from_user.id

    if user_id not in games:
        return

    game = games[user_id]

    if not message.dice:
        return

    emoji = message.dice.emoji
    value = message.dice.value

    # =====================================================
    # КУБИКИ
    # =====================================================

    if game["type"] == "dice":

        if emoji != "🎲":
            return

        if game["first_dice"] is None:

            game["first_dice"] = value

            await message.answer(
                "🎲 Первый кубик: "
                f"<b>{value}</b>\n\n"
                "Теперь отправь второй 🎲",
                parse_mode="HTML"
            )

            return

        first = game["first_dice"]
        second = value
        total = first + second

        del games[user_id]

        if 6 <= total <= 8:
            multiplier = 2

        elif 9 <= total <= 10:
            multiplier = 3

        elif 11 <= total <= 12:
            multiplier = 5

        else:
            multiplier = 0

        if multiplier > 0:

            payout = STAKE * multiplier

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                f"🎉 <b>Выигрыш +{payout}</b>\n"
                f"📈 Коэффициент: <b>x{multiplier}</b>"
            )

        else:

            new_balance = get_balance(user_id)

            result_text = "😔 <b>Проигрыш</b>"

        await message.answer(
            "🎲 <b>Результат</b>\n\n"
            f"Первый кубик: <b>{first}</b>\n"
            f"Второй кубик: <b>{second}</b>\n"
            f"Сумма: <b>{total}</b>\n\n"
            f"{result_text}\n\n"
            f"💰 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu(),
            parse_mode="HTML"
        )

        return

    # =====================================================
    # СЛОТЫ
    # =====================================================

    if game["type"] == "slots":

        if emoji != "🎰":
            return

        del games[user_id]

        symbols, multiplier = slot_result(value)

        payout = STAKE * multiplier

        new_balance = change_balance(
            user_id,
            payout
        )

        await message.answer(
            "🎰 <b>Результат слотов</b>\n\n"
            f"{symbols[0]} | {symbols[1]} | {symbols[2]}\n\n"
            "🎉 <b>Выигрыш!</b>\n"
            f"📈 Коэффициент: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{payout}</b>\n\n"
            f"💰 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu(),
            parse_mode="HTML"
        )

        return


# =========================================================
# ПОВТОРНАЯ ИГРА
# =========================================================

@dp.callback_query(lambda c: c.data == "play_again")
async def play_again_callback(callback: types.CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "🎮 <b>Выбери игру</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# WEBHOOK
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    init_db()

    print("SETTING WEBHOOK:", WEBHOOK_URL)

    await bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=[
            "message",
            "callback_query"
        ]
    )

    webhook_info = await bot.get_webhook_info()

    print("WEBHOOK URL:", webhook_info.url)
    print(
        "PENDING UPDATES:",
        webhook_info.pending_update_count
    )
    print(
        "LAST ERROR:",
        webhook_info.last_error_message
    )

    yield

    await bot.session.close()


app = FastAPI(
    lifespan=lifespan
)


@app.get("/")
async def root():

    return {
        "status": "ok",
        "bot": "Emoji Casino"
    }


@app.post(
    f"/webhook/{WEBHOOK_SECRET}"
)
async def telegram_webhook(
    request: Request
):

    data = await request.json()

    print("=== WEBHOOK ===")
    print("UPDATE RECEIVED:", data)

    update = types.Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }
