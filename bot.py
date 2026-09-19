import asyncio
import os
import random

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "emoji_casino_secret_2026_x7k9"
)

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_URL = (
    f"https://emoji-casino-bot.onrender.com"
    f"{WEBHOOK_PATH}"
)

STAKE = 100

# Слоты
SLOT_TWO_MULTIPLIER = 1.85
SLOT_OTHER_THREE_MULTIPLIER = 3.5
SLOT_COCKTAIL_MULTIPLIER = 5
SLOT_GRAPES_MULTIPLIER = 8
SLOT_LEMON_MULTIPLIER = 10
SLOT_SEVEN_MULTIPLIER = 50

# Crash
CRASH_MIN = 1.10
CRASH_MAX = 20.00
CRASH_SPEED = 0.50


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")


# =========================
# DATABASE
# =========================

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


# =========================
# BOT
# =========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

games = {}


# =========================
# КЛАВИАТУРЫ
# =========================

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


# =========================
# ДИЗЫ / МЕНЮ
# =========================

def dice_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🎲 | Один бросок",
                    callback_data="dice_one"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🎲🎲 | Два броска",
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


def dice_one_keyboard():
    return types.InlineKeyboardMarkup(
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
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="game_dice"
                )
            ],
        ]
    )


def dice_two_keyboard():
    return types.InlineKeyboardMarkup(
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
            [
                types.InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="game_dice"
                )
            ],
        ]
    )


def roulette_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔴 Красное x1.95",
                    callback_data="roulette_red"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⚫ Чёрное x1.95",
                    callback_data="roulette_black"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="1–18 x1.95",
                    callback_data="roulette_low"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="19–36 x1.95",
                    callback_data="roulette_high"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⚖️ Чётное x1.95",
                    callback_data="roulette_even"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⚖️ Нечётное x1.95",
                    callback_data="roulette_odd"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🟢 Ноль x36",
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


def bowling_keyboard():
    return types.InlineKeyboardMarkup(
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


# =========================
# MINES
# =========================

MINES_MULTIPLIERS = {
    1: 1.15,
    2: 1.35,
    3: 1.60,
    4: 1.95,
    5: 2.40,
    6: 3.00,
}


def mines_keyboard(user_id):
    game = games.get(user_id)

    if not game:
        return mini_games_keyboard()

    mines = game["mines"]
    opened = game["opened"]

    buttons = []

    for position in range(9):
        if position in opened:
            text = "💎"
        else:
            text = "⬜"

        buttons.append(
            types.InlineKeyboardButton(
                text=text,
                callback_data=f"mine_{position}"
            )
        )

    rows = [
        buttons[0:3],
        buttons[3:6],
        buttons[6:9],
    ]

    safe_count = len(opened)

    if safe_count > 0:
        multiplier = MINES_MULTIPLIERS[safe_count]

        rows.append(
            [
                types.InlineKeyboardButton(
                    text=f"💰 Забрать x{multiplier}",
                    callback_data="mines_cashout"
                )
            ]
        )

    rows.append(
        [
            types.InlineKeyboardButton(
                text="❌ | Отмена",
                callback_data="mines_cancel"
            )
        ]
    )

    return types.InlineKeyboardMarkup(
        inline_keyboard=rows
    )


# =========================
# CRASH
# =========================

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


def crash_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💰 Забрать",
                    callback_data="crash_cashout"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="crash_cancel"
                )
            ],
        ]
    )


def crash_text(multiplier):
    return (
        "🧨 <b>CRASH</b>\n\n"
        f"🚀 Коэффициент: <b>x{multiplier:.2f}</b>\n\n"
        "💰 Забери выигрыш до краша!"
    )


# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def on_startup():
    init_db()

    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=[
            "message",
            "callback_query",
        ]
    )

    print("SETTING WEBHOOK:", WEBHOOK_URL)
    print("WEBHOOK URL:", WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()


# =========================
# WEBHOOK
# =========================

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()

    update = types.Update.model_validate(data)

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
        "bot": "Emoji Casino"
    }


# =========================
# START
# =========================

@dp.message(Command("start"))
async def start_handler(message: types.Message):

    user_id = message.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>Emoji Casino</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Добро пожаловать!"
    )

    await message.answer(
        text,
        reply_markup=main_menu_keyboard()
    )


# =========================
# MAIN MENU
# =========================

@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: types.CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>Emoji Casino</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu_keyboard()
    )

    await callback.answer()


# =========================
# PROFILE
# =========================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: types.CallbackQuery):

    user = callback.from_user
    balance = get_balance(user.id)

    username = (
        f"@{user.username}"
        if user.username
        else "не указан"
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
# MINI GAMES
# =========================

@dp.callback_query(F.data == "mini_games")
async def mini_games_handler(callback: types.CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>Мини-игры</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выбери игру:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=mini_games_keyboard()
    )

    await callback.answer()


# =========================
# DICE MENU
# =========================

@dp.callback_query(F.data == "game_dice")
async def game_dice_handler(callback: types.CallbackQuery):

    text = (
        "🎲 <b>Кубики</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n\n"
        "Выбери режим:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=dice_keyboard()
    )

    await callback.answer()


# =========================
# DICE ONE
# =========================

@dp.callback_query(F.data.in_({
    "dice_one_less",
    "dice_one_more"
}))
async def dice_one_handler(callback: types.CallbackQuery):

    user_id = callback.from_user.id

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
        "less"
        if callback.data == "dice_one_less"
        else "more"
    )

    games[user_id] = {
        "type": "dice_one",
        "bet": bet,
    }

    await callback.message.edit_text(
        "🎲 Бросаю кубик..."
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


# =========================
# DICE TWO
# =========================

@dp.callback_query(F.data.in_({
    "dice_two_equal",
    "dice_two_less",
    "dice_two_more"
}))
async def dice_two_handler(callback: types.CallbackQuery):

    user_id = callback.from_user.id

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "❌ Недостаточно средств",
            show_alert=True
        )
        return

    if callback.data == "dice_two_equal":
        bet = "equal"
    elif callback.data == "dice_two_less":
        bet = "less"
    else:
        bet = "more"

    games[user_id] = {
        "type": "dice_two",
        "bet": bet,
        "first": None,
    }

    await callback.message.edit_text(
        "🎲🎲 Первый бросок..."
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


# =========================
# SLOTS
# =========================

@dp.callback_query(F.data == "game_slots")
async def game_slots_handler(callback: types.CallbackQuery):

    user_id = callback.from_user.id

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

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        "🎰 Крутим барабаны..."
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
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


# =========================
# ROULETTE
# =========================

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}


@dp.callback_query(F.data.startswith("roulette_"))
async def roulette_handler(callback: types.CallbackQuery):

    user_id = callback.from_user.id

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

    number = random.randint(
        0,
        36
    )

    won = False
    multiplier = 1.95

    if bet == "zero":
        won = number == 0
        multiplier = 36

    elif bet == "red":
        won = number in RED_NUMBERS

    elif bet == "black":
        won = (
            number != 0
            and number not in RED_NUMBERS
        )

    elif bet == "low":
        won = 1 <= number <= 18

    elif bet == "high":
        won = 19 <= number <= 36

    elif bet == "even":
        won = number != 0 and number % 2 == 0

    elif bet == "odd":
        won = number != 0 and number % 2 == 1

    if won:
        payout = int(
            STAKE * multiplier
        )

        balance = change_balance(
            user_id,
            payout
        )

        result_text = (
            f"🎉 <b>Победа!</b>\n\n"
            f"🎡 Выпало: <b>{number}</b>\n"
            f"💰 Выигрыш: <b>{payout}</b>\n"
            f"💳 Баланс: <b>{balance}</b>"
        )

    else:
        balance = get_balance(
            user_id
        )

        result_text = (
            f"🎡 Выпало: <b>{number}</b>\n\n"
            "❌ <b>Проигрыш</b>\n"
            f"💳 Баланс: <b>{balance}</b>"
        )

    await callback.message.edit_text(
        result_text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data == "game_roulette")
async def game_roulette_handler(
    callback: types.CallbackQuery
):

    balance = get_balance(
        callback.from_user.id
    )

    text = (
        "🎡 <b>Рулетка</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n"
        f"💳 Баланс: <b>{balance}</b>\n\n"
        "Выбери ставку:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=roulette_keyboard()
    )

    await callback.answer()


# =========================
# BOWLING
# =========================

@dp.callback_query(F.data.in_({
    "bowling_more",
    "bowling_less"
}))
async def bowling_bet_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

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

    await callback.message.edit_text(
        "🎳 Бросаю шар..."
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎳"
    )

    await callback.answer()


@dp.callback_query(F.data == "game_bowling")
async def game_bowling_handler(
    callback: types.CallbackQuery
):

    balance = get_balance(
        callback.from_user.id
    )

    text = (
        "🎳 <b>Боулинг</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n"
        f"💳 Баланс: <b>{balance}</b>\n\n"
        "Выбери ставку:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=bowling_keyboard()
    )

    await callback.answer()


# =========================
# MINES START
# =========================

@dp.callback_query(F.data == "game_mines")
async def game_mines_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

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
        "opened": set(),
    }

    await callback.message.edit_text(
        "💣 <b>Мины</b>\n\n"
        "💰 Ставка: <b>100</b>\n"
        "💎 Открывай клетки и забери выигрыш!",
        reply_markup=mines_keyboard(user_id)
    )

    await callback.answer()


# =========================
# MINES CELL
# =========================

@dp.callback_query(F.data.startswith("mine_"))
async def mine_cell_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра не найдена",
            show_alert=True
        )
        return

    position = int(
        callback.data.split("_")[1]
    )

    if position in game["opened"]:
        await callback.answer(
            "Эта клетка уже открыта"
        )
        return

    if position in game["mines"]:

        game["opened"].add(position)

        keyboard_rows = []

        for i in range(9):
            if i in game["mines"]:
                text = "💣"
            elif i in game["opened"]:
                text = "💎"
            else:
                text = "⬜"

            keyboard_rows.append(
                types.InlineKeyboardButton(
                    text=text,
                    callback_data="mine_disabled"
                )
            )

        rows = [
            keyboard_rows[0:3],
            keyboard_rows[3:6],
            keyboard_rows[6:9],
        ]

        rows.append(
            [
                types.InlineKeyboardButton(
                    text="🔄 | Играть снова",
                    callback_data="game_mines"
                )
            ]
        )

        rows.append(
            [
                types.InlineKeyboardButton(
                    text="📂 | Меню",
                    callback_data="mini_games"
                )
            ]
        )

        del games[user_id]

        await callback.message.edit_text(
            "💣 <b>БАБАХ!</b>\n\n"
            "❌ Ты попал на мину.\n"
            "💰 Ставка проиграна.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=rows
            )
        )

        await callback.answer()
        return

    game["opened"].add(position)

    safe_count = len(
        game["opened"]
    )

    if safe_count >= 6:

        multiplier = MINES_MULTIPLIERS[6]

        payout = int(
            STAKE * multiplier
        )

        balance = change_balance(
            user_id,
            payout
        )

        del games[user_id]

        await callback.message.edit_text(
            "💣 <b>Мины</b>\n\n"
            "🎉 Все безопасные клетки открыты!\n\n"
            f"💰 Выигрыш: <b>{payout}</b>\n"
            f"💳 Баланс: <b>{balance}</b>",
            reply_markup=after_game_keyboard()
        )

        await callback.answer()
        return

    multiplier = MINES_MULTIPLIERS[
        safe_count
    ]

    await callback.message.edit_reply_markup(
        reply_markup=mines_keyboard(user_id)
    )

    await callback.answer(
        f"💎 Безопасно! x{multiplier}"
    )


# =========================
# MINES CASHOUT
# =========================

@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "❌ Игра не найдена",
            show_alert=True
        )
        return

    safe_count = len(
        game["opened"]
    )

    if safe_count == 0:
        await callback.answer(
            "Сначала открой хотя бы одну клетку",
            show_alert=True
        )
        return

    multiplier = MINES_MULTIPLIERS[
        safe_count
    ]

    payout = int(
        STAKE * multiplier
    )

    balance = change_balance(
        user_id,
        payout
    )

    del games[user_id]

    await callback.message.edit_text(
        "💣 <b>Мины</b>\n\n"
        f"💎 Открыто клеток: <b>{safe_count}</b>\n"
        f"📈 Коэффициент: <b>x{multiplier}</b>\n\n"
        f"💰 Выигрыш: <b>{payout}</b>\n"
        f"💳 Баланс: <b>{balance}</b>",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================
# MINES CANCEL
# =========================

@dp.callback_query(F.data == "mines_cancel")
async def mines_cancel_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

    games.pop(
        user_id,
        None
    )

    await callback.message.edit_text(
        "💣 Игра отменена.",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================
# CRASH MENU
# =========================

@dp.callback_query(F.data == "game_crash")
async def game_crash_handler(
    callback: types.CallbackQuery
):

    balance = get_balance(
        callback.from_user.id
    )

    text = (
        "🧨 <b>CRASH</b>\n\n"
        f"💰 Ставка: <b>{STAKE}</b>\n"
        f"💳 Баланс: <b>{balance}</b>\n\n"
        "Нажми «Начать», чтобы запустить игру."
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🚀 | Начать",
                    callback_data="crash_start"
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

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# =========================
# CRASH START
# =========================

@dp.callback_query(F.data == "crash_start")
async def crash_start_handler(
    callback: types.CallbackQuery
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
        "crash_point": crash_point,
        "multiplier": 1.00,
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
        "task": None,
    }

    await callback.message.edit_text(
        crash_text(1.00),
        reply_markup=crash_keyboard()
    )

    task = asyncio.create_task(
        crash_loop(user_id)
    )

    games[user_id]["task"] = task

    await callback.answer()


# =========================
# CRASH LOOP
# =========================

async def crash_loop(user_id):

    while True:

        await asyncio.sleep(
            CRASH_SPEED
        )

        game = games.get(user_id)

        if not game:
            return

        multiplier = round(
            game["multiplier"] + 0.05,
            2
        )

        game["multiplier"] = multiplier

        if multiplier >= game["crash_point"]:

            crash_point = game["crash_point"]

            games.pop(
                user_id,
                None
            )

            balance = get_balance(
                user_id
            )

            try:
                await bot.edit_message_text(
                    chat_id=game["chat_id"],
                    message_id=game["message_id"],
                    text=(
                        "🧨 <b>CRASH</b>\n\n"
                        f"💥 Краш на <b>x{crash_point:.2f}</b>\n\n"
                        "❌ Ставка проиграна.\n"
                        f"💳 Баланс: <b>{balance}</b>"
                    ),
                    reply_markup=after_game_keyboard()
                )
            except Exception:
                pass

            return

        try:
            await bot.edit_message_text(
                chat_id=game["chat_id"],
                message_id=game["message_id"],
                text=crash_text(multiplier),
                reply_markup=crash_keyboard()
            )
        except Exception:
            pass


# =========================
# CRASH CASHOUT
# =========================

@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game or game.get("type") != "crash":
        await callback.answer(
            "❌ Игра уже закончена",
            show_alert=True
        )
        return

    multiplier = game["multiplier"]

    payout = int(
        STAKE * multiplier
    )

    balance = change_balance(
        user_id,
        payout
    )

    task = game.get("task")

    if task:
        task.cancel()

    games.pop(
        user_id,
        None
    )

    await callback.message.edit_text(
        "🧨 <b>CRASH</b>\n\n"
        f"🚀 Коэффициент: <b>x{multiplier:.2f}</b>\n\n"
        f"🎉 Ты забрал: <b>{payout}</b>\n"
        f"💳 Баланс: <b>{balance}</b>",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================
# CRASH CANCEL
# =========================

@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel_handler(
    callback: types.CallbackQuery
):

    user_id = callback.from_user.id

    game = games.get(user_id)

    if game and game.get("type") == "crash":

        task = game.get("task")

        if task:
            task.cancel()

        games.pop(
            user_id,
            None
        )

    await callback.message.edit_text(
        "🧨 Игра Crash отменена.",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================
# DICE / SLOTS / BOWLING RESULTS
# =========================

@dp.message(F.dice)
async def dice_handler(message: types.Message):

    user_id = message.from_user.id

    game = games.get(user_id)

    if not game:
        return

    dice = message.dice

    # -------------------------
    # КУБИКИ
    # -------------------------

    if dice.emoji == "🎲":

        if game["type"] == "dice_one":

            value = dice.value
            bet = game["bet"]

            won = (
                value < 3
                if bet == "less"
                else value > 3
            )

            if won:
                payout = int(
                    STAKE * 1.85
                )

                balance = change_balance(
                    user_id,
                    payout
                )

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    "🎉 <b>Победа!</b>\n"
                    f"💰 Выигрыш: <b>{payout}</b>\n"
                    f"💳 Баланс: <b>{balance}</b>"
                )

            else:

                balance = get_balance(
                    user_id
                )

                text = (
                    "🎲 <b>Кубики</b>\n\n"
                    f"Выпало: <b>{value}</b>\n\n"
                    "❌ <b>Проигрыш</b>\n"
                    f"💳 Баланс: <b>{balance}</b>"
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

            if game["first"] is None:

                game["first"] = dice.value

                await message.answer(
                    f"🎲 Первый бросок: <b>{dice.value}</b>\n\n"
                    "🎲 Бросаю второй..."
                )

                await bot.send_dice(
                    chat_id=message.chat.id,
                    emoji="🎲"
                )

                return

            first = game["first"]
            second = dice.value
            total = first + second
            bet = game["bet"]

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

                balance = change_balance(
                    user_id,
                    payout
                )

                text = (
                    "🎲🎲 <b>Кубики</b>\n\n"
                    f"Первый: <b>{first}</b>\n"
                    f"Второй: <b>{second}</b>\n"
                    f"Сумма: <b>{total}</b>\n\n"
                    "🎉 <b>Победа!</b>\n"
                    f"💰 Выигрыш: <b>{payout}</b>\n"
                    f"💳 Баланс: <b>{balance}</b>"
                )

            else:

                balance = get_balance(
                    user_id
                )

                text = (
                    "🎲🎲 <b>Кубики</b>\n\n"
                    f"Первый: <b>{first}</b>\n"
                    f"Второй: <b>{second}</b>\n"
                    f"Сумма: <b>{total}</b>\n\n"
                    "❌ <b>Проигрыш</b>\n"
                    f"💳 Баланс: <b>{balance}</b>"
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

    # -------------------------
    # СЛОТЫ
    # -------------------------

    if dice.emoji == "🎰":

        if game["type"] != "slots":
            return

        result, multiplier = slot_result(
            dice.value
        )

        result_text = " ".join(result)

        if multiplier > 0:

            payout = int(
                STAKE * multiplier
            )

            balance = change_balance(
                user_id,
                payout
            )

            text = (
                "🎰 <b>Слоты</b>\n\n"
                f"{result_text}\n\n"
                f"🎉 <b>Победа x{multiplier}</b>\n"
                f"💰 Выигрыш: <b>{payout}</b>\n"
                f"💳 Баланс: <b>{balance}</b>"
            )

        else:

            balance = get_balance(
                user_id
            )

            text = (
                "🎰 <b>Слоты</b>\n\n"
                f"{result_text}\n\n"
                "❌ <b>Проигрыш</b>\n"
                f"💳 Баланс: <b>{balance}</b>"
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

    # -------------------------
    # БОУЛИНГ
    # -------------------------

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
                STAKE * 1.85
            )

            balance = change_balance(
                user_id,
                payout
            )

            text = (
                "🎳 <b>Боулинг</b>\n\n"
                f"Выпало: <b>{value}</b>\n\n"
                "🎉 <b>Победа!</b>\n"
                f"💰 Выигрыш: <b>{payout}</b>\n"
                f"💳 Баланс: <b>{balance}</b>"
            )

        else:

            balance = get_balance(
                user_id
            )

            text = (
                "🎳 <b>Боулинг</b>\n\n"
                f"Выпало: <b>{value}</b>\n\n"
                "❌ <b>Проигрыш</b>\n"
                f"💳 Баланс: <b>{balance}</b>"
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


# =========================
# ERROR HANDLER
# =========================

@dp.errors()
async def error_handler(event):

    print(
        "BOT ERROR:",
        event.exception
    )


# =========================
# LOCAL START
# =========================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8000"
            )
        )
    )
