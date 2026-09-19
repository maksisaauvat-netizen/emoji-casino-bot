import os
import random
import asyncio

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is not set")


STAKE = 100

# Dice
DICE_ONE_MULTIPLIER = 1.85
DICE_TWO_EQUAL_MULTIPLIER = 5.0
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

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}

# Mines
MINES_COUNT = 3

MINES_MULTIPLIERS = {
    1: 1.15,
    2: 1.35,
    3: 1.60,
    4: 1.95,
    5: 2.40,
    6: 3.00,
}


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()
app = FastAPI()

# Игровые состояния в памяти
games = {}


# =========================
# КЛАВИАТУРЫ
# =========================

def main_menu():
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
            ]
        ]
    )


def mini_games_menu():
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
                    text="📂 | Назад",
                    callback_data="main_menu"
                )
            ]
        ]
    )


def after_game_menu():
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
            ]
        ]
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_id = message.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>Emoji Casino</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выберите раздел:"
    )

    await message.answer(
        text,
        reply_markup=main_menu()
    )


# =========================
# ГЛАВНОЕ МЕНЮ
# =========================

@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>Emoji Casino</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выберите раздел:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# ПРОФИЛЬ
# =========================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: types.CallbackQuery):
    user = callback.from_user
    balance = get_balance(user.id)

    username = (
        f"@{user.username}"
        if user.username
        else "Не указан"
    )

    text = (
        "🥷 <b>Профиль</b>\n\n"
        f"👤 Имя: <b>{user.first_name}</b>\n"
        f"🔗 Username: <b>{username}</b>\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n\n"
        f"💰 Баланс: <b>{balance}</b>"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="main_menu"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# =========================
# МИНИ-ИГРЫ
# =========================

@dp.callback_query(F.data == "mini_games")
async def mini_games_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    text = (
        "🎰 <b>Мини-игры</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выберите игру:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=mini_games_menu()
    )

    await callback.answer()


# ============================================================
# 🎲 КУБИКИ
# ============================================================

@dp.callback_query(F.data == "game_dice")
async def dice_menu_handler(callback: types.CallbackQuery):
    text = (
        "🎲 <b>Кубики</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "Выберите режим:"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="1 кубик",
                    callback_data="dice_one"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="2 кубика",
                    callback_data="dice_two"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_one")
async def dice_one_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_one"
    }

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="⬇️ | Меньше 3 x1.85",
                    callback_data="dice_bet_less"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⬆️ | Больше 3 x1.85",
                    callback_data="dice_bet_more"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "🎲 <b>Кубик — 1 бросок</b>\n\n"
        "Выберите ставку:"
    )

    await callback.message.edit_reply_markup(
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_bet_less")
async def dice_bet_less_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    games[user_id]["bet"] = "less"

    await callback.message.edit_text(
        "🎲 <b>Меньше 3</b>\n\n"
        "Сейчас будет брошен кубик 🎲"
    )

    await bot.send_dice(
        callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_bet_more")
async def dice_bet_more_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    games[user_id]["bet"] = "more"

    await callback.message.edit_text(
        "🎲 <b>Больше 3</b>\n\n"
        "Сейчас будет брошен кубик 🎲"
    )

    await bot.send_dice(
        callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_two")
async def dice_two_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_two",
        "first": None
    }

    await callback.message.edit_text(
        "🎲 <b>Кубики — 2 броска</b>\n\n"
        "Сейчас будут брошены два кубика.\n"
        "Сначала первый 🎲"
    )

    await bot.send_dice(
        callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


# ============================================================
# 🎳 БОУЛИНГ
# ============================================================

@dp.callback_query(F.data == "game_bowling")
async def bowling_menu_handler(callback: types.CallbackQuery):
    text = (
        "🎳 <b>Боулинг</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "Выберите ставку:"
    )

    keyboard = types.InlineKeyboardMarkup(
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
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data.in_({"bowling_more", "bowling_less"}))
async def bowling_bet_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
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

    if bet == "more":
        text = (
            "🎳 <b>Больше 3</b>\n\n"
            "Бросаем шар..."
        )
    else:
        text = (
            "🎳 <b>Меньше 3</b>\n\n"
            "Бросаем шар..."
        )

    await callback.message.edit_text(text)

    await bot.send_dice(
        callback.message.chat.id,
        emoji="🎳"
    )

    await callback.answer()


# ============================================================
# 🎡 РУЛЕТКА
# ============================================================

@dp.callback_query(F.data == "game_roulette")
async def roulette_menu_handler(callback: types.CallbackQuery):
    text = (
        "🎡 <b>Рулетка</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "Выберите ставку:"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔴 | Красное x1.95",
                    callback_data="roulette_red"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⚫ | Чёрное x1.95",
                    callback_data="roulette_black"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⬇️ | 1–18 x1.95",
                    callback_data="roulette_low"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⬆️ | 19–36 x1.95",
                    callback_data="roulette_high"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="➗ | Чётное x1.95",
                    callback_data="roulette_even"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔢 | Нечётное x1.95",
                    callback_data="roulette_odd"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🟢 | 0 x36",
                    callback_data="roulette_zero"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("roulette_"))
async def roulette_bet_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    bet = callback.data.replace("roulette_", "")

    number = random.randint(0, 36)

    win = False
    multiplier = ROULETTE_MULTIPLIER

    if bet == "zero":
        win = number == 0
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

    if number == 0:
        color = "🟢"
    elif number in RED_NUMBERS:
        color = "🔴"
    else:
        color = "⚫"

    if win:
        payout = int(STAKE * multiplier)
        balance = change_balance(user_id, payout)

        text = (
            "🎡 <b>Рулетка</b>\n\n"
            f"Выпало: {color} <b>{number}</b>\n\n"
            f"🎉 Победа!\n"
            f"💰 Выигрыш: <b>{payout}</b>\n\n"
            f"💳 Баланс: <b>{balance}</b>"
        )
    else:
        balance = get_balance(user_id)

        text = (
            "🎡 <b>Рулетка</b>\n\n"
            f"Выпало: {color} <b>{number}</b>\n\n"
            "❌ Вы проиграли.\n\n"
            f"💳 Баланс: <b>{balance}</b>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_menu()
    )

    await callback.answer()


# ============================================================
# 🎰 СЛОТЫ
# ============================================================

@dp.callback_query(F.data == "game_slots")
async def slots_menu_handler(callback: types.CallbackQuery):
    text = (
        "🎰 <b>Слоты</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "🎯 2 одинаковых → x1.85\n"
        "🍸🍸🍸 → x5\n"
        "🍇🍇🍇 → x8\n"
        "🍋🍋🍋 → x10\n"
        "7️⃣7️⃣7️⃣ → x50\n"
        "Другие 3 одинаковых → x3.5"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🎰 | Крутить",
                    callback_data="slots_spin"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data == "slots_spin")
async def slots_spin_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "slots"
    }

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        "Крутим..."
    )

    await bot.send_dice(
        callback.message.chat.id,
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

        elif result[0] == "🍇":
            return result, SLOT_GRAPES_MULTIPLIER

        elif result[0] == "🍋":
            return result, SLOT_LEMON_MULTIPLIER

        elif result[0] == "7️⃣":
            return result, SLOT_SEVEN_MULTIPLIER

        else:
            return result, SLOT_OTHER_THREE_MULTIPLIER

    if (
        result[0] == result[1]
        or result[0] == result[2]
        or result[1] == result[2]
    ):
        return result, SLOT_TWO_MULTIPLIER

    return result, 0


# ============================================================
# 💣 МИНЫ
# ============================================================

def mines_board(game, reveal=False):
    buttons = []

    mines = game["mines"]
    opened = game["opened"]

    for row in range(3):
        row_buttons = []

        for col in range(3):
            index = row * 3 + col

            if reveal:
                if index in mines:
                    text = "💣"
                else:
                    text = "💎"

                row_buttons.append(
                    types.InlineKeyboardButton(
                        text=text,
                        callback_data="mines_noop"
                    )
                )

            elif index in opened:
                row_buttons.append(
                    types.InlineKeyboardButton(
                        text="💎",
                        callback_data="mines_noop"
                    )
                )

            else:
                row_buttons.append(
                    types.InlineKeyboardButton(
                        text="❔",
                        callback_data=f"mine_cell_{index}"
                    )
                )

        buttons.append(row_buttons)

    if not reveal:
        buttons.append(
            [
                types.InlineKeyboardButton(
                    text="💰 | Забрать выигрыш",
                    callback_data="mines_cashout"
                )
            ]
        )

    return types.InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def mines_text(game):
    opened_count = len(game["opened"])
    multiplier = MINES_MULTIPLIERS.get(
        opened_count,
        1.0
    )

    payout = int(STAKE * multiplier)

    return (
        "💣 <b>Мины</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n"
        f"💎 Открыто: <b>{opened_count}</b>\n"
        f"📈 Коэффициент: <b>x{multiplier:.2f}</b>\n"
        f"💵 Можно забрать: <b>{payout}</b>\n\n"
        "Выберите клетку:"
    )


@dp.callback_query(F.data == "game_mines")
async def mines_menu_handler(callback: types.CallbackQuery):
    text = (
        "💣 <b>Мины</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "Поле 3×3.\n"
        "На поле спрятано 3 мины 💣.\n\n"
        "Открывайте безопасные клетки 💎 "
        "и увеличивайте множитель.\n\n"
        "Если попадёте на мину — ставка сгорает."
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💣 | Начать игру",
                    callback_data="mines_start"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data == "mines_start")
async def mines_start_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    mine_positions = set(
        random.sample(range(9), MINES_COUNT)
    )

    games[user_id] = {
        "type": "mines",
        "mines": mine_positions,
        "opened": set(),
    }

    game = games[user_id]

    await callback.message.edit_text(
        mines_text(game),
        reply_markup=mines_board(game)
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("mine_cell_"))
async def mine_cell_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра закончена",
            show_alert=True
        )
        return

    index = int(
        callback.data.replace("mine_cell_", "")
    )

    if index in game["opened"]:
        await callback.answer()
        return

    # Попадание на мину
    if index in game["mines"]:
        game["opened"].add(index)

        await callback.message.edit_text(
            "💣 <b>Мины</b>\n\n"
            "💥 Вы попали на мину!\n\n"
            "❌ Ставка сгорела.",
            reply_markup=mines_board(
                game,
                reveal=True
            )
        )

        del games[user_id]

        await callback.answer(
            "💣 Мина!",
            show_alert=True
        )
        return

    # Безопасная клетка
    game["opened"].add(index)

    opened_count = len(game["opened"])

    # Все 6 безопасных клеток открыты
    if opened_count == 6:
        multiplier = MINES_MULTIPLIERS[6]
        payout = int(STAKE * multiplier)

        balance = change_balance(
            user_id,
            payout
        )

        await callback.message.edit_text(
            "💣 <b>Мины</b>\n\n"
            "🎉 Все безопасные клетки открыты!\n\n"
            f"💎 Открыто: <b>6</b>\n"
            f"📈 Коэффициент: <b>x{multiplier:.2f}</b>\n"
            f"💰 Выигрыш: <b>{payout}</b>\n\n"
            f"💳 Баланс: <b>{balance}</b>",
            reply_markup=after_game_menu()
        )

        del games[user_id]

        await callback.answer(
            "🎉 Максимальный выигрыш!",
            show_alert=True
        )
        return

    multiplier = MINES_MULTIPLIERS[opened_count]
    payout = int(STAKE * multiplier)

    await callback.message.edit_text(
        mines_text(game),
        reply_markup=mines_board(game)
    )

    await callback.answer(
        f"💎 Безопасно! x{multiplier:.2f}"
    )


@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра закончена",
            show_alert=True
        )
        return

    opened_count = len(game["opened"])

    if opened_count == 0:
        await callback.answer(
            "Сначала откройте хотя бы одну клетку 💎",
            show_alert=True
        )
        return

    multiplier = MINES_MULTIPLIERS[opened_count]
    payout = int(STAKE * multiplier)

    balance = change_balance(
        user_id,
        payout
    )

    await callback.message.edit_text(
        "💣 <b>Мины</b>\n\n"
        "💰 Вы забрали выигрыш!\n\n"
        f"💎 Открыто клеток: <b>{opened_count}</b>\n"
        f"📈 Коэффициент: <b>x{multiplier:.2f}</b>\n"
        f"💵 Выигрыш: <b>{payout}</b>\n\n"
        f"💳 Баланс: <b>{balance}</b>",
        reply_markup=after_game_menu()
    )

    del games[user_id]

    await callback.answer("💰 Выигрыш забран!")


@dp.callback_query(F.data == "mines_noop")
async def mines_noop_handler(callback: types.CallbackQuery):
    await callback.answer()


# ============================================================
# 🎯 ОБРАБОТКА TELEGRAM DICE
# ============================================================

@dp.message(F.dice)
async def dice_handler(message: types.Message):
    user_id = message.from_user.id
    dice = message.dice

    game = games.get(user_id)

    if not game:
        return

    # -------------------------
    # 🎳 БОУЛИНГ
    # -------------------------

    if dice.emoji == "🎳":
        if game.get("type") != "bowling":
            return

        value = dice.value
        bet = game["bet"]

        win = False

        if bet == "more":
            win = value > 3
        elif bet == "less":
            win = value < 3

        if win:
            payout = int(STAKE * 1.85)

            balance = change_balance(
                user_id,
                payout
            )

            text = (
                "🎳 <b>Боулинг</b>\n\n"
                f"Выпало: <b>{value}</b>\n\n"
                "🎉 Победа!\n"
                f"💰 Выигрыш: <b>{payout}</b>\n\n"
                f"💳 Баланс: <b>{balance}</b>"
            )

        else:
            balance = get_balance(user_id)

            text = (
                "🎳 <b>Боулинг</b>\n\n"
                f"Выпало: <b>{value}</b>\n\n"
                "❌ Вы проиграли.\n\n"
                f"💳 Баланс: <b>{balance}</b>"
            )

        del games[user_id]

        await message.answer(
            text,
            reply_markup=after_game_menu()
        )

        return

    # -------------------------
    # 🎰 СЛОТЫ
    # -------------------------

    if dice.emoji == "🎰":
        if game.get("type") != "slots":
            return

        result, multiplier = slot_result(
            dice.value
        )

        result_text = " ".join(result)

        if multiplier > 0:
            payout = int(STAKE * multiplier)

            balance = change_balance(
                user_id,
                payout
            )

            text = (
                "🎰 <b>Слоты</b>\n\n"
                f"{result_text}\n\n"
                "🎉 Победа!\n"
                f"📈 Коэффициент: <b>x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>{payout}</b>\n\n"
                f"💳 Баланс: <b>{balance}</b>"
            )

        else:
            balance = get_balance(user_id)

            text = (
                "🎰 <b>Слоты</b>\n\n"
                f"{result_text}\n\n"
                "❌ Нет совпадений.\n\n"
                f"💳 Баланс: <b>{balance}</b>"
            )

        del games[user_id]

        await message.answer(
            text,
            reply_markup=after_game_menu()
        )

        return

    # -------------------------
    # 🎲 КУБИКИ
    # -------------------------

    if dice.emoji == "🎲":
        if game.get("type") == "dice_one":
            value = dice.value
            bet = game.get("bet")

            win = False

            if bet == "less":
                win = value < 3

            elif bet == "more":
                win = value > 3

            if win:
                payout = int(
                    STAKE * DICE_ONE_MULTIPLIER
                )

                balance = change_balance(
                    user_id,
                    payout
                )

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    "🎉 Победа!\n"
                    f"💰 Выигрыш: <b>{payout}</b>\n\n"
                    f"💳 Баланс: <b>{balance}</b>"
                )

            else:
                balance = get_balance(user_id)

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    "❌ Вы проиграли.\n\n"
                    f"💳 Баланс: <b>{balance}</b>"
                )

            del games[user_id]

            await message.answer(
                text,
                reply_markup=after_game_menu()
            )

            return

        if game.get("type") == "dice_two":
            if game["first"] is None:
                game["first"] = dice.value

                await message.answer(
                    "🎲 <b>Первый кубик:</b> "
                    f"{dice.value}\n\n"
                    "Бросаем второй 🎲"
                )

                await bot.send_dice(
                    message.chat.id,
                    emoji="🎲"
                )

                return

            first = game["first"]
            second = dice.value

            total = first + second

            if total == 7:
                multiplier = DICE_TWO_EQUAL_MULTIPLIER

            else:
                multiplier = DICE_TWO_MULTIPLIER

            if (
                (total == 7)
                or (total < 7)
                or (total > 7)
            ):
                payout = int(
                    STAKE * multiplier
                )

                balance = change_balance(
                    user_id,
                    payout
                )

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"Первый: <b>{first}</b>\n"
                    f"Второй: <b>{second}</b>\n"
                    f"Сумма: <b>{total}</b>\n\n"
                )

                if total == 7:
                    text += (
                        "🎉 Равно 7!\n"
                        f"📈 x{multiplier}\n"
                    )

                elif total < 7:
                    text += (
                        "🎉 Меньше 7!\n"
                        f"📈 x{multiplier}\n"
                    )

                else:
                    text += (
                        "🎉 Больше 7!\n"
                        f"📈 x{multiplier}\n"
                    )

                text += (
                    f"💰 Выигрыш: <b>{payout}</b>\n\n"
                    f"💳 Баланс: <b>{balance}</b>"
                )

            del games[user_id]

            await message.answer(
                text,
                reply_markup=after_game_menu()
            )

            return


# ============================================================
# WEBHOOK
# ============================================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "Emoji Casino"
    }


@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    data = await request.json()

    update = types.Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

@app.on_event("startup")
async def startup():
    init_db()

    webhook_url = (
        f"https://emoji-casino-bot.onrender.com/"
        f"webhook/{WEBHOOK_SECRET}"
    )

    print("SETTING WEBHOOK:", webhook_url)

    await bot.set_webhook(
        webhook_url,
        allowed_updates=[
            "message",
            "callback_query"
        ]
    )

    info = await bot.get_webhook_info()

    print("WEBHOOK URL:", info.url)
    print("PENDING UPDATES:", info.pending_update_count)
    print("LAST ERROR:", info.last_error_message)


@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()
