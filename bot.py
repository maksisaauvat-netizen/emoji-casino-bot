import asyncio
import os
import random
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
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
    get_payment_history,
    record_game,
    DB_PATH,
)
from payments import (
    create_invoice,
    process_paid_invoice,
    get_invoice,
)


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

games = {}

STAKES = [
    50,
    100,
    250,
    500,
    1000,
]

SLOT_SEVEN_MULTIPLIER = 50

CRASH_MIN = 1.05
CRASH_MAX = 20.0


# =========================================================
# HELPERS
# =========================================================

def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def safe_user_id(user_id: int) -> int:
    return int(user_id)


async def edit_or_answer(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup
        )
    except Exception:
        try:
            await callback.message.answer(
                text,
                reply_markup=reply_markup
            )
        except Exception:
            pass


def confirm_bet_keyboard(game: str, stake: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"✅ ИГРАТЬ {money(stake)} ₽",
        callback_data=f"confirm:{game}:{stake}"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data=f"cancel:{game}"
    )

    builder.adjust(1)

    return builder.as_markup()


def stake_keyboard(game: str):
    builder = InlineKeyboardBuilder()

    for stake in STAKES:
        builder.button(
            text=f"{money(stake)} ₽",
            callback_data=f"stake:{game}:{stake}"
        )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="games"
    )

    builder.adjust(2)

    return builder.as_markup()


def main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎮 ИГРЫ",
        callback_data="games"
    )

    builder.button(
        text="💰 БАЛАНС",
        callback_data="wallet"
    )

    builder.button(
        text="👤 ПРОФИЛЬ",
        callback_data="profile"
    )

    builder.button(
        text="💳 ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    if is_admin(user_id):
        builder.button(
            text="🛠 ADMIN PANEL",
            callback_data="admin"
        )

    builder.adjust(2)

    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲 КУБИК",
        callback_data="game:dice"
    )

    builder.button(
        text="🎲 ДВА КУБИКА",
        callback_data="game:two_dice"
    )

    builder.button(
        text="🎰 СЛОТЫ",
        callback_data="game:slots"
    )

    builder.button(
        text="🎳 БОУЛИНГ",
        callback_data="game:bowling"
    )

    builder.button(
        text="🎯 РУЛЕТКА",
        callback_data="game:roulette"
    )

    builder.button(
        text="💥 CRASH",
        callback_data="game:crash"
    )

    builder.button(
        text="💣 MINES",
        callback_data="game:mines"
    )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="main"
    )

    builder.adjust(2)

    return builder.as_markup()


def wallet_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💳 ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="main"
    )

    builder.adjust(1)

    return builder.as_markup()


def deposit_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="1 USDT → 80 ₽",
        callback_data="deposit_amount:1"
    )

    builder.button(
        text="5 USDT → 400 ₽",
        callback_data="deposit_amount:5"
    )

    builder.button(
        text="10 USDT → 800 ₽",
        callback_data="deposit_amount:10"
    )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="wallet"
    )

    builder.adjust(1)

    return builder.as_markup()


def after_game_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎮 ИГРАТЬ ЕЩЁ",
        callback_data="games"
    )

    builder.button(
        text="💰 БАЛАНС",
        callback_data="wallet"
    )

    builder.button(
        text="🏠 ГЛАВНОЕ МЕНЮ",
        callback_data="main"
    )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# TELEGRAM SLOT MACHINE DECODER
# =========================================================

def slot_symbols_from_value(value: int):
    """
    Точное декодирование результата Telegram 🎰.

    Telegram использует value от 1 до 64.

    value == 64:
        777

    Для остальных значений Telegram использует
    три 2-битных значения.

    Внутренний порядок Telegram:
        0 = BAR
        1 = BERRIES / GRAPES
        2 = LEMON
        3 = SEVEN
    """

    value = int(value)

    if value < 1 or value > 64:
        return ["❓", "❓", "❓"]

    if value == 64:
        return [
            "7️⃣",
            "7️⃣",
            "7️⃣"
        ]

    # Telegram's official mapping.
    mapping = [
        1,
        2,
        3,
        0
    ]

    # Text representation of Telegram's four slot symbols.
    symbols = [
        "BAR",
        "🍇",
        "🍋",
        "7️⃣"
    ]

    left_index = mapping[
        (value - 1) & 3
    ]

    center_index = mapping[
        ((value - 1) >> 2) & 3
    ]

    right_index = mapping[
        ((value - 1) >> 4) & 3
    ]

    return [
        symbols[left_index],
        symbols[center_index],
        symbols[right_index]
    ]


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = safe_user_id(message.from_user.id)

    balance = get_balance(user_id)

    text = (
        "🎰 <b>RESONANT CASINO</b>\n\n"
        "Добро пожаловать!\n\n"
        f"💰 Ваш баланс: <b>{money(balance)} ₽</b>\n\n"
        "Выберите действие:"
    )

    await message.answer(
        text,
        reply_markup=main_keyboard(user_id)
    )


# =========================================================
# MAIN
# =========================================================

@dp.callback_query(F.data == "main")
async def main_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    balance = get_balance(user_id)

    text = (
        "🎰 <b>RESONANT CASINO</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "Выберите действие:"
    )

    await edit_or_answer(
        callback,
        text,
        main_keyboard(user_id)
    )


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "games")
async def games_callback(callback: CallbackQuery):
    await callback.answer()

    balance = get_balance(
        safe_user_id(callback.from_user.id)
    )

    text = (
        "🎮 <b>ИГРЫ</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "Выберите игру:"
    )

    await edit_or_answer(
        callback,
        text,
        games_keyboard()
    )


# =========================================================
# WALLET
# =========================================================

@dp.callback_query(F.data == "wallet")
async def wallet_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    balance = get_balance(user_id)

    text = (
        "💰 <b>КОШЕЛЁК</b>\n\n"
        f"Баланс: <b>{money(balance)} ₽</b>\n\n"
        "Пополнить баланс можно через Crypto Pay."
    )

    await edit_or_answer(
        callback,
        text,
        wallet_keyboard()
    )


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    stats = get_user_stats(user_id)

    total_bet = stats["total_bet"]
    total_won = stats["total_won"]
    games_played = stats["games_played"]
    wins = stats["wins"]
    losses = stats["losses"]
    biggest_win = stats["biggest_win"]

    text = (
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💰 Баланс: <b>{money(stats['balance'])} ₽</b>\n"
        f"🎮 Игр: <b>{games_played}</b>\n"
        f"✅ Побед: <b>{wins}</b>\n"
        f"❌ Поражений: <b>{losses}</b>\n\n"
        f"💵 Всего ставок: <b>{money(total_bet)} ₽</b>\n"
        f"🏆 Всего выиграно: <b>{money(total_won)} ₽</b>\n"
        f"🔥 Максимальный выигрыш: <b>{money(biggest_win)} ₽</b>"
    )

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📜 ИСТОРИЯ ИГР",
        callback_data="profile_history"
    )

    builder.button(
        text="💳 ИСТОРИЯ ПЛАТЕЖЕЙ",
        callback_data="payment_history"
    )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="main"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# GAME STAKE SELECTION
# =========================================================

@dp.callback_query(F.data.startswith("game:"))
async def game_select_callback(callback: CallbackQuery):
    await callback.answer()

    game = callback.data.split(":", 1)[1]

    names = {
        "dice": "🎲 КУБИК",
        "two_dice": "🎲 ДВА КУБИКА",
        "slots": "🎰 СЛОТЫ",
        "bowling": "🎳 БОУЛИНГ",
        "roulette": "🎯 РУЛЕТКА",
        "crash": "💥 CRASH",
        "mines": "💣 MINES",
    }

    name = names.get(game, "ИГРА")

    await edit_or_answer(
        callback,
        (
            f"<b>{name}</b>\n\n"
            "Выберите размер ставки:"
        ),
        stake_keyboard(game)
    )


# =========================================================
# STAKE CALLBACK
# =========================================================

@dp.callback_query(F.data.startswith("stake:"))
async def stake_callback(callback: CallbackQuery):
    await callback.answer()

    _, game, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    balance = get_balance(user_id)

    if balance < stake:
        await edit_or_answer(
            callback,
            (
                "❌ <b>Недостаточно средств</b>\n\n"
                f"Ваш баланс: <b>{money(balance)} ₽</b>\n"
                f"Ставка: <b>{money(stake)} ₽</b>"
            ),
            wallet_keyboard()
        )
        return

    names = {
        "dice": "🎲 КУБИК",
        "two_dice": "🎲 ДВА КУБИКА",
        "slots": "🎰 СЛОТЫ",
        "bowling": "🎳 БОУЛИНГ",
        "roulette": "🎯 РУЛЕТКА",
        "crash": "💥 CRASH",
        "mines": "💣 MINES",
    }

    name = names.get(game, "ИГРА")

    await edit_or_answer(
        callback,
        (
            f"<b>{name}</b>\n\n"
            f"💰 Баланс: <b>{money(balance)} ₽</b>\n"
            f"🎯 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Подтвердить ставку?"
        ),
        confirm_bet_keyboard(game, stake)
    )


# =========================================================
# CANCEL BET
# =========================================================

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_bet_callback(callback: CallbackQuery):
    await callback.answer("Ставка отменена")

    await edit_or_answer(
        callback,
        "🎮 <b>ИГРЫ</b>\n\nВыберите игру:",
        games_keyboard()
    )


# =========================================================
# DICE
# =========================================================

@dp.callback_query(F.data.startswith("confirm:dice:"))
async def confirm_dice(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️ МЕНЬШЕ 4",
        callback_data=f"dice_pred:{stake}:less"
    )

    builder.button(
        text="⬆️ БОЛЬШЕ 3",
        callback_data=f"dice_pred:{stake}:more"
    )

    builder.button(
        text="🎯 РОВНО 2",
        callback_data=f"dice_pred:{stake}:two"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data="games"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИК</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Что выбираете?"
        ),
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("dice_pred:"))
async def dice_prediction(callback: CallbackQuery):
    await callback.answer()

    _, stake_text, prediction = callback.data.split(":")

    stake = int(stake_text)

    games[callback.from_user.id] = {
        "type": "dice",
        "stake": stake,
        "prediction": prediction
    }

    labels = {
        "less": "меньше 4",
        "more": "больше 3",
        "two": "ровно 2"
    }

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИК</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n"
            f"Выбор: <b>{labels[prediction]}</b>\n\n"
            "Подтвердить?"
        ),
        confirm_bet_keyboard("dice_play", stake)
    )


@dp.callback_query(F.data.startswith("confirm:dice_play:"))
async def play_dice(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    game = games.get(user_id)

    if not game or game.get("type") != "dice":
        await callback.message.answer(
            "❌ Игра устарела. Начните заново."
        )
        return

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    prediction = game["prediction"]

    dice_message = await callback.message.answer_dice(
        emoji="🎲"
    )

    value = dice_message.dice.value

    await asyncio.sleep(1.5)

    won = False
    multiplier = 0

    if prediction == "less":
        won = value < 4
        multiplier = 1.8

    elif prediction == "more":
        won = value > 3
        multiplier = 1.8

    elif prediction == "two":
        won = value == 2
        multiplier = 5

    payout = int(stake * multiplier) if won else 0

    if payout > 0:
        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        text = (
            "🎲 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"Выпало: <b>{value}</b>\n"
            f"Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    else:
        new_balance = get_balance(user_id)

        result = "loss"

        text = (
            "🎲 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"Выпало: <b>{value}</b>\n"
            "❌ Вы проиграли.\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    record_game(
        user_id=user_id,
        game="dice",
        stake=stake,
        result=result,
        multiplier=multiplier if won else 0,
        payout=payout
    )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# TWO DICE
# =========================================================

@dp.callback_query(F.data.startswith("confirm:two_dice:"))
async def confirm_two_dice(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬆️ БОЛЬШЕ 7",
        callback_data=f"two_dice_pred:{stake}:high"
    )

    builder.button(
        text="⬇️ МЕНЬШЕ 7",
        callback_data=f"two_dice_pred:{stake}:low"
    )

    builder.button(
        text="🎯 РОВНО 7",
        callback_data=f"two_dice_pred:{stake}:seven"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data="games"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        (
            "🎲 <b>ДВА КУБИКА</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Выберите прогноз:"
        ),
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("two_dice_pred:"))
async def two_dice_prediction(callback: CallbackQuery):
    await callback.answer()

    _, stake_text, prediction = callback.data.split(":")

    stake = int(stake_text)

    games[callback.from_user.id] = {
        "type": "two_dice",
        "stake": stake,
        "prediction": prediction
    }

    labels = {
        "high": "больше 7",
        "low": "меньше 7",
        "seven": "ровно 7"
    }

    await edit_or_answer(
        callback,
        (
            "🎲 <b>ДВА КУБИКА</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n"
            f"Выбор: <b>{labels[prediction]}</b>\n\n"
            "Подтвердить?"
        ),
        confirm_bet_keyboard(
            "two_dice_play",
            stake
        )
    )


@dp.callback_query(F.data.startswith("confirm:two_dice_play:"))
async def play_two_dice(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    game = games.get(user_id)

    if not game or game.get("type") != "two_dice":
        await callback.message.answer(
            "❌ Игра устарела."
        )
        return

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    prediction = game["prediction"]

    first = await callback.message.answer_dice(
        emoji="🎲"
    )

    second = await callback.message.answer_dice(
        emoji="🎲"
    )

    value1 = first.dice.value
    value2 = second.dice.value

    await asyncio.sleep(1.5)

    total = value1 + value2

    won = False
    multiplier = 0

    if prediction == "high":
        won = total > 7
        multiplier = 1.8

    elif prediction == "low":
        won = total < 7
        multiplier = 1.8

    elif prediction == "seven":
        won = total == 7
        multiplier = 5

    payout = int(stake * multiplier) if won else 0

    if payout:
        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        text = (
            "🎲 <b>ДВА КУБИКА</b>\n\n"
            f"Выпало: <b>{value1} + {value2} = {total}</b>\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    else:
        new_balance = get_balance(user_id)

        result = "loss"

        text = (
            "🎲 <b>ДВА КУБИКА</b>\n\n"
            f"Выпало: <b>{value1} + {value2} = {total}</b>\n"
            "❌ Вы проиграли.\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    record_game(
        user_id=user_id,
        game="two_dice",
        stake=stake,
        result=result,
        multiplier=multiplier if won else 0,
        payout=payout
    )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# SLOTS
# =========================================================

@dp.callback_query(F.data.startswith("confirm:slots:"))
async def confirm_slots(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        (
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"💰 Баланс: <b>{money(balance)} ₽</b>\n"
            f"🎯 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Нажмите «ИГРАТЬ», чтобы запустить слот."
        ),
        confirm_bet_keyboard(
            "slots_play",
            stake
        )
    )


@dp.callback_query(F.data.startswith("confirm:slots_play:"))
async def play_slots(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    # Telegram itself generates the slot result.
    dice_message = await callback.message.answer_dice(
        emoji="🎰"
    )

    value = dice_message.dice.value

    # Telegram animation needs a moment to finish.
    await asyncio.sleep(2.5)

    symbols = slot_symbols_from_value(value)

    is_jackpot = value == 64

    if is_jackpot:
        multiplier = SLOT_SEVEN_MULTIPLIER
        payout = stake * multiplier

        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        result_text = (
            "🎉 <b>ДЖЕКПОТ!</b>\n\n"
            f"🎰 {' '.join(symbols)}\n\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    elif symbols[0] == symbols[1] == symbols[2]:
        multiplier = 10
        payout = stake * multiplier

        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        result_text = (
            "🎰 <b>ТРИ ОДИНАКОВЫХ!</b>\n\n"
            f"{' '.join(symbols)}\n\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    elif symbols.count("🍋") >= 2:
        multiplier = 2
        payout = stake * multiplier

        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        result_text = (
            "🎰 <b>ДВА ЛИМОНА!</b>\n\n"
            f"{' '.join(symbols)}\n\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    else:
        multiplier = 0
        payout = 0

        new_balance = get_balance(user_id)

        result = "loss"

        result_text = (
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"{' '.join(symbols)}\n\n"
            "❌ Не повезло.\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    record_game(
        user_id=user_id,
        game="slots",
        stake=stake,
        result=result,
        multiplier=multiplier,
        payout=payout
    )

    await callback.message.answer(
        result_text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# BOWLING
# =========================================================

@dp.callback_query(F.data.startswith("confirm:bowling:"))
async def confirm_bowling(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎳 СБИТЬ ВСЕ",
        callback_data=f"bowling_pred:{stake}:six"
    )

    builder.button(
        text="🎳 НЕ ВСЕ",
        callback_data=f"bowling_pred:{stake}:other"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data="games"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Выберите прогноз:"
        ),
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("bowling_pred:"))
async def bowling_prediction(callback: CallbackQuery):
    await callback.answer()

    _, stake_text, prediction = callback.data.split(":")

    stake = int(stake_text)

    games[callback.from_user.id] = {
        "type": "bowling",
        "stake": stake,
        "prediction": prediction
    }

    label = (
        "сбить все кегли"
        if prediction == "six"
        else "не сбить все"
    )

    await edit_or_answer(
        callback,
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n"
            f"Выбор: <b>{label}</b>\n\n"
            "Подтвердить?"
        ),
        confirm_bet_keyboard(
            "bowling_play",
            stake
        )
    )


@dp.callback_query(F.data.startswith("confirm:bowling_play:"))
async def play_bowling(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    game = games.get(user_id)

    if not game or game.get("type") != "bowling":
        await callback.message.answer(
            "❌ Игра устарела."
        )
        return

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    dice_message = await callback.message.answer_dice(
        emoji="🎳"
    )

    value = dice_message.dice.value

    await asyncio.sleep(1.5)

    prediction = game["prediction"]

    won = (
        value == 6
        if prediction == "six"
        else value != 6
    )

    multiplier = 4 if prediction == "six" else 1.5

    payout = int(stake * multiplier) if won else 0

    if payout:
        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        text = (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            f"Результат: <b>{value}</b>\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    else:
        new_balance = get_balance(user_id)

        result = "loss"

        text = (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            f"Результат: <b>{value}</b>\n"
            "❌ Вы проиграли.\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    record_game(
        user_id=user_id,
        game="bowling",
        stake=stake,
        result=result,
        multiplier=multiplier if won else 0,
        payout=payout
    )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# ROULETTE
# =========================================================

@dp.callback_query(F.data.startswith("confirm:roulette:"))
async def confirm_roulette(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔴 КРАСНОЕ",
        callback_data=f"roulette_pred:{stake}:red"
    )

    builder.button(
        text="⚫ ЧЁРНОЕ",
        callback_data=f"roulette_pred:{stake}:black"
    )

    builder.button(
        text="🟢 ЗЕЛЁНОЕ",
        callback_data=f"roulette_pred:{stake}:green"
    )

    builder.button(
        text="❌ ОТМЕНА",
        callback_data="games"
    )

    builder.adjust(2)

    await edit_or_answer(
        callback,
        (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Выберите цвет:"
        ),
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("roulette_pred:"))
async def roulette_prediction(callback: CallbackQuery):
    await callback.answer()

    _, stake_text, prediction = callback.data.split(":")

    stake = int(stake_text)

    games[callback.from_user.id] = {
        "type": "roulette",
        "stake": stake,
        "prediction": prediction
    }

    labels = {
        "red": "🔴 красное",
        "black": "⚫ чёрное",
        "green": "🟢 зелёное"
    }

    await edit_or_answer(
        callback,
        (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n"
            f"Выбор: <b>{labels[prediction]}</b>\n\n"
            "Подтвердить?"
        ),
        confirm_bet_keyboard(
            "roulette_play",
            stake
        )
    )


@dp.callback_query(F.data.startswith("confirm:roulette_play:"))
async def play_roulette(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    game = games.get(user_id)

    if not game or game.get("type") != "roulette":
        await callback.message.answer(
            "❌ Игра устарела."
        )
        return

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    animation_values = [
        "🎯 8",
        "🎯 17",
        "🎯 32",
        "🎯 5",
        "🎯 21",
        "🎯 14",
        "🎯 29",
        "🎯 10",
    ]

    animation_message = await callback.message.answer(
        animation_values[0]
    )

    for value in animation_values[1:]:
        await asyncio.sleep(0.18)

        try:
            await animation_message.edit_text(value)
        except Exception:
            pass

    number = random.randint(0, 36)

    if number == 0:
        color = "green"
        color_text = "🟢 ЗЕЛЁНОЕ"
    elif number in {
        1, 3, 5, 7, 9, 12, 14, 16, 18,
        19, 21, 23, 25, 27, 30, 32, 34, 36
    }:
        color = "red"
        color_text = "🔴 КРАСНОЕ"
    else:
        color = "black"
        color_text = "⚫ ЧЁРНОЕ"

    prediction = game["prediction"]

    if prediction == color:
        multiplier = 14 if color == "green" else 2
        payout = stake * multiplier
        won = True
    else:
        multiplier = 0
        payout = 0
        won = False

    if payout:
        new_balance = change_balance(
            user_id,
            payout
        )

        result = "win"

        text = (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            f"Выпало: <b>{number}</b>\n"
            f"{color_text}\n\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    else:
        new_balance = get_balance(user_id)

        result = "loss"

        text = (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            f"Выпало: <b>{number}</b>\n"
            f"{color_text}\n\n"
            "❌ Вы проиграли.\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        )

    record_game(
        user_id=user_id,
        game="roulette",
        stake=stake,
        result=result,
        multiplier=multiplier,
        payout=payout
    )

    games.pop(user_id, None)

    await animation_message.edit_text(
        text
    )

    await callback.message.answer(
        "Выберите действие:",
        reply_markup=after_game_keyboard()
    )


# =========================================================
# MINES
# =========================================================

@dp.callback_query(F.data.startswith("confirm:mines:"))
async def confirm_mines(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    if get_balance(user_id) < stake:
        await edit_or_answer(
            callback,
            "❌ Недостаточно средств.",
            wallet_keyboard()
        )
        return

    await edit_or_answer(
        callback,
        (
            "💣 <b>MINES</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n\n"
            "На поле 9 клеток.\n"
            "2 из них — мины.\n\n"
            "Подтвердить ставку?"
        ),
        confirm_bet_keyboard(
            "mines_play",
            stake
        )
    )


@dp.callback_query(F.data.startswith("confirm:mines_play:"))
async def play_mines(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    mines = set(
        random.sample(
            range(9),
            2
        )
    )

    games[user_id] = {
        "type": "mines",
        "stake": stake,
        "mines": mines,
        "opened": set(),
        "multiplier": 1.0
    }

    await show_mines_board(
        callback.message,
        user_id
    )


async def show_mines_board(
    message: Message,
    user_id: int
):
    game = games.get(user_id)

    if not game:
        return

    builder = InlineKeyboardBuilder()

    for index in range(9):
        if index in game["opened"]:
            builder.button(
                text="💎",
                callback_data="mines_disabled"
            )
        else:
            builder.button(
                text="⬜",
                callback_data=f"mine:{index}"
            )

    builder.button(
        text="💰 ЗАБРАТЬ",
        callback_data="mines_cashout"
    )

    builder.button(
        text="❌ ЗАКОНЧИТЬ",
        callback_data="mines_finish"
    )

    builder.adjust(3)

    await message.answer(
        (
            "💣 <b>MINES</b>\n\n"
            f"Ставка: <b>{money(game['stake'])} ₽</b>\n"
            f"Множитель: <b>x{game['multiplier']:.2f}</b>\n\n"
            "Откройте клетку:"
        ),
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "mines_disabled")
async def mines_disabled(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("mine:"))
async def mine_click(callback: CallbackQuery):
    user_id = safe_user_id(callback.from_user.id)

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "Игра закончена."
        )
        return

    index = int(
        callback.data.split(":")[1]
    )

    if index in game["opened"]:
        await callback.answer()
        return

    if index in game["mines"]:
        game["opened"].add(index)

        await callback.answer(
            "💣 МИНА!"
        )

        record_game(
            user_id=user_id,
            game="mines",
            stake=game["stake"],
            result="loss",
            multiplier=0,
            payout=0
        )

        games.pop(user_id, None)

        await callback.message.answer(
            (
                "💣 <b>МИНА!</b>\n\n"
                f"Вы проиграли <b>{money(game['stake'])} ₽</b>.\n\n"
                f"💰 Баланс: <b>{money(get_balance(user_id))} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )

        return

    game["opened"].add(index)

    game["multiplier"] += 0.35

    await callback.answer(
        "💎 Безопасно!"
    )

    builder = InlineKeyboardBuilder()

    for cell in range(9):
        if cell in game["opened"]:
            builder.button(
                text="💎",
                callback_data="mines_disabled"
            )
        else:
            builder.button(
                text="⬜",
                callback_data=f"mine:{cell}"
            )

    builder.button(
        text="💰 ЗАБРАТЬ",
        callback_data="mines_cashout"
    )

    builder.button(
        text="❌ ЗАКОНЧИТЬ",
        callback_data="mines_finish"
    )

    builder.adjust(3)

    await callback.message.edit_reply_markup(
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.message.answer(
            "❌ Игра закончена."
        )
        return

    payout = int(
        game["stake"] * game["multiplier"]
    )

    new_balance = change_balance(
        user_id,
        payout
    )

    record_game(
        user_id=user_id,
        game="mines",
        stake=game["stake"],
        result="win",
        multiplier=game["multiplier"],
        payout=payout
    )

    games.pop(user_id, None)

    await callback.message.answer(
        (
            "💣 <b>MINES</b>\n\n"
            f"Множитель: <b>x{game['multiplier']:.2f}</b>\n"
            f"🏆 Вы забрали: <b>{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


@dp.callback_query(F.data == "mines_finish")
async def mines_finish(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    game = games.pop(user_id, None)

    if not game:
        await callback.message.answer(
            "❌ Игра закончена."
        )
        return

    await callback.message.answer(
        (
            "💣 <b>MINES</b>\n\n"
            "Игра завершена.\n"
            "Вы не забрали выигрыш.\n\n"
            f"💰 Баланс: <b>{money(get_balance(user_id))} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# CRASH
# =========================================================

@dp.callback_query(F.data.startswith("confirm:crash:"))
async def confirm_crash(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        (
            "💥 <b>CRASH</b>\n\n"
            f"Баланс: <b>{money(balance)} ₽</b>\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Множитель начинает расти.\n"
            "Заберите выигрыш до краша.\n\n"
            "Подтвердить?"
        ),
        confirm_bet_keyboard(
            "crash_play",
            stake
        )
    )


@dp.callback_query(F.data.startswith("confirm:crash_play:"))
async def play_crash(callback: CallbackQuery):
    await callback.answer()

    _, _, stake_text = callback.data.split(":")

    stake = int(stake_text)

    user_id = safe_user_id(callback.from_user.id)

    if not subtract_balance(user_id, stake):
        await callback.message.answer(
            "❌ Недостаточно средств."
        )
        return

    crash_point = round(
        random.uniform(
            CRASH_MIN,
            CRASH_MAX
        ),
        2
    )

    current = 1.00

    message = await callback.message.answer(
        (
            "💥 <b>CRASH</b>\n\n"
            f"📈 <b>x{current:.2f}</b>\n\n"
            f"Ставка: <b>{money(stake)} ₽</b>"
        )
    )

    while current < crash_point:
        await asyncio.sleep(0.65)

        current = round(
            current + 0.08 + current * 0.05,
            2
        )

        if current >= crash_point:
            break

        try:
            await message.edit_text(
                (
                    "💥 <b>CRASH</b>\n\n"
                    f"📈 <b>x{current:.2f}</b>\n\n"
                    f"Ставка: <b>{money(stake)} ₽</b>"
                )
            )
        except Exception:
            pass

    await asyncio.sleep(0.2)

    games[user_id] = {
        "type": "crash",
        "stake": stake,
        "current": crash_point
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"💰 ЗАБРАТЬ x{crash_point:.2f}",
        callback_data="crash_cashout"
    )

    builder.button(
        text="💥 ПРОДОЛЖИТЬ",
        callback_data="crash_continue"
    )

    builder.adjust(1)

    await message.edit_text(
        (
            "💥 <b>CRASH</b>\n\n"
            f"📈 <b>x{crash_point:.2f}</b>\n\n"
            "Выберите действие:"
        ),
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    game = games.pop(user_id, None)

    if not game:
        await callback.message.answer(
            "❌ Игра закончена."
        )
        return

    multiplier = game["current"]

    payout = int(
        game["stake"] * multiplier
    )

    new_balance = change_balance(
        user_id,
        payout
    )

    record_game(
        user_id=user_id,
        game="crash",
        stake=game["stake"],
        result="win",
        multiplier=multiplier,
        payout=payout
    )

    await callback.message.answer(
        (
            "💥 <b>CRASH</b>\n\n"
            f"Вы забрали на <b>x{multiplier:.2f}</b>\n"
            f"🏆 Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
            f"💰 Баланс: <b>{money(new_balance)} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


@dp.callback_query(F.data == "crash_continue")
async def crash_continue(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    game = games.pop(user_id, None)

    if not game:
        await callback.message.answer(
            "❌ Игра закончена."
        )
        return

    record_game(
        user_id=user_id,
        game="crash",
        stake=game["stake"],
        result="loss",
        multiplier=0,
        payout=0
    )

    await callback.message.answer(
        (
            "💥 <b>CRASH!</b>\n\n"
            "Раунд завершён.\n"
            "Ставка потеряна.\n\n"
            f"💰 Баланс: <b>{money(get_balance(user_id))} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# PROFILE HISTORY
# =========================================================

@dp.callback_query(F.data == "profile_history")
async def profile_history(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    history = get_game_history(
        user_id,
        10
    )

    if not history:
        text = (
            "📜 <b>ИСТОРИЯ ИГР</b>\n\n"
            "История пока пустая."
        )

    else:
        lines = [
            "📜 <b>ИСТОРИЯ ИГР</b>\n"
        ]

        for item in history:
            emoji = {
                "dice": "🎲",
                "two_dice": "🎲",
                "slots": "🎰",
                "bowling": "🎳",
                "roulette": "🎯",
                "mines": "💣",
                "crash": "💥",
            }.get(
                item["game"],
                "🎮"
            )

            result_emoji = (
                "✅"
                if item["result"] == "win"
                else "❌"
            )

            lines.append(
                (
                    f"{emoji} {result_emoji} "
                    f"{money(item['stake'])} ₽"
                    f" → "
                    f"{money(item['payout'])} ₽"
                )
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="profile"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# PAYMENT HISTORY
# =========================================================

@dp.callback_query(F.data == "payment_history")
async def payment_history(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    history = get_payment_history(
        user_id,
        20
    )

    if not history:
        text = (
            "💳 <b>ИСТОРИЯ ПЛАТЕЖЕЙ</b>\n\n"
            "Платежей пока нет."
        )

    else:
        lines = [
            "💳 <b>ИСТОРИЯ ПЛАТЕЖЕЙ</b>\n"
        ]

        for item in history:
            lines.append(
                (
                    f"🧾 #{item['invoice_id']}\n"
                    f"💵 {item['amount_usdt']} USDT"
                    f" → "
                    f"{money(item['amount_rub'])} ₽\n"
                    f"📌 {item['status']}\n"
                )
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="profile"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# DEPOSIT
# =========================================================

@dp.callback_query(F.data == "deposit")
async def deposit_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "💳 <b>ПОПОЛНЕНИЕ</b>\n\n"
            "Выберите сумму:"
        ),
        deposit_keyboard()
    )


@dp.callback_query(F.data.startswith("deposit_amount:"))
async def deposit_amount(callback: CallbackQuery):
    await callback.answer()

    amount = float(
        callback.data.split(":")[1]
    )

    user_id = safe_user_id(callback.from_user.id)

    try:
        invoice = await create_invoice(
            user_id=user_id,
            amount_usdt=amount
        )

    except Exception as error:
        print(
            "CREATE INVOICE ERROR:",
            repr(error)
        )

        await callback.message.answer(
            (
                "❌ Не удалось создать счёт.\n\n"
                "Попробуйте ещё раз позже."
            )
        )

        return

    pay_url = invoice.get("pay_url")

    builder = InlineKeyboardBuilder()

    if pay_url:
        builder.button(
            text="💳 ОПЛАТИТЬ",
            url=pay_url
        )

    builder.button(
        text="🔄 ПРОВЕРИТЬ ОПЛАТУ",
        callback_data=f"check_payment:{invoice['invoice_id']}"
    )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="wallet"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        (
            "💳 <b>СЧЁТ СОЗДАН</b>\n\n"
            f"Сумма: <b>{amount:g} USDT</b>\n"
            f"Начисление: <b>{money(int(amount * 80))} ₽</b>\n\n"
            "Оплатите счёт и затем нажмите "
            "«ПРОВЕРИТЬ ОПЛАТУ»."
        ),
        builder.as_markup()
    )


# =========================================================
# CHECK PAYMENT
# =========================================================

@dp.callback_query(F.data.startswith("check_payment:"))
async def check_payment(callback: CallbackQuery):
    await callback.answer()

    invoice_id = int(
        callback.data.split(":")[1]
    )

    try:
        result = await process_paid_invoice(
            invoice_id
        )

    except Exception as error:
        print(
            "CHECK PAYMENT ERROR:",
            repr(error)
        )

        await callback.message.answer(
            "❌ Ошибка проверки платежа."
        )

        return

    if result is None:
        invoice = await get_invoice(
            invoice_id
        )

        status = (
            invoice.get("status")
            if invoice
            else "unknown"
        )

        if status == "paid":
            await callback.message.answer(
                "ℹ️ Этот платёж уже был обработан."
            )
        else:
            await callback.message.answer(
                (
                    "⏳ Платёж пока не подтверждён.\n\n"
                    f"Статус: <b>{status}</b>"
                )
            )

        return

    await callback.message.answer(
        (
            "✅ <b>ОПЛАТА ПОЛУЧЕНА!</b>\n\n"
            f"💵 Получено: <b>{result['amount_usdt']} USDT</b>\n"
            f"💰 Начислено: <b>+{money(result['amount_rub'])} ₽</b>\n\n"
            f"Ваш баланс: <b>{money(result['balance'])} ₽</b>"
        ),
        reply_markup=wallet_keyboard()
    )


# =========================================================
# ADMIN
# =========================================================

@dp.callback_query(F.data == "admin")
async def admin_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤 НАЙТИ ПОЛЬЗОВАТЕЛЯ",
        callback_data="admin_find"
    )

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="main"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        "🛠 <b>ADMIN PANEL</b>\n\nВыберите действие:",
        builder.as_markup()
    )


@dp.callback_query(F.data == "admin_find")
async def admin_find(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        return

    games[user_id] = {
        "type": "admin_find"
    }

    await edit_or_answer(
        callback,
        (
            "👤 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
            "Отправьте ID пользователя отдельным сообщением."
        )
    )


@dp.message()
async def admin_text_handler(message: Message):
    user_id = safe_user_id(message.from_user.id)

    state = games.get(user_id)

    if not state:
        return

    if state.get("type") != "admin_find":
        return

    if not is_admin(user_id):
        return

    text = message.text.strip()

    if not text.isdigit():
        await message.answer(
            "❌ ID должен содержать только цифры."
        )
        return

    target_id = int(text)

    games[user_id] = {
        "type": "admin_user",
        "target_id": target_id
    }

    balance = get_balance(target_id)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰 ВЫДАТЬ БАЛАНС",
        callback_data="admin_give"
    )

    builder.button(
        text="➖ СНЯТЬ С БАЛАНСА",
        callback_data="admin_take"
    )

    builder.button(
        text="📊 ОБНОВИТЬ",
        callback_data="admin_refresh"
    )

    builder.button(
        text="📜 ИСТОРИЯ ИГР",
        callback_data="admin_game_history"
    )

    builder.button(
        text="💳 ИСТОРИЯ ПЛАТЕЖЕЙ",
        callback_data="admin_payment_history"
    )

    builder.button(
        text="🛠 ADMIN PANEL",
        callback_data="admin"
    )

    builder.adjust(1)

    await message.answer(
        (
            "👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
            f"ID: <code>{target_id}</code>\n"
            f"💰 Баланс: <b>{money(balance)} ₽</b>"
        ),
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "admin_refresh")
async def admin_refresh(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        return

    state = games.get(user_id)

    if not state or state.get("type") != "admin_user":
        await callback.message.answer(
            "❌ Пользователь не выбран."
        )
        return

    target_id = state["target_id"]

    balance = get_balance(target_id)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰 ВЫДАТЬ БАЛАНС",
        callback_data="admin_give"
    )

    builder.button(
        text="➖ СНЯТЬ С БАЛАНСА",
        callback_data="admin_take"
    )

    builder.button(
        text="📊 ОБНОВИТЬ",
        callback_data="admin_refresh"
    )

    builder.button(
        text="📜 ИСТОРИЯ ИГР",
        callback_data="admin_game_history"
    )

    builder.button(
        text="💳 ИСТОРИЯ ПЛАТЕЖЕЙ",
        callback_data="admin_payment_history"
    )

    builder.button(
        text="🛠 ADMIN PANEL",
        callback_data="admin"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        (
            "👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
            f"ID: <code>{target_id}</code>\n"
            f"💰 Баланс: <b>{money(balance)} ₽</b>"
        ),
        builder.as_markup()
    )


@dp.callback_query(F.data == "admin_give")
async def admin_give(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        return

    state = games.get(user_id)

    if not state or state.get("type") != "admin_user":
        return

    games[user_id]["type"] = "admin_amount"
    games[user_id]["action"] = "give"

    await callback.message.answer(
        "💰 Отправьте сумму, которую нужно выдать:"
    )


@dp.callback_query(F.data == "admin_take")
async def admin_take(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        return

    state = games.get(user_id)

    if not state or state.get("type") != "admin_user":
        return

    games[user_id]["type"] = "admin_amount"
    games[user_id]["action"] = "take"

    await callback.message.answer(
        "➖ Отправьте сумму, которую нужно снять:"
    )


@dp.message()
async def admin_amount_handler(message: Message):
    user_id = safe_user_id(message.from_user.id)

    state = games.get(user_id)

    if not state:
        return

    if state.get("type") != "admin_amount":
        return

    if not is_admin(user_id):
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text.isdigit():
        await message.answer(
            "❌ Введите целое число."
        )
        return

    amount = int(text)

    if amount <= 0:
        await message.answer(
            "❌ Сумма должна быть больше нуля."
        )
        return

    target_id = state["target_id"]
    action = state["action"]

    if action == "give":
        new_balance = change_balance(
            target_id,
            amount
        )

        await message.answer(
            (
                "✅ <b>БАЛАНС ВЫДАН</b>\n\n"
                f"Пользователь: <code>{target_id}</code>\n"
                f"Сумма: <b>+{money(amount)} ₽</b>\n"
                f"Новый баланс: <b>{money(new_balance)} ₽</b>"
            )
        )

    else:
        success = subtract_balance(
            target_id,
            amount
        )

        if success:
            new_balance = get_balance(
                target_id
            )

            await message.answer(
                (
                    "✅ <b>БАЛАНС СНЯТ</b>\n\n"
                    f"Пользователь: <code>{target_id}</code>\n"
                    f"Сумма: <b>-{money(amount)} ₽</b>\n"
                    f"Новый баланс: <b>{money(new_balance)} ₽</b>"
                )
            )

        else:
            await message.answer(
                "❌ Недостаточно средств у пользователя."
            )

    games[user_id] = {
        "type": "admin_user",
        "target_id": target_id
    }


@dp.callback_query(F.data == "admin_game_history")
async def admin_game_history(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        return

    state = games.get(user_id)

    if not state or state.get("type") != "admin_user":
        return

    target_id = state["target_id"]

    history = get_game_history(
        target_id,
        20
    )

    if not history:
        text = (
            "📜 <b>ИСТОРИЯ ИГР</b>\n\n"
            "История пуста."
        )

    else:
        lines = [
            "📜 <b>ИСТОРИЯ ИГР</b>\n"
        ]

        for item in history:
            lines.append(
                (
                    f"🎮 {item['game']} | "
                    f"{money(item['stake'])} ₽ | "
                    f"{item['result']} | "
                    f"{money(item['payout'])} ₽"
                )
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="admin_refresh"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


@dp.callback_query(F.data == "admin_payment_history")
async def admin_payment_history(callback: CallbackQuery):
    await callback.answer()

    user_id = safe_user_id(callback.from_user.id)

    if not is_admin(user_id):
        return

    state = games.get(user_id)

    if not state or state.get("type") != "admin_user":
        return

    target_id = state["target_id"]

    history = get_payment_history(
        target_id,
        20
    )

    if not history:
        text = (
            "💳 <b>ИСТОРИЯ ПЛАТЕЖЕЙ</b>\n\n"
            "Платежей нет."
        )

    else:
        lines = [
            "💳 <b>ИСТОРИЯ ПЛАТЕЖЕЙ</b>\n"
        ]

        for item in history:
            lines.append(
                (
                    f"🧾 #{item['invoice_id']} | "
                    f"{item['amount_usdt']} USDT | "
                    f"{money(item['amount_rub'])} ₽ | "
                    f"{item['status']}"
                )
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ НАЗАД",
        callback_data="admin_refresh"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# UNKNOWN CALLBACKS
# =========================================================

@dp.callback_query()
async def unknown_callback(callback: CallbackQuery):
    await callback.answer()


# =========================================================
# WEBHOOK
# =========================================================

@app.on_event("startup")
async def startup():
    init_db()

    try:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=False
        )

        print(
            "WEBHOOK SET:",
            WEBHOOK_URL
        )

        info = await bot.get_webhook_info()

        print(
            "TELEGRAM WEBHOOK URL:",
            info.url
        )

        print(
            "TELEGRAM PENDING UPDATES:",
            info.pending_update_count
        )

        if info.url != WEBHOOK_URL:
            print(
                "WARNING: TELEGRAM WEBHOOK URL DOES NOT MATCH!"
            )

    except Exception as error:
        print(
            "WEBHOOK ERROR:",
            repr(error)
        )


@app.on_event("shutdown")
async def shutdown():
    try:
        await bot.session.close()
    except Exception as error:
        print(
            "BOT SESSION CLOSE ERROR:",
            repr(error)
        )


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:
        return JSONResponse(
            {
                "ok": False,
                "error": "invalid secret"
            },
            status_code=403
        )

    try:
        data = await request.json()

        update = Update.model_validate(
            data,
            context={"bot": bot}
        )

        print(
            "TELEGRAM UPDATE:",
            update.update_id
        )

        if update.callback_query:
            print(
                "CALLBACK:",
                update.callback_query.data
            )

        await dp.feed_update(
            bot,
            update
        )

        return JSONResponse(
            {"ok": True}
        )

    except Exception as error:
        print(
            "WEBHOOK UPDATE ERROR:",
            repr(error)
        )

        return JSONResponse(
            {
                "ok": False,
                "error": str(error)
            },
            status_code=500
        )


@app.get("/")
async def health():
    return {
        "ok": True,
        "service": "emoji-casino-bot"
    }
