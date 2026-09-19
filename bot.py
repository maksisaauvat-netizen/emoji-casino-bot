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


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

BASE_URL = "https://emoji-casino-bot.onrender.com"

STAKE = 100


# =========================================================
# 🎰 СЛОТЫ — КОЭФФИЦИЕНТЫ
# =========================================================

SLOT_TWO_MULTIPLIER = 1.85
SLOT_OTHER_THREE_MULTIPLIER = 3.5
SLOT_COCKTAIL_MULTIPLIER = 5
SLOT_GRAPES_MULTIPLIER = 8
SLOT_LEMON_MULTIPLIER = 10
SLOT_SEVEN_MULTIPLIER = 50


# =========================================================
# 🎡 РУЛЕТКА — КОЭФФИЦИЕНТЫ
# =========================================================

ROULETTE_MULTIPLIER = 1.95
ROULETTE_ZERO_MULTIPLIER = 36


# =========================================================
# 🤖 BOT
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()
app = FastAPI()

games = {}


# =========================================================
# 📂 ГЛАВНОЕ МЕНЮ
# =========================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 | Меню",
                    callback_data="main_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🥷 | Профиль",
                    callback_data="profile"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 | Мини-игры",
                    callback_data="mini_games"
                )
            ],
        ]
    )


# =========================================================
# 🎰 МИНИ-ИГРЫ
# =========================================================

def mini_games_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | Кубики",
                    callback_data="game_dice"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎰 | Слоты",
                    callback_data="game_slots"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎡 | Рулетка",
                    callback_data="game_roulette"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎳 | Боулинг",
                    callback_data="game_bowling"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="main_menu"
                )
            ],
        ]
    )


# =========================================================
# 🔄 МЕНЮ ПОСЛЕ ИГРЫ
# =========================================================

def after_game_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 | Играть снова",
                    callback_data="mini_games"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 | Меню",
                    callback_data="main_menu"
                )
            ],
        ]
    )


# =========================================================
# /START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):

    user_id = message.from_user.id

    balance = get_balance(user_id)

    await message.answer(
        "🎰 <b>Emoji Casino</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Добро пожаловать!\n"
        "Выберите раздел:",
        reply_markup=main_menu()
    )


# =========================================================
# 📂 ГЛАВНОЕ МЕНЮ
# =========================================================

@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎰 <b>Emoji Casino</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выберите раздел:",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# 🥷 ПРОФИЛЬ
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):

    user_id = callback.from_user.id
    user = callback.from_user

    balance = get_balance(user_id)

    username = (
        f"@{user.username}"
        if user.username
        else "не указан"
    )

    await callback.message.edit_text(
        "🥷 <b>Профиль</b>\n\n"
        f"👤 Имя: <b>{user.first_name}</b>\n"
        f"🔗 Username: <b>{username}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💰 Баланс: <b>{balance}</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📂 | Назад",
                        callback_data="main_menu"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# 🎰 МИНИ-ИГРЫ
# =========================================================

@dp.callback_query(F.data == "mini_games")
async def mini_games_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎰 <b>Мини-игры</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n\n"
        "Выберите игру:",
        reply_markup=mini_games_menu()
    )

    await callback.answer()


# =========================================================
# 🎲 КУБИКИ
# =========================================================

def dice_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | 1 бросок",
                    callback_data="dice_one"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎲🎲 | 2 броска",
                    callback_data="dice_two"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ],
        ]
    )


@dp.callback_query(F.data == "game_dice")
async def game_dice_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎲 <b>Кубики</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"

        "<b>Один бросок</b>\n"
        "x1.85 | Меньше 3\n"
        "x1.85 | Больше 3\n\n"

        "<b>Два броска</b>\n"
        "x5.00 | Равно 7\n"
        "x1.85 | Меньше 7\n"
        "x1.85 | Больше 7\n\n"

        "Выберите режим:",
        reply_markup=dice_menu()
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "dice_one",
        "dice_two"
    })
)
async def dice_mode_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    if not subtract_balance(user_id, STAKE):

        await callback.answer(
            "❌ Недостаточно средств!",
            show_alert=True
        )

        return

    if callback.data == "dice_one":

        games[user_id] = {
            "type": "dice_one"
        }

        await callback.message.answer(
            "🎲 <b>Один бросок</b>\n\n"
            "Отправьте 🎲\n\n"
            "x1.85 — меньше 3\n"
            "x1.85 — больше 3"
        )

    else:

        games[user_id] = {
            "type": "dice_two",
            "first_dice": None
        }

        await callback.message.answer(
            "🎲🎲 <b>Два броска</b>\n\n"
            "Отправьте первый 🎲"
        )

    await callback.answer()


# =========================================================
# 🎳 БОУЛИНГ
# =========================================================

def bowling_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬆️ | Больше 3 x1.85",
                    callback_data="bowling_more"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬇️ | Меньше 3 x1.85",
                    callback_data="bowling_less"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ],
        ]
    )


@dp.callback_query(F.data == "game_bowling")
async def game_bowling_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎳 <b>Боулинг</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"

        "⬆️ Больше 3 → <b>x1.85</b>\n"
        "⬇️ Меньше 3 → <b>x1.85</b>\n\n"

        "Выберите ставку:",
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

    bet = callback.data

    if not subtract_balance(user_id, STAKE):

        await callback.answer(
            "❌ Недостаточно средств!",
            show_alert=True
        )

        return

    games[user_id] = {
        "type": "bowling",
        "bet": bet
    }

    if bet == "bowling_more":

        bet_text = "⬆️ Больше 3"

    else:

        bet_text = "⬇️ Меньше 3"

    await callback.message.answer(
        "🎳 <b>Боулинг</b>\n\n"
        f"Ваша ставка: <b>{bet_text}</b>\n"
        "Коэффициент: <b>x1.85</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"
        "Отправьте 🎳"
    )

    await callback.answer()


# =========================================================
# 🎡 РУЛЕТКА
# =========================================================

def roulette_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 | Красное x1.95",
                    callback_data="roulette_red"
                ),
                InlineKeyboardButton(
                    text="⚫ | Чёрное x1.95",
                    callback_data="roulette_black"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬆️ | 1–18 x1.95",
                    callback_data="roulette_low"
                ),
                InlineKeyboardButton(
                    text="⬇️ | 19–36 x1.95",
                    callback_data="roulette_high"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚪ | Чётное x1.95",
                    callback_data="roulette_even"
                ),
                InlineKeyboardButton(
                    text="🟣 | Нечётное x1.95",
                    callback_data="roulette_odd"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🟢 | Зеро x36",
                    callback_data="roulette_zero"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ],
        ]
    )


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

        else:

            multiplier = ROULETTE_MULTIPLIER

        payout = int(STAKE * multiplier)

        new_balance = change_balance(
            user_id,
            payout
        )

        result_text = (
            "🎉 <b>Выигрыш!</b>\n"
            f"📈 Коэффициент: <b>x{multiplier}</b>\n"
            f"💰 Выплата: <b>+{payout}</b>"
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


# =========================================================
# 🎰 СЛОТЫ
# =========================================================

def slots_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎰 | Крутить",
                    callback_data="slots_spin"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 | Назад",
                    callback_data="mini_games"
                )
            ],
        ]
    )


@dp.callback_query(F.data == "game_slots")
async def game_slots_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎰 <b>Слоты</b>\n\n"
        f"💰 Баланс: <b>{balance}</b>\n"
        f"💵 Ставка: <b>{STAKE}</b>\n\n"

        "<b>Выигрыши:</b>\n"
        "2 одинаковых → <b>x1.85</b>\n"
        "🍸🍸🍸 → <b>x5</b>\n"
        "🍇🍇🍇 → <b>x8</b>\n"
        "🍋🍋🍋 → <b>x10</b>\n"
        "7️⃣7️⃣7️⃣ → <b>x50</b>\n"
        "Другие 3 одинаковых → <b>x3.5</b>\n\n"

        "Нажмите «Крутить».",
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


# =========================================================
# 🎰 РЕЗУЛЬТАТ СЛОТОВ
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


# =========================================================
# 🎲🎰🎳 TELEGRAM DICE
# =========================================================

@dp.message(F.dice)
async def dice_handler(message: Message):

    user_id = message.from_user.id

    if user_id not in games:

        return

    game = games[user_id]

    emoji = message.dice.emoji
    value = message.dice.value


    # =====================================================
    # 🎳 БОУЛИНГ
    # =====================================================

    if game["type"] == "bowling":

        if emoji != "🎳":

            return

        bet = game["bet"]

        del games[user_id]

        if bet == "bowling_more":

            won = value > 3
            bet_text = "⬆️ Больше 3"

        else:

            won = value < 3
            bet_text = "⬇️ Меньше 3"

        if won:

            multiplier = 1.85

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                f"📊 Ставка: <b>{bet_text}</b>\n"
                "📈 Коэффициент: <b>x1.85</b>\n"
                f"💰 Выплата: <b>+{payout}</b>"
            )

        else:

            new_balance = get_balance(
                user_id
            )

            result_text = (
                "😔 <b>Проигрыш</b>\n"
                f"📊 Ставка: <b>{bet_text}</b>\n"
                "💰 Ставка сгорела."
            )

        await message.answer(
            "🎳 <b>Результат боулинга</b>\n\n"
            f"🎯 Выпало: <b>{value}</b>\n\n"
            f"{result_text}\n\n"
            f"💳 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu()
        )

        return


    # =====================================================
    # 🎰 СЛОТЫ
    # =====================================================

    if game["type"] == "slots":

        if emoji != "🎰":

            return

        del games[user_id]

        symbols, multiplier = slot_result(
            value
        )

        if multiplier > 0:

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            if multiplier == SLOT_TWO_MULTIPLIER:

                result_text = (
                    "🎉 <b>Выигрыш!</b>\n"
                    "✨ 2 из 3 одинаковых\n"
                    "📈 Коэффициент: <b>x1.85</b>\n"
                    f"💰 Выплата: <b>+{payout}</b>"
                )

            elif multiplier == SLOT_COCKTAIL_MULTIPLIER:

                result_text = (
                    "🎉 <b>Выигрыш!</b>\n"
                    "🍸🍸🍸\n"
                    "📈 Коэффициент: <b>x5</b>\n"
                    f"💰 Выплата: <b>+{payout}</b>"
                )

            elif multiplier == SLOT_GRAPES_MULTIPLIER:

                result_text = (
                    "🎉 <b>Выигрыш!</b>\n"
                    "🍇🍇🍇\n"
                    "📈 Коэффициент: <b>x8</b>\n"
                    f"💰 Выплата: <b>+{payout}</b>"
                )

            elif multiplier == SLOT_LEMON_MULTIPLIER:

                result_text = (
                    "🎉 <b>Выигрыш!</b>\n"
                    "🍋🍋🍋\n"
                    "📈 Коэффициент: <b>x10</b>\n"
                    f"💰 Выплата: <b>+{payout}</b>"
                )

            elif multiplier == SLOT_SEVEN_MULTIPLIER:

                result_text = (
                    "🎉 <b>ДЖЕКПОТ!</b>\n"
                    "7️⃣7️⃣7️⃣\n"
                    "📈 Коэффициент: <b>x50</b>\n"
                    f"💰 Выплата: <b>+{payout}</b>"
                )

            else:

                result_text = (
                    "🎉 <b>Выигрыш!</b>\n"
                    "🔥 3 из 3 одинаковых\n"
                    "📈 Коэффициент: <b>x3.5</b>\n"
                    f"💰 Выплата: <b>+{payout}</b>"
                )

        else:

            new_balance = get_balance(
                user_id
            )

            result_text = (
                "😔 <b>Проигрыш</b>\n"
                "Нет совпадений."
            )

        await message.answer(
            "🎰 <b>Результат слотов</b>\n\n"
            f"{symbols[0]} | "
            f"{symbols[1]} | "
            f"{symbols[2]}\n\n"
            f"{result_text}\n\n"
            f"💳 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu()
        )

        return


    # =====================================================
    # 🎲 ОДИН БРОСОК
    # =====================================================

    if game["type"] == "dice_one":

        if emoji != "🎲":

            return

        del games[user_id]

        if value < 3:

            multiplier = 1.85

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                "📊 Меньше 3\n"
                "📈 Коэффициент: <b>x1.85</b>\n"
                f"💰 Выплата: <b>+{payout}</b>"
            )

        elif value > 3:

            multiplier = 1.85

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                "📊 Больше 3\n"
                "📈 Коэффициент: <b>x1.85</b>\n"
                f"💰 Выплата: <b>+{payout}</b>"
            )

        else:

            new_balance = get_balance(
                user_id
            )

            result_text = (
                "😔 <b>Проигрыш</b>\n"
                "🎯 Выпало: <b>3</b>"
            )

        await message.answer(
            "🎲 <b>Результат</b>\n\n"
            f"🎯 Выпало: <b>{value}</b>\n\n"
            f"{result_text}\n\n"
            f"💳 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu()
        )

        return


    # =====================================================
    # 🎲 ДВА БРОСКА
    # =====================================================

    if game["type"] == "dice_two":

        if emoji != "🎲":

            return

        first_dice = game["first_dice"]

        if first_dice is None:

            game["first_dice"] = value

            await message.answer(
                "🎲 <b>Первый кубик:</b> "
                f"<b>{value}</b>\n\n"
                "🎲 Теперь отправьте второй кубик."
            )

            return

        second_dice = value

        total = first_dice + second_dice

        del games[user_id]

        if total == 7:

            multiplier = 5.00

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>ДЖЕКПОТ!</b>\n"
                "🎯 Сумма ровно 7\n"
                "📈 Коэффициент: <b>x5.00</b>\n"
                f"💰 Выплата: <b>+{payout}</b>"
            )

        elif total < 7:

            multiplier = 1.85

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                "📊 Сумма меньше 7\n"
                "📈 Коэффициент: <b>x1.85</b>\n"
                f"💰 Выплата: <b>+{payout}</b>"
            )

        else:

            multiplier = 1.85

            payout = int(
                STAKE * multiplier
            )

            new_balance = change_balance(
                user_id,
                payout
            )

            result_text = (
                "🎉 <b>Выигрыш!</b>\n"
                "📊 Сумма больше 7\n"
                "📈 Коэффициент: <b>x1.85</b>\n"
                f"💰 Выплата: <b>+{payout}</b>"
            )

        await message.answer(
            "🎲🎲 <b>Результат двух бросков</b>\n\n"
            f"Первый кубик: <b>{first_dice}</b>\n"
            f"Второй кубик: <b>{second_dice}</b>\n"
            f"Сумма: <b>{total}</b>\n\n"
            f"{result_text}\n\n"
            f"💳 Баланс: <b>{new_balance}</b>",
            reply_markup=after_game_menu()
        )

        return


# =========================================================
# 🌐 WEB
# =========================================================

@app.get("/")
async def root():

    return {
        "status": "ok",
        "bot": "Emoji Casino"
    }


@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):

    data = await request.json()

    from aiogram.types import Update

    update = Update.model_validate(data)

    await dp.feed_update(
        bot,
        update
    )

    return {
        "ok": True
    }


# =========================================================
# 🚀 STARTUP
# =========================================================

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


# =========================================================
# 🛑 SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown():

    await bot.session.close()
