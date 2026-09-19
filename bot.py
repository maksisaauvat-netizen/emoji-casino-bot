import asyncio
import random

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = None
WEBHOOK_SECRET = None

# Render передаёт переменные окружения
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "emoji_casino_secret_2026_x7k9"
)

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")


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

STAKE = 100

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

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}

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
CRASH_SPEED = 0.25
CRASH_STAKE = 100


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📂 | Меню",
                    callback_data="main_menu"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🥷 | Профиль",
                    callback_data="profile"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🎰 | Мини-игры",
                    callback_data="mini_games"
                )
            ],
        ]
    )


def mini_games_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🎲 | Кубики",
                    callback_data="game_dice"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🎰 | Слоты",
                    callback_data="game_slots"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🎡 | Рулетка",
                    callback_data="game_roulette"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🎳 | Боулинг",
                    callback_data="game_bowling"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="💣 | Мины",
                    callback_data="game_mines"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🧨 | Crash",
                    callback_data="game_crash"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="main_menu"
                )
            ],
        ]
    )


def after_game_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔄 | Играть снова",
                    callback_data="mini_games"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Меню",
                    callback_data="main_menu"
                )
            ],
        ]
    )


# =========================================================
# MAIN MENU
# =========================================================

async def show_main_menu(message):
    user_id = message.from_user.id
    balance = get_balance(user_id)

    await message.answer(
        "🎰 <b>Resonant Casino 🎰</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>",
        reply_markup=main_menu_keyboard()
    )


@dp.message(F.text == "/start")
async def start_command(message: types.Message):
    get_balance(message.from_user.id)

    await message.answer(
        "🎰 <b>Resonant Casino 🎰</b>\n\n"
        f"💰 Баланс: <b>{get_balance(message.from_user.id)}</b>",
        reply_markup=main_menu_keyboard()
    )


@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "🎰 <b>Resonant Casino 🎰</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>",
        reply_markup=main_menu_keyboard()
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user = callback.from_user
    balance = get_balance(user.id)

    username = (
        f"@{user.username}"
        if user.username
        else "Не указан"
    )

    await callback.message.edit_text(
        "🥷 <b>Профиль</b>\n\n"
        f"👤 Имя: <b>{user.first_name}</b>\n"
        f"🔗 Username: <b>{username}</b>\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n\n"
        f"💰 Баланс: <b>{balance}</b>",
        reply_markup=main_menu_keyboard()
    )

    await callback.answer()


# =========================================================
# MINI GAMES MENU
# =========================================================

@dp.callback_query(F.data == "mini_games")
async def mini_games(callback: CallbackQuery):
    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "🎮 <b>Мини-игры</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выбери игру:",
        reply_markup=mini_games_keyboard()
    )

    await callback.answer()


# =========================================================
# 🎲 DICE
# =========================================================

@dp.callback_query(F.data == "game_dice")
async def game_dice(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎲 <b>Кубики</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "Выбери режим:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="🎲 | 1 кубик",
                        callback_data="dice_one"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🎲🎲 | 2 кубика",
                        callback_data="dice_two"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📂 | Назад",
                        callback_data="mini_games"
                    )
                ],
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_one")
async def dice_one(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_one"
    }

    await callback.message.edit_text(
        "🎲 <b>1 кубик</b>\n\n"
        "Выбери ставку:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="x1.85 | Меньше 3",
                        callback_data="dice_one_less"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="x1.85 | Больше 3",
                        callback_data="dice_one_more"
                    )
                ],
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data.in_({"dice_one_less", "dice_one_more"}))
async def dice_one_bet(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_one":
        await callback.answer(
            "❌ Игра не найдена.",
            show_alert=True
        )
        return

    bet = (
        "less"
        if callback.data == "dice_one_less"
        else "more"
    )

    game["bet"] = bet

    await callback.message.edit_text(
        "🎲 <b>Бросок...</b>\n\n"
        "Результат появится ниже."
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_two")
async def dice_two(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_two",
        "first": None,
    }

    await callback.message.edit_text(
        "🎲🎲 <b>2 кубика</b>\n\n"
        "Выбери ставку:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="x5.00 | Равно 7",
                        callback_data="dice_two_equal"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="x1.85 | Меньше 7",
                        callback_data="dice_two_less"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="x1.85 | Больше 7",
                        callback_data="dice_two_more"
                    )
                ],
            ]
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "dice_two_equal",
        "dice_two_less",
        "dice_two_more"
    })
)
async def dice_two_bet(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "dice_two":
        await callback.answer(
            "❌ Игра не найдена.",
            show_alert=True
        )
        return

    if callback.data == "dice_two_equal":
        bet = "equal"
    elif callback.data == "dice_two_less":
        bet = "less"
    else:
        bet = "more"

    game["bet"] = bet

    await callback.message.edit_text(
        "🎲 <b>Первый бросок...</b>"
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


# =========================================================
# 🎰 SLOTS
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


@dp.callback_query(F.data == "game_slots")
async def game_slots(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "slots"
    }

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "🎰 Крутим..."
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎰"
    )

    await callback.answer()


# =========================================================
# 🎡 ROULETTE
# =========================================================

def roulette_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔴 Красное x1.95",
                    callback_data="roulette_red"
                ),
                types.InlineKeyboardButton(
                    text="⚫ Чёрное x1.95",
                    callback_data="roulette_black"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="1–18 x1.95",
                    callback_data="roulette_low"
                ),
                types.InlineKeyboardButton(
                    text="19–36 x1.95",
                    callback_data="roulette_high"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="⚪ Чётное x1.95",
                    callback_data="roulette_even"
                ),
                types.InlineKeyboardButton(
                    text="🔵 Нечётное x1.95",
                    callback_data="roulette_odd"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="0 x36",
                    callback_data="roulette_zero"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ],
        ]
    )


@dp.callback_query(F.data == "game_roulette")
async def game_roulette(callback: CallbackQuery):
    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "🎡 <b>Рулетка</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"
        "Выбери ставку:",
        reply_markup=roulette_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("roulette_"))
async def roulette_bet(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    bet = callback.data.replace(
        "roulette_",
        ""
    )

    number = random.randint(0, 36)

    won = False
    multiplier = 0

    if bet == "zero":
        won = number == 0
        multiplier = ROULETTE_ZERO_MULTIPLIER

    elif number != 0:

        if bet == "red":
            won = number in RED_NUMBERS

        elif bet == "black":
            won = number not in RED_NUMBERS

        elif bet == "low":
            won = 1 <= number <= 18

        elif bet == "high":
            won = 19 <= number <= 36

        elif bet == "even":
            won = number % 2 == 0

        elif bet == "odd":
            won = number % 2 == 1

        multiplier = ROULETTE_MULTIPLIER

    if won:
        payout = int(STAKE * multiplier)
        change_balance(user_id, payout)

        result_text = (
            "🎡 <b>Рулетка</b>\n\n"
            f"🎯 Выпало: <b>{number}</b>\n\n"
            f"🎉 Победа!\n"
            f"💰 Выигрыш: <b>{payout}</b>"
        )
    else:
        result_text = (
            "🎡 <b>Рулетка</b>\n\n"
            f"🎯 Выпало: <b>{number}</b>\n\n"
            "❌ Ставка проиграла."
        )

    await callback.message.edit_text(
        result_text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# 🎳 BOWLING
# =========================================================

@dp.callback_query(F.data == "game_bowling")
async def game_bowling(callback: CallbackQuery):
    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "🎳 <b>Боулинг</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"
        "Выбери ставку:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="⬆️ | Больше 3 x1.85",
                        callback_data="bowling_more"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="⬇️ | Меньше 3 x1.85",
                        callback_data="bowling_less"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📂 | Назад",
                        callback_data="mini_games"
                    )
                ],
            ]
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "bowling_more",
        "bowling_less"
    })
)
async def bowling_bet(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств.",
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

    await callback.message.edit_text(
        "🎳 <b>Бросок...</b>"
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎳"
    )

    await callback.answer()


# =========================================================
# 💣 MINES
# =========================================================

def mines_keyboard(opened, mines=None):
    buttons = []

    for position in range(9):
        row = position // 3
        col = position % 3

        if position in opened:
            text = "💎"
        elif mines and position in mines:
            text = "💣"
        else:
            text = "⬜"

        buttons.append(
            types.InlineKeyboardButton(
                text=text,
                callback_data=f"mine_{position}"
            )
        )

        if col == 2:
            pass

    rows = []

    for i in range(0, 9, 3):
        rows.append(buttons[i:i + 3])

    rows.append(
        [
            types.InlineKeyboardButton(
                text="💰 | Забрать",
                callback_data="mines_cashout"
            )
        ]
    )

    rows.append(
        [
            types.InlineKeyboardButton(
                text="❌ | Выйти",
                callback_data="mines_cancel"
            )
        ]
    )

    return types.InlineKeyboardMarkup(
        inline_keyboard=rows
    )


@dp.callback_query(F.data == "game_mines")
async def game_mines(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    mine_positions = set(
        random.sample(range(9), 3)
    )

    games[user_id] = {
        "type": "mines",
        "mines": mine_positions,
        "opened": set(),
    }

    await callback.message.edit_text(
        "💣 <b>Мины</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "💎 Открывай клетки.\n"
        "💣 Не попадись на мину!",
        reply_markup=mines_keyboard(set())
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("mine_"))
async def mine_open(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра не найдена.",
            show_alert=True
        )
        return

    position = int(
        callback.data.replace("mine_", "")
    )

    opened = game["opened"]
    mines = game["mines"]

    if position in opened:
        await callback.answer(
            "Уже открыто."
        )
        return

    if position in mines:

        rows = []

        for i in range(9):
            if i in mines:
                text = "💣"
            elif i in opened:
                text = "💎"
            else:
                text = "⬜"

            rows.append(text)

        await callback.message.edit_text(
            "💥 <b>БУМ!</b>\n\n"
            "Ты попал на мину 💣\n\n"
            f"💸 Потеряно: <b>{STAKE}</b>",
            reply_markup=after_game_keyboard()
        )

        games.pop(user_id, None)

        await callback.answer()
        return

    opened.add(position)

    count = len(opened)

    if count >= 6:

        multiplier = MINES_MULTIPLIERS[6]
        payout = int(STAKE * multiplier)

        change_balance(
            user_id,
            payout
        )

        await callback.message.edit_text(
            "💎 <b>Все безопасные клетки открыты!</b>\n\n"
            f"🔥 Множитель: <b>x{multiplier:.2f}</b>\n"
            f"💰 Выигрыш: <b>{payout}</b>",
            reply_markup=after_game_keyboard()
        )

        games.pop(user_id, None)

        await callback.answer()
        return

    multiplier = MINES_MULTIPLIERS[count]
    potential = int(STAKE * multiplier)

    await callback.message.edit_text(
        "💣 <b>Мины</b>\n\n"
        f"💎 Открыто: <b>{count}/6</b>\n"
        f"🔥 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Забрать: <b>{potential}</b>",
        reply_markup=mines_keyboard(opened)
    )

    await callback.answer()


@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра не найдена.",
            show_alert=True
        )
        return

    count = len(game["opened"])

    if count == 0:
        await callback.answer(
            "❌ Сначала открой хотя бы одну клетку.",
            show_alert=True
        )
        return

    multiplier = MINES_MULTIPLIERS[count]
    payout = int(STAKE * multiplier)

    change_balance(
        user_id,
        payout
    )

    await callback.message.edit_text(
        "💰 <b>Выигрыш забран!</b>\n\n"
        f"💎 Открыто: <b>{count}/6</b>\n"
        f"🔥 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Выигрыш: <b>{payout}</b>",
        reply_markup=after_game_keyboard()
    )

    games.pop(user_id, None)

    await callback.answer()


@dp.callback_query(F.data == "mines_cancel")
async def mines_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра не найдена.",
            show_alert=True
        )
        return

    games.pop(user_id, None)

    await callback.message.edit_text(
        "💣 <b>Мины</b>\n\n"
        "❌ Игра завершена.\n\n"
        "💸 Ставка не возвращается.",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# 🧨 CRASH
# =========================================================

def generate_crash_point():
    value = random.expovariate(1.0 / 2.5)

    crash_point = 1.00 + value

    crash_point = max(
        CRASH_MIN,
        crash_point
    )

    crash_point = min(
        CRASH_MAX,
        crash_point
    )

    return round(crash_point, 2)


def crash_multiplier_text(multiplier):

    if multiplier < 2.00:
        return f"🟢 🚀 <b>{multiplier:.2f}x</b>"

    if multiplier < 5.00:
        return f"🟡 🚀 <b>{multiplier:.2f}x</b>"

    return f"🔴 🚀 <b>{multiplier:.2f}x</b>"


def crash_text(multiplier, stake):

    return (
        "🧨 <b>CRASH</b>\n\n"
        f"{crash_multiplier_text(multiplier)}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📈 Множитель растёт...\n\n"
        f"💰 Ставка: <b>{stake}</b>"
    )


def crash_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💰 | Забрать",
                    callback_data="crash_cashout"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ | Отменить",
                    callback_data="crash_cancel"
                )
            ],
        ]
    )


def crash_result_text(
    multiplier,
    win=False,
    payout=0
):
    if win:
        return (
            "💰 <b>CASHOUT!</b>\n\n"
            f"🚀 <b>{multiplier:.2f}x</b>\n\n"
            f"💵 Ставка: <b>{CRASH_STAKE}</b>\n"
            f"💰 Выигрыш: <b>{payout}</b>\n\n"
            "🎉 <b>Забрано вовремя!</b>"
        )

    return (
        "💥 <b>CRASH!</b>\n\n"
        f"🔴 <b>{multiplier:.2f}x</b>\n\n"
        f"💸 Ставка: <b>{CRASH_STAKE}</b>\n\n"
        "😢 <b>Ставка сгорела.</b>"
    )


def crash_game_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔄 | Играть снова",
                    callback_data="game_crash"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Меню",
                    callback_data="main_menu"
                )
            ],
        ]
    )


@dp.callback_query(F.data == "game_crash")
async def game_crash(callback: CallbackQuery):

    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "⚠️ У тебя уже есть активная игра.",
            show_alert=True
        )
        return

    balance = get_balance(user_id)

    if balance < CRASH_STAKE:
        await callback.answer(
            "❌ Недостаточно средств.",
            show_alert=True
        )
        return

    success = subtract_balance(
        user_id,
        CRASH_STAKE
    )

    if not success:
        await callback.answer(
            "❌ Не удалось принять ставку.",
            show_alert=True
        )
        return

    crash_point = generate_crash_point()

    games[user_id] = {
        "type": "crash",
        "stake": CRASH_STAKE,
        "crash_point": crash_point,
        "multiplier": 1.00,
        "message_id": None,
        "chat_id": callback.message.chat.id,
        "active": True,
    }

    sent_message = await callback.message.edit_text(
        crash_text(
            1.00,
            CRASH_STAKE
        ),
        reply_markup=crash_keyboard()
    )

    games[user_id]["message_id"] = (
        sent_message.message_id
    )

    await callback.answer()

    asyncio.create_task(
        crash_loop(user_id)
    )


async def crash_loop(user_id):

    multiplier = 1.00

    try:

        while True:

            await asyncio.sleep(
                CRASH_SPEED
            )

            game = games.get(user_id)

            if not game:
                return

            if not game.get(
                "active",
                False
            ):
                return

            if multiplier < 2.00:
                increment = 0.05

            elif multiplier < 5.00:
                increment = 0.08

            else:
                increment = 0.12

            multiplier += increment
            multiplier = round(
                multiplier,
                2
            )

            game["multiplier"] = multiplier

            if multiplier >= game["crash_point"]:

                crash_point = game[
                    "crash_point"
                ]

                game["active"] = False

                await bot.edit_message_text(
                    chat_id=game["chat_id"],
                    message_id=game["message_id"],
                    text=crash_result_text(
                        crash_point,
                        win=False
                    ),
                    reply_markup=crash_game_keyboard()
                )

                games.pop(
                    user_id,
                    None
                )

                return

            try:

                await bot.edit_message_text(
                    chat_id=game["chat_id"],
                    message_id=game["message_id"],
                    text=crash_text(
                        multiplier,
                        CRASH_STAKE
                    ),
                    reply_markup=crash_keyboard()
                )

            except Exception:
                return

    except asyncio.CancelledError:
        return

    except Exception:
        games.pop(
            user_id,
            None
        )


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout(callback: CallbackQuery):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get(
        "type"
    ) != "crash":

        await callback.answer(
            "❌ Активная игра не найдена.",
            show_alert=True
        )
        return

    if not game.get(
        "active",
        False
    ):

        await callback.answer(
            "💥 Игра уже закончилась.",
            show_alert=True
        )
        return

    game["active"] = False

    multiplier = game[
        "multiplier"
    ]

    payout = int(
        CRASH_STAKE * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    try:

        await bot.edit_message_text(
            chat_id=game["chat_id"],
            message_id=game["message_id"],
            text=crash_result_text(
                multiplier,
                win=True,
                payout=payout
            ),
            reply_markup=crash_game_keyboard()
        )

    except Exception:
        pass

    games.pop(
        user_id,
        None
    )

    await callback.answer(
        f"💰 Забрано {payout}!"
    )


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel(callback: CallbackQuery):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get(
        "type"
    ) != "crash":

        await callback.answer(
            "❌ Активная игра не найдена.",
            show_alert=True
        )
        return

    game["active"] = False

    games.pop(
        user_id,
        None
    )

    await callback.message.edit_text(
        "🧨 <b>CRASH</b>\n\n"
        "❌ <b>Игра отменена.</b>\n\n"
        "💸 Ставка не возвращается.",
        reply_markup=crash_game_keyboard()
    )

    await callback.answer()


# =========================================================
# 🎲🎰🎳 TELEGRAM DICE RESULTS
# =========================================================

@dp.message(F.dice)
async def dice_result(message: types.Message):

    user_id = message.from_user.id

    game = games.get(user_id)

    if not game:
        return

    dice = message.dice

    # -----------------------------------------------------
    # 🎲 DICE
    # -----------------------------------------------------

    if dice.emoji == "🎲":

        value = dice.value

        if game["type"] == "dice_one":

            bet = game.get("bet")

            won = (
                value < 3
                if bet == "less"
                else value > 3
            )

            if won:
                payout = int(
                    STAKE * 1.85
                )

                change_balance(
                    user_id,
                    payout
                )

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"🎯 Выпало: <b>{value}</b>\n\n"
                    f"🎉 Победа!\n"
                    f"💰 Выигрыш: <b>{payout}</b>"
                )

            else:

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"🎯 Выпало: <b>{value}</b>\n\n"
                    "❌ Ставка проиграла."
                )

            games.pop(
                user_id,
                None
            )

            await message.answer(
                text,
                reply_markup=after_game_keyboard()
            )

            return

        if game["type"] == "dice_two":

            if game.get("first") is None:

                game["first"] = value

                await message.answer(
                    f"🎲 Первый кубик: <b>{value}</b>\n\n"
                    "🎲 Бросаем второй..."
                )

                await bot.send_dice(
                    chat_id=message.chat.id,
                    emoji="🎲"
                )

                return

            first = game["first"]
            total = first + value
            bet = game.get("bet")

            if bet == "equal":
                won = total == 7
                multiplier = 5.00

            elif bet == "less":
                won = total < 7
                multiplier = 1.85

            else:
                won = total > 7
                multiplier = 1.85

            if won:

                payout = int(
                    STAKE * multiplier
                )

                change_balance(
                    user_id,
                    payout
                )

                text = (
                    "🎲🎲 <b>Кубики</b>\n\n"
                    f"🎯 Результат: "
                    f"<b>{first} + {value} = {total}</b>\n\n"
                    f"🎉 Победа!\n"
                    f"💰 Выигрыш: <b>{payout}</b>"
                )

            else:

                text = (
                    "🎲🎲 <b>Кубики</b>\n\n"
                    f"🎯 Результат: "
                    f"<b>{first} + {value} = {total}</b>\n\n"
                    "❌ Ставка проиграла."
                )

            games.pop(
                user_id,
                None
            )

            await message.answer(
                text,
                reply_markup=after_game_keyboard()
            )

            return

    # -----------------------------------------------------
    # 🎰 SLOTS
    # -----------------------------------------------------

    if dice.emoji == "🎰":

        if game["type"] != "slots":
            return

        result, multiplier = slot_result(
            dice.value
        )

        symbols = " ".join(result)

        if multiplier > 0:

            payout = int(
                STAKE * multiplier
            )

            change_balance(
                user_id,
                payout
            )

            text = (
                "🎰 <b>Слоты</b>\n\n"
                f"{symbols}\n\n"
                f"🎉 Победа!\n"
                f"🔥 Множитель: <b>x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>{payout}</b>"
            )

        else:

            text = (
                "🎰 <b>Слоты</b>\n\n"
                f"{symbols}\n\n"
                "❌ Совпадений нет."
            )

        games.pop(
            user_id,
            None
        )

        await message.answer(
            text,
            reply_markup=after_game_keyboard()
        )

        return

    # -----------------------------------------------------
    # 🎳 BOWLING
    # -----------------------------------------------------

    if dice.emoji == "🎳":

        if game["type"] != "bowling":
            return

        value = dice.value
        bet = game["bet"]

        if bet == "more":
            won = value > 3
        else:
            won = value < 3

        if won:

            payout = int(
                STAKE * BOWLING_MULTIPLIER
            )

            change_balance(
                user_id,
                payout
            )

            text = (
                "🎳 <b>Боулинг</b>\n\n"
                f"🎯 Выпало: <b>{value}</b>\n\n"
                "🎉 Победа!\n"
                f"💰 Выигрыш: <b>{payout}</b>"
            )

        else:

            text = (
                "🎳 <b>Боулинг</b>\n\n"
                f"🎯 Выпало: <b>{value}</b>\n\n"
                "❌ Ставка проиграла."
            )

        games.pop(
            user_id,
            None
        )

        await message.answer(
            text,
            reply_markup=after_game_keyboard()
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

    update = types.Update.model_validate(
        data
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
        "bot": "Resonant Casino"
    }


# =========================================================
# STARTUP / SHUTDOWN
# =========================================================

@app.on_event("startup")
async def on_startup():

    init_db()

    webhook_url = (
        "https://emoji-casino-bot.onrender.com"
        + WEBHOOK_PATH
    )

    print(
        "SETTING WEBHOOK:",
        webhook_url
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


@app.on_event("shutdown")
async def on_shutdown():

    # ВАЖНО:
    # НЕ удаляем webhook при shutdown.
    # Render может перезапускать сервис,
    # и webhook должен оставаться установленным.

    await bot.session.close()

    print(
        "BOT SESSION CLOSED"
    )
