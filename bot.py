import asyncio
import os
import random

from fastapi import FastAPI, Request

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
    get_user_stats,
    get_game_history,
    record_game,
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
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()
app = FastAPI()

init_db()


# =========================================================
# SETTINGS
# =========================================================

STAKE_OPTIONS = [
    50,
    100,
    250,
    500,
    1000,
]


# =========================================================
# DICE
# =========================================================

DICE_ONE_MULTIPLIER = 1.85
DICE_TWO_MULTIPLIER = 1.85
DICE_TWO_EQUAL_MULTIPLIER = 5.00


# =========================================================
# SLOTS
# =========================================================

SLOT_TWO_MULTIPLIER = 1.85
SLOT_OTHER_THREE_MULTIPLIER = 3.5
SLOT_COCKTAIL_MULTIPLIER = 5
SLOT_GRAPES_MULTIPLIER = 8
SLOT_LEMON_MULTIPLIER = 10
SLOT_SEVEN_MULTIPLIER = 50


# =========================================================
# ROULETTE
# =========================================================

ROULETTE_MULTIPLIER = 1.95
ROULETTE_ZERO_MULTIPLIER = 36

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25,
    27, 30, 32, 34, 36
}


# =========================================================
# BOWLING
# =========================================================

BOWLING_MULTIPLIER = 1.85


# =========================================================
# MINES
# =========================================================

MINES_COUNT = 3

MINES_MULTIPLIERS = {
    1: 1.15,
    2: 1.35,
    3: 1.60,
    4: 1.95,
    5: 2.40,
    6: 3.00,
}


# =========================================================
# CRASH
# =========================================================

CRASH_MIN = 1.00
CRASH_MAX = 20.00

# Настройка вероятности Crash.
# Чем меньше значение, тем чаще будут ранние Crash.
# Было: 2.5
# Сейчас: 2.1
CRASH_MEAN = 2.1


# =========================================================
# ACTIVE GAMES
# =========================================================

games = {}


# =========================================================
# HELPERS
# =========================================================

def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


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
# STAKE MENU
# =========================================================

def stake_menu(game_name: str):
    builder = InlineKeyboardBuilder()

    for amount in STAKE_OPTIONS:
        builder.button(
            text=f"💰  {money(amount)} ₽",
            callback_data=f"stake_{game_name}_{amount}"
        )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(2, 2, 1, 1)

    return builder.as_markup()


def stake_card(
    game_title: str,
    balance: int
):
    return (
        f"<b>{game_title}</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{money(balance)} ₽\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
        "💡 Ставка действует только для этой игры.\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )


# =========================================================
# START
# =========================================================

@dp.message(F.text == "/start")
async def start_command(message: Message):

    user_id = message.from_user.id

    if user_id in games:
        del games[user_id]

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

    await message.answer(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# MAIN MENU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

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

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

def profile_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📜  ИСТОРИЯ ИГР",
        callback_data="history"
    )

    builder.button(
        text="🎰  ИГРЫ",
        callback_data="mini_games"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="menu"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    stats = get_user_stats(user_id)

    balance = stats["balance"]
    games_played = stats["games_played"]
    wins = stats["wins"]
    losses = stats["losses"]
    total_bet = stats["total_bet"]
    total_won = stats["total_won"]
    biggest_win = stats["biggest_win"]

    text = (
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Баланс</b>\n"
        f"{money(balance)} ₽\n\n"
        "🎮 <b>СТАТИСТИКА</b>\n\n"
        f"🎲 Игр сыграно: <b>{games_played}</b>\n"
        f"🏆 Побед: <b>{wins}</b>\n"
        f"💥 Поражений: <b>{losses}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💵 <b>ФИНАНСЫ</b>\n\n"
        f"🎯 Сумма ставок: <b>{money(total_bet)} ₽</b>\n"
        f"💎 Сумма выигрышей: <b>{money(total_won)} ₽</b>\n"
        f"🏅 Макс. выигрыш: <b>{money(biggest_win)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    await callback.message.edit_text(
        text,
        reply_markup=profile_keyboard()
    )

    await callback.answer()


# =========================================================
# HISTORY
# =========================================================

def history_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤  ПРОФИЛЬ",
        callback_data="profile"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="menu"
    )

    builder.adjust(1)

    return builder.as_markup()


def history_game_name(game):

    names = {
        "dice_one": "🎲 Кубик",
        "dice_two": "🎲🎲 2 Кубика",
        "slots": "🎰 Слоты",
        "roulette": "🎡 Рулетка",
        "bowling": "🎳 Боуллинг",
        "mines": "💣 Мины",
        "crash": "🧨 Crash",
    }

    return names.get(
        game,
        game
    )


@dp.callback_query(F.data == "history")
async def history_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    history = get_game_history(
        user_id,
        limit=10
    )

    if not history:

        text = (
            "📜 <b>ИСТОРИЯ ИГР</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🎮 Здесь пока нет сыгранных игр.\n\n"
            "Начни играть, и результаты появятся здесь."
        )

    else:

        lines = [
            "📜 <b>ИСТОРИЯ ИГР</b>",
            "",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for item in history:

            game_name = history_game_name(
                item["game"]
            )

            stake = item["stake"]
            result = item["result"]
            multiplier = item["multiplier"]
            payout = item["payout"]

            if result == "win":

                result_icon = "🟢"
                result_text = (
                    f"+{money(payout)} ₽"
                )

            else:

                result_icon = "🔴"
                result_text = (
                    f"-{money(stake)} ₽"
                )

            if multiplier > 0:

                multiplier_text = (
                    f" • x{multiplier:g}"
                )

            else:

                multiplier_text = ""

            lines.append(
                f"{result_icon} {game_name}"
            )

            lines.append(
                f"   Ставка: {money(stake)} ₽"
                f"{multiplier_text}"
            )

            lines.append(
                f"   Результат: <b>{result_text}</b>"
            )

            lines.append("")

        lines.append(
            "━━━━━━━━━━━━━━━━━━"
        )

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=history_keyboard()
    )

    await callback.answer()


# =========================================================
# MINI GAMES
# =========================================================

@dp.callback_query(F.data == "mini_games")
async def mini_games_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

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
        reply_markup=mini_games_menu()
    )

    await callback.answer()


# =========================================================
# DICE
# =========================================================

def dice_mode_menu():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲  1 КУБИК • x1.85",
        callback_data="dice_one"
    )

    builder.button(
        text="🎲🎲  2 КУБИКА • до x5.00",
        callback_data="dice_two"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="dice"
    )

    builder.adjust(1)

    return builder.as_markup()


def dice_bet_menu():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️  МЕНЬШЕ 3",
        callback_data="dice_bet_less"
    )

    builder.button(
        text="⬆️  БОЛЬШЕ 3",
        callback_data="dice_bet_more"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="dice"
    )

    builder.adjust(1)

    return builder.as_markup()


def dice_two_menu():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎯  РАВНО 7 • x5.00",
        callback_data="dice_two_equal"
    )

    builder.button(
        text="⬇️  МЕНЬШЕ 7 • x1.85",
        callback_data="dice_two_less"
    )

    builder.button(
        text="⬆️  БОЛЬШЕ 7 • x1.85",
        callback_data="dice_two_more"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="dice"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "dice")
async def dice_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        stake_card(
            "🎲 КУБИКИ",
            balance
        ),
        reply_markup=stake_menu("dice")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stake_dice_"))
async def dice_stake_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    balance = get_balance(user_id)

    games[user_id] = {
        "type": "dice_setup",
        "stake": stake
    }

    text = (
        "🎲 <b>КУБИКИ</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>ВЫБЕРИ РЕЖИМ</b>\n\n"
        "🎲 <b>1 КУБИК</b>\n"
        "⬇️ Меньше 3 • ⬆️ Больше 3\n"
        "💎 x1.85\n\n"
        "🎲🎲 <b>2 КУБИКА</b>\n"
        "🎯 Равно 7 • ⬇️ Меньше 7 • ⬆️ Больше 7\n"
        "💎 до x5.00\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Ставка: {money(stake)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=dice_mode_menu()
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ выбрана"
    )


@dp.callback_query(F.data == "dice_one")
async def dice_one_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_setup":

        await callback.answer(
            "Сначала выбери ставку.",
            show_alert=True
        )

        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    games[user_id] = {
        "type": "dice_one",
        "stake": stake,
        "bet": None
    }

    await callback.message.edit_text(
        (
            "🎲 <b>1 КУБИК</b>\n\n"
            f"💰 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 <b>ВЫБЕРИ РЕЗУЛЬТАТ</b>\n\n"
            "⬇️ Меньше 3\n"
            "⬆️ Больше 3"
        ),
        reply_markup=dice_bet_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_bet_less")
async def dice_bet_less(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_one":

        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )

        return

    game["bet"] = "less"

    await callback.answer(
        "Бросаем 🎲"
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )


@dp.callback_query(F.data == "dice_bet_more")
async def dice_bet_more(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_one":

        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )

        return

    game["bet"] = "more"

    await callback.answer(
        "Бросаем 🎲"
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )


@dp.callback_query(F.data == "dice_two")
async def dice_two_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_setup":

        await callback.answer(
            "Сначала выбери ставку.",
            show_alert=True
        )

        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    games[user_id] = {
        "type": "dice_two_setup",
        "stake": stake,
        "bet": None,
        "first": None
    }

    await callback.message.edit_text(
        (
            "🎲🎲 <b>2 КУБИКА</b>\n\n"
            f"💰 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
            "🎯 Равно 7 • x5.00\n"
            "⬇️ Меньше 7 • x1.85\n"
            "⬆️ Больше 7 • x1.85"
        ),
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
async def dice_two_bet_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_two_setup":

        await callback.answer(
            "Игра не найдена.",
            show_alert=True
        )

        return

    if callback.data == "dice_two_equal":

        bet = "equal"

    elif callback.data == "dice_two_less":

        bet = "less"

    else:

        bet = "more"

    game["type"] = "dice_two"
    game["bet"] = bet

    await callback.message.edit_text(
        (
            "🎲🎲 <b>2 КУБИКА</b>\n\n"
            f"💰 Ставка: <b>{money(game['stake'])} ₽</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🎲 Первый бросок..."
        )
    )

    await callback.answer()

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )


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


def slots_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎰  КРУТИТЬ",
        callback_data="slots_spin"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="slots"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "slots")
async def slots_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        stake_card(
            "🎰 СЛОТЫ",
            balance
        ),
        reply_markup=stake_menu("slots")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stake_slots_"))
async def slots_stake_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    balance = get_balance(user_id)

    games[user_id] = {
        "type": "slots",
        "stake": stake
    }

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>ТАБЛИЦА ВЫИГРЫШЕЙ</b>\n\n"
        "🍸🍸  x1.85\n"
        "🍸🍸🍸  x5\n"
        "🍇🍇🍇  x8\n"
        "🍋🍋🍋  x10\n"
        "7️⃣7️⃣7️⃣  x50\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💡 Два одинаковых: x1.85\n"
        "✨ Другие три одинаковых: x3.5\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Ставка: {money(stake)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=slots_keyboard()
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ выбрана"
    )


@dp.callback_query(F.data == "slots_spin")
async def slots_spin_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "slots":

        await callback.answer(
            "Сначала выбери ставку.",
            show_alert=True
        )

        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    await callback.answer(
        "🎰 Крутим..."
    )

    await callback.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "⏳ Вращение..."
    )

    await asyncio.sleep(1)

    value = random.randint(
        1,
        64
    )

    result, multiplier = slot_result(
        value
    )

    result_text = "  ".join(result)

    if multiplier > 0:

        payout = int(
            stake * multiplier
        )

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id=user_id,
            game="slots",
            stake=stake,
            result="win",
            multiplier=multiplier,
            payout=payout
        )

        balance = get_balance(user_id)

        text = (
            "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"┌──────────────┐\n"
            f"│  {result_text}  │\n"
            f"└──────────────┘\n\n"
            "🎉 <b>ПОБЕДА!</b>\n"
            f"📈 Множитель: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    else:

        record_game(
            user_id=user_id,
            game="slots",
            stake=stake,
            result="loss",
            multiplier=0,
            payout=0
        )

        balance = get_balance(user_id)

        text = (
            "🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"┌──────────────┐\n"
            f"│  {result_text}  │\n"
            f"└──────────────┘\n\n"
            "💥 <b>НЕ ПОВЕЗЛО</b>\n"
            f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    del games[user_id]

    await callback.message.edit_text(
        text,
        reply_markup=after_game_menu()
    )


# =========================================================
# ROULETTE
# =========================================================

def roulette_menu():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔴  КРАСНОЕ • x1.95",
        callback_data="roulette_red"
    )

    builder.button(
        text="⚫  ЧЁРНОЕ • x1.95",
        callback_data="roulette_black"
    )

    builder.button(
        text="1️⃣  1–18 • x1.95",
        callback_data="roulette_low"
    )

    builder.button(
        text="2️⃣  19–36 • x1.95",
        callback_data="roulette_high"
    )

    builder.button(
        text="⚪  ЧЁТ • x1.95",
        callback_data="roulette_even"
    )

    builder.button(
        text="⚪  НЕЧЁТ • x1.95",
        callback_data="roulette_odd"
    )

    builder.button(
        text="🟢  ZERO • x36",
        callback_data="roulette_zero"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="roulette"
    )

    builder.adjust(1)

    return builder.as_markup()


def roulette_color(number):

    if number == 0:
        return "🟢"

    if number in RED_NUMBERS:
        return "🔴"

    return "⚫"


@dp.callback_query(F.data == "roulette")
async def roulette_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        stake_card(
            "🎡 РУЛЕТКА",
            balance
        ),
        reply_markup=stake_menu("roulette")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stake_roulette_"))
async def roulette_stake_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    balance = get_balance(user_id)

    games[user_id] = {
        "type": "roulette",
        "stake": stake
    }

    text = (
        "🎡 <b>РУЛЕТКА</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>СТАВКИ</b>\n\n"
        "🔴 Красное  x1.95\n"
        "⚫ Чёрное  x1.95\n"
        "1–18  x1.95\n"
        "19–36  x1.95\n"
        "Чёт  x1.95\n"
        "Нечёт  x1.95\n"
        "🟢 Zero  x36\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Ставка: {money(stake)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=roulette_menu()
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ выбрана"
    )


@dp.callback_query(
    F.data.in_({
        "roulette_red",
        "roulette_black",
        "roulette_low",
        "roulette_high",
        "roulette_even",
        "roulette_odd",
        "roulette_zero"
    })
)
async def roulette_bet_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "roulette":

        await callback.answer(
            "Сначала выбери ставку.",
            show_alert=True
        )

        return

    bet = callback.data.replace(
        "roulette_",
        ""
    )

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    labels = {
        "red": "🔴 Красное",
        "black": "⚫ Чёрное",
        "low": "1–18",
        "high": "19–36",
        "even": "Чёт",
        "odd": "Нечёт",
        "zero": "🟢 Zero"
    }

    bet_text = labels[bet]

    number = random.randint(
        0,
        36
    )

    color = roulette_color(
        number
    )

    win = False
    multiplier = ROULETTE_MULTIPLIER

    if bet == "zero":

        if number == 0:
            win = True
            multiplier = ROULETTE_ZERO_MULTIPLIER

    elif number != 0:

        if bet == "red":
            win = number in RED_NUMBERS

        elif bet == "black":
            win = number not in RED_NUMBERS

        elif bet == "low":
            win = 1 <= number <= 18

        elif bet == "high":
            win = 19 <= number <= 36

        elif bet == "even":
            win = number % 2 == 0

        elif bet == "odd":
            win = number % 2 == 1

    if win:

        payout = int(
            stake * multiplier
        )

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id=user_id,
            game="roulette",
            stake=stake,
            result="win",
            multiplier=multiplier,
            payout=payout
        )

        balance = get_balance(user_id)

        text = (
            "🎡 <b>РУЛЕТКА</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"{color} <b>{number}</b>\n\n"
            f"🎯 Ставка: <b>{bet_text}</b>\n"
            f"📈 Множитель: <b>x{multiplier}</b>\n\n"
            "🎉 <b>ПОБЕДА!</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    else:

        record_game(
            user_id=user_id,
            game="roulette",
            stake=stake,
            result="loss",
            multiplier=0,
            payout=0
        )

        balance = get_balance(user_id)

        text = (
            "🎡 <b>РУЛЕТКА</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"{color} <b>{number}</b>\n\n"
            f"🎯 Ставка: <b>{bet_text}</b>\n\n"
            "💥 <b>ПРОИГРЫШ</b>\n"
            f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    del games[user_id]

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
        text="⬆️  БОЛЬШЕ 3 • x1.85",
        callback_data="bowling_more"
    )

    builder.button(
        text="⬇️  МЕНЬШЕ 3 • x1.85",
        callback_data="bowling_less"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="bowling"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "bowling")
async def bowling_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        stake_card(
            "🎳 БОУЛИНГ",
            balance
        ),
        reply_markup=stake_menu("bowling")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stake_bowling_"))
async def bowling_stake_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    balance = get_balance(user_id)

    games[user_id] = {
        "type": "bowling",
        "stake": stake
    }

    text = (
        "🎳 <b>БОУЛИНГ</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⬆️ Больше 3 = 4, 5, 6\n"
        "⬇️ Меньше 3 = 1, 2\n"
        "💥 Результат 3 = проигрыш\n\n"
        "📈 Множитель: x1.85\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Ставка: {money(stake)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=bowling_menu()
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ выбрана"
    )


@dp.callback_query(
    F.data.in_({
        "bowling_more",
        "bowling_less"
    })
)
async def bowling_bet_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "bowling":

        await callback.answer(
            "Сначала выбери ставку.",
            show_alert=True
        )

        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    bet = (
        "more"
        if callback.data == "bowling_more"
        else "less"
    )

    games[user_id] = {
        "type": "bowling_active",
        "stake": stake,
        "bet": bet
    }

    await callback.message.edit_text(
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            f"💰 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "🎳 Бросок..."
        )
    )

    await callback.answer()

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎳"
    )


# =========================================================
# MINES
# =========================================================

def mines_keyboard(
    opened,
    hit_mine=None,
    finished=False
):

    builder = InlineKeyboardBuilder()

    for position in range(9):

        if position in opened:

            text = "💎"

        elif (
            finished
            and hit_mine is not None
            and position == hit_mine
        ):

            text = "💣"

        else:

            text = "▫️"

        builder.button(
            text=text,
            callback_data=f"mine_{position}"
        )

    builder.adjust(3, 3, 3)

    if not finished:

        builder.button(
            text="💰  ЗАБРАТЬ ВЫИГРЫШ",
            callback_data="mines_cashout"
        )

        builder.adjust(
            3, 3, 3, 1
        )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    if not finished:

        builder.adjust(
            3, 3, 3, 1, 1
        )

    else:

        builder.adjust(
            3, 3, 3, 1
        )

    return builder.as_markup()


def mines_text(
    balance,
    stake,
    opened_count
):

    if opened_count == 0:

        current = "—"

    else:

        current = (
            f"x{MINES_MULTIPLIERS[opened_count]}"
        )

    return (
        "💣 <b>МИНЫ</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n"
        f"🎯 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💎 Безопасная клетка\n"
        "💣 Мина\n\n"
        f"✨ Открыто: <b>{opened_count}/6</b>\n"
        f"📈 Множитель: <b>{current}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери клетку."
    )


@dp.callback_query(F.data == "mines")
async def mines_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        stake_card(
            "💣 МИНЫ",
            balance
        ),
        reply_markup=stake_menu("mines")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stake_mines_"))
async def mines_stake_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    balance = get_balance(user_id)

    if balance < stake:

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    if user_id in games:
        del games[user_id]

    subtract_balance(
        user_id,
        stake
    )

    mine_positions = set(
        random.sample(
            range(9),
            MINES_COUNT
        )
    )

    games[user_id] = {
        "type": "mines",
        "stake": stake,
        "mines": mine_positions,
        "opened": set()
    }

    balance = get_balance(user_id)

    await callback.message.edit_text(
        mines_text(
            balance,
            stake,
            0
        ),
        reply_markup=mines_keyboard(
            set()
        )
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ принята"
    )


@dp.callback_query(F.data.startswith("mine_"))
async def mine_click_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":

        await callback.answer(
            "Игра уже завершена.",
            show_alert=True
        )

        return

    position = int(
        callback.data.split("_")[-1]
    )

    opened = game["opened"]

    if position in opened:

        await callback.answer(
            "Эта клетка уже открыта."
        )

        return

    mines = game["mines"]
    stake = game["stake"]

    if position in mines:

        record_game(
            user_id=user_id,
            game="mines",
            stake=stake,
            result="loss",
            multiplier=0,
            payout=0
        )

        balance = get_balance(user_id)

        text = (
            "💣 <b>МИНЫ</b>\n\n"
            "💥 <b>МИНА!</b>\n\n"
            f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

        del games[user_id]

        await callback.message.edit_text(
            text,
            reply_markup=mines_keyboard(
                opened,
                hit_mine=position,
                finished=True
            )
        )

        await callback.answer(
            "💣 Мина!",
            show_alert=True
        )

        return

    opened.add(position)

    opened_count = len(opened)

    if opened_count >= 6:

        multiplier = MINES_MULTIPLIERS[6]

        payout = int(
            stake * multiplier
        )

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id=user_id,
            game="mines",
            stake=stake,
            result="win",
            multiplier=multiplier,
            payout=payout
        )

        balance = get_balance(user_id)

        del games[user_id]

        text = (
            "💣 <b>МИНЫ</b>\n\n"
            "💎💎💎\n"
            "💎💎💎\n\n"
            "🎉 <b>ВСЕ КЛЕТКИ НАЙДЕНЫ!</b>\n\n"
            f"📈 Множитель: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

        await callback.message.edit_text(
            text,
            reply_markup=after_game_menu()
        )

        await callback.answer(
            "🎉 Максимальный выигрыш!"
        )

        return

    multiplier = MINES_MULTIPLIERS[
        opened_count
    ]

    potential = int(
        stake * multiplier
    )

    balance = get_balance(user_id)

    await callback.message.edit_text(
        mines_text(
            balance,
            stake,
            opened_count
        ),
        reply_markup=mines_keyboard(
            opened
        )
    )

    await callback.answer(
        f"💎 x{multiplier} • {money(potential)} ₽"
    )


@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":

        await callback.answer(
            "Игра уже завершена.",
            show_alert=True
        )

        return

    opened_count = len(
        game["opened"]
    )

    if opened_count == 0:

        await callback.answer(
            "Сначала открой хотя бы одну клетку.",
            show_alert=True
        )

        return

    stake = game["stake"]

    multiplier = MINES_MULTIPLIERS[
        opened_count
    ]

    payout = int(
        stake * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    record_game(
        user_id=user_id,
        game="mines",
        stake=stake,
        result="win",
        multiplier=multiplier,
        payout=payout
    )

    balance = get_balance(user_id)

    del games[user_id]

    text = (
        "💣 <b>МИНЫ</b>\n\n"
        "💎 <b>ВЫИГРЫШ ЗАБРАН</b>\n\n"
        f"💎 Открыто: <b>{opened_count}</b>\n"
        f"📈 Множитель: <b>x{multiplier}</b>\n"
        f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
        f"💳 Баланс: <b>{money(balance)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_menu()
    )

    await callback.answer(
        "💰 Выигрыш забран!"
    )


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


def crash_indicator(multiplier):

    if multiplier < 2:
        return "🟢"

    if multiplier < 5:
        return "🟡"

    return "🔴"


def crash_keyboard():

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


@dp.callback_query(F.data == "crash")
async def crash_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        stake_card(
            "🧨 CRASH",
            balance
        ),
        reply_markup=stake_menu("crash")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("stake_crash_"))
async def crash_stake_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    balance = get_balance(user_id)

    if balance < stake:

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    if not subtract_balance(
        user_id,
        stake
    ):

        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        return

    crash_point = generate_crash_point()

    games[user_id] = {
        "type": "crash",
        "stake": stake,
        "multiplier": 1.00,
        "crash_point": crash_point,
        "active": True,
        "message_id": callback.message.message_id
    }

    await callback.message.edit_text(
        (
            "🧨 <b>CRASH</b>\n\n"
            "🟢 <b>1.00x</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "💡 Забери выигрыш до краша.\n"
            "⚡ Множитель растёт..."
        ),
        reply_markup=crash_keyboard()
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ принята"
    )

    asyncio.create_task(
        crash_loop(
            callback.message.chat.id,
            user_id
        )
    )


async def crash_loop(
    chat_id: int,
    user_id: int
):

    while True:

        await asyncio.sleep(0.7)

        game = games.get(user_id)

        if not game:
            return

        if game.get("type") != "crash":
            return

        if not game.get("active"):
            return

        multiplier = game["multiplier"]

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

        crash_point = game["crash_point"]
        stake = game["stake"]

        # =================================================
        # CRASH
        # =================================================

        if multiplier >= crash_point:

            game["active"] = False

            record_game(
                user_id=user_id,
                game="crash",
                stake=stake,
                result="loss",
                multiplier=0,
                payout=0
            )

            balance = get_balance(user_id)

            try:

                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=game["message_id"],
                    text=(
                        "🧨 <b>CRASH</b>\n\n"
                        f"💥 <b>{crash_point:.2f}x</b>\n\n"
                        "━━━━━━━━━━━━━━━━━━\n\n"
                        "💥 <b>КРАШ!</b>\n\n"
                        f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
                        f"💳 Баланс: <b>{money(balance)} ₽</b>"
                    ),
                    reply_markup=after_game_menu()
                )

            except Exception:
                pass

            if user_id in games:
                del games[user_id]

            return

        # =================================================
        # ANIMATION
        # =================================================

        indicator = crash_indicator(
            multiplier
        )

        potential = int(
            stake * multiplier
        )

        try:

            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=game["message_id"],
                text=(
                    "🧨 <b>CRASH</b>\n\n"
                    f"{indicator} <b>{multiplier:.2f}x</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    f"💰 Ставка: <b>{money(stake)} ₽</b>\n"
                    f"💎 Забрать сейчас: <b>{money(potential)} ₽</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "⚡ Множитель растёт...\n"
                    "💥 Успей забрать до Crash!"
                ),
                reply_markup=crash_keyboard()
            )

        except Exception:
            continue


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "crash":

        await callback.answer(
            "Игра уже завершена.",
            show_alert=True
        )

        return

    game["active"] = False

    stake = game["stake"]
    multiplier = game["multiplier"]

    payout = int(
        stake * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    record_game(
        user_id=user_id,
        game="crash",
        stake=stake,
        result="win",
        multiplier=multiplier,
        payout=payout
    )

    balance = get_balance(user_id)

    del games[user_id]

    text = (
        "🧨 <b>CRASH</b>\n\n"
        "🎉 <b>ВЫИГРЫШ ЗАБРАН!</b>\n\n"
        f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Ставка: <b>{money(stake)} ₽</b>\n"
        f"💎 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
        f"💳 Баланс: <b>{money(balance)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_menu()
    )

    await callback.answer(
        f"💰 +{money(payout)} ₽"
    )


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel_callback(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "crash":

        await callback.answer(
            "Игра уже завершена.",
            show_alert=True
        )

        return

    game["active"] = False

    stake = game["stake"]

    # ==============================================
    # ВОЗВРАЩАЕМ СТАВКУ
    # ==============================================

    change_balance(
        user_id,
        stake
    )

    balance = get_balance(user_id)

    del games[user_id]

    text = (
        "🧨 <b>CRASH</b>\n\n"
        "❌ <b>ИГРА ОТМЕНЕНА</b>\n\n"
        f"↩️ Ставка возвращена: <b>+{money(stake)} ₽</b>\n\n"
        f"💳 Баланс: <b>{money(balance)} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_menu()
    )

    await callback.answer(
        f"Ставка {money(stake)} ₽ возвращена"
    )


# =========================================================
# TELEGRAM DICE
# =========================================================

@dp.message(F.dice)
async def dice_handler(
    message: Message
):

    user_id = message.from_user.id

    game = games.get(user_id)

    if not game:
        return

    emoji = message.dice.emoji
    value = message.dice.value

    # =====================================================
    # DICE
    # =====================================================

    if emoji == "🎲":

        # -------------------------------------------------
        # ONE DICE
        # -------------------------------------------------

        if game.get("type") == "dice_one":

            bet = game.get("bet")
            stake = game["stake"]

            win = False

            if bet == "less" and value < 3:
                win = True

            if bet == "more" and value > 3:
                win = True

            if win:

                payout = int(
                    stake * DICE_ONE_MULTIPLIER
                )

                change_balance(
                    user_id,
                    payout
                )

                record_game(
                    user_id=user_id,
                    game="dice_one",
                    stake=stake,
                    result="win",
                    multiplier=DICE_ONE_MULTIPLIER,
                    payout=payout
                )

                balance = get_balance(user_id)

                text = (
                    "🎲 <b>КУБИК</b>\n\n"
                    f"🎯 Результат: <b>{value}</b>\n\n"
                    "🎉 <b>ПОБЕДА!</b>\n"
                    f"📈 Множитель: <b>x{DICE_ONE_MULTIPLIER}</b>\n"
                    f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
                    f"💳 Баланс: <b>{money(balance)} ₽</b>"
                )

            else:

                record_game(
                    user_id=user_id,
                    game="dice_one",
                    stake=stake,
                    result="loss",
                    multiplier=0,
                    payout=0
                )

                balance = get_balance(user_id)

                text = (
                    "🎲 <b>КУБИК</b>\n\n"
                    f"🎯 Результат: <b>{value}</b>\n\n"
                    "💥 <b>ПРОИГРЫШ</b>\n"
                    f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
                    f"💳 Баланс: <b>{money(balance)} ₽</b>"
                )

            del games[user_id]

            await message.answer(
                text,
                reply_markup=after_game_menu()
            )

            return

        # -------------------------------------------------
        # TWO DICE
        # -------------------------------------------------

        if game.get("type") == "dice_two":

            first = game.get("first")

            if first is None:

                game["first"] = value

                await message.answer(
                    (
                        "🎲🎲 <b>ПЕРВЫЙ КУБИК</b>\n\n"
                        f"🎲 Результат: <b>{value}</b>\n\n"
                        "🎲 Второй бросок..."
                    )
                )

                await bot.send_dice(
                    chat_id=message.chat.id,
                    emoji="🎲"
                )

                return

            second = value
            total = first + second

            stake = game["stake"]
            bet = game["bet"]

            if bet == "equal":

                win = total == 7
                multiplier = DICE_TWO_EQUAL_MULTIPLIER

            elif bet == "less":

                win = total < 7
                multiplier = DICE_TWO_MULTIPLIER

            else:

                win = total > 7
                multiplier = DICE_TWO_MULTIPLIER

            if win:

                payout = int(
                    stake * multiplier
                )

                change_balance(
                    user_id,
                    payout
                )

                record_game(
                    user_id=user_id,
                    game="dice_two",
                    stake=stake,
                    result="win",
                    multiplier=multiplier,
                    payout=payout
                )

                balance = get_balance(user_id)

                text = (
                    "🎲🎲 <b>2 КУБИКА</b>\n\n"
                    f"🎲 Первый: <b>{first}</b>\n"
                    f"🎲 Второй: <b>{second}</b>\n"
                    f"🎯 Сумма: <b>{total}</b>\n\n"
                    "🎉 <b>ПОБЕДА!</b>\n"
                    f"📈 Множитель: <b>x{multiplier}</b>\n"
                    f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
                    f"💳 Баланс: <b>{money(balance)} ₽</b>"
                )

            else:

                record_game(
                    user_id=user_id,
                    game="dice_two",
                    stake=stake,
                    result="loss",
                    multiplier=0,
                    payout=0
                )

                balance = get_balance(user_id)

                text = (
                    "🎲🎲 <b>2 КУБИКА</b>\n\n"
                    f"🎲 Первый: <b>{first}</b>\n"
                    f"🎲 Второй: <b>{second}</b>\n"
                    f"🎯 Сумма: <b>{total}</b>\n\n"
                    "💥 <b>ПРОИГРЫШ</b>\n"
                    f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
                    f"💳 Баланс: <b>{money(balance)} ₽</b>"
                )

            del games[user_id]

            await message.answer(
                text,
                reply_markup=after_game_menu()
            )

            return

    # =====================================================
    # BOWLING
    # =====================================================

    if emoji == "🎳":

        if game.get("type") != "bowling_active":
            return

        stake = game["stake"]
        bet = game["bet"]

        win = False

        if bet == "more" and value > 3:
            win = True

        if bet == "less" and value < 3:
            win = True

        if win:

            payout = int(
                stake * BOWLING_MULTIPLIER
            )

            change_balance(
                user_id,
                payout
            )

            record_game(
                user_id=user_id,
                game="bowling",
                stake=stake,
                result="win",
                multiplier=BOWLING_MULTIPLIER,
                payout=payout
            )

            balance = get_balance(user_id)

            direction = (
                "⬆️ Больше 3"
                if bet == "more"
                else "⬇️ Меньше 3"
            )

            text = (
                "🎳 <b>БОУЛИНГ</b>\n\n"
                f"🎯 Ставка: <b>{direction}</b>\n"
                f"🎳 Результат: <b>{value}</b>\n\n"
                "🎉 <b>ПОБЕДА!</b>\n"
                f"📈 Множитель: <b>x{BOWLING_MULTIPLIER}</b>\n"
                f"💰 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
                f"💳 Баланс: <b>{money(balance)} ₽</b>"
            )

        else:

            record_game(
                user_id=user_id,
                game="bowling",
                stake=stake,
                result="loss",
                multiplier=0,
                payout=0
            )

            balance = get_balance(user_id)

            text = (
                "🎳 <b>БОУЛИНГ</b>\n\n"
                f"🎳 Результат: <b>{value}</b>\n\n"
                "💥 <b>ПРОИГРЫШ</b>\n"
                f"💸 Ставка: <b>-{money(stake)} ₽</b>\n\n"
                f"💳 Баланс: <b>{money(balance)} ₽</b>"
            )

        del games[user_id]

        await message.answer(
            text,
            reply_markup=after_game_menu()
        )

        return


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
        context={"bot": bot}
    )

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


@app.get("/")
async def root():

    return {
        "status": "ok",
        "service": "emoji-casino-bot"
    }


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup():

    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=[
            "message",
            "callback_query"
        ]
    )


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown():

    await bot.session.close()
