import asyncio
import os
import random

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

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

BASE_URL = "https://emoji-casino-bot.onrender.com"

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

STAKE = 100


# =========================================================
# СЛОТЫ
# =========================================================

SLOT_TWO_MULTIPLIER = 1.85
SLOT_OTHER_THREE_MULTIPLIER = 3.5
SLOT_COCKTAIL_MULTIPLIER = 5
SLOT_GRAPES_MULTIPLIER = 8
SLOT_LEMON_MULTIPLIER = 10
SLOT_SEVEN_MULTIPLIER = 50


# =========================================================
# МИНЫ
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

CRASH_MIN = 1.10
CRASH_MAX = 20.00


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
# АКТИВНЫЕ ИГРЫ
# =========================================================

games = {}


# =========================================================
# ГЛАВНОЕ МЕНЮ
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


def main_menu_text(balance):
    balance_text = f"{balance:,}".replace(",", " ")

    return (
        f"🎰 <b>RESONANT CASINO</b>\n\n"
        f"✦ Добро пожаловать ✦\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{balance_text} ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>ВЫБЕРИ РАЗДЕЛ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 6 игр  •  ⚡ Resonant"
    )


# =========================================================
# МЕНЮ ИГР
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


def mini_games_text(balance):
    balance_text = f"{balance:,}".replace(",", " ")

    return (
        f"🎰 <b>МИНИ-ИГРЫ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{balance_text} ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>ВЫБЕРИ ИГРУ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ 6 игр  •  Ставка от 100 ₽"
    )


# =========================================================
# ПОСЛЕ ИГРЫ
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

@dp.message(F.text == "/start")
async def start_handler(message: Message):
    user_id = message.from_user.id

    balance = get_balance(user_id)

    await message.answer(
        main_menu_text(balance),
        reply_markup=main_menu()
    )


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Любая активная игра полностью закрывается
    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        main_menu_text(balance),
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# МИНИ-ИГРЫ
# =========================================================

@dp.callback_query(F.data == "mini_games")
async def mini_games_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # ВАЖНО:
    # выход из игры полностью очищает её состояние
    if user_id in games:
        del games[user_id]

    balance = get_balance(user_id)

    await callback.message.edit_text(
        mini_games_text(balance),
        reply_markup=mini_games_menu()
    )

    await callback.answer()


# =========================================================
# ПРОФИЛЬ
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"👤 <b>ПРОФИЛЬ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Баланс: <b>{balance_text} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# 🎲 КУБИКИ
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
async def dice_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"🎲 <b>КУБИКИ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{balance_text} ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ВЫБЕРИ РЕЖИМ</b>\n\n"
        f"🎲 <b>1 КУБИК</b>\n"
        f"Угадай результат\n"
        f"⬇️ Меньше 3  •  ⬆️ Больше 3\n"
        f"💎 Выигрыш: x1.85\n\n"
        f"🎲🎲 <b>2 КУБИКА</b>\n"
        f"Угадай сумму\n"
        f"🎯 Равно 7  •  ⬇️ Меньше 7  •  ⬆️ Больше 7\n"
        f"💎 Выигрыш: до x5.00\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=dice_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_one")
async def dice_one_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_one"
    }

    await callback.message.edit_text(
        f"🎲 <b>1 КУБИК</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⬇️ МЕНЬШЕ 3 • x1.85\n"
        f"⬆️ БОЛЬШЕ 3 • x1.85\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎲 Бросаем кубик...",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


@dp.callback_query(F.data == "dice_two")
async def dice_two_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_two",
        "rolls": []
    }

    await callback.message.edit_text(
        f"🎲🎲 <b>2 КУБИКА</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Цель: сумма двух кубиков\n\n"
        f"🎯 Равно 7 • x5.00\n"
        f"⬇️ Меньше 7 • x1.85\n"
        f"⬆️ Больше 7 • x1.85\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎲 Первый бросок...",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎲"
    )

    await callback.answer()


# =========================================================
# 🎰 СЛОТЫ
# =========================================================

def slots_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎰  КРУТИТЬ • 100 ₽",
        callback_data="slots_spin"
    )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


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


@dp.callback_query(F.data == "slots")
async def slots_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"🎰 <b>СЛОТЫ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{balance_text} ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ТАБЛИЦА ВЫИГРЫШЕЙ</b>\n\n"
        f"🍸🍸  x1.85\n"
        f"🍸🍸🍸  x5\n"
        f"🍇🍇🍇  x8\n"
        f"🍋🍋🍋  x10\n"
        f"7️⃣7️⃣7️⃣  x50\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Два одинаковых символа: <b>x1.85</b>\n"
        f"✨ Другие три одинаковых: <b>x3.5</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=slots_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "slots_spin")
async def slots_spin_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    dice_message = await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎰"
    )

    await asyncio.sleep(2)

    value = dice_message.dice.value

    result, multiplier = slot_result(value)

    result_text = " ".join(result)

    if multiplier > 0:

        winnings = int(
            STAKE * multiplier
        )

        change_balance(
            user_id,
            winnings
        )

        balance = get_balance(user_id)
        balance_text = f"{balance:,}".replace(",", " ")

        await callback.message.edit_text(
            f"🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"┌──────────────┐\n"
            f"│  {result_text}  │\n"
            f"└──────────────┘\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n"
            f"📈 Множитель: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{winnings} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance_text} ₽</b>",
            reply_markup=after_game_menu()
        )

    else:

        balance = get_balance(user_id)
        balance_text = f"{balance:,}".replace(",", " ")

        await callback.message.edit_text(
            f"🎰 <b>РЕЗУЛЬТАТ</b>\n\n"
            f"┌──────────────┐\n"
            f"│  {result_text}  │\n"
            f"└──────────────┘\n\n"
            f"💥 <b>НЕПОВЕЗЛО</b>\n"
            f"💸 Потеряно: <b>{STAKE} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance_text} ₽</b>",
            reply_markup=after_game_menu()
        )

    await callback.answer()


# =========================================================
# 🎡 РУЛЕТКА
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
        text="🔴 КРАСНОЕ • x1.95",
        callback_data="roulette_red"
    )

    builder.button(
        text="⚫ ЧЁРНОЕ • x1.95",
        callback_data="roulette_black"
    )

    builder.button(
        text="1️⃣ 1–18 • x1.95",
        callback_data="roulette_low"
    )

    builder.button(
        text="2️⃣ 19–36 • x1.95",
        callback_data="roulette_high"
    )

    builder.button(
        text="⚪ ЧЁТ • x1.95",
        callback_data="roulette_even"
    )

    builder.button(
        text="⚪ НЕЧЁТ • x1.95",
        callback_data="roulette_odd"
    )

    builder.button(
        text="🟢 ZERO • x36",
        callback_data="roulette_zero"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "roulette")
async def roulette_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"🎡 <b>РУЛЕТКА</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{balance_text} ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>СТАВКИ</b>\n\n"
        f"🔴 Красное  x1.95\n"
        f"⚫ Чёрное  x1.95\n"
        f"1–18  x1.95\n"
        f"19–36  x1.95\n"
        f"Чёт  x1.95\n"
        f"Нечёт  x1.95\n"
        f"🟢 Zero  x36\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>",
        reply_markup=roulette_menu()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("roulette_"))
async def roulette_bet_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    bet = callback.data.replace(
        "roulette_",
        ""
    )

    if not subtract_balance(user_id, STAKE):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    number = random.randint(0, 36)

    if number == 0:
        color = "🟢"
        color_name = "ZERO"

    elif number in RED_NUMBERS:
        color = "🔴"
        color_name = "КРАСНОЕ"

    else:
        color = "⚫"
        color_name = "ЧЁРНОЕ"

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
        won = (
            number != 0
            and number % 2 == 0
        )

    elif bet == "odd":
        won = number % 2 == 1

    if won:

        winnings = int(
            STAKE * multiplier
        )

        change_balance(
            user_id,
            winnings
        )

        balance = get_balance(user_id)
        balance_text = f"{balance:,}".replace(",", " ")

        await callback.message.edit_text(
            f"🎡 <b>РУЛЕТКА</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Выпало: <b>{color} {number}</b>\n"
            f"🎨 {color_name}\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n"
            f"📈 Множитель: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{winnings} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance_text} ₽</b>",
            reply_markup=after_game_menu()
        )

    else:

        balance = get_balance(user_id)
        balance_text = f"{balance:,}".replace(",", " ")

        await callback.message.edit_text(
            f"🎡 <b>РУЛЕТКА</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Выпало: <b>{color} {number}</b>\n"
            f"🎨 {color_name}\n\n"
            f"💥 <b>ПРОИГРЫШ</b>\n"
            f"💸 Потеряно: <b>{STAKE} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance_text} ₽</b>",
            reply_markup=after_game_menu()
        )

    await callback.answer()


# =========================================================
# 🎳 БОУЛИНГ
# =========================================================

def bowling_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬆️ БОЛЬШЕ 3 • x1.85",
        callback_data="bowling_more"
    )

    builder.button(
        text="⬇️ МЕНЬШЕ 3 • x1.85",
        callback_data="bowling_less"
    )

    builder.button(
        text="📂 НАЗАД",
        callback_data="mini_games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "bowling")
async def bowling_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"🎳 <b>БОУЛИНГ</b>\n\n"
        f"💰 <b>БАЛАНС</b>\n"
        f"{balance_text} ₽\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ВЫБЕРИ СТАВКУ</b>\n\n"
        f"⬆️ Больше 3\n"
        f"Результат: 4, 5 или 6\n"
        f"💎 x1.85\n\n"
        f"⬇️ Меньше 3\n"
        f"Результат: 1 или 2\n"
        f"💎 x1.85\n\n"
        f"⚠️ Результат 3 — проигрыш\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
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
async def bowling_bet_callback(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    bet = (
        "more"
        if callback.data == "bowling_more"
        else "less"
    )

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "bowling",
        "bet": bet
    }

    await callback.message.edit_text(
        f"🎳 <b>БОУЛИНГ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Твоя ставка:\n"
        f"<b>"
        f"{'⬆️ БОЛЬШЕ 3' if bet == 'more' else '⬇️ МЕНЬШЕ 3'}"
        f"</b>\n\n"
        f"🎳 Бросаем...",
        reply_markup=InlineKeyboardBuilder().as_markup()
    )

    await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji="🎳"
    )

    await callback.answer()


# =========================================================
# 💣 MINES — 3 x 3
# =========================================================

def mines_keyboard(
    opened,
    hit_mine=None,
    finished=False
):
    builder = InlineKeyboardBuilder()

    # =====================================================
    # ПОЛЕ
    # РОВНО 9 КНОПОК
    # 3 КНОПКИ × 3 РЯДА
    # =====================================================

    for position in range(9):

        # Открытая безопасная клетка
        if position in opened:
            text = "💎"

        # Только та мина, на которую нажали
        elif (
            finished
            and hit_mine is not None
            and position == hit_mine
        ):
            text = "💣"

        # Закрытая клетка
        else:
            text = "▫️"

        builder.button(
            text=text,
            callback_data=f"mine_{position}"
        )

    # КРИТИЧНО:
    # первые 9 кнопок формируют ТОЛЬКО 3x3
    builder.adjust(
        3,
        3,
        3
    )

    # =====================================================
    # КНОПКИ НИЖЕ ПОЛЯ
    # =====================================================

    if not finished:

        builder.button(
            text="💰  ЗАБРАТЬ ВЫИГРЫШ",
            callback_data="mines_cashout"
        )

        builder.adjust(
            3,
            3,
            3,
            1
        )

    builder.button(
        text="📂  НАЗАД",
        callback_data="mini_games"
    )

    if not finished:

        builder.adjust(
            3,
            3,
            3,
            1,
            1
        )

    else:

        builder.adjust(
            3,
            3,
            3,
            1
        )

    return builder.as_markup()


@dp.callback_query(F.data == "mines")
async def mines_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем баланс ДО начала игры
    balance = get_balance(user_id)

    if balance < STAKE:
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    # Если каким-то образом осталась старая игра —
    # очищаем её
    if user_id in games:
        del games[user_id]

    # Списываем ставку
    subtract_balance(
        user_id,
        STAKE
    )

    # Создаём 3 мины
    mine_positions = set(
        random.sample(
            range(9),
            MINES_COUNT
        )
    )

    games[user_id] = {
        "type": "mines",
        "mines": mine_positions,
        "opened": set()
    }

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n"
        f"💳 Баланс: <b>{balance_text} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>ОТКРЫВАЙ КЛЕТКИ</b>\n\n"
        f"▫️ Закрытая клетка\n"
        f"💎 Безопасная клетка\n"
        f"💣 Мина\n\n"
        f"📦 Открыто: <b>0 / 6</b>\n"
        f"📈 Множитель: <b>x1.00</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Открой безопасную клетку, чтобы начать.",
        reply_markup=mines_keyboard(
            set()
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("mine_"))
async def mines_cell_callback(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    # Нет активной игры
    if user_id not in games:
        await callback.answer(
            "Сначала начни новую игру.",
            show_alert=True
        )
        return

    game = games[user_id]

    if game.get("type") != "mines":
        await callback.answer(
            "Сейчас запущена другая игра.",
            show_alert=True
        )
        return

    position = int(
        callback.data.replace(
            "mine_",
            ""
        )
    )

    opened = game["opened"]

    # Уже открытая клетка
    if position in opened:
        await callback.answer(
            "Эта клетка уже открыта."
        )
        return

    # =====================================================
    # МИНА
    # =====================================================

    if position in game["mines"]:

        opened_copy = opened.copy()

        # Игра закончена
        del games[user_id]

        balance = get_balance(user_id)
        balance_text = f"{balance:,}".replace(",", " ")

        await callback.message.edit_text(
            f"💣 <b>МИНЫ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💥 <b>МИНА!</b>\n\n"
            f"Эта клетка оказалась заминирована.\n\n"
            f"💸 Потеряно: <b>{STAKE} ₽</b>\n"
            f"📦 Безопасных клеток: "
            f"<b>{len(opened_copy)} / 6</b>\n"
            f"💳 Баланс: <b>{balance_text} ₽</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💣 <b>ИГРА ОКОНЧЕНА</b>",
            reply_markup=mines_keyboard(
                opened=opened_copy,
                hit_mine=position,
                finished=True
            )
        )

        await callback.answer(
            "💣 Мина!"
        )

        return

    # =====================================================
    # БЕЗОПАСНО
    # =====================================================

    opened.add(position)

    opened_count = len(opened)

    # =====================================================
    # ОТКРЫТЫ ВСЕ 6 БЕЗОПАСНЫХ
    # =====================================================

    if opened_count == 6:

        multiplier = MINES_MULTIPLIERS[6]

        winnings = int(
            STAKE * multiplier
        )

        change_balance(
            user_id,
            winnings
        )

        balance = get_balance(user_id)
        balance_text = f"{balance:,}".replace(",", " ")

        del games[user_id]

        await callback.message.edit_text(
            f"💣 <b>МИНЫ</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 <b>ВСЕ КЛЕТКИ ОТКРЫТЫ!</b>\n\n"
            f"💎 Безопасных клеток: <b>6 / 6</b>\n"
            f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
            f"💰 Выигрыш: <b>+{winnings} ₽</b>\n\n"
            f"💳 Баланс: <b>{balance_text} ₽</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"✨ ИДЕАЛЬНЫЙ РАУНД",
            reply_markup=mines_keyboard(
                opened=opened,
                finished=True
            )
        )

        await callback.answer(
            "🏆 Все клетки открыты!"
        )

        return

    # =====================================================
    # ОБЫЧНОЕ ОТКРЫТИЕ
    # =====================================================

    multiplier = MINES_MULTIPLIERS[
        opened_count
    ]

    potential_win = int(
        STAKE * multiplier
    )

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>БЕЗОПАСНО!</b>\n\n"
        f"📦 Открыто: <b>{opened_count} / 6</b>\n"
        f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Можно забрать: "
        f"<b>{potential_win} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Выбери следующую клетку\n"
        f"или забери выигрыш.",
        reply_markup=mines_keyboard(
            game["opened"]
        )
    )

    await callback.answer(
        "💎 Безопасно!"
    )


@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_callback(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Нет активной игры.",
            show_alert=True
        )
        return

    game = games[user_id]

    if game.get("type") != "mines":
        await callback.answer(
            "Сейчас запущена другая игра.",
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

    multiplier = MINES_MULTIPLIERS[
        opened_count
    ]

    winnings = int(
        STAKE * multiplier
    )

    change_balance(
        user_id,
        winnings
    )

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    opened = game["opened"].copy()

    # Игра полностью завершается
    del games[user_id]

    await callback.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>ВЫИГРЫШ ЗАБРАН</b>\n\n"
        f"💎 Безопасных клеток: "
        f"<b>{opened_count} / 6</b>\n"
        f"📈 Множитель: <b>x{multiplier:.2f}</b>\n"
        f"💰 Выигрыш: <b>+{winnings} ₽</b>\n\n"
        f"💳 Баланс: <b>{balance_text} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏦 Вы забрали выигрыш вовремя.",
        reply_markup=mines_keyboard(
            opened=opened,
            finished=True
        )
    )

    await callback.answer(
        "💰 Выигрыш забран!"
    )


# =========================================================
# 🧨 CRASH
# =========================================================

def crash_menu():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰 | ЗАБРАТЬ",
        callback_data="crash_cashout"
    )

    builder.button(
        text="❌ | ОТМЕНИТЬ",
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


def crash_indicator(multiplier):
    if multiplier < 2:
        return "🟢"

    if multiplier < 5:
        return "🟡"

    return "🔴"


@dp.callback_query(F.data == "crash")
async def crash_callback(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id in games:
        await callback.answer(
            "Сначала закончи текущую игру.",
            show_alert=True
        )
        return

    if not subtract_balance(
        user_id,
        STAKE
    ):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )
        return

    crash_point = generate_crash_point()

    # Сначала создаём состояние
    games[user_id] = {
        "type": "crash",
        "multiplier": 1.00,
        "crash_point": crash_point,
        "active": True,
        "message_id": callback.message.message_id
    }

    await callback.message.edit_text(
        f"🧨 <b>CRASH</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 <b>x1.00</b>\n\n"
        f"💰 Ставка: <b>{STAKE} ₽</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━",
        reply_markup=crash_menu()
    )

    await callback.answer()

    asyncio.create_task(
        crash_loop(
            callback.message.chat.id,
            user_id
        )
    )


async def crash_loop(
    chat_id,
    user_id
):
    while True:

        game = games.get(user_id)

        if not game:
            return

        if game.get("type") != "crash":
            return

        if not game.get("active"):
            return

        multiplier = game["multiplier"]
        crash_point = game["crash_point"]
        message_id = game["message_id"]

        # =================================================
        # CRASH
        # =================================================

        if multiplier >= crash_point:

            del games[user_id]

            balance = get_balance(user_id)
            balance_text = f"{balance:,}".replace(",", " ")

            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        f"🧨 <b>CRASH</b>\n\n"
                        f"━━━━━━━━━━━━━━━━━━\n\n"
                        f"💥 <b>CRASH НА x"
                        f"{crash_point:.2f}</b>\n\n"
                        f"💸 Ставка: "
                        f"<b>{STAKE} ₽</b>\n"
                        f"❌ Вы не успели "
                        f"забрать выигрыш.\n\n"
                        f"💳 Баланс: "
                        f"<b>{balance_text} ₽</b>"
                    ),
                    reply_markup=after_game_menu()
                )
            except Exception:
                pass

            return

        # =================================================
        # УВЕЛИЧЕНИЕ
        # =================================================

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

        potential_win = int(
            STAKE * multiplier
        )

        indicator = crash_indicator(
            multiplier
        )

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"🧨 <b>CRASH</b>\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"{indicator} "
                    f"<b>x{multiplier:.2f}</b>\n\n"
                    f"💰 Ставка: "
                    f"<b>{STAKE} ₽</b>\n"
                    f"💵 Забрать сейчас: "
                    f"<b>{potential_win} ₽</b>\n\n"
                    f"━━━━━━━━━━━━━━━━━━"
                ),
                reply_markup=crash_menu()
            )
        except Exception:
            pass

        await asyncio.sleep(0.25)


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout_callback(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра уже завершена.",
            show_alert=True
        )
        return

    game = games[user_id]

    if game.get("type") != "crash":
        await callback.answer(
            "Сейчас запущена другая игра.",
            show_alert=True
        )
        return

    multiplier = game["multiplier"]

    winnings = int(
        STAKE * multiplier
    )

    change_balance(
        user_id,
        winnings
    )

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    del games[user_id]

    await callback.message.edit_text(
        f"🧨 <b>CRASH</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎉 <b>ВЫИГРЫШ ЗАБРАН!</b>\n\n"
        f"📈 Множитель: "
        f"<b>x{multiplier:.2f}</b>\n"
        f"💰 Выигрыш: "
        f"<b>+{winnings} ₽</b>\n\n"
        f"💳 Баланс: "
        f"<b>{balance_text} ₽</b>",
        reply_markup=after_game_menu()
    )

    await callback.answer(
        "💰 Выигрыш забран!"
    )


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel_callback(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id in games:
        if games[user_id].get("type") == "crash":
            del games[user_id]

    balance = get_balance(user_id)
    balance_text = f"{balance:,}".replace(",", " ")

    await callback.message.edit_text(
        f"🧨 <b>CRASH</b>\n\n"
        f"❌ <b>ИГРА ОТМЕНЕНА</b>\n\n"
        f"💸 Ставка не возвращается.\n"
        f"💳 Баланс: <b>{balance_text} ₽</b>",
        reply_markup=after_game_menu()
    )

    await callback.answer(
        "Игра отменена"
    )


# =========================================================
# 🎲🎳 ОБРАБОТЧИК TELEGRAM DICE
# =========================================================

@dp.message(F.dice)
async def dice_handler(message: Message):
    user_id = message.from_user.id

    if user_id not in games:
        return

    game = games[user_id]

    # =====================================================
    # 🎲 КУБИКИ
    # =====================================================

    if message.dice.emoji == "🎲":

        # -------------------------------------------------
        # 1 КУБИК
        # -------------------------------------------------

        if game["type"] == "dice_one":

            value = message.dice.value

            del games[user_id]

            if value < 3:

                winnings = int(
                    STAKE * 1.85
                )

                change_balance(
                    user_id,
                    winnings
                )

                result_text = "⬇️ МЕНЬШЕ 3"

                balance = get_balance(user_id)
                balance_text = f"{balance:,}".replace(",", " ")

                await message.answer(
                    f"🎲 <b>КУБИК</b>\n\n"
                    f"🎯 Выпало: <b>{value}</b>\n"
                    f"{result_text}\n\n"
                    f"🎉 <b>ПОБЕДА!</b>\n"
                    f"📈 Множитель: <b>x1.85</b>\n"
                    f"💰 Выигрыш: "
                    f"<b>+{winnings} ₽</b>\n\n"
                    f"💳 Баланс: "
                    f"<b>{balance_text} ₽</b>",
                    reply_markup=after_game_menu()
                )

            elif value > 3:

                winnings = int(
                    STAKE * 1.85
                )

                change_balance(
                    user_id,
                    winnings
                )

                result_text = "⬆️ БОЛЬШЕ 3"

                balance = get_balance(user_id)
                balance_text = f"{balance:,}".replace(",", " ")

                await message.answer(
                    f"🎲 <b>КУБИК</b>\n\n"
                    f"🎯 Выпало: <b>{value}</b>\n"
                    f"{result_text}\n\n"
                    f"🎉 <b>ПОБЕДА!</b>\n"
                    f"📈 Множитель: <b>x1.85</b>\n"
                    f"💰 Выигрыш: "
                    f"<b>+{winnings} ₽</b>\n\n"
                    f"💳 Баланс: "
                    f"<b>{balance_text} ₽</b>",
                    reply_markup=after_game_menu()
                )

            else:

                balance = get_balance(user_id)
                balance_text = f"{balance:,}".replace(",", " ")

                await message.answer(
                    f"🎲 <b>КУБИК</b>\n\n"
                    f"🎯 Выпало: <b>3</b>\n\n"
                    f"💥 <b>ПРОИГРЫШ</b>\n"
                    f"💸 Потеряно: "
                    f"<b>{STAKE} ₽</b>\n\n"
                    f"💳 Баланс: "
                    f"<b>{balance_text} ₽</b>",
                    reply_markup=after_game_menu()
                )

        # -------------------------------------------------
        # 2 КУБИКА
        # -------------------------------------------------

        elif game["type"] == "dice_two":

            value = message.dice.value

            game["rolls"].append(value)

            if len(game["rolls"]) == 1:

                await message.answer(
                    f"🎲🎲 <b>2 КУБИКА</b>\n\n"
                    f"🎲 Первый: <b>{value}</b>\n\n"
                    f"🎲 Бросаем второй кубик..."
                )

                await bot.send_dice(
                    chat_id=message.chat.id,
                    emoji="🎲"
                )

                return

            first = game["rolls"][0]
            second = game["rolls"][1]

            total = first + second

            del games[user_id]

            if total == 7:

                multiplier = 5.00
                result_text = "🎯 РАВНО 7"

            elif total < 7:

                multiplier = 1.85
                result_text = "⬇️ МЕНЬШЕ 7"

            else:

                multiplier = 1.85
                result_text = "⬆️ БОЛЬШЕ 7"

            winnings = int(
                STAKE * multiplier
            )

            change_balance(
                user_id,
                winnings
            )

            balance = get_balance(user_id)
            balance_text = f"{balance:,}".replace(",", " ")

            await message.answer(
                f"🎲🎲 <b>2 КУБИКА</b>\n\n"
                f"🎲 Первый: <b>{first}</b>\n"
                f"🎲 Второй: <b>{second}</b>\n"
                f"🎯 Сумма: <b>{total}</b>\n\n"
                f"🎉 <b>ПОБЕДА!</b>\n"
                f"{result_text}\n"
                f"📈 Множитель: "
                f"<b>x{multiplier:.2f}</b>\n"
                f"💰 Выигрыш: "
                f"<b>+{winnings} ₽</b>\n\n"
                f"💳 Баланс: "
                f"<b>{balance_text} ₽</b>",
                reply_markup=after_game_menu()
            )

    # =====================================================
    # 🎳 БОУЛИНГ
    # =====================================================

    elif message.dice.emoji == "🎳":

        if game["type"] != "bowling":
            return

        value = message.dice.value
        bet = game["bet"]

        del games[user_id]

        if bet == "more":

            won = value > 3
            bet_text = "⬆️ БОЛЬШЕ 3"

        else:

            won = value < 3
            bet_text = "⬇️ МЕНЬШЕ 3"

        if won:

            winnings = int(
                STAKE * 1.85
            )

            change_balance(
                user_id,
                winnings
            )

            balance = get_balance(user_id)
            balance_text = f"{balance:,}".replace(",", " ")

            await message.answer(
                f"🎳 <b>БОУЛИНГ</b>\n\n"
                f"🎯 Ставка: <b>{bet_text}</b>\n"
                f"🎳 Выпало: <b>{value}</b>\n\n"
                f"🎉 <b>ПОБЕДА!</b>\n"
                f"📈 Множитель: <b>x1.85</b>\n"
                f"💰 Выигрыш: "
                f"<b>+{winnings} ₽</b>\n\n"
                f"💳 Баланс: "
                f"<b>{balance_text} ₽</b>",
                reply_markup=after_game_menu()
            )

        else:

            balance = get_balance(user_id)
            balance_text = f"{balance:,}".replace(",", " ")

            await message.answer(
                f"🎳 <b>БОУЛИНГ</b>\n\n"
                f"🎯 Ставка: <b>{bet_text}</b>\n"
                f"🎳 Выпало: <b>{value}</b>\n\n"
                f"💥 <b>ПРОИГРЫШ</b>\n"
                f"💸 Потеряно: "
                f"<b>{STAKE} ₽</b>\n\n"
                f"💳 Баланс: "
                f"<b>{balance_text} ₽</b>",
                reply_markup=after_game_menu()
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
        data
    )

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
        f"SETTING WEBHOOK: {WEBHOOK_URL}"
    )

    print(
        f"WEBHOOK URL: {WEBHOOK_URL}"
    )


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown():

    # НЕ удаляем webhook!
    # Иначе после рестарта Render Telegram перестанет
    # отправлять обновления.

    await bot.session.close()
