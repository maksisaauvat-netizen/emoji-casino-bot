import asyncio
import os
import random
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin import is_admin

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
    get_user_stats,
    get_game_history,
    record_game,
    DB_PATH,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "emoji_casino_secret_2026_x7k9"
)

BASE_URL = "https://emoji-casino-bot.onrender.com"

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH


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

games = {}


# =========================================================
# CONSTANTS
# =========================================================

STAKES = [50, 100, 250, 500, 1000]

CRASH_MIN = 1.00
CRASH_MAX = 20.00
CRASH_MEAN = 2.1

SLOT_SEVEN_MULTIPLIER = 50


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup():

    init_db()

    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=["message", "callback_query"]
    )

    print("SETTING WEBHOOK:", WEBHOOK_URL)

    info = await bot.get_webhook_info()

    print("WEBHOOK URL:", info.url)
    print("PENDING UPDATES:", info.pending_update_count)
    print("LAST ERROR:", info.last_error_message)


@app.on_event("shutdown")
async def shutdown():

    await bot.session.close()


# =========================================================
# HELPERS
# =========================================================

def money(value):
    return f"{int(value):,}".replace(",", " ")


def get_user_id(event):
    if isinstance(event, Message):
        return event.from_user.id

    return event.from_user.id


def main_keyboard(user_id: int):

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎰  МИНИ-ИГРЫ",
        callback_data="menu_games"
    )

    builder.button(
        text="👤  ПРОФИЛЬ",
        callback_data="profile"
    )

    if is_admin(user_id):
        builder.button(
            text="👑  ADMIN PANEL",
            callback_data="admin_panel"
        )

    builder.adjust(1)

    return builder.as_markup()


def games_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲 КУБИКИ",
        callback_data="game_dice"
    )

    builder.button(
        text="🎰 СЛОТЫ",
        callback_data="game_slots"
    )

    builder.button(
        text="🎡 РУЛЕТКА",
        callback_data="game_roulette"
    )

    builder.button(
        text="🎳 БОУЛИНГ",
        callback_data="game_bowling"
    )

    builder.button(
        text="💣 МИНЫ",
        callback_data="game_mines"
    )

    builder.button(
        text="🧨 CRASH",
        callback_data="game_crash"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="main_menu"
    )

    builder.adjust(2, 2, 2, 1)

    return builder.as_markup()


def profile_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📜 ИСТОРИЯ ИГР",
        callback_data="history_0"
    )

    builder.button(
        text="🎰 ИГРЫ",
        callback_data="menu_games"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="main_menu"
    )

    builder.adjust(1)

    return builder.as_markup()


def after_game_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔄 ИГРАТЬ СНОВА",
        callback_data="menu_games"
    )

    builder.button(
        text="📂 МЕНЮ",
        callback_data="main_menu"
    )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# MAIN MENU
# =========================================================

async def show_main_menu(
    target,
    user_id: int
):

    balance = get_balance(user_id)

    text = (
        "🎰 <b>RESONANT CASINO</b>\n\n"
        "✦ Добро пожаловать ✦\n\n"
        "💰 <b>БАЛАНС</b>\n"
        f"{money(balance)} ₽\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎮 <b>ВЫБЕРИ РАЗДЕЛ</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎲 6 игр  •  ⚡ Resonant"
    )

    if isinstance(target, Message):
        await target.answer(
            text,
            reply_markup=main_keyboard(user_id)
        )

    else:
        await target.message.edit_text(
            text,
            reply_markup=main_keyboard(user_id)
        )


# =========================================================
# /START
# =========================================================

@dp.message(F.text == "/start")
async def start_handler(message: Message):

    user_id = message.from_user.id

    get_balance(user_id)

    await show_main_menu(
        message,
        user_id
    )


# =========================================================
# MAIN MENU CALLBACK
# =========================================================

@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(
    callback: CallbackQuery
):

    await callback.answer()

    await show_main_menu(
        callback,
        callback.from_user.id
    )


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "menu_games")
async def games_menu(
    callback: CallbackQuery
):

    await callback.answer()

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>МИНИ-ИГРЫ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{money(balance)} ₽\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎮 <b>ВЫБЕРИ ИГРУ</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ 6 игр  •  Ставка от 50 ₽"
    )

    await callback.message.edit_text(
        text,
        reply_markup=games_keyboard()
    )


# =========================================================
# STAKE KEYBOARD
# =========================================================

def stake_keyboard(prefix: str):

    builder = InlineKeyboardBuilder()

    for stake in STAKES:

        builder.button(
            text=f"{stake} ₽",
            callback_data=f"{prefix}_{stake}"
        )

    builder.button(
        text="📂 НАЗАД",
        callback_data="menu_games"
    )

    builder.adjust(2, 2, 1)

    return builder.as_markup()


# =========================================================
# DICE
# =========================================================

@dp.callback_query(F.data == "game_dice")
async def dice_menu(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "🎲 <b>КУБИКИ</b>\n\n"
        "Выбери размер ставки:\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "1 кубик:\n"
        "• меньше 3 — x1.85\n"
        "• больше 3 — x1.85\n"
        "• 3 — проигрыш\n\n"
        "2 кубика:\n"
        "• меньше 7 — x1.85\n"
        "• больше 7 — x1.85\n"
        "• ровно 7 — x5",
        reply_markup=stake_keyboard("dice_stake")
    )


@dp.callback_query(F.data.startswith("dice_stake_"))
async def dice_stake(
    callback: CallbackQuery
):

    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    if get_balance(user_id) < stake:
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲 1 КУБИК",
        callback_data="dice_one"
    )

    builder.button(
        text="🎲🎲 2 КУБИКА",
        callback_data="dice_two"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="game_dice"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        f"🎲 <b>СТАВКА {stake} ₽</b>\n\n"
        "Выбери режим:",
        reply_markup=builder.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.in_({"dice_one", "dice_two"}))
async def dice_mode(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )
        return

    stake = games[user_id]["stake"]
    count = 1 if callback.data == "dice_one" else 2

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        games.pop(user_id, None)
        return

    games[user_id]["count"] = count

    builder = InlineKeyboardBuilder()

    if count == 1:

        builder.button(
            text="⬇️ МЕНЬШЕ 3",
            callback_data="dice_less"
        )

        builder.button(
            text="⬆️ БОЛЬШЕ 3",
            callback_data="dice_more"
        )

    else:

        builder.button(
            text="⬇️ МЕНЬШЕ 7",
            callback_data="dice_less"
        )

        builder.button(
            text="⚖️ РОВНО 7",
            callback_data="dice_equal"
        )

        builder.button(
            text="⬆️ БОЛЬШЕ 7",
            callback_data="dice_more"
        )

    builder.button(
        text="📂 НАЗАД",
        callback_data="menu_games"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        f"🎲 <b>СТАВКА {stake} ₽</b>\n\n"
        "Выбери исход:",
        reply_markup=builder.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "dice_less",
        "dice_more",
        "dice_equal"
    })
)
async def dice_roll(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )
        return

    stake = game["stake"]
    count = game["count"]
    choice = callback.data

    del games[user_id]

    if count == 1:

        dice = await bot.send_dice(
            callback.message.chat.id,
            emoji="🎲"
        )

        value = dice.dice.value

        if choice == "dice_less":
            win = value < 3
        else:
            win = value > 3

        multiplier = 1.85

    else:

        first = await bot.send_dice(
            callback.message.chat.id,
            emoji="🎲"
        )

        await asyncio.sleep(0.8)

        second = await bot.send_dice(
            callback.message.chat.id,
            emoji="🎲"
        )

        value = first.dice.value + second.dice.value

        if choice == "dice_equal":
            win = value == 7
            multiplier = 5
        elif choice == "dice_less":
            win = value < 7
            multiplier = 1.85
        else:
            win = value > 7
            multiplier = 1.85

    if win:

        payout = int(stake * multiplier)

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "dice",
            stake,
            "win",
            multiplier,
            payout
        )

        balance = get_balance(user_id)

        await callback.message.answer(
            "🎲 <b>ПОБЕДА!</b>\n\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>",
            reply_markup=after_game_keyboard()
        )

    else:

        record_game(
            user_id,
            "dice",
            stake,
            "loss",
            multiplier,
            0
        )

        balance = get_balance(user_id)

        await callback.message.answer(
            "🎲 <b>ПРОИГРЫШ</b>\n\n"
            f"💸 Ставка: {money(stake)} ₽\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>",
            reply_markup=after_game_keyboard()
        )

    await callback.answer()


# =========================================================
# SLOTS
# =========================================================

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
            multiplier = 5
        elif result[0] == "🍇":
            multiplier = 8
        elif result[0] == "🍋":
            multiplier = 10
        elif result[0] == "7️⃣":
            multiplier = 50
        else:
            multiplier = 3.5

    elif (
        result[0] == result[1]
        or result[1] == result[2]
        or result[0] == result[2]
    ):

        multiplier = 1.85

    else:

        multiplier = 0

    return result, multiplier


@dp.callback_query(F.data == "game_slots")
async def slots_menu(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "Попробуй поймать комбинацию!\n\n"
        "🍸🍸 — x1.85\n"
        "🍸🍸🍸 — x5\n"
        "🍇🍇🍇 — x8\n"
        "🍋🍋🍋 — x10\n"
        "7️⃣7️⃣7️⃣ — x50\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери ставку:",
        reply_markup=stake_keyboard("slots_stake")
    )


@dp.callback_query(F.data.startswith("slots_stake_"))
async def slots_stake(callback: CallbackQuery):

    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    if get_balance(user_id) < stake:
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    if not subtract_balance(user_id, stake):

        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    result_message = await bot.send_dice(
        callback.message.chat.id,
        emoji="🎰"
    )

    await asyncio.sleep(2)

    result, multiplier = slot_result(
        result_message.dice.value
    )

    if multiplier > 0:

        payout = int(stake * multiplier)

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "slots",
            stake,
            "win",
            multiplier,
            payout
        )

        await callback.message.answer(
            "🎰 <b>ПОБЕДА!</b>\n\n"
            f"{' '.join(result)}\n\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard()
        )

    else:

        record_game(
            user_id,
            "slots",
            stake,
            "loss",
            0,
            0
        )

        await callback.message.answer(
            "🎰 <b>ПРОИГРЫШ</b>\n\n"
            f"{' '.join(result)}\n\n"
            f"💸 Ставка: {money(stake)} ₽\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard()
        )

    await callback.answer()


# =========================================================
# ROULETTE
# =========================================================

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}


@dp.callback_query(F.data == "game_roulette")
async def roulette_menu(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "🎡 <b>РУЛЕТКА</b>\n\n"
        "Выбери ставку:\n\n"
        "🔴 Красное — x1.95\n"
        "⚫ Чёрное — x1.95\n"
        "⬆️ 1–18 — x1.95\n"
        "⬇️ 19–36 — x1.95\n"
        "➗ Чётное — x1.95\n"
        "➖ Нечётное — x1.95\n"
        "🟢 Ноль — x36",
        reply_markup=stake_keyboard("roulette_stake")
    )


@dp.callback_query(F.data.startswith("roulette_stake_"))
async def roulette_stake(callback: CallbackQuery):

    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    if get_balance(user_id) < stake:
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "roulette",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔴 КРАСНОЕ",
        callback_data="roulette_red"
    )

    builder.button(
        text="⚫ ЧЁРНОЕ",
        callback_data="roulette_black"
    )

    builder.button(
        text="⬆️ 1–18",
        callback_data="roulette_low"
    )

    builder.button(
        text="⬇️ 19–36",
        callback_data="roulette_high"
    )

    builder.button(
        text="➗ ЧЁТНОЕ",
        callback_data="roulette_even"
    )

    builder.button(
        text="➖ НЕЧЁТНОЕ",
        callback_data="roulette_odd"
    )

    builder.button(
        text="🟢 НОЛЬ",
        callback_data="roulette_zero"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="game_roulette"
    )

    builder.adjust(2, 2, 2, 1, 1)

    await callback.message.edit_text(
        f"🎡 <b>СТАВКА {stake} ₽</b>\n\n"
        "Выбери ставку на исход:",
        reply_markup=builder.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("roulette_"))
async def roulette_play(callback: CallbackQuery):

    user_id = callback.from_user.id

    if callback.data == "roulette_stake":
        return

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )
        return

    if callback.data == "roulette_stake":
        return

    if callback.data in (
        "roulette_red",
        "roulette_black",
        "roulette_low",
        "roulette_high",
        "roulette_even",
        "roulette_odd",
        "roulette_zero"
    ):

        stake = game["stake"]

        if not subtract_balance(user_id, stake):

            del games[user_id]

            await callback.answer(
                "❌ Недостаточно средств.",
                show_alert=True
            )
            return

        choice = callback.data.replace(
            "roulette_",
            ""
        )

        result = random.randint(0, 36)

        if result == 0:
            color = "🟢"
        elif result in RED_NUMBERS:
            color = "🔴"
        else:
            color = "⚫"

        if choice == "red":
            win = result in RED_NUMBERS
            multiplier = 1.95

        elif choice == "black":
            win = (
                result != 0
                and result not in RED_NUMBERS
            )
            multiplier = 1.95

        elif choice == "low":
            win = 1 <= result <= 18
            multiplier = 1.95

        elif choice == "high":
            win = 19 <= result <= 36
            multiplier = 1.95

        elif choice == "even":
            win = result != 0 and result % 2 == 0
            multiplier = 1.95

        elif choice == "odd":
            win = result % 2 == 1
            multiplier = 1.95

        else:
            win = result == 0
            multiplier = 36

        del games[user_id]

        if win:

            payout = int(stake * multiplier)

            change_balance(
                user_id,
                payout
            )

            record_game(
                user_id,
                "roulette",
                stake,
                "win",
                multiplier,
                payout
            )

            await callback.message.answer(
                "🎡 <b>РУЛЕТКА</b>\n\n"
                f"{color} <b>{result}</b>\n\n"
                "🎉 <b>ПОБЕДА!</b>\n"
                f"💰 +{money(payout)} ₽\n"
                f"💳 Баланс: {money(get_balance(user_id))} ₽",
                reply_markup=after_game_keyboard()
            )

        else:

            record_game(
                user_id,
                "roulette",
                stake,
                "loss",
                multiplier,
                0
            )

            await callback.message.answer(
                "🎡 <b>РУЛЕТКА</b>\n\n"
                f"{color} <b>{result}</b>\n\n"
                "💸 <b>ПРОИГРЫШ</b>\n"
                f"Ставка: {money(stake)} ₽\n"
                f"💳 Баланс: {money(get_balance(user_id))} ₽",
                reply_markup=after_game_keyboard()
            )

        await callback.answer()


# =========================================================
# BOWLING
# =========================================================

@dp.callback_query(F.data == "game_bowling")
async def bowling_menu(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "🎳 <b>БОУЛИНГ</b>\n\n"
        "Выбери ставку:",
        reply_markup=stake_keyboard("bowling_stake")
    )


@dp.callback_query(F.data.startswith("bowling_stake_"))
async def bowling_stake(callback: CallbackQuery):

    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    if get_balance(user_id) < stake:
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "bowling",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️ МЕНЬШЕ 3",
        callback_data="bowling_less"
    )

    builder.button(
        text="⬆️ БОЛЬШЕ 3",
        callback_data="bowling_more"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="game_bowling"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        f"🎳 <b>СТАВКА {stake} ₽</b>\n\n"
        "Выбери исход:",
        reply_markup=builder.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "bowling_less",
        "bowling_more"
    })
)
async def bowling_play(callback: CallbackQuery):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(user_id, stake):

        del games[user_id]

        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    del games[user_id]

    choice = callback.data

    result_message = await bot.send_dice(
        callback.message.chat.id,
        emoji="🎳"
    )

    await asyncio.sleep(2)

    value = result_message.dice.value

    if choice == "bowling_less":
        win = value < 3
    else:
        win = value > 3

    multiplier = 1.85

    if win:

        payout = int(stake * multiplier)

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "bowling",
            stake,
            "win",
            multiplier,
            payout
        )

        await callback.message.answer(
            "🎳 <b>ПОБЕДА!</b>\n\n"
            f"💰 +{money(payout)} ₽\n"
            f"💳 Баланс: {money(get_balance(user_id))} ₽",
            reply_markup=after_game_keyboard()
        )

    else:

        record_game(
            user_id,
            "bowling",
            stake,
            "loss",
            multiplier,
            0
        )

        await callback.message.answer(
            "🎳 <b>ПРОИГРЫШ</b>\n\n"
            f"💸 -{money(stake)} ₽\n"
            f"💳 Баланс: {money(get_balance(user_id))} ₽",
            reply_markup=after_game_keyboard()
        )

    await callback.answer()


# =========================================================
# MINES
# =========================================================

MINES_MULTIPLIERS = {
    1: 1.15,
    2: 1.35,
    3: 1.60,
    4: 1.95,
    5: 2.40,
    6: 3.00,
}


def mines_keyboard(game):

    builder = InlineKeyboardBuilder()

    opened = game["opened"]
    mines = game["mines"]

    for i in range(9):

        if i in opened:
            text = "💎"

        elif i in mines and game.get("finished"):
            text = "💣"

        else:
            text = "▫️"

        builder.button(
            text=text,
            callback_data=f"mine_{i}"
        )

    if opened and not game.get("finished"):

        builder.button(
            text="💰 ЗАБРАТЬ",
            callback_data="mine_cashout"
        )

    builder.button(
        text="📂 МЕНЮ",
        callback_data="menu_games"
    )

    builder.adjust(3, 3, 3, 1, 1)

    return builder.as_markup()


@dp.callback_query(F.data == "game_mines")
async def mines_menu(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "💣 <b>МИНЫ</b>\n\n"
        "3 мины • 6 безопасных клеток\n\n"
        "💎 1 — x1.15\n"
        "💎 2 — x1.35\n"
        "💎 3 — x1.60\n"
        "💎 4 — x1.95\n"
        "💎 5 — x2.40\n"
        "💎 6 — x3.00\n\n"
        "Выбери ставку:",
        reply_markup=stake_keyboard("mines_stake")
    )


@dp.callback_query(F.data.startswith("mines_stake_"))
async def mines_stake(callback: CallbackQuery):

    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    if get_balance(user_id) < stake:
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    mines = set(
        random.sample(
            range(9),
            3
        )
    )

    games[user_id] = {
        "type": "mines",
        "stake": stake,
        "mines": mines,
        "opened": set(),
        "finished": False
    }

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"Ставка: <b>{money(stake)} ₽</b>\n\n"
        "Открывай безопасные клетки 💎",
        reply_markup=mines_keyboard(
            games[user_id]
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("mine_"))
async def mines_play(callback: CallbackQuery):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game["type"] != "mines":

        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )
        return

    if callback.data == "mine_cashout":

        opened_count = len(game["opened"])

        if opened_count == 0:

            await callback.answer(
                "Сначала открой хотя бы одну клетку.",
                show_alert=True
            )
            return

        multiplier = MINES_MULTIPLIERS[
            opened_count
        ]

        payout = int(
            game["stake"] * multiplier
        )

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "mines",
            game["stake"],
            "win",
            multiplier,
            payout
        )

        del games[user_id]

        await callback.message.edit_text(
            "💣 <b>МИНЫ</b>\n\n"
            "💰 <b>ВЫ ЗАБРАЛИ ВЫИГРЫШ!</b>\n\n"
            f"Множитель: x{multiplier}\n"
            f"Выигрыш: <b>+{money(payout)} ₽</b>\n"
            f"Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard()
        )

        await callback.answer()
        return

    cell = int(
        callback.data.split("_")[-1]
    )

    if cell in game["opened"]:

        await callback.answer(
            "Эта клетка уже открыта.",
            show_alert=True
        )
        return

    if cell in game["mines"]:

        game["finished"] = True

        record_game(
            user_id,
            "mines",
            game["stake"],
            "loss",
            0,
            0
        )

        del games[user_id]

        await callback.message.edit_text(
            "💣 <b>МИНЫ</b>\n\n"
            "💥 <b>МИНА!</b>\n\n"
            f"💸 Потеряно: {money(game['stake'])} ₽\n"
            f"💳 Баланс: {money(get_balance(user_id))} ₽",
            reply_markup=after_game_keyboard()
        )

        await callback.answer(
            "💣 Мина!",
            show_alert=True
        )
        return

    game["opened"].add(cell)

    count = len(game["opened"])
    multiplier = MINES_MULTIPLIERS[count]

    if count == 6:

        payout = int(
            game["stake"] * multiplier
        )

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "mines",
            game["stake"],
            "win",
            multiplier,
            payout
        )

        del games[user_id]

        await callback.message.edit_text(
            "💣 <b>МИНЫ</b>\n\n"
            "🏆 <b>ВСЕ КЛЕТКИ ОТКРЫТЫ!</b>\n\n"
            f"x{multiplier}\n"
            f"💰 +{money(payout)} ₽\n"
            f"💳 Баланс: {money(get_balance(user_id))} ₽",
            reply_markup=after_game_keyboard()
        )

        await callback.answer()
        return

    await callback.message.edit_text(
        "💣 <b>МИНЫ</b>\n\n"
        f"💎 Открыто: {count}/6\n"
        f"🔥 Множитель: x{multiplier}\n\n"
        "Продолжить или забрать выигрыш?",
        reply_markup=mines_keyboard(game)
    )

    await callback.answer()


# =========================================================
# CRASH
# =========================================================

def generate_crash_point():

    value = random.expovariate(
        1.0 / CRASH_MEAN
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


@dp.callback_query(F.data == "game_crash")
async def crash_menu(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        "🧨 <b>CRASH</b>\n\n"
        "Коэффициент растёт.\n"
        "Забери выигрыш до краша.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери ставку:",
        reply_markup=stake_keyboard("crash_stake")
    )


@dp.callback_query(F.data.startswith("crash_stake_"))
async def crash_stake(callback: CallbackQuery):

    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    if get_balance(user_id) < stake:

        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    crash_point = generate_crash_point()

    games[user_id] = {
        "type": "crash",
        "stake": stake,
        "crash_point": crash_point,
        "current": 1.00,
        "active": True
    }

    message = await callback.message.edit_text(
        "🧨 <b>CRASH</b>\n\n"
        "📈 <b>1.00x</b>\n\n"
        f"💰 Ставка: {money(stake)} ₽",
        reply_markup=crash_keyboard()
    )

    games[user_id]["message_id"] = message.message_id

    asyncio.create_task(
        crash_loop(
            user_id,
            callback.message.chat.id
        )
    )

    await callback.answer()


def crash_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰 ЗАБРАТЬ",
        callback_data="crash_cashout"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data="crash_cancel"
    )

    builder.adjust(1)

    return builder.as_markup()


async def crash_loop(
    user_id: int,
    chat_id: int
):

    while True:

        await asyncio.sleep(0.7)

        game = games.get(user_id)

        if not game:
            return

        if game["type"] != "crash":
            return

        if not game["active"]:
            return

        current = game["current"]
        crash_point = game["crash_point"]

        if current >= crash_point:

            game["active"] = False

            record_game(
                user_id,
                "crash",
                game["stake"],
                "loss",
                current,
                0
            )

            try:

                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=game["message_id"],
                    text=(
                        "🧨 <b>CRASH</b>\n\n"
                        f"💥 <b>{crash_point:.2f}x</b>\n\n"
                        "💸 КРАШ!"
                    ),
                    reply_markup=after_game_keyboard()
                )

            except Exception:
                pass

            games.pop(user_id, None)

            return

        if current < 2:
            current += 0.05
        elif current < 5:
            current += 0.08
        else:
            current += 0.12

        current = round(
            current,
            2
        )

        game["current"] = current

        try:

            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=game["message_id"],
                text=(
                    "🧨 <b>CRASH</b>\n\n"
                    f"📈 <b>{current:.2f}x</b>\n\n"
                    f"💰 Ставка: {money(game['stake'])} ₽"
                ),
                reply_markup=crash_keyboard()
            )

        except Exception:
            pass


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout(callback: CallbackQuery):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game["type"] != "crash":

        await callback.answer(
            "Игра уже закончена.",
            show_alert=True
        )
        return

    if not game["active"]:

        await callback.answer(
            "Слишком поздно.",
            show_alert=True
        )
        return

    game["active"] = False

    multiplier = game["current"]

    payout = int(
        game["stake"] * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    record_game(
        user_id,
        "crash",
        game["stake"],
        "win",
        multiplier,
        payout
    )

    games.pop(user_id, None)

    await callback.message.edit_text(
        "🧨 <b>CRASH</b>\n\n"
        "💰 <b>ВЫ ЗАБРАЛИ!</b>\n\n"
        f"📈 Множитель: x{multiplier:.2f}\n"
        f"💰 Выигрыш: +{money(payout)} ₽\n"
        f"💳 Баланс: {money(get_balance(user_id))} ₽",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel(callback: CallbackQuery):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game["type"] != "crash":

        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )
        return

    game["active"] = False

    change_balance(
        user_id,
        game["stake"]
    )

    games.pop(user_id, None)

    await callback.message.edit_text(
        "🧨 <b>CRASH</b>\n\n"
        "Игра отменена.\n\n"
        f"💰 Возвращено: {money(game['stake'])} ₽\n"
        f"💳 Баланс: {money(get_balance(user_id))} ₽",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# DICE MESSAGE HANDLER
# =========================================================

@dp.message(F.dice)
async def dice_message_handler(message: Message):

    if message.dice.emoji != "🎲":
        return


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(
    callback: CallbackQuery
):

    await callback.answer()

    user_id = callback.from_user.id

    stats = get_user_stats(user_id)

    text = (
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Баланс: <b>{money(stats['balance'])} ₽</b>\n\n"
        f"🎮 Игр сыграно: <b>{stats['games_played']}</b>\n"
        f"🏆 Побед: <b>{stats['wins']}</b>\n"
        f"💔 Поражений: <b>{stats['losses']}</b>\n\n"
        f"💵 Всего ставок: <b>{money(stats['total_bet'])} ₽</b>\n"
        f"💰 Всего выиграно: <b>{money(stats['total_won'])} ₽</b>\n"
        f"🔥 Максимальный выигрыш: <b>{money(stats['biggest_win'])} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    await callback.message.edit_text(
        text,
        reply_markup=profile_keyboard()
    )


# =========================================================
# HISTORY
# =========================================================

def format_history_date(value):

    try:

        dt = datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S"
        )

        return dt.strftime(
            "%d.%m.%Y %H:%M"
        )

    except Exception:

        return value


@dp.callback_query(F.data.startswith("history_"))
async def history(
    callback: CallbackQuery
):

    await callback.answer()

    user_id = callback.from_user.id

    try:
        page = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        page = 0

    all_games = get_game_history(
        user_id,
        limit=100
    )

    per_page = 5

    total_pages = max(
        1,
        (len(all_games) + per_page - 1)
        // per_page
    )

    page = max(
        0,
        min(page, total_pages - 1)
    )

    start = page * per_page
    items = all_games[
        start:start + per_page
    ]

    if not items:

        text = (
            "📜 <b>ИСТОРИЯ ИГР</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "История пока пуста.\n\n"
            "🎰 Сыграй первую игру!"
        )

    else:

        lines = [
            "📜 <b>ИСТОРИЯ ИГР</b>",
            "",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for item in items:

            game_name = {
                "dice": "🎲 Кубики",
                "slots": "🎰 Слоты",
                "roulette": "🎡 Рулетка",
                "bowling": "🎳 Боулинг",
                "mines": "💣 Мины",
                "crash": "🧨 Crash"
            }.get(
                item["game"],
                item["game"]
            )

            date = format_history_date(
                item["created_at"]
            )

            if item["result"] == "win":

                result = (
                    f"🟢 +{money(item['payout'])} ₽"
                )

            else:

                result = (
                    f"🔴 -{money(item['stake'])} ₽"
                )

            lines.append(
                f"{game_name} • {result}"
            )

            lines.append(
                f"🕒 {date} UTC"
            )

            if item["result"] == "win":

                lines.append(
                    f"📈 x{item['multiplier']}"
                )

            lines.append("")

        lines.append(
            f"Страница {page + 1}/{total_pages}"
        )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    if page > 0:

        builder.button(
            text="⬅️",
            callback_data=f"history_{page - 1}"
        )

    if page < total_pages - 1:

        builder.button(
            text="➡️",
            callback_data=f"history_{page + 1}"
        )

    if all_games:

        builder.button(
            text="🗑 ОЧИСТИТЬ ИСТОРИЮ",
            callback_data="history_clear"
        )

    builder.button(
        text="👤 ПРОФИЛЬ",
        callback_data="profile"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="main_menu"
    )

    builder.adjust(2, 1, 1, 1)

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup()
    )


# =========================================================
# CLEAR HISTORY
# =========================================================

def clear_user_history(user_id: int):

    connection = sqlite3.connect(
        DB_PATH
    )

    connection.execute(
        """
        DELETE FROM game_history
        WHERE user_id = ?
        """,
        (user_id,)
    )

    connection.commit()
    connection.close()


@dp.callback_query(F.data == "history_clear")
async def history_clear(
    callback: CallbackQuery
):

    await callback.answer()

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ ДА, ОЧИСТИТЬ",
        callback_data="history_clear_confirm"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data="history_0"
    )

    builder.adjust(1)

    await callback.message.edit_text(
        "🗑 <b>ОЧИСТКА ИСТОРИИ</b>\n\n"
        "Ты действительно хочешь удалить историю игр?\n\n"
        "⚠️ Статистика профиля при этом <b>не изменится</b>.",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(
    F.data == "history_clear_confirm"
)
async def history_clear_confirm(
    callback: CallbackQuery
):

    clear_user_history(
        callback.from_user.id
    )

    await callback.answer(
        "История очищена."
    )

    await history(
        callback
    )


# =========================================================
# ADMIN MENU
# =========================================================

def admin_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👥 ПОЛЬЗОВАТЕЛЬ",
        callback_data="admin_user"
    )

    builder.button(
        text="📊 СТАТИСТИКА",
        callback_data="admin_stats"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="main_menu"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if not is_admin(user_id):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        "👑 <b>ADMIN PANEL</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Центр управления Resonant Casino.\n\n"
        "Выбери действие:",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN USER SEARCH
# =========================================================

@dp.callback_query(F.data == "admin_user")
async def admin_user(
    callback: CallbackQuery
):

    if not is_admin(
        callback.from_user.id
    ):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True
        )
        return

    games[
        callback.from_user.id
    ] = {
        "type": "admin_user_search"
    }

    await callback.answer()

    await callback.message.edit_text(
        "👥 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
        "Отправь Telegram ID пользователя.\n\n"
        "Например:\n"
        "<code>123456789</code>\n\n"
        "Для отмены отправь /cancel"
    )


@dp.message()
async def text_message_handler(
    message: Message
):

    user_id = message.from_user.id

    # -----------------------------------------------------
    # ADMIN USER SEARCH
    # -----------------------------------------------------

    state = games.get(user_id)

    if (
        is_admin(user_id)
        and state
        and state.get("type") == "admin_user_search"
    ):

        if message.text == "/cancel":

            games.pop(
                user_id,
                None
            )

            await message.answer(
                "👑 Админ-панель:",
                reply_markup=admin_keyboard()
            )

            return

        if not message.text.isdigit():

            await message.answer(
                "❌ ID должен состоять только из цифр.\n\n"
                "Попробуй ещё раз."
            )

            return

        target_id = int(
            message.text
        )

        games.pop(
            user_id,
            None
        )

        try:

            stats = get_user_stats(
                target_id
            )

        except Exception:

            await message.answer(
                "❌ Не удалось найти пользователя."
            )

            return

        games[user_id] = {
            "type": "admin_target",
            "target_id": target_id
        }

        builder = InlineKeyboardBuilder()

        builder.button(
            text="💰 ДОБАВИТЬ 100 ₽",
            callback_data="admin_add_100"
        )

        builder.button(
            text="💰 ДОБАВИТЬ 500 ₽",
            callback_data="admin_add_500"
        )

        builder.button(
            text="💰 ДОБАВИТЬ 1000 ₽",
            callback_data="admin_add_1000"
        )

        builder.button(
            text="💸 СНЯТЬ 100 ₽",
            callback_data="admin_sub_100"
        )

        builder.button(
            text="💸 СНЯТЬ 500 ₽",
            callback_data="admin_sub_500"
        )

        builder.button(
            text="💸 СНЯТЬ 1000 ₽",
            callback_data="admin_sub_1000"
        )

        builder.button(
            text="👑 АДМИН-ПАНЕЛЬ",
            callback_data="admin_panel"
        )

        builder.adjust(1)

        await message.answer(
            "👥 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 ID: <code>{target_id}</code>\n"
            f"💰 Баланс: <b>{money(stats['balance'])} ₽</b>\n\n"
            f"🎮 Игр: {stats['games_played']}\n"
            f"🏆 Побед: {stats['wins']}\n"
            f"💔 Поражений: {stats['losses']}\n\n"
            f"💵 Ставок: {money(stats['total_bet'])} ₽\n"
            f"💰 Выплат: {money(stats['total_won'])} ₽\n"
            f"🔥 Макс. выигрыш: {money(stats['biggest_win'])} ₽",
            reply_markup=builder.as_markup()
        )

        return


# =========================================================
# ADMIN BALANCE ACTIONS
# =========================================================

async def admin_change_target_balance(
    callback: CallbackQuery,
    amount: int
):

    if not is_admin(
        callback.from_user.id
    ):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True
        )
        return

    state = games.get(
        callback.from_user.id
    )

    if not state:
        await callback.answer(
            "Пользователь не выбран.",
            show_alert=True
        )
        return

    target_id = state.get(
        "target_id"
    )

    if not target_id:
        await callback.answer(
            "Пользователь не выбран.",
            show_alert=True
        )
        return

    new_balance = change_balance(
        target_id,
        amount
    )

    await callback.answer(
        "Баланс изменён."
    )

    await callback.message.edit_text(
        "👥 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"💰 Новый баланс: <b>{money(new_balance)} ₽</b>\n\n"
        (
            f"🟢 Добавлено: +{money(amount)} ₽"
            if amount > 0
            else f"🔴 Списано: {money(abs(amount))} ₽"
        ),
        reply_markup=admin_target_keyboard()
    )


def admin_target_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰 +100 ₽",
        callback_data="admin_add_100"
    )

    builder.button(
        text="💰 +500 ₽",
        callback_data="admin_add_500"
    )

    builder.button(
        text="💰 +1000 ₽",
        callback_data="admin_add_1000"
    )

    builder.button(
        text="💸 -100 ₽",
        callback_data="admin_sub_100"
    )

    builder.button(
        text="💸 -500 ₽",
        callback_data="admin_sub_500"
    )

    builder.button(
        text="💸 -1000 ₽",
        callback_data="admin_sub_1000"
    )

    builder.button(
        text="👑 АДМИН-ПАНЕЛЬ",
        callback_data="admin_panel"
    )

    builder.adjust(3, 3, 1)

    return builder.as_markup()


@dp.callback_query(F.data == "admin_add_100")
async def admin_add_100(
    callback: CallbackQuery
):

    await admin_change_target_balance(
        callback,
        100
    )


@dp.callback_query(F.data == "admin_add_500")
async def admin_add_500(
    callback: CallbackQuery
):

    await admin_change_target_balance(
        callback,
        500
    )


@dp.callback_query(F.data == "admin_add_1000")
async def admin_add_1000(
    callback: CallbackQuery
):

    await admin_change_target_balance(
        callback,
        1000
    )


@dp.callback_query(F.data == "admin_sub_100")
async def admin_sub_100(
    callback: CallbackQuery
):

    await admin_change_target_balance(
        callback,
        -100
    )


@dp.callback_query(F.data == "admin_sub_500")
async def admin_sub_500(
    callback: CallbackQuery
):

    await admin_change_target_balance(
        callback,
        -500
    )


@dp.callback_query(F.data == "admin_sub_1000")
async def admin_sub_1000(
    callback: CallbackQuery
):

    await admin_change_target_balance(
        callback,
        -1000
    )


# =========================================================
# ADMIN STATISTICS
# =========================================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(
    callback: CallbackQuery
):

    if not is_admin(
        callback.from_user.id
    ):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True
        )
        return

    connection = sqlite3.connect(
        DB_PATH
    )

    connection.row_factory = sqlite3.Row

    users_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        """
    ).fetchone()["count"]

    games_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM game_history
        """
    ).fetchone()["count"]

    total_bet = connection.execute(
        """
        SELECT COALESCE(
            SUM(total_bet),
            0
        ) AS total
        FROM users
        """
    ).fetchone()["total"]

    total_won = connection.execute(
        """
        SELECT COALESCE(
            SUM(total_won),
            0
        ) AS total
        FROM users
        """
    ).fetchone()["total"]

    total_balance = connection.execute(
        """
        SELECT COALESCE(
            SUM(balance),
            0
        ) AS total
        FROM users
        """
    ).fetchone()["total"]

    connection.close()

    await callback.answer()

    await callback.message.edit_text(
        "📊 <b>СТАТИСТИКА КАЗИНО</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователей: <b>{users_count}</b>\n"
        f"🎮 Игр сыграно: <b>{games_count}</b>\n\n"
        f"💵 Всего ставок: <b>{money(total_bet)} ₽</b>\n"
        f"💰 Всего выплат: <b>{money(total_won)} ₽</b>\n"
        f"🏦 Баланс игроков: <b>{money(total_balance)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━",
        reply_markup=admin_keyboard()
    )


# =========================================================
# WEBHOOK
# =========================================================

@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request
):

    data = await request.json()

    update = Update.model_validate(
        data,
        context={
            "bot": bot
        }
    )

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "10000"
            )
        )
    )
