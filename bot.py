import asyncio
import os
import random

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is not set")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

WEBHOOK_URL = (
    f"https://emoji-casino-bot.onrender.com"
    f"{WEBHOOK_PATH}"
)


# =========================================================
# BOT
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()
app = FastAPI()


# =========================================================
# CONSTANTS
# =========================================================

STAKE = 100

# Dice
DICE_ONE_MULTIPLIER = 1.85
DICE_EQUAL_MULTIPLIER = 5.0
DICE_TWO_MULTIPLIER = 1.85

# Slots
SLOT_TWO_MULTIPLIER = 1.85
SLOT_OTHER_THREE_MULTIPLIER = 3.5
SLOT_COCKTAIL_MULTIPLIER = 5
SLOT_GRAPES_MULTIPLIER = 8
SLOT_LEMON_MULTIPLIER = 10
SLOT_SEVEN_MULTIPLIER = 50

# Roulette
ROULETTE_MULTIPLIER = 1.95
ROULETTE_ZERO_MULTIPLIER = 36

# Bowling
BOWLING_MULTIPLIER = 1.85

# Mines
MINES_MULTIPLIERS = {
    1: 1.15,
    2: 1.35,
    3: 1.60,
    4: 1.95,
    5: 2.40,
    6: 3.00,
}

# Crash
CRASH_MIN = 1.10
CRASH_MAX = 20.00


# =========================================================
# ACTIVE GAMES
# =========================================================

games = {}


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎰  МИНИ-ИГРЫ",
        callback_data="mini_games"
    )

    builder.button(
        text="👤  ПРОФИЛЬ",
        callback_data="profile"
    )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# MINI GAMES MENU
# =========================================================

def mini_games_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲  КУБИКИ",
        callback_data="dice"
    )

    builder.button(
        text="🎰  СЛОТЫ",
        callback_data="slots"
    )

    builder.button(
        text="🎡  РУЛЕТКА",
        callback_data="roulette"
    )

    builder.button(
        text="🎳  БОУЛИНГ",
        callback_data="bowling"
    )

    builder.button(
        text="💣  МИНЫ",
        callback_data="mines"
    )

    builder.button(
        text="🧨  CRASH",
        callback_data="crash"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="menu"
    )

    builder.adjust(2, 2, 2, 1)

    return builder.as_markup()


# =========================================================
# AFTER GAME MENU
# =========================================================

def after_game_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔄  ИГРАТЬ СНОВА",
        callback_data="mini_games"
    )

    builder.button(
        text="📂  МЕНЮ",
        callback_data="menu"
    )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    balance = get_balance(user_id)

    await message.answer(
        f"🎰 <b>RESONANT CASINO</b>\n\n"
        f"✦ Добро пожаловать ✦\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>ВЫБЕРИ РАЗДЕЛ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 6 игр  •  ⚡ Resonant",
        reply_markup=main_menu()
    )


# =========================================================
# MAIN MENU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🎰 <b>RESONANT CASINO</b>\n\n"
        f"✦ Добро пожаловать ✦\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>ВЫБЕРИ РАЗДЕЛ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 6 игр  •  ⚡ Resonant",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    first_name = (
        callback.from_user.first_name
        or "Игрок"
    )

    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else "не указан"
    )

    await callback.message.edit_text(
        f"👤 <b>ПРОФИЛЬ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🧑 Игрок: <b>{first_name}</b>\n"
        f"🔗 Username: <b>{username}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💰 Баланс\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# MINI GAMES
# =========================================================

@dp.callback_query(F.data == "mini_games")
async def mini_games_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🎰 <b>МИНИ-ИГРЫ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>ВЫБЕРИ ИГРУ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ 6 игр  •  Ставка от 100 ₽",
        reply_markup=mini_games_menu()
    )

    await callback.answer()


# =========================================================
# DICE
# =========================================================

def dice_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲  1 КУБИК  •  x1.85",
        callback_data="dice_one"
    )

    builder.button(
        text="🎲🎲  2 КУБИКА  •  до x5.00",
        callback_data="dice_two"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "dice")
async def dice_handler(callback: CallbackQuery):
    balance = get_balance(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"🎲 <b>КУБИКИ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ВЫБЕРИ РЕЖИМ</b>\n\n"
        f"🎲 <b>1 КУБИК</b>\n"
        f"Угадай результат\n"
        f"⬇️ Меньше 3  •  ⬆️ Больше 3\n"
        f"💎 Выигрыш: <b>x1.85</b>\n\n"
        f"🎲🎲 <b>2 КУБИКА</b>\n"
        f"Угадай сумму\n"
        f"🎯 Равно 7  •  ⬇️ Меньше 7  •  ⬆️ Больше 7\n"
        f"💎 Выигрыш: <b>до x5.00</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=dice_menu()
    )

    await callback.answer()


def dice_one_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️  МЕНЬШЕ 3  •  x1.85",
        callback_data="dice_one_less"
    )

    builder.button(
        text="⬆️  БОЛЬШЕ 3  •  x1.85",
        callback_data="dice_one_more"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="dice"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "dice_one")
async def dice_one_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_one"
    }

    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🎲 <b>1 КУБИК</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n"
        f"💎 Множитель: <b>x1.85</b>\n\n"
        f"🎯 Выбери направление:",
        reply_markup=dice_one_menu()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "dice_one_less",
        "dice_one_more"
    })
)
async def dice_one_bet_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    game = games[user_id]

    if game["type"] != "dice_one":
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    bet = (
        "less"
        if callback.data == "dice_one_less"
        else "more"
    )

    game["bet"] = bet

    direction = (
        "⬇️ МЕНЬШЕ 3"
        if bet == "less"
        else "⬆️ БОЛЬШЕ 3"
    )

    await callback.message.edit_text(
        f"🎲 <b>1 КУБИК</b>\n\n"
        f"🎯 Ставка: <b>{direction}</b>\n"
        f"💰 Сумма: <b>{STAKE} ₽</b>\n"
        f"💎 Множитель: <b>x1.85</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎲 <b>БРОСОК!</b>"
    )

    await callback.message.answer_dice(
        emoji="🎲"
    )

    await callback.answer()


# =========================================================
# DICE TWO
# =========================================================

def dice_two_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎯  РАВНО 7  •  x5.00",
        callback_data="dice_two_equal"
    )

    builder.button(
        text="⬇️  МЕНЬШЕ 7  •  x1.85",
        callback_data="dice_two_less"
    )

    builder.button(
        text="⬆️  БОЛЬШЕ 7  •  x1.85",
        callback_data="dice_two_more"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="dice"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "dice_two")
async def dice_two_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_two",
        "rolls": []
    }

    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🎲🎲 <b>2 КУБИКА</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n\n"
        f"🎯 Выбери направление:",
        reply_markup=dice_two_menu()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "dice_two_equal",
        "dice_two_less",
        "dice_two_more"
    })
)
async def dice_two_bet_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    game = games[user_id]

    game["bet"] = {
        "dice_two_equal": "equal",
        "dice_two_less": "less",
        "dice_two_more": "more"
    }[callback.data]

    game["rolls"] = []

    bet_text = {
        "equal": "🎯 РАВНО 7",
        "less": "⬇️ МЕНЬШЕ 7",
        "more": "⬆️ БОЛЬШЕ 7"
    }[game["bet"]]

    await callback.message.edit_text(
        f"🎲🎲 <b>2 КУБИКА</b>\n\n"
        f"🎯 Ставка: <b>{bet_text}</b>\n"
        f"💰 Сумма: <b>{STAKE} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎲 <b>ПЕРВЫЙ БРОСОК</b>"
    )

    await callback.message.answer_dice(
        emoji="🎲"
    )

    await callback.answer()


# =========================================================
# SLOTS
# =========================================================

def slots_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎰  КРУТИТЬ  •  100 ₽",
        callback_data="slots_play"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "slots")
async def slots_handler(callback: CallbackQuery):
    balance = get_balance(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ТАБЛИЦА ВЫИГРЫШЕЙ</b>\n\n"
        f"🍸🍸  <b>x1.85</b>\n"
        f"🍸🍸🍸  <b>x5</b>\n"
        f"🍇🍇🍇  <b>x8</b>\n"
        f"🍋🍋🍋  <b>x10</b>\n"
        f"7️⃣7️⃣7️⃣  <b>x50</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Два одинаковых символа: <b>x1.85</b>\n"
        f"✨ Другие три одинаковых: <b>x3.5</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=slots_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "slots_play")
async def slots_play_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "slots"
    }

    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n"
        f"💳 Баланс: <b>{balance} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎰 <b>КРУТИМ...</b>"
    )

    await callback.message.answer_dice(
        emoji="🎰"
    )

    await callback.answer()


def slot_result(value):
    if value == 64:
        return (
            ["7️⃣", "7️⃣", "7️⃣"],
            SLOT_SEVEN_MULTIPLIER
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

    if result[0] == result[1] == result[2]:

        if result[0] == "🍸":
            return result, SLOT_COCKTAIL_MULTIPLIER

        if result[0] == "🍇":
            return result, SLOT_GRAPES_MULTIPLIER

        if result[0] == "🍋":
            return result, SLOT_LEMON_MULTIPLIER

        if result[0] == "7️⃣":
            return result, SLOT_SEVEN_MULTIPLIER

        return result, SLOT_OTHER_THREE_MULTIPLIER

    if (
        result[0] == result[1]
        or result[0] == result[2]
        or result[1] == result[2]
    ):
        return result, SLOT_TWO_MULTIPLIER

    return result, 0


# =========================================================
# ROULETTE
# =========================================================

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}


def roulette_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔴  КРАСНОЕ  •  x1.95",
        callback_data="roulette_red"
    )

    builder.button(
        text="⚫  ЧЁРНОЕ  •  x1.95",
        callback_data="roulette_black"
    )

    builder.button(
        text="1️⃣  1–18  •  x1.95",
        callback_data="roulette_low"
    )

    builder.button(
        text="2️⃣  19–36  •  x1.95",
        callback_data="roulette_high"
    )

    builder.button(
        text="⚪  ЧЁТ  •  x1.95",
        callback_data="roulette_even"
    )

    builder.button(
        text="⚪  НЕЧЁТ  •  x1.95",
        callback_data="roulette_odd"
    )

    builder.button(
        text="🟢  ZERO  •  x36",
        callback_data="roulette_zero"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "roulette")
async def roulette_handler(callback: CallbackQuery):
    balance = get_balance(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"🎡 <b>РУЛЕТКА</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
        f"🔴 Красное  •  <b>x1.95</b>\n"
        f"⚫ Чёрное  •  <b>x1.95</b>\n"
        f"1–18  •  <b>x1.95</b>\n"
        f"19–36  •  <b>x1.95</b>\n"
        f"Чёт  •  <b>x1.95</b>\n"
        f"Нечёт  •  <b>x1.95</b>\n"
        f"🟢 Zero  •  <b>x36</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=roulette_menu()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("roulette_"))
async def roulette_bet_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    bet = callback.data.replace(
        "roulette_",
        ""
    )

    await callback.message.edit_text(
        f"🎡 <b>РУЛЕТКА</b>\n\n"
        f"🎯 Ставка принята\n\n"
        f"💰 Сумма: <b>{STAKE} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎡 <b>КРУТИМ...</b>"
    )

    await asyncio.sleep(0.8)

    result = random.randint(0, 36)

    win = False
    multiplier = 0

    if bet == "zero":

        if result == 0:
            win = True
            multiplier = ROULETTE_ZERO_MULTIPLIER

    elif result != 0:

        if (
            bet == "red"
            and result in RED_NUMBERS
        ):
            win = True
            multiplier = ROULETTE_MULTIPLIER

        elif (
            bet == "black"
            and result not in RED_NUMBERS
        ):
            win = True
            multiplier = ROULETTE_MULTIPLIER

        elif (
            bet == "low"
            and 1 <= result <= 18
        ):
            win = True
            multiplier = ROULETTE_MULTIPLIER

        elif (
            bet == "high"
            and 19 <= result <= 36
        ):
            win = True
            multiplier = ROULETTE_MULTIPLIER

        elif (
            bet == "even"
            and result % 2 == 0
        ):
            win = True
            multiplier = ROULETTE_MULTIPLIER

        elif (
            bet == "odd"
            and result % 2 == 1
        ):
            win = True
            multiplier = ROULETTE_MULTIPLIER

    payout = 0

    if win:
        payout = int(
            STAKE * multiplier
        )

        change_balance(
            user_id,
            payout
        )

    balance = get_balance(user_id)

    if result == 0:
        number_display = "🟢 0"
    elif result in RED_NUMBERS:
        number_display = f"🔴 {result}"
    else:
        number_display = f"⚫ {result}"

    bet_names = {
        "red": "🔴 Красное",
        "black": "⚫ Чёрное",
        "low": "1–18",
        "high": "19–36",
        "even": "⚪ Чёт",
        "odd": "⚪ Нечёт",
        "zero": "🟢 Zero"
    }

    bet_name = bet_names.get(
        bet,
        "Ставка"
    )

    if win:

        text = (
            f"🎡 <b>РУЛЕТКА</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Выпало\n\n"
            f"<b>{number_display}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"Ставка: <b>{bet_name}</b>\n"
            f"Множитель: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{payout} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance} ₽</b>"
        )

    else:

        text = (
            f"🎡 <b>РУЛЕТКА</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Выпало\n\n"
            f"<b>{number_display}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ <b>ПРОИГРЫШ</b>\n\n"
            f"Ставка: <b>{bet_name}</b>\n"
            f"💸 Потеряно: <b>{STAKE} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance} ₽</b>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_menu()
    )

    await callback.answer()


# =========================================================
# BOWLING
# =========================================================

def bowling_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬆️  БОЛЬШЕ 3  •  x1.85",
        callback_data="bowling_more"
    )

    builder.button(
        text="⬇️  МЕНЬШЕ 3  •  x1.85",
        callback_data="bowling_less"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "bowling")
async def bowling_handler(callback: CallbackQuery):
    balance = get_balance(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"🎳 <b>БОУЛИНГ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"<b>{balance}</b> ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
        f"⬆️ <b>БОЛЬШЕ 3</b>\n"
        f"Если выпадет 4, 5 или 6\n"
        f"💎 Выигрыш: <b>x1.85</b>\n\n"
        f"⬇️ <b>МЕНЬШЕ 3</b>\n"
        f"Если выпадет 1 или 2\n"
        f"💎 Выигрыш: <b>x1.85</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⚠️ Результат <b>3</b> — проигрыш\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=bowling_menu()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "bowling_more",
        "bowling_less"
    })
)
async def bowling_bet_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    bet = (
        "more"
        if callback.data == "bowling_more"
        else "less"
    )

    games[user_id] = {
        "type": "bowling",
        "bet": bet
    }

    bet_text = (
        "⬆️ БОЛЬШЕ 3"
        if bet == "more"
        else "⬇️ МЕНЬШЕ 3"
    )

    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🎳 <b>БОУЛИНГ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Твоя ставка\n"
        f"<b>{bet_text}</b>\n\n"
        f"💰 Сумма: <b>{STAKE} ₽</b>\n"
        f"💎 Множитель: <b>x1.85</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎳 <b>БРОСОК...</b>\n\n"
        f"💳 Баланс после ставки: <b>{balance} ₽</b>"
    )

    await callback.message.answer_dice(
        emoji="🎳"
    )

    await callback.answer()


# =========================================================
# MINES — PREMIUM
# =========================================================

def mines_keyboard(
    opened,
    mines=None,
    finished=False
):
    builder = InlineKeyboardBuilder()

    for position in range(9):

        if position in opened:
            text = "💎"

        elif (
            finished
            and mines is not None
            and position in mines
        ):
            text = "💣"

        elif finished:
            text = "▫️"

        else:
            text = "❓"

        builder.button(
            text=text,
            callback_data=f"mine_{position}"
        )

    builder.adjust(3)

    if not finished:
        builder.button(
            text="💰  ЗАБРАТЬ ВЫИГРЫШ",
            callback_data="mines_cashout"
        )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    if not finished:
        builder.adjust(3, 1, 1)
    else:
        builder.adjust(3, 1)

    return builder.as_markup()


def mines_multiplier_text(opened_count):
    if opened_count == 0:
        return "x1.00"

    return f"x{MINES_MULTIPLIERS[opened_count]:.2f}"


@dp.callback_query(F.data == "mines")
async def mines_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    mine_positions = set(
        random.sample(
            range(9),
            3
        )
    )

    games[user_id] = {
        "type": "mines",
        "mines": mine_positions,
        "opened": set()
    }

    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n"
        f"💳 Баланс: <b>{balance} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ОТКРЫВАЙ КЛЕТКИ</b>\n\n"
        f"💎 Безопасная клетка\n"
        f"💣 Мина\n\n"
        f"📦 Открыто: <b>0 / 6</b>\n"
        f"📈 Множитель: <b>x1.00</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Выигрыш можно забрать после первого безопасного хода.",
        reply_markup=mines_keyboard(set())
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("mine_"))
async def mine_cell_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    game = games[user_id]

    if game["type"] != "mines":
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    position = int(
        callback.data.replace(
            "mine_",
            ""
        )
    )

    if position in game["opened"]:
        await callback.answer(
            "Эта клетка уже открыта"
        )
        return

    if position in game["mines"]:

        opened = game["opened"].copy()
        mines = game["mines"].copy()

        del games[user_id]

        balance = get_balance(user_id)

        await callback.message.edit_text(
            f"💣 <b>МИНЫ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💥 <b>МИНА!</b>\n\n"
            f"Ты открыл опасную клетку.\n"
            f"💸 Потеряно: <b>{STAKE} ₽</b>\n\n"
            f"📦 Безопасных клеток: <b>{len(opened)} / 6</b>\n"
            f"💳 Баланс: <b>{balance} ₽</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💣 Поле раскрыто",
            reply_markup=mines_keyboard(
                opened,
                mines,
                finished=True
            )
        )

        await callback.answer(
            "💥 Мина!"
        )

        return

    game["opened"].add(position)

    opened_count = len(
        game["opened"]
    )

    if opened_count >= 6:

        multiplier = MINES_MULTIPLIERS[6]

        payout = int(
            STAKE * multiplier
        )

        change_balance(
            user_id,
            payout
        )

        balance = get_balance(user_id)

        opened = game["opened"].copy()
        mines = game["mines"].copy()

        del games[user_id]

        await callback.message.edit_text(
            f"💣 <b>МИНЫ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 <b>ИДЕАЛЬНАЯ ИГРА!</b>\n\n"
            f"💎 Все безопасные клетки открыты\n\n"
            f"📦 Открыто: <b>6 / 6</b>\n"
            f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
            f"💰 Выигрыш: <b>+{payout} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance} ₽</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=mines_keyboard(
                opened,
                mines,
                finished=True
            )
        )

        await callback.answer(
            "🏆 Максимальный выигрыш!"
        )

        return

    multiplier = MINES_MULTIPLIERS[
        opened_count
    ]

    potential_win = int(
        STAKE * multiplier
    )

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>БЕЗОПАСНО</b>\n\n"
        f"📦 Открыто: <b>{opened_count} / 6</b>\n"
        f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Сейчас можно забрать: <b>{potential_win} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Риск продолжается...",
        reply_markup=mines_keyboard(
            game["opened"]
        )
    )

    await callback.answer(
        "💎 Безопасно!"
    )


@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    game = games[user_id]

    if game["type"] != "mines":
        await callback.answer(
            "Игра не найдена",
            show_alert=True
        )
        return

    opened_count = len(
        game["opened"]
    )

    if opened_count == 0:
        await callback.answer(
            "Сначала открой хотя бы одну клетку",
            show_alert=True
        )
        return

    multiplier = MINES_MULTIPLIERS[
        opened_count
    ]

    payout = int(
        STAKE * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    balance = get_balance(user_id)

    opened = game["opened"].copy()
    mines = game["mines"].copy()

    del games[user_id]

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>ВЫИГРЫШ ЗАБРАН</b>\n\n"
        f"💎 Безопасных клеток: <b>{opened_count} / 6</b>\n"
        f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Получено: <b>+{payout} ₽</b>\n\n"
        f"💳 Баланс: <b>{balance} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🧠 Хороший момент остановиться.",
        reply_markup=after_game_menu()
    )

    await callback.answer(
        "💰 Выигрыш забран!"
    )


# =========================================================
# CRASH
# =========================================================

def crash_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰  ЗАБРАТЬ",
        callback_data="crash_cashout"
    )

    builder.button(
        text="❌  ОТМЕНИТЬ",
        callback_data="crash_cancel"
    )

    builder.adjust(1)

    return builder.as_markup()


def generate_crash_point():
    value = random.expovariate(
        1.0 / 2.5
    )

    crash_point = 1.00 + value

    crash_point = max(
        CRASH_MIN,
        crash_point
    )

    crash_point = min(
        CRASH_MAX,
        crash_point
    )

    return round(
        crash_point,
        2
    )


@dp.callback_query(F.data == "crash")
async def crash_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "У тебя уже есть активная игра",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    crash_point = generate_crash_point()

    games[user_id] = {
        "type": "crash",
        "multiplier": 1.00,
        "crash_point": crash_point,
        "active": True
    }

    await callback.message.edit_text(
        f"🧨 <b>CRASH</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n\n"
        f"🟢 <b>1.00x</b>\n\n"
        f"Забери выигрыш до краша!",
        reply_markup=crash_menu()
    )

    await callback.answer()

    asyncio.create_task(
        crash_loop(
            callback.message,
            user_id
        )
    )


async def crash_loop(
    message: Message,
    user_id: int
):
    while True:

        await asyncio.sleep(0.25)

        if user_id not in games:
            return

        game = games[user_id]

        if game["type"] != "crash":
            return

        if not game["active"]:
            return

        multiplier = game["multiplier"]
        crash_point = game["crash_point"]

        if multiplier >= crash_point:

            game["active"] = False

            del games[user_id]

            balance = get_balance(user_id)

            try:
                await message.edit_text(
                    f"🧨 <b>CRASH</b>\n\n"
                    f"🔴 <b>{crash_point:.2f}x</b>\n\n"
                    f"💥 <b>КРАШ!</b>\n\n"
                    f"❌ Ставка <b>{STAKE} ₽</b> потеряна.\n\n"
                    f"💰 Баланс: <b>{balance} ₽</b>",
                    reply_markup=after_game_menu()
                )
            except Exception:
                pass

            return

        if multiplier < 2:
            multiplier += 0.05
        elif multiplier < 5:
            multiplier += 0.08
        else:
            multiplier += 0.12

        multiplier = round(
            multiplier,
            2
        )

        game["multiplier"] = multiplier

        if multiplier < 2:
            indicator = "🟢"
        elif multiplier < 5:
            indicator = "🟡"
        else:
            indicator = "🔴"

        try:
            await message.edit_text(
                f"🧨 <b>CRASH</b>\n\n"
                f"{indicator} <b>{multiplier:.2f}x</b>\n\n"
                f"💰 Забрать: <b>{int(STAKE * multiplier)} ₽</b>",
                reply_markup=crash_menu()
            )
        except Exception:
            pass


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра уже завершена",
            show_alert=True
        )
        return

    game = games[user_id]

    if game["type"] != "crash":
        await callback.answer(
            "Игра уже завершена",
            show_alert=True
        )
        return

    multiplier = game["multiplier"]

    game["active"] = False

    payout = int(
        STAKE * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    balance = get_balance(user_id)

    del games[user_id]

    await callback.message.edit_text(
        f"🧨 <b>CRASH</b>\n\n"
        f"🟢 <b>{multiplier:.2f}x</b>\n\n"
        f"💰 <b>ВЫИГРЫШ ЗАБРАН!</b>\n\n"
        f"Получено: <b>+{payout} ₽</b>\n"
        f"Баланс: <b>{balance} ₽</b>",
        reply_markup=after_game_menu()
    )

    await callback.answer(
        "💰 Выигрыш забран!"
    )


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра уже завершена",
            show_alert=True
        )
        return

    game = games[user_id]

    if game["type"] != "crash":
        await callback.answer(
            "Игра уже завершена",
            show_alert=True
        )
        return

    game["active"] = False

    del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        f"🧨 <b>CRASH</b>\n\n"
        f"❌ <b>ИГРА ОТМЕНЕНА</b>\n\n"
        f"Ставка <b>{STAKE} ₽</b> не возвращается.\n\n"
        f"💰 Баланс: <b>{balance} ₽</b>",
        reply_markup=after_game_menu()
    )

    await callback.answer(
        "Игра отменена"
    )


# =========================================================
# COMMON TELEGRAM DICE HANDLER
# =========================================================

@dp.message(F.dice)
async def dice_result_handler(
    message: Message
):
    user_id = message.from_user.id

    if user_id not in games:
        return

    game = games[user_id]

    emoji = message.dice.emoji
    value = message.dice.value

    # =====================================================
    # 🎲 DICE
    # =====================================================

    if emoji == "🎲":

        if game["type"] == "dice_one":

            bet = game.get("bet")

            if not bet:
                return

            win = False

            if (
                bet == "less"
                and value < 3
            ):
                win = True

            elif (
                bet == "more"
                and value > 3
            ):
                win = True

            if win:

                payout = int(
                    STAKE * DICE_ONE_MULTIPLIER
                )

                change_balance(
                    user_id,
                    payout
                )

                balance = get_balance(
                    user_id
                )

                await message.answer(
                    f"🎲 <b>РЕЗУЛЬТАТ</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    f"🎉 <b>ПОБЕДА!</b>\n"
                    f"📈 Множитель: <b>x1.85</b>\n"
                    f"💰 +{payout} ₽\n\n"
                    f"Баланс: <b>{balance} ₽</b>",
                    reply_markup=after_game_menu()
                )

            else:

                balance = get_balance(
                    user_id
                )

                await message.answer(
                    f"🎲 <b>РЕЗУЛЬТАТ</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    f"❌ <b>ПРОИГРЫШ</b>\n"
                    f"💸 -{STAKE} ₽\n\n"
                    f"Баланс: <b>{balance} ₽</b>",
                    reply_markup=after_game_menu()
                )

            del games[user_id]
            return

        if game["type"] == "dice_two":

            game["rolls"].append(value)

            if len(game["rolls"]) == 1:

                await message.answer(
                    f"🎲 <b>ПЕРВЫЙ КУБИК</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    f"🎲 Брось второй кубик"
                )

                await message.answer_dice(
                    emoji="🎲"
                )

                return

            first = game["rolls"][0]
            second = game["rolls"][1]

            total = first + second
            bet = game["bet"]

            win = False
            multiplier = 0

            if (
                bet == "equal"
                and total == 7
            ):
                win = True
                multiplier = DICE_EQUAL_MULTIPLIER

            elif (
                bet == "less"
                and total < 7
            ):
                win = True
                multiplier = DICE_TWO_MULTIPLIER

            elif (
                bet == "more"
                and total > 7
            ):
                win = True
                multiplier = DICE_TWO_MULTIPLIER

            if win:

                payout = int(
                    STAKE * multiplier
                )

                change_balance(
                    user_id,
                    payout
                )

                balance = get_balance(
                    user_id
                )

                await message.answer(
                    f"🎲🎲 <b>РЕЗУЛЬТАТ</b>\n\n"
                    f"Кубик 1: <b>{first}</b>\n"
                    f"Кубик 2: <b>{second}</b>\n"
                    f"Сумма: <b>{total}</b>\n\n"
                    f"🎉 <b>ПОБЕДА!</b>\n"
                    f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
                    f"💰 +{payout} ₽\n\n"
                    f"Баланс: <b>{balance} ₽</b>",
                    reply_markup=after_game_menu()
                )

            else:

                balance = get_balance(
                    user_id
                )

                await message.answer(
                    f"🎲🎲 <b>РЕЗУЛЬТАТ</b>\n\n"
                    f"Кубик 1: <b>{first}</b>\n"
                    f"Кубик 2: <b>{second}</b>\n"
                    f"Сумма: <b>{total}</b>\n\n"
                    f"❌ <b>ПРОИГРЫШ</b>\n"
                    f"💸 -{STAKE} ₽\n\n"
                    f"Баланс: <b>{balance} ₽</b>",
                    reply_markup=after_game_menu()
                )

            del games[user_id]
            return

    # =====================================================
    # 🎰 SLOTS
    # =====================================================

    if emoji == "🎰":

        if game["type"] != "slots":
            return

        result, multiplier = slot_result(value)

        result_text = "".join(result)

        if multiplier > 0:

            payout = int(
                STAKE * multiplier
            )

            change_balance(
                user_id,
                payout
            )

            balance = get_balance(
                user_id
            )

            await message.answer(
                f"🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
                f"┌──────────────┐\n"
                f"│  {result_text}  │\n"
                f"└──────────────┘\n\n"
                f"🎉 <b>ПОБЕДА!</b>\n\n"
                f"📈 Множитель: <b>x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>+{payout} ₽</b>\n\n"
                f"💳 Баланс: <b>{balance} ₽</b>",
                reply_markup=after_game_menu()
            )

        else:

            balance = get_balance(
                user_id
            )

            await message.answer(
                f"🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
                f"┌──────────────┐\n"
                f"│  {result_text}  │\n"
                f"└──────────────┘\n\n"
                f"❌ <b>ПРОИГРЫШ</b>\n"
                f"💸 Ставка: <b>{STAKE} ₽</b>\n\n"
                f"💳 Баланс: <b>{balance} ₽</b>",
                reply_markup=after_game_menu()
            )

        del games[user_id]
        return

    # =====================================================
    # 🎳 BOWLING
    # =====================================================

    if emoji == "🎳":

        if game["type"] != "bowling":
            return

        bet = game["bet"]

        win = False

        if (
            bet == "more"
            and value > 3
        ):
            win = True

        elif (
            bet == "less"
            and value < 3
        ):
            win = True

        bet_text = (
            "⬆️ БОЛЬШЕ 3"
            if bet == "more"
            else "⬇️ МЕНЬШЕ 3"
        )

        if win:

            payout = int(
                STAKE * BOWLING_MULTIPLIER
            )

            change_balance(
                user_id,
                payout
            )

            balance = get_balance(
                user_id
            )

            await message.answer(
                f"🎳 <b>РЕЗУЛЬТАТ</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 Твоя ставка\n"
                f"<b>{bet_text}</b>\n\n"
                f"🎳 Выпало: <b>{value}</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🎉 <b>ПОПАЛ!</b>\n\n"
                f"📈 Множитель: <b>x1.85</b>\n"
                f"💰 Выигрыш: <b>+{payout} ₽</b>\n\n"
                f"💳 Баланс: <b>{balance} ₽</b>",
                reply_markup=after_game_menu()
            )

        else:

            balance = get_balance(
                user_id
            )

            if value == 3:
                result_title = "🎳 СПЛИТ!"
            else:
                result_title = "❌ НЕ ПОПАЛ"

            await message.answer(
                f"🎳 <b>РЕЗУЛЬТАТ</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 Твоя ставка\n"
                f"<b>{bet_text}</b>\n\n"
                f"🎳 Выпало: <b>{value}</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"{result_title}\n\n"
                f"💸 Потеряно: <b>{STAKE} ₽</b>\n\n"
                f"💳 Баланс: <b>{balance} ₽</b>",
                reply_markup=after_game_menu()
            )

        del games[user_id]
        return


# =========================================================
# WEBHOOK
# =========================================================

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    data = await request.json()

    update = Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup():
    init_db()

    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=[
            "message",
            "callback_query"
        ]
    )

    print(
        "SETTING WEBHOOK:",
        WEBHOOK_URL
    )

    info = await bot.get_webhook_info()

    print(
        "WEBHOOK URL:",
        info.url
    )

    print(
        "PENDING UPDATES:",
        info.pending_update_count
    )

    print(
        "LAST ERROR:",
        info.last_error_message
    )


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()
