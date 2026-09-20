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
from payments import (
    create_invoice,
    process_paid_invoice,
    get_payment_info,
    get_invoice,
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
# GAME SETTINGS
# =========================================================

STAKES = [50, 100, 250, 500, 1000]

CRASH_MIN = 1.05
CRASH_MAX = 20.0

SLOT_SEVEN_MULTIPLIER = 50


# =========================================================
# HELPERS
# =========================================================

def money(value):
    return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")


def get_user_id(obj):
    if isinstance(obj, Message):
        return obj.from_user.id

    if isinstance(obj, CallbackQuery):
        return obj.from_user.id

    return None


def user_name(obj):
    if isinstance(obj, Message):
        return obj.from_user.first_name or "Игрок"

    if isinstance(obj, CallbackQuery):
        return obj.from_user.first_name or "Игрок"

    return "Игрок"


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(user_id: int):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🎰 МИНИ-ИГРЫ",
        callback_data="games"
    )

    kb.button(
        text="💳 КОШЕЛЁК",
        callback_data="wallet"
    )

    kb.button(
        text="👤 ПРОФИЛЬ",
        callback_data="profile"
    )

    if is_admin(user_id):
        kb.button(
            text="🛠 АДМИН",
            callback_data="admin"
        )

    kb.adjust(1)

    return kb.as_markup()


def games_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🎲 КУБИКИ",
        callback_data="game_dice"
    )

    kb.button(
        text="🎰 СЛОТЫ",
        callback_data="game_slots"
    )

    kb.button(
        text="🎯 РУЛЕТКА",
        callback_data="game_roulette"
    )

    kb.button(
        text="🎳 БОУЛИНГ",
        callback_data="game_bowling"
    )

    kb.button(
        text="💣 MINES",
        callback_data="game_mines"
    )

    kb.button(
        text="📈 CRASH",
        callback_data="game_crash"
    )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="main"
    )

    kb.adjust(2)

    return kb.as_markup()


def wallet_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="➕ ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="main"
    )

    kb.adjust(1)

    return kb.as_markup()


def deposit_keyboard():
    kb = InlineKeyboardBuilder()

    for amount in [1, 5, 10, 25, 50]:
        kb.button(
            text=f"💵 {amount} USDT",
            callback_data=f"deposit_{amount}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="wallet"
    )

    kb.adjust(2)

    return kb.as_markup()


def after_game_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🎰 ИГРАТЬ ЕЩЁ",
        callback_data="games"
    )

    kb.button(
        text="💳 КОШЕЛЁК",
        callback_data="wallet"
    )

    kb.button(
        text="🏠 ГЛАВНОЕ МЕНЮ",
        callback_data="main"
    )

    kb.adjust(1)

    return kb.as_markup()


# =========================================================
# START / MAIN
# =========================================================

@dp.message(F.text == "/start")
async def start_handler(message: Message):
    user_id = message.from_user.id

    get_balance(user_id)

    await message.answer(
        "🎰 <b>RESONANT — CASINO</b>\n\n"
        "Добро пожаловать!\n\n"
        "💰 Здесь ты можешь играть в мини-игры "
        "за внутренние рубли ₽.\n\n"
        "Выбери действие:",
        reply_markup=main_keyboard(user_id)
    )


@dp.callback_query(F.data == "main")
async def main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.message.edit_text(
        "🎰 <b>RESONANT — CASINO</b>\n\n"
        "Главное меню:",
        reply_markup=main_keyboard(user_id)
    )

    await callback.answer()


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "games")
async def games_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎰 <b>МИНИ-ИГРЫ</b>\n\n"
        "Выбери игру:",
        reply_markup=games_keyboard()
    )

    await callback.answer()


# =========================================================
# WALLET
# =========================================================

@dp.callback_query(F.data == "wallet")
async def wallet_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_balance(user_id)

    await callback.message.edit_text(
        "💳 <b>КОШЕЛЁК</b>\n\n"
        f"💰 Баланс: <b>{money(balance)} ₽</b>\n\n"
        "Пополнение выполняется через Crypto Pay.\n"
        "Курс тестовой системы: <b>1 USDT = 80 ₽</b>.",
        reply_markup=wallet_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data == "deposit")
async def deposit_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "➕ <b>ПОПОЛНЕНИЕ</b>\n\n"
        "Выбери сумму:",
        reply_markup=deposit_keyboard()
    )

    await callback.answer()


# =========================================================
# CREATE DEPOSIT
# =========================================================

@dp.callback_query(F.data.startswith("deposit_"))
async def create_deposit(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        amount_usdt = float(
            callback.data.split("_", 1)[1]
        )
    except Exception:
        await callback.answer(
            "Ошибка суммы",
            show_alert=True
        )
        return

    try:
        invoice = await create_invoice(
            user_id=user_id,
            amount_usdt=amount_usdt
        )
    except Exception as error:
        print("CREATE INVOICE ERROR:", error)

        await callback.message.edit_text(
            "❌ <b>Не удалось создать счёт.</b>\n\n"
            "Попробуй ещё раз позже.",
            reply_markup=wallet_keyboard()
        )

        await callback.answer()
        return

    invoice_id = invoice["invoice_id"]
    pay_url = invoice["pay_url"]

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💳 ОПЛАТИТЬ",
        url=pay_url
    )

    kb.button(
        text="🔄 ПРОВЕРИТЬ ОПЛАТУ",
        callback_data=f"check_payment_{invoice_id}"
    )

    kb.button(
        text="💳 КОШЕЛЁК",
        callback_data="wallet"
    )

    kb.adjust(1)

    await callback.message.edit_text(
        "💳 <b>СЧЁТ СОЗДАН</b>\n\n"
        f"💵 Сумма: <b>{amount_usdt:g} USDT</b>\n"
        f"💰 Будет зачислено: "
        f"<b>{money(amount_usdt * 80)} ₽</b>\n\n"
        "Нажми «ОПЛАТИТЬ», затем после оплаты "
        "можно нажать «ПРОВЕРИТЬ ОПЛАТУ».\n\n"
        "⏱ Система также автоматически проверяет оплату.",
        reply_markup=kb.as_markup()
    )

    asyncio.create_task(
        payment_checker(
            user_id,
            invoice_id
        )
    )

    await callback.answer()


# =========================================================
# PAYMENT CHECKER
# =========================================================

async def payment_checker(
    user_id: int,
    invoice_id: int
):
    for _ in range(360):
        await asyncio.sleep(5)

        try:
            result = await process_paid_invoice(
                invoice_id
            )
        except Exception as error:
            print(
                "PAYMENT CHECK ERROR:",
                error
            )
            continue

        if result is None:
            continue

        if result["user_id"] != user_id:
            return

        try:
            await bot.send_message(
                user_id,
                "✅ <b>ОПЛАТА ПОЛУЧЕНА!</b>\n\n"
                f"💵 Получено: "
                f"<b>{result['amount_usdt']:g} USDT</b>\n"
                f"💰 Зачислено: "
                f"<b>+{money(result['amount_rub'])} ₽</b>\n\n"
                f"💳 Баланс: "
                f"<b>{money(result['balance'])} ₽</b>"
            )
        except Exception as error:
            print(
                "PAYMENT MESSAGE ERROR:",
                error
            )

        return


# =========================================================
# MANUAL PAYMENT CHECK
# =========================================================

@dp.callback_query(
    F.data.startswith("check_payment_")
)
async def check_payment(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    try:
        invoice_id = int(
            callback.data.split("_", 2)[2]
        )
    except Exception:
        await callback.answer(
            "Неверный счёт",
            show_alert=True
        )
        return

    # -----------------------------------------------------
    # Сначала получаем invoice
    # -----------------------------------------------------

    try:
        invoice = await get_invoice(
            invoice_id
        )
    except Exception as error:
        print(
            "GET INVOICE ERROR:",
            error
        )

        await callback.answer(
            "Не удалось проверить счёт",
            show_alert=True
        )
        return

    if not invoice:
        await callback.answer(
            "Счёт не найден",
            show_alert=True
        )
        return

    # -----------------------------------------------------
    # Проверяем владельца invoice
    # -----------------------------------------------------

    payload = invoice.get("payload")

    try:
        invoice_user_id = int(payload)
    except Exception:
        await callback.answer(
            "Ошибка владельца счёта",
            show_alert=True
        )
        return

    if invoice_user_id != user_id:
        await callback.answer(
            "Этот счёт принадлежит другому пользователю.",
            show_alert=True
        )
        return

    # -----------------------------------------------------
    # Проверяем оплату
    # -----------------------------------------------------

    if invoice.get("status") != "paid":
        await callback.answer(
            "Оплата ещё не получена.",
            show_alert=True
        )
        return

    # -----------------------------------------------------
    # Обрабатываем оплату
    # -----------------------------------------------------

    try:
        result = await process_paid_invoice(
            invoice_id
        )
    except Exception as error:
        print(
            "PROCESS PAYMENT ERROR:",
            error
        )

        await callback.answer(
            "Ошибка обработки платежа",
            show_alert=True
        )
        return

    # -----------------------------------------------------
    # Если None — invoice уже обработан
    # -----------------------------------------------------

    if result is None:
        balance = get_balance(user_id)

        await callback.message.edit_text(
            "✅ <b>ПЛАТЁЖ УЖЕ ОБРАБОТАН</b>\n\n"
            "Повторное зачисление невозможно.\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>",
            reply_markup=wallet_keyboard()
        )

        await callback.answer()
        return

    # -----------------------------------------------------
    # Успешное зачисление
    # -----------------------------------------------------

    await callback.message.edit_text(
        "✅ <b>ОПЛАТА ПОЛУЧЕНА!</b>\n\n"
        f"💵 Получено: "
        f"<b>{result['amount_usdt']:g} USDT</b>\n"
        f"💰 Зачислено: "
        f"<b>+{money(result['amount_rub'])} ₽</b>\n\n"
        f"💳 Баланс: "
        f"<b>{money(result['balance'])} ₽</b>",
        reply_markup=wallet_keyboard()
    )

    await callback.answer()


# =========================================================
# DICE
# =========================================================

@dp.callback_query(F.data == "game_dice")
async def dice_game(callback: CallbackQuery):
    user_id = callback.from_user.id

    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"🎲 {stake} ₽",
            callback_data=f"dice_stake_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="games"
    )

    kb.adjust(2)

    await callback.message.edit_text(
        "🎲 <b>КУБИКИ</b>\n\n"
        "Выбери ставку:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("dice_stake_")
)
async def dice_stake(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬇️ МЕНЬШЕ 3",
        callback_data=f"dice_play_{stake}_less"
    )

    kb.button(
        text="⬆️ БОЛЬШЕ 3",
        callback_data=f"dice_play_{stake}_more"
    )

    kb.button(
        text="🎲 ДВА КУБИКА",
        callback_data=f"dice_two_{stake}"
    )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="game_dice"
    )

    kb.adjust(1)

    await callback.message.edit_text(
        f"🎲 <b>КУБИКИ</b>\n\n"
        f"Ставка: <b>{stake} ₽</b>\n\n"
        "Выбери исход:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("dice_play_")
)
async def dice_play(callback: CallbackQuery):
    user_id = callback.from_user.id

    _, _, stake, choice = callback.data.split("_")
    stake = int(stake)

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    roll = random.randint(1, 6)

    win = (
        choice == "less" and roll < 3
    ) or (
        choice == "more" and roll > 3
    )

    if roll == 3:
        win = False

    multiplier = 1.85 if win else 0
    payout = stake * multiplier

    if win:
        change_balance(
            user_id,
            payout
        )

    record_game(
        user_id,
        "dice",
        stake,
        payout,
        {
            "roll": roll,
            "choice": choice
        }
    )

    text = (
        "🎲 <b>КУБИКИ</b>\n\n"
        f"Выпало: <b>{roll}</b>\n\n"
    )

    if win:
        text += (
            "🎉 <b>ПОБЕДА!</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>"
        )
    else:
        text += (
            "💥 <b>ПРОИГРЫШ</b>\n"
            f"💸 Ставка: <b>{money(stake)} ₽</b>"
        )

    text += (
        "\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("dice_two_")
)
async def dice_two(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    d1 = random.randint(1, 6)
    d2 = random.randint(1, 6)

    total = d1 + d2

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬇️ МЕНЬШЕ 7",
        callback_data=f"dice_two_play_{stake}_less"
    )

    kb.button(
        text="⬆️ БОЛЬШЕ 7",
        callback_data=f"dice_two_play_{stake}_more"
    )

    kb.button(
        text="🎯 РОВНО 7",
        callback_data=f"dice_two_play_{stake}_seven"
    )

    # сохраняем результат для следующего клика
    games[user_id] = {
        "type": "dice_two",
        "stake": stake,
        "d1": d1,
        "d2": d2,
        "total": total
    }

    await callback.message.edit_text(
        f"🎲 <b>ДВА КУБИКА</b>\n\n"
        f"Первый: <b>{d1}</b>\n"
        f"Второй: <b>{d2}</b>\n"
        f"Сумма: <b>{total}</b>\n\n"
        "Выбери исход:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("dice_two_play_")
)
async def dice_two_play(callback: CallbackQuery):
    user_id = callback.from_user.id

    _, _, _, stake, choice = callback.data.split("_")
    stake = int(stake)

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    total = game["total"]
    d1 = game["d1"]
    d2 = game["d2"]

    win = False
    multiplier = 0

    if choice == "less" and total < 7:
        win = True
        multiplier = 1.85

    elif choice == "more" and total > 7:
        win = True
        multiplier = 1.85

    elif choice == "seven" and total == 7:
        win = True
        multiplier = 5

    payout = stake * multiplier

    if win:
        change_balance(
            user_id,
            payout
        )

    record_game(
        user_id,
        "dice_two",
        stake,
        payout,
        {
            "d1": d1,
            "d2": d2,
            "total": total,
            "choice": choice
        }
    )

    games.pop(user_id, None)

    text = (
        "🎲 <b>ДВА КУБИКА</b>\n\n"
        f"🎲 {d1} + {d2} = <b>{total}</b>\n\n"
    )

    if win:
        text += (
            "🎉 <b>ПОБЕДА!</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>"
        )
    else:
        text += "💥 <b>ПРОИГРЫШ</b>"

    text += (
        "\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# SLOTS
# =========================================================

@dp.callback_query(F.data == "game_slots")
async def slots_game(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"🎰 {stake} ₽",
            callback_data=f"slots_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="games"
    )

    kb.adjust(2)

    await callback.message.edit_text(
        "🎰 <b>СЛОТЫ</b>\n\n"
        "🍸 🍇 🍋 7️⃣\n\n"
        "2 одинаковых = x1.85\n"
        "🍸🍸🍸 = x5\n"
        "🍇🍇🍇 = x8\n"
        "🍋🍋🍋 = x10\n"
        "7️⃣7️⃣7️⃣ = x50\n\n"
        "Выбери ставку:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("slots_")
)
async def slots_play(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    symbols = [
        "🍸",
        "🍇",
        "🍋",
        "7️⃣"
    ]

    result = [
        random.choice(symbols)
        for _ in range(3)
    ]

    payout = 0

    if result[0] == result[1] == result[2]:
        multipliers = {
            "🍸": 5,
            "🍇": 8,
            "🍋": 10,
            "7️⃣": 50
        }

        payout = stake * multipliers.get(
            result[0],
            3.5
        )

    elif (
        result[0] == result[1]
        or result[1] == result[2]
        or result[0] == result[2]
    ):
        payout = stake * 1.85

    if payout:
        change_balance(
            user_id,
            payout
        )

    record_game(
        user_id,
        "slots",
        stake,
        payout,
        {
            "result": result
        }
    )

    text = (
        "🎰 <b>СЛОТЫ</b>\n\n"
        f"┃ {' '.join(result)} ┃\n\n"
    )

    if payout:
        text += (
            "🎉 <b>ПОБЕДА!</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>"
        )
    else:
        text += "💥 <b>ПРОИГРЫШ</b>"

    text += (
        "\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# ROULETTE
# =========================================================

@dp.callback_query(F.data == "game_roulette")
async def roulette_game(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"🎯 {stake} ₽",
            callback_data=f"roulette_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="games"
    )

    kb.adjust(2)

    await callback.message.edit_text(
        "🎯 <b>РУЛЕТКА</b>\n\n"
        "🔴 Красное\n"
        "⚫ Чёрное\n"
        "🟢 Ноль\n\n"
        "Красное/чёрное — x1.95\n"
        "Ноль — x36\n\n"
        "Выбери ставку:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("roulette_")
)
async def roulette_play(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🔴 КРАСНОЕ",
        callback_data=f"roulette_play_{stake}_red"
    )

    kb.button(
        text="⚫ ЧЁРНОЕ",
        callback_data=f"roulette_play_{stake}_black"
    )

    kb.button(
        text="🟢 НОЛЬ",
        callback_data=f"roulette_play_{stake}_zero"
    )

    kb.button(
        text="◀️ ОТМЕНА",
        callback_data="games"
    )

    games[user_id] = {
        "type": "roulette",
        "stake": stake
    }

    await callback.message.edit_text(
        f"🎯 <b>РУЛЕТКА</b>\n\n"
        f"Ставка: <b>{stake} ₽</b>\n\n"
        "Выбери цвет:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("roulette_play_")
)
async def roulette_play_result(callback: CallbackQuery):
    user_id = callback.from_user.id

    _, _, stake, choice = callback.data.split("_")
    stake = int(stake)

    game = games.pop(user_id, None)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    red_numbers = {
        1, 3, 5, 7, 9,
        12, 14, 16, 18,
        19, 21, 23, 25,
        27, 30, 32, 34, 36
    }

    number = random.randint(0, 36)

    if number == 0:
        result = "zero"
        emoji = "🟢"
    elif number in red_numbers:
        result = "red"
        emoji = "🔴"
    else:
        result = "black"
        emoji = "⚫"

    win = choice == result

    if win:
        multiplier = 36 if result == "zero" else 1.95
        payout = stake * multiplier
        change_balance(
            user_id,
            payout
        )
    else:
        payout = 0

    record_game(
        user_id,
        "roulette",
        stake,
        payout,
        {
            "number": number,
            "result": result,
            "choice": choice
        }
    )

    text = (
        "🎯 <b>РУЛЕТКА</b>\n\n"
        f"{emoji} Выпало: <b>{number}</b>\n\n"
    )

    if win:
        text += (
            "🎉 <b>ПОБЕДА!</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>"
        )
    else:
        text += "💥 <b>ПРОИГРЫШ</b>"

    text += (
        "\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# BOWLING
# =========================================================

@dp.callback_query(F.data == "game_bowling")
async def bowling_game(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"🎳 {stake} ₽",
            callback_data=f"bowling_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="games"
    )

    kb.adjust(2)

    await callback.message.edit_text(
        "🎳 <b>БОУЛИНГ</b>\n\n"
        "Выбери ставку:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("bowling_")
)
async def bowling_play(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    pins = random.randint(0, 6)

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬇️ МЕНЬШЕ 3",
        callback_data=f"bowling_result_{stake}_{pins}_less"
    )

    kb.button(
        text="⬆️ БОЛЬШЕ 3",
        callback_data=f"bowling_result_{stake}_{pins}_more"
    )

    await callback.message.edit_text(
        f"🎳 <b>БОУЛИНГ</b>\n\n"
        f"Сбито кеглей: <b>{pins}</b>\n\n"
        "Выбери прогноз:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("bowling_result_")
)
async def bowling_result(callback: CallbackQuery):
    user_id = callback.from_user.id

    _, _, stake, pins, choice = callback.data.split("_")

    stake = int(stake)
    pins = int(pins)

    win = (
        choice == "less" and pins < 3
    ) or (
        choice == "more" and pins > 3
    )

    payout = stake * 1.85 if win else 0

    if win:
        change_balance(
            user_id,
            payout
        )

    record_game(
        user_id,
        "bowling",
        stake,
        payout,
        {
            "pins": pins,
            "choice": choice
        }
    )

    text = (
        "🎳 <b>БОУЛИНГ</b>\n\n"
        f"Сбито кеглей: <b>{pins}</b>\n\n"
    )

    if win:
        text += (
            "🎉 <b>ПОБЕДА!</b>\n"
            f"💰 Выигрыш: <b>+{money(payout)} ₽</b>"
        )
    else:
        text += "💥 <b>ПРОИГРЫШ</b>"

    text += (
        "\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# MINES
# =========================================================

@dp.callback_query(F.data == "game_mines")
async def mines_game(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"💣 {stake} ₽",
            callback_data=f"mines_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="games"
    )

    kb.adjust(2)

    await callback.message.edit_text(
        "💣 <b>MINES</b>\n\n"
        "9 клеток, 3 мины.\n"
        "Открывай клетки и забирай выигрыш.\n\n"
        "Выбери ставку:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("mines_")
)
async def mines_start(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    mines = random.sample(
        range(9),
        3
    )

    games[user_id] = {
        "type": "mines",
        "stake": stake,
        "mines": mines,
        "opened": [],
        "multiplier": 1.0
    }

    await show_mines_board(
        callback,
        user_id
    )


async def show_mines_board(
    callback: CallbackQuery,
    user_id: int
):
    game = games[user_id]

    kb = InlineKeyboardBuilder()

    for i in range(9):
        if i in game["opened"]:
            text = "💎"
            data = "noop"
        else:
            text = "⬜"
            data = f"mine_open_{i}"

        kb.button(
            text=text,
            callback_data=data
        )

    kb.button(
        text="💰 ЗАБРАТЬ",
        callback_data="mine_cashout"
    )

    kb.button(
        text="❌ ЗАКОНЧИТЬ",
        callback_data="mine_cancel"
    )

    kb.adjust(3)

    await callback.message.edit_text(
        "💣 <b>MINES</b>\n\n"
        f"Множитель: <b>x{game['multiplier']:.2f}</b>\n"
        f"Открыто: <b>{len(game['opened'])}</b>/6\n\n"
        "Выбирай клетку:",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(
    F.data.startswith("mine_open_")
)
async def mine_open(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра закончилась",
            show_alert=True
        )
        return

    cell = int(
        callback.data.split("_")[-1]
    )

    if cell in game["opened"]:
        await callback.answer()
        return

    if cell in game["mines"]:
        stake = game["stake"]

        games.pop(user_id, None)

        record_game(
            user_id,
            "mines",
            stake,
            0,
            {
                "result": "mine"
            }
        )

        await callback.message.edit_text(
            "💣 <b>MINES</b>\n\n"
            "💥 <b>МИНА!</b>\n\n"
            f"Потеряно: <b>{money(stake)} ₽</b>\n\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard()
        )

        await callback.answer()

        return

    game["opened"].append(cell)

    multipliers = [
        1.15,
        1.35,
        1.60,
        1.95,
        2.40,
        3.00
    ]

    index = min(
        len(game["opened"]) - 1,
        len(multipliers) - 1
    )

    game["multiplier"] = multipliers[index]

    if len(game["opened"]) >= 6:
        payout = game["stake"] * game["multiplier"]

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "mines",
            game["stake"],
            payout,
            {
                "result": "max_win"
            }
        )

        games.pop(user_id, None)

        await callback.message.edit_text(
            "💣 <b>MINES</b>\n\n"
            "🏆 <b>МАКСИМАЛЬНЫЙ ВЫИГРЫШ!</b>\n\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard()
        )

        await callback.answer()

        return

    await show_mines_board(
        callback,
        user_id
    )

    await callback.answer(
        "💎 Безопасно!"
    )


@dp.callback_query(F.data == "mine_cashout")
async def mine_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.pop(user_id, None)

    if not game:
        await callback.answer(
            "Игра закончилась",
            show_alert=True
        )
        return

    payout = game["stake"] * game["multiplier"]

    change_balance(
        user_id,
        payout
    )

    record_game(
        user_id,
        "mines",
        game["stake"],
        payout,
        {
            "result": "cashout",
            "multiplier": game["multiplier"]
        }
    )

    await callback.message.edit_text(
        "💣 <b>MINES</b>\n\n"
        "💰 <b>ВЫ ЗАБРАЛИ ВЫИГРЫШ!</b>\n\n"
        f"Множитель: <b>x{game['multiplier']:.2f}</b>\n"
        f"Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data == "mine_cancel")
async def mine_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.pop(user_id, None)

    if not game:
        await callback.answer(
            "Игра закончилась",
            show_alert=True
        )
        return

    record_game(
        user_id,
        "mines",
        game["stake"],
        0,
        {
            "result": "cancel"
        }
    )

    await callback.message.edit_text(
        "💣 <b>MINES</b>\n\n"
        "❌ Игра завершена.\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# CRASH
# =========================================================

@dp.callback_query(F.data == "game_crash")
async def crash_game(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"📈 {stake} ₽",
            callback_data=f"crash_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="games"
    )

    kb.adjust(2)

    await callback.message.edit_text(
        "📈 <b>CRASH</b>\n\n"
        "Множитель растёт.\n"
        "Забери выигрыш до краша.\n\n"
        "Выбери ставку:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("crash_")
)
async def crash_start(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    crash_point = round(
        random.expovariate(1 / 3) + 1,
        2
    )

    crash_point = max(
        CRASH_MIN,
        min(
            crash_point,
            CRASH_MAX
        )
    )

    games[user_id] = {
        "type": "crash",
        "stake": stake,
        "crash_point": crash_point,
        "multiplier": 1.0
    }

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💰 ЗАБРАТЬ",
        callback_data="crash_cashout"
    )

    kb.button(
        text="❌ ОТМЕНА",
        callback_data="crash_cancel"
    )

    await callback.message.edit_text(
        "📈 <b>CRASH</b>\n\n"
        "Множитель начинает расти...\n\n"
        "Текущий: <b>x1.00</b>",
        reply_markup=kb.as_markup()
    )

    await callback.answer()

    asyncio.create_task(
        crash_loop(user_id)
    )


async def crash_loop(user_id: int):
    while True:
        await asyncio.sleep(2)

        game = games.get(user_id)

        if not game:
            return

        game["multiplier"] += 0.25

        if (
            game["multiplier"]
            >= game["crash_point"]
        ):
            crash_point = game["crash_point"]
            stake = game["stake"]

            games.pop(user_id, None)

            record_game(
                user_id,
                "crash",
                stake,
                0,
                {
                    "crash_point": crash_point
                }
            )

            try:
                await bot.send_message(
                    user_id,
                    "📈 <b>CRASH</b>\n\n"
                    f"💥 <b>КРАШ!</b>\n\n"
                    f"Коэффициент: "
                    f"<b>x{crash_point:.2f}</b>\n\n"
                    f"Потеряно: "
                    f"<b>{money(stake)} ₽</b>\n\n"
                    f"💳 Баланс: "
                    f"<b>{money(get_balance(user_id))} ₽</b>",
                    reply_markup=after_game_keyboard()
                )
            except Exception as error:
                print(
                    "CRASH MESSAGE ERROR:",
                    error
                )

            return

        try:
            kb = InlineKeyboardBuilder()

            kb.button(
                text="💰 ЗАБРАТЬ",
                callback_data="crash_cashout"
            )

            kb.button(
                text="❌ ОТМЕНА",
                callback_data="crash_cancel"
            )

            await bot.send_message(
                user_id,
                "📈 <b>CRASH</b>\n\n"
                f"Текущий множитель: "
                f"<b>x{game['multiplier']:.2f}</b>",
                reply_markup=kb.as_markup()
            )
        except Exception as error:
            print(
                "CRASH UPDATE ERROR:",
                error
            )


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.pop(user_id, None)

    if not game:
        await callback.answer(
            "Игра уже закончилась",
            show_alert=True
        )
        return

    multiplier = game["multiplier"]

    payout = (
        game["stake"]
        * multiplier
    )

    change_balance(
        user_id,
        payout
    )

    record_game(
        user_id,
        "crash",
        game["stake"],
        payout,
        {
            "result": "cashout",
            "multiplier": multiplier
        }
    )

    await callback.message.edit_text(
        "📈 <b>CRASH</b>\n\n"
        "💰 <b>ВЫ ЗАБРАЛИ ВЫИГРЫШ!</b>\n\n"
        f"Множитель: <b>x{multiplier:.2f}</b>\n"
        f"Выигрыш: <b>+{money(payout)} ₽</b>\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id

    game = games.pop(user_id, None)

    if not game:
        await callback.answer(
            "Игра уже закончилась",
            show_alert=True
        )
        return

    record_game(
        user_id,
        "crash",
        game["stake"],
        0,
        {
            "result": "cancel"
        }
    )

    await callback.message.edit_text(
        "📈 <b>CRASH</b>\n\n"
        "❌ Игра отменена.\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>",
        reply_markup=after_game_keyboard()
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id

    balance = get_balance(user_id)
    stats = get_user_stats(user_id)

    await callback.message.edit_text(
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💳 Баланс: <b>{money(balance)} ₽</b>\n\n"
        f"🎮 Игр: <b>{stats['games']}</b>\n"
        f"🏆 Побед: <b>{stats['wins']}</b>\n"
        f"💰 Всего ставок: "
        f"<b>{money(stats['total_bet'])} ₽</b>\n"
        f"💵 Всего выиграно: "
        f"<b>{money(stats['total_win'])} ₽</b>",
        reply_markup=profile_keyboard()
    )

    await callback.answer()


def profile_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="📜 ИСТОРИЯ",
        callback_data="history"
    )

    kb.button(
        text="🗑 ОЧИСТИТЬ ИСТОРИЮ",
        callback_data="clear_history"
    )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="main"
    )

    kb.adjust(1)

    return kb.as_markup()


@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):
    user_id = callback.from_user.id

    rows = get_game_history(
        user_id,
        15
    )

    if not rows:
        text = (
            "📜 <b>ИСТОРИЯ</b>\n\n"
            "История пока пустая."
        )
    else:
        text = "📜 <b>ИСТОРИЯ</b>\n\n"

        for row in rows:
            text += (
                f"🎮 {row['game']} | "
                f"ставка {money(row['bet'])} ₽ | "
                f"выигрыш {money(row['win'])} ₽\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=profile_keyboard()
    )

    await callback.answer()


@dp.callback_query(F.data == "clear_history")
async def clear_history(callback: CallbackQuery):
    user_id = callback.from_user.id

    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute(
            "DELETE FROM game_history WHERE user_id = ?",
            (user_id,)
        )

        conn.commit()

    finally:
        conn.close()

    await callback.message.edit_text(
        "🗑 <b>ИСТОРИЯ ОЧИЩЕНА</b>\n\n"
        "История игр удалена.",
        reply_markup=profile_keyboard()
    )

    await callback.answer()


# =========================================================
# ADMIN
# =========================================================

@dp.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    kb = InlineKeyboardBuilder()

    kb.button(
        text="👤 НАЙТИ ПОЛЬЗОВАТЕЛЯ",
        callback_data="admin_search"
    )

    kb.button(
        text="◀️ НАЗАД",
        callback_data="main"
    )

    kb.adjust(1)

    await callback.message.edit_text(
        "🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выбери действие:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_search")
async def admin_search(callback: CallbackQuery):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        "👤 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
        "Отправь Telegram ID пользователя."
    )

    games[user_id] = {
        "type": "admin_search"
    }

    await callback.answer()


@dp.message()
async def catch_all(message: Message):
    user_id = message.from_user.id

    admin_state = games.get(user_id)

    if (
        admin_state
        and admin_state.get("type") == "admin_search"
        and is_admin(user_id)
    ):
        try:
            target_id = int(
                message.text.strip()
            )
        except Exception:
            await message.answer(
                "❌ Введи корректный Telegram ID."
            )
            return

        games.pop(user_id, None)

        balance = get_balance(target_id)
        stats = get_user_stats(target_id)

        await message.answer(
            "👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
            f"🆔 ID: <code>{target_id}</code>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>\n\n"
            f"🎮 Игр: <b>{stats['games']}</b>\n"
            f"🏆 Побед: <b>{stats['wins']}</b>\n"
            f"💰 Ставок: "
            f"<b>{money(stats['total_bet'])} ₽</b>\n"
            f"💵 Выиграно: "
            f"<b>{money(stats['total_win'])} ₽</b>"
        )

        return

    await message.answer(
        "Используй меню ниже:",
        reply_markup=main_keyboard(user_id)
    )


# =========================================================
# STARTUP / SHUTDOWN
# =========================================================

@app.on_event("startup")
async def startup():
    init_db()

    try:
        await bot.set_webhook(
            WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET
        )

        print(
            "Webhook set:",
            WEBHOOK_URL
        )

    except Exception as error:
        print(
            "WEBHOOK ERROR:",
            error
        )


@app.on_event("shutdown")
async def shutdown():
    try:
        await bot.delete_webhook()
    except Exception:
        pass

    await bot.session.close()


# =========================================================
# WEBHOOK
# =========================================================

@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request
):
    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:
        return {
            "ok": False,
            "error": "unauthorized"
        }

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
# HEALTH
# =========================================================

@app.get("/")
async def health():
    return {
        "status": "ok",
        "bot": "Resonant Casino"
    }


# =========================================================
# LOCAL START
# =========================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", 8000)
        )
    )
