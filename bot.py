import asyncio
import os
import random

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
    ensure_user,
    get_balance,
    change_balance,
    subtract_balance,
    get_user_stats,
    get_game_history,
    get_payment_history,
    record_game,

    create_withdrawal,
    get_withdrawal,
    get_pending_withdrawals,
    get_withdrawal_history,
    approve_withdrawal,
    reject_withdrawal,
    complete_withdrawal,
)

from payments import (
    create_invoice,
    process_paid_invoice,
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

# 1 USDT = 80 ₽
# Минимальный вывод = 1 USDT
MIN_WITHDRAWAL = 80


# =========================================================
# PREMIUM UI / HELPERS
# =========================================================

def money(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def safe_user_id(message: Message) -> int:
    return message.from_user.id


async def edit_or_answer(
    callback: CallbackQuery,
    text: str,
    keyboard=None
):
    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=keyboard
        )


def main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎰  ИГРЫ",
        callback_data="games"
    )

    builder.button(
        text="💰  БАЛАНС",
        callback_data="wallet"
    )

    builder.button(
        text="👤  ПРОФИЛЬ",
        callback_data="profile"
    )

    builder.button(
        text="💳  ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    builder.button(
        text="💸  ВЫВЕСТИ",
        callback_data="withdraw"
    )

    builder.adjust(2)

    if is_admin(user_id):
        builder.button(
            text="🛠  ADMIN PANEL",
            callback_data="admin"
        )

    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎲  КУБИК",
        callback_data="game_dice"
    )

    builder.button(
        text="🎲🎲  ДВА КУБИКА",
        callback_data="game_two_dice"
    )

    builder.button(
        text="🎰  СЛОТЫ",
        callback_data="game_slots"
    )

    builder.button(
        text="🎳  БОУЛИНГ",
        callback_data="game_bowling"
    )

    builder.button(
        text="🎡  РУЛЕТКА",
        callback_data="game_roulette"
    )

    builder.button(
        text="💣  MINES",
        callback_data="game_mines"
    )

    builder.button(
        text="🚀  CRASH",
        callback_data="game_crash"
    )

    builder.button(
        text="⬅️  ГЛАВНОЕ МЕНЮ",
        callback_data="back_main"
    )

    builder.adjust(2)

    return builder.as_markup()


def stake_keyboard(prefix: str):
    builder = InlineKeyboardBuilder()

    for stake in STAKES:
        builder.button(
            text=f"💎  {money(stake)} ₽",
            callback_data=f"{prefix}_stake_{stake}"
        )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="games"
    )

    builder.adjust(2)

    return builder.as_markup()


def confirm_bet_keyboard(game: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💎  ПОДТВЕРДИТЬ СТАВКУ",
        callback_data=f"confirm_{game}"
    )

    builder.button(
        text="✕  ОТМЕНА",
        callback_data="games"
    )

    builder.adjust(1)

    return builder.as_markup()


def wallet_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💳  ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    builder.button(
        text="💸  ВЫВЕСТИ",
        callback_data="withdraw"
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="back_main"
    )

    builder.adjust(1)

    return builder.as_markup()


def after_game_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔄  ЕЩЁ РАЗ",
        callback_data="games"
    )

    builder.button(
        text="💰  БАЛАНС",
        callback_data="wallet"
    )

    builder.button(
        text="🏠  ГЛАВНОЕ МЕНЮ",
        callback_data="back_main"
    )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# SLOT DECODER
# =========================================================

def slot_symbols_from_value(value: int):
    """
    Логика Telegram для 🎰.

    value == 64:
        777

    Для остальных значений Telegram
    извлекает три 2-битных значения.

    raw 0 -> BAR
    raw 1 -> BERRIES
    raw 2 -> LEMON
    raw 3 -> SEVEN
    """

    value = int(value)

    if value < 1 or value > 64:
        return ["❓", "❓", "❓"]

    if value == 64:
        return [
            "7️⃣",
            "7️⃣",
            "7️⃣",
        ]

    symbols = [
        "🍸",
        "🍇",
        "🍋",
        "7️⃣",
    ]

    left_raw = (value - 1) & 0x03

    center_raw = (
        (value - 1) >> 2
    ) & 0x03

    right_raw = (
        (value - 1) >> 4
    ) & 0x03

    return [
        symbols[left_raw],
        symbols[center_raw],
        symbols[right_raw],
    ]


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = safe_user_id(message)

    ensure_user(user_id)

    await message.answer(
        "╔══════════════════════╗\n"
        "      🎰 <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "╚══════════════════════╝\n\n"
        "💎 <b>VIP GAMING CLUB</b>\n\n"
        "💰 <b>ДОСТУПНЫЙ БАЛАНС</b>\n"
        f"<b>{money(get_balance(user_id))} ₽</b>\n\n"
        "◆ ИГРЫ\n"
        "◆ СТАВКИ\n"
        "◆ ВЫИГРЫШИ\n\n"
        "Выберите действие 👇",
        reply_markup=main_keyboard(user_id)
    )


# =========================================================
# MAIN MENU
# =========================================================

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.answer()

    await edit_or_answer(
        callback,
        "╔══════════════════════╗\n"
        "      🎰 <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "╚══════════════════════╝\n\n"
        "💎 <b>VIP GAMING CLUB</b>\n\n"
        "💰 <b>ДОСТУПНЫЙ БАЛАНС</b>\n"
        f"<b>{money(get_balance(user_id))} ₽</b>\n\n"
        "Выберите действие 👇",
        main_keyboard(user_id)
    )


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "games")
async def games_handler(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎰 <b>GAMES</b>\n"
        "╰────────────────────╯\n\n"
        "💎 <b>ВЫБЕРИТЕ ИГРУ</b>\n\n"
        "🎲 Азарт • 🎰 Удача • 🚀 Риск\n\n"
        "Ставка списывается только после подтверждения.",
        games_keyboard()
    )


# =========================================================
# WALLET
# =========================================================

@dp.callback_query(F.data == "wallet")
async def wallet_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.answer()

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💎 <b>WALLET</b>\n"
        "╰────────────────────╯\n\n"
        "💰 <b>ДОСТУПНО</b>\n\n"
        f"      <b>{money(balance)} ₽</b>\n\n"
        "◆ Пополняйте баланс\n"
        "◆ Играйте в мини-игры\n"
        "◆ Вывод от 80 ₽",
        wallet_keyboard()
    )


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.answer()

    stats = get_user_stats(user_id)

    winrate = 0

    if stats["games_played"] > 0:
        winrate = round(
            stats["wins"] / stats["games_played"] * 100,
            1
        )

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📜  ИСТОРИЯ ИГР",
        callback_data="my_history"
    )

    builder.button(
        text="💳  ПЛАТЕЖИ",
        callback_data="my_payments"
    )

    builder.button(
        text="💸  МОИ ВЫВОДЫ",
        callback_data="my_withdrawals"
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="back_main"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       👤 <b>PROFILE</b>\n"
        "╰────────────────────╯\n\n"
        "💎 <b>BALANCE</b>\n"
        f"<b>{money(stats['balance'])} ₽</b>\n\n"
        f"🎮 ИГРЫ        <b>{stats['games_played']}</b>\n"
        f"🏆 ПОБЕДЫ      <b>{stats['wins']}</b>\n"
        f"❌ ПОРАЖЕНИЯ   <b>{stats['losses']}</b>\n"
        f"📈 WINRATE     <b>{winrate}%</b>\n\n"
        f"💵 СТАВКИ      <b>{money(stats['total_bet'])} ₽</b>\n"
        f"🏆 ВЫИГРАНО    <b>{money(stats['total_won'])} ₽</b>\n"
        f"🔥 MAX WIN     <b>{money(stats['biggest_win'])} ₽</b>",
        builder.as_markup()
    )


# =========================================================
# USER GAME HISTORY
# =========================================================

@dp.callback_query(F.data == "my_history")
async def my_history_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.answer()

    history = get_game_history(user_id, 10)

    if not history:
        text = (
            "📜 <b>GAME HISTORY</b>\n\n"
            "Пока игр нет."
        )
    else:
        lines = [
            "📜 <b>GAME HISTORY</b>\n"
        ]

        for item in history:
            result = (
                "✅"
                if item["result"] == "win"
                else "❌"
            )

            lines.append(
                f"{result} "
                f"{item['game']} — "
                f"{money(item['stake'])} ₽ → "
                f"{money(item['payout'])} ₽"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️  ПРОФИЛЬ",
        callback_data="profile"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# USER PAYMENTS
# =========================================================

@dp.callback_query(F.data == "my_payments")
async def my_payments_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.answer()

    history = get_payment_history(user_id, 10)

    if not history:
        text = (
            "💳 <b>PAYMENTS</b>\n\n"
            "Платежей пока нет."
        )
    else:
        lines = [
            "💳 <b>PAYMENT HISTORY</b>\n"
        ]

        for item in history:
            lines.append(
                f"💵 {item['amount_usdt']} USDT → "
                f"{money(item['amount_rub'])} ₽\n"
                f"🧾 #{item['invoice_id']}"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️  ПРОФИЛЬ",
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
async def deposit_handler(callback: CallbackQuery):
    await callback.answer()

    builder = InlineKeyboardBuilder()

    for amount in [1, 5, 10, 25, 50, 100]:
        builder.button(
            text=f"💳  {amount} USDT",
            callback_data=f"deposit_{amount}"
        )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="wallet"
    )

    builder.adjust(2)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💳 <b>DEPOSIT</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите сумму пополнения в USDT.\n\n"
        "💎 Курс бота: <b>1 USDT = 80 ₽</b>",
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("deposit_"))
async def deposit_create_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    amount_text = callback.data.split("_", 1)[1]

    try:
        amount_usdt = float(amount_text)
    except Exception:
        await callback.answer(
            "Ошибка суммы",
            show_alert=True
        )
        return

    await callback.answer()

    try:
        invoice = await create_invoice(
            user_id,
            amount_usdt
        )
    except Exception as error:
        print(
            "CREATE INVOICE ERROR:",
            repr(error)
        )

        await callback.message.answer(
            "❌ Не удалось создать счёт.\n"
            "Попробуйте ещё раз."
        )
        return

    pay_url = invoice.get("pay_url")

    builder = InlineKeyboardBuilder()

    if pay_url:
        builder.button(
            text="💳  ОПЛАТИТЬ",
            url=pay_url
        )

    builder.button(
        text="🔄  ПРОВЕРИТЬ ОПЛАТУ",
        callback_data=(
            f"check_payment_{invoice['invoice_id']}"
        )
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="wallet"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💳 <b>INVOICE</b>\n"
        "╰────────────────────╯\n\n"
        f"💵 Сумма: <b>{amount_usdt} USDT</b>\n"
        f"💰 Начисление: "
        f"<b>{money(int(round(amount_usdt * 80)))} ₽</b>\n\n"
        f"🧾 Invoice ID: "
        f"<code>{invoice['invoice_id']}</code>\n\n"
        "После оплаты нажмите "
        "«ПРОВЕРИТЬ ОПЛАТУ».",
        builder.as_markup()
    )


# =========================================================
# CHECK PAYMENT
# =========================================================

@dp.callback_query(
    F.data.startswith("check_payment_")
)
async def check_payment_handler(
    callback: CallbackQuery
):
    invoice_id = int(
        callback.data.split("_")[-1]
    )

    await callback.answer(
        "Проверяю оплату..."
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
            text = (
                "⚠️ <b>ПЛАТЁЖ УЖЕ ОБРАБОТАН</b>\n\n"
                "Если баланс не обновился, "
                "обратитесь к администратору."
            )
        else:
            text = (
                "⏳ <b>ОПЛАТА НЕ НАЙДЕНА</b>\n\n"
                f"Статус: <code>{status}</code>\n\n"
                "Если вы уже оплатили, "
                "подождите несколько секунд "
                "и проверьте снова."
            )

        await callback.message.answer(text)
        return

    await callback.message.answer(
        "╭────────────────────╮\n"
        "       💎 <b>PAYMENT OK</b>\n"
        "╰────────────────────╯\n\n"
        "✅ <b>ОПЛАТА ПОЛУЧЕНА</b>\n\n"
        f"💵 {result['amount_usdt']} USDT\n"
        f"💰 Начислено: "
        f"<b>{money(result['amount_rub'])} ₽</b>\n"
        f"💳 Баланс: "
        f"<b>{money(result['balance'])} ₽</b>",
        reply_markup=main_keyboard(
            callback.from_user.id
        )
    )


# =========================================================
# DICE
# =========================================================

@dp.callback_query(F.data == "game_dice")
async def dice_start(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎲 <b>DICE</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите ставку:",
        stake_keyboard("dice")
    )


@dp.callback_query(F.data.startswith("dice_stake_"))
async def dice_stake(callback: CallbackQuery):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "dice",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬆️  БОЛЬШЕ 3",
        callback_data="dice_more"
    )

    builder.button(
        text="⬇️  МЕНЬШЕ 4",
        callback_data="dice_less"
    )

    builder.button(
        text="🎯  РОВНО 2",
        callback_data="dice_two"
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="game_dice"
    )

    builder.adjust(1)

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎲 <b>DICE</b>\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "Выберите прогноз:",
        builder.as_markup()
    )


@dp.callback_query(
    F.data.in_(
        {
            "dice_more",
            "dice_less",
            "dice_two"
        }
    )
)
async def dice_prediction(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if user_id not in games:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    prediction = {
        "dice_more": "more",
        "dice_less": "less",
        "dice_two": "two"
    }[callback.data]

    games[user_id]["prediction"] = prediction

    stake = games[user_id]["stake"]

    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎲 <b>DICE</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n"
        f"🎯 Прогноз: <b>{prediction}</b>\n\n"
        "Подтвердить ставку?",
        confirm_bet_keyboard("dice")
    )


@dp.callback_query(F.data == "confirm_dice")
async def confirm_dice(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    await callback.answer()

    dice = await callback.message.answer_dice(
        emoji="🎲"
    )

    await asyncio.sleep(3)

    value = dice.dice.value
    prediction = game["prediction"]

    won = False

    if prediction == "more":
        won = value > 3

    elif prediction == "less":
        won = value < 4

    elif prediction == "two":
        won = value == 2

    if won:
        multiplier = 2
        payout = stake * multiplier

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

        text = (
            "╭────────────────────╮\n"
            "       🏆 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎲 Выпало: <b>{value}</b>\n\n"
            "✅ <b>ПОБЕДА</b>\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    else:
        record_game(
            user_id,
            "dice",
            stake,
            "loss",
            0,
            0
        )

        text = (
            "╭────────────────────╮\n"
            "       💥 <b>LOSS</b>\n"
            "╰────────────────────╯\n\n"
            f"🎲 Выпало: <b>{value}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# TWO DICE
# =========================================================

@dp.callback_query(F.data == "game_two_dice")
async def two_dice_start(
    callback: CallbackQuery
):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "      🎲🎲 <b>TWO DICE</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите ставку:",
        stake_keyboard("two_dice")
    )


@dp.callback_query(
    F.data.startswith("two_dice_stake_")
)
async def two_dice_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "two_dice",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬆️  СУММА 8–12",
        callback_data="two_dice_high"
    )

    builder.button(
        text="⬇️  СУММА 2–6",
        callback_data="two_dice_low"
    )

    builder.button(
        text="🎯  РОВНО 7",
        callback_data="two_dice_seven"
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="game_two_dice"
    )

    builder.adjust(1)

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎲🎲 <b>TWO DICE</b>\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "Выберите прогноз:",
        builder.as_markup()
    )


@dp.callback_query(
    F.data.in_(
        {
            "two_dice_high",
            "two_dice_low",
            "two_dice_seven"
        }
    )
)
async def two_dice_prediction(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    prediction = callback.data.replace(
        "two_dice_",
        ""
    )

    game["prediction"] = prediction

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎲🎲 <b>TWO DICE</b>\n\n"
        f"💎 Ставка: "
        f"<b>{money(game['stake'])} ₽</b>\n"
        f"🎯 Прогноз: <b>{prediction}</b>\n\n"
        "Подтвердить?",
        confirm_bet_keyboard("two_dice")
    )


@dp.callback_query(F.data == "confirm_two_dice")
async def confirm_two_dice(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    await callback.answer()

    dice1 = await callback.message.answer_dice(
        emoji="🎲"
    )

    dice2 = await callback.message.answer_dice(
        emoji="🎲"
    )

    await asyncio.sleep(3)

    value1 = dice1.dice.value
    value2 = dice2.dice.value

    total = value1 + value2

    prediction = game["prediction"]

    won = False

    if prediction == "high":
        won = total >= 8

    elif prediction == "low":
        won = total <= 6

    elif prediction == "seven":
        won = total == 7

    if won:
        multiplier = 2
        payout = stake * multiplier

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "two_dice",
            stake,
            "win",
            multiplier,
            payout
        )

        text = (
            "╭────────────────────╮\n"
            "       🏆 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎲 {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            "✅ <b>ПОБЕДА</b>\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    else:
        record_game(
            user_id,
            "two_dice",
            stake,
            "loss",
            0,
            0
        )

        text = (
            "╭────────────────────╮\n"
            "       💥 <b>LOSS</b>\n"
            "╰────────────────────╯\n\n"
            f"🎲 {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# SLOTS
# =========================================================

@dp.callback_query(F.data == "game_slots")
async def slots_start(
    callback: CallbackQuery
):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎰 <b>SLOTS</b>\n"
        "╰────────────────────╯\n\n"
        "Три символа вращаются прямо "
        "в Telegram.\n\n"
        "Выберите ставку:",
        stake_keyboard("slots")
    )


@dp.callback_query(
    F.data.startswith("slots_stake_")
)
async def slots_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "slots",
        "stake": stake
    }

    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎰 <b>SLOTS</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "🍋🍋🍋 — ×10\n"
        "7️⃣7️⃣7️⃣ — ×50\n"
        "Другие комбинации — проигрыш.\n\n"
        "Подтвердить ставку?",
        confirm_bet_keyboard("slots")
    )


@dp.callback_query(F.data == "confirm_slots")
async def confirm_slots(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    await callback.answer()

    dice = await callback.message.answer_dice(
        emoji="🎰"
    )

    await asyncio.sleep(4)

    value = dice.dice.value

    symbols = slot_symbols_from_value(value)

    print(
        "SLOT RESULT:",
        {
            "value": value,
            "symbols": symbols
        }
    )

    display_result = " | ".join(symbols)

    if value == 64:
        multiplier = SLOT_SEVEN_MULTIPLIER
        payout = stake * multiplier

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

        text = (
            "╔══════════════════════╗\n"
            "       🔥 <b>JACKPOT</b>\n"
            "╚══════════════════════╝\n\n"
            f"🎰 <b>{display_result}</b>\n\n"
            "🔥 <b>777 — ДЖЕКПОТ!</b>\n\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    elif (
        symbols[0] == "🍋"
        and symbols[1] == "🍋"
        and symbols[2] == "🍋"
    ):
        multiplier = 10
        payout = stake * multiplier

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

        text = (
            "╭────────────────────╮\n"
            "       🍋 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎰 <b>{display_result}</b>\n\n"
            "🍋 <b>ТРИ ЛИМОНА</b>\n\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
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

        text = (
            "╭────────────────────╮\n"
            "       💥 <b>LOSS</b>\n"
            "╰────────────────────╯\n\n"
            f"🎰 <b>{display_result}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# BOWLING
# =========================================================

@dp.callback_query(F.data == "game_bowling")
async def bowling_start(
    callback: CallbackQuery
):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎳 <b>BOWLING</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите ставку:",
        stake_keyboard("bowling")
    )


@dp.callback_query(
    F.data.startswith("bowling_stake_")
)
async def bowling_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "bowling",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎳  ПОПАЛ",
        callback_data="bowling_hit"
    )

    builder.button(
        text="💨  ПРОМАХ",
        callback_data="bowling_miss"
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="game_bowling"
    )

    builder.adjust(1)

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎳 <b>BOWLING</b>\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "Выберите прогноз:",
        builder.as_markup()
    )


@dp.callback_query(
    F.data.in_(
        {
            "bowling_hit",
            "bowling_miss"
        }
    )
)
async def bowling_prediction(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    game["prediction"] = callback.data.replace(
        "bowling_",
        ""
    )

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎳 <b>BOWLING</b>\n\n"
        f"💎 Ставка: "
        f"<b>{money(game['stake'])} ₽</b>\n"
        f"🎯 Прогноз: <b>{game['prediction']}</b>\n\n"
        "Подтвердить?",
        confirm_bet_keyboard("bowling")
    )


@dp.callback_query(F.data == "confirm_bowling")
async def confirm_bowling(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    await callback.answer()

    dice = await callback.message.answer_dice(
        emoji="🎳"
    )

    await asyncio.sleep(3)

    value = dice.dice.value

    hit = value >= 4

    won = (
        hit
        if game["prediction"] == "hit"
        else not hit
    )

    if won:
        multiplier = 2
        payout = stake * multiplier

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

        text = (
            "╭────────────────────╮\n"
            "       🏆 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎳 Результат: <b>{value}</b>\n\n"
            "✅ <b>ПОБЕДА</b>\n"
            f"💰 +{money(payout)} ₽\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    else:
        record_game(
            user_id,
            "bowling",
            stake,
            "loss",
            0,
            0
        )

        text = (
            "╭────────────────────╮\n"
            "       💥 <b>LOSS</b>\n"
            "╰────────────────────╯\n\n"
            f"🎳 Результат: <b>{value}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    games.pop(user_id, None)

    await callback.message.answer(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# ROULETTE
# =========================================================

@dp.callback_query(F.data == "game_roulette")
async def roulette_start(
    callback: CallbackQuery
):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎡 <b>ROULETTE</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите ставку:",
        stake_keyboard("roulette")
    )


@dp.callback_query(
    F.data.startswith("roulette_stake_")
)
async def roulette_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "roulette",
        "stake": stake
    }

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔴  КРАСНОЕ",
        callback_data="roulette_red"
    )

    builder.button(
        text="⚫  ЧЁРНОЕ",
        callback_data="roulette_black"
    )

    builder.button(
        text="🟢  ZERO",
        callback_data="roulette_zero"
    )

    builder.button(
        text="⬅️  НАЗАД",
        callback_data="game_roulette"
    )

    builder.adjust(1)

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎡 <b>ROULETTE</b>\n\n"
        f"💎 Ставка: "
        f"<b>{money(stake)} ₽</b>\n\n"
        "Выберите цвет:",
        builder.as_markup()
    )


@dp.callback_query(
    F.data.in_(
        {
            "roulette_red",
            "roulette_black",
            "roulette_zero"
        }
    )
)
async def roulette_color(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    game["color"] = callback.data.replace(
        "roulette_",
        ""
    )

    await callback.answer()

    await edit_or_answer(
        callback,
        f"🎡 <b>ROULETTE</b>\n\n"
        f"💎 Ставка: "
        f"<b>{money(game['stake'])} ₽</b>\n"
        f"🎯 Выбор: <b>{game['color']}</b>\n\n"
        "Подтвердить?",
        confirm_bet_keyboard("roulette")
    )


@dp.callback_query(F.data == "confirm_roulette")
async def confirm_roulette(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "Недостаточно средств",
            show_alert=True
        )
        return

    await callback.answer()

    message = callback.message

    animation = [
        "🎡 🔴 ⚫ 🟢 ⚫ 🔴",
        "🎡 ⚫ 🔴 ⚫ 🟢 🔴",
        "🎡 🔴 🟢 ⚫ 🔴 ⚫",
        "🎡 ⚫ 🔴 🟢 ⚫ 🔴",
        "🎡 🔴 ⚫ 🔴 🟢 ⚫",
    ]

    for frame in animation:
        try:
            await message.edit_text(frame)
        except Exception:
            pass

        await asyncio.sleep(0.35)

    number = random.randint(
        0,
        36
    )

    if number == 0:
        result_color = "zero"

    elif number in {
        1, 3, 5, 7, 9,
        12, 14, 16, 18,
        19, 21, 23, 25,
        27, 30, 32, 34, 36
    }:
        result_color = "red"

    else:
        result_color = "black"

    won = (
        game["color"] == result_color
    )

    if won:
        multiplier = (
            35
            if result_color == "zero"
            else 2
        )

        payout = stake * multiplier

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

        emoji = (
            "🟢"
            if result_color == "zero"
            else "🔴"
            if result_color == "red"
            else "⚫"
        )

        text = (
            "╭────────────────────╮\n"
            "       🏆 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎡 Выпало: <b>{number}</b> "
            f"{emoji}\n\n"
            "✅ <b>ПОБЕДА</b>\n"
            f"💰 +{money(payout)} ₽\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    else:
        record_game(
            user_id,
            "roulette",
            stake,
            "loss",
            0,
            0
        )

        text = (
            "╭────────────────────╮\n"
            "       💥 <b>LOSS</b>\n"
            "╰────────────────────╯\n\n"
            f"🎡 Выпало: <b>{number}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )

    games.pop(user_id, None)

    await message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# MINES
# =========================================================

@dp.callback_query(F.data == "game_mines")
async def mines_start(
    callback: CallbackQuery
):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        "На поле 9 клеток.\n"
        "2 из них — мины.\n\n"
        "Выберите ставку:",
        stake_keyboard("mines")
    )


@dp.callback_query(
    F.data.startswith("mines_stake_")
)
async def mines_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "mines",
        "stake": stake
    }

    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "Подтвердить ставку?",
        confirm_bet_keyboard("mines")
    )


def mines_keyboard(user_id: int):
    game = games.get(user_id)

    builder = InlineKeyboardBuilder()

    opened = (
        game.get("opened", [])
        if game
        else []
    )

    for i in range(9):
        text = (
            "💎"
            if i in opened
            else "⬜"
        )

        builder.button(
            text=text,
            callback_data=f"mine_{i}"
        )

    builder.button(
        text="💰  ЗАБРАТЬ",
        callback_data="mine_cashout"
    )

    builder.adjust(3)

    return builder.as_markup()


@dp.callback_query(F.data == "confirm_mines")
async def confirm_mines(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

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
        2
    )

    game["mines"] = mines
    game["opened"] = []
    game["multiplier"] = 1.0

    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n"
        "💎 Открывайте клетки 👇",
        mines_keyboard(user_id)
    )


@dp.callback_query(F.data.startswith("mine_"))
async def mine_click(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    action = callback.data.split("_")[1]

    if action == "cashout":
        multiplier = game["multiplier"]
        stake = game["stake"]

        payout = int(
            round(
                stake * multiplier
            )
        )

        change_balance(
            user_id,
            payout
        )

        record_game(
            user_id,
            "mines",
            stake,
            "win",
            multiplier,
            payout
        )

        games.pop(
            user_id,
            None
        )

        await callback.answer()

        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💎 <b>MINES</b>\n"
            "╰────────────────────╯\n\n"
            "💰 <b>ВЫ ЗАБРАЛИ ВЫИГРЫШ</b>\n\n"
            f"📈 Множитель: "
            f"<b>x{multiplier:.2f}</b>\n"
            f"💵 Выигрыш: "
            f"<b>{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>",
            after_game_keyboard()
        )

        return

    index = int(action)

    if index in game["opened"]:
        await callback.answer(
            "Эта клетка уже открыта"
        )
        return

    if index in game["mines"]:
        stake = game["stake"]

        record_game(
            user_id,
            "mines",
            stake,
            "loss",
            0,
            0
        )

        games.pop(
            user_id,
            None
        )

        await callback.answer(
            "💥 БУМ!",
            show_alert=True
        )

        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💥 <b>MINES</b>\n"
            "╰────────────────────╯\n\n"
            "💣 <b>МИНА!</b>\n\n"
            "❌ Ты проиграл.\n\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>",
            after_game_keyboard()
        )

        return

    game["opened"].append(index)

    game["multiplier"] += 0.35

    await callback.answer(
        f"💎 x{game['multiplier']:.2f}"
    )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        f"📈 Множитель: "
        f"<b>x{game['multiplier']:.2f}</b>\n"
        f"💰 Забрать: "
        f"<b>{money(int(game['stake'] * game['multiplier']))} ₽</b>",
        mines_keyboard(user_id)
    )


# =========================================================
# CRASH
# =========================================================

@dp.callback_query(F.data == "game_crash")
async def crash_start(
    callback: CallbackQuery
):
    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🚀 <b>CRASH</b>\n"
        "╰────────────────────╯\n\n"
        "Множитель растёт каждую секунду.\n"
        "Нажмите «💰 ЗАБРАТЬ», "
        "пока самолёт не разбился.\n\n"
        "Выберите ставку:",
        stake_keyboard("crash")
    )


@dp.callback_query(
    F.data.startswith("crash_stake_")
)
async def crash_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    stake = int(
        callback.data.split("_")[-1]
    )

    games[user_id] = {
        "type": "crash",
        "stake": stake
    }

    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🚀 <b>CRASH</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: "
        f"<b>{money(stake)} ₽</b>\n\n"
        "Самолёт будет набирать множитель.\n"
        "Ваша задача — забрать выигрыш "
        "до CRASH.\n\n"
        "Подтвердить ставку?",
        confirm_bet_keyboard("crash")
    )


def crash_keyboard(multiplier: float):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"💰  ЗАБРАТЬ x{multiplier:.2f}",
        callback_data="crash_cashout"
    )

    builder.button(
        text="❌  СДАТЬСЯ",
        callback_data="crash_giveup"
    )

    builder.adjust(1)

    return builder.as_markup()


async def run_crash_game(
    user_id: int,
    message,
    crash_point: float
):
    try:
        multiplier = 1.00

        if user_id in games:
            games[user_id]["multiplier"] = multiplier
            games[user_id]["crash_point"] = crash_point

        while True:
            game = games.get(user_id)

            if not game:
                return

            if game.get("crash_finished"):
                return

            if multiplier >= crash_point:
                break

            games[user_id]["multiplier"] = round(
                multiplier,
                2
            )

            try:
                await message.edit_text(
                    "╭────────────────────╮\n"
                    "       🚀 <b>CRASH</b>\n"
                    "╰────────────────────╯\n\n"
                    "✈️ Самолёт летит...\n\n"
                    f"📈 Множитель: "
                    f"<b>x{multiplier:.2f}</b>\n\n"
                    "💰 Успейте забрать выигрыш!",
                    reply_markup=crash_keyboard(
                        multiplier
                    )
                )
            except Exception as error:
                print(
                    "CRASH EDIT ERROR:",
                    repr(error)
                )

            await asyncio.sleep(0.55)

            if multiplier < 2:
                multiplier += 0.08

            elif multiplier < 5:
                multiplier += 0.15

            elif multiplier < 10:
                multiplier += 0.25

            else:
                multiplier += 0.40

            multiplier = round(
                multiplier,
                2
            )

        game = games.get(user_id)

        if not game:
            return

        if game.get("cashed_out"):
            return

        game["crash_finished"] = True

        stake = game["stake"]

        record_game(
            user_id,
            "crash",
            stake,
            "loss",
            0,
            0
        )

        games.pop(
            user_id,
            None
        )

        try:
            await message.edit_text(
                "╭────────────────────╮\n"
                "       💥 <b>CRASH</b>\n"
                "╰────────────────────╯\n\n"
                f"📈 Самолёт разбился на "
                f"<b>x{crash_point:.2f}</b>\n\n"
                "❌ <b>Слишком поздно.</b>\n"
                "Ставка проиграна.\n\n"
                f"💳 Баланс: "
                f"<b>{money(get_balance(user_id))} ₽</b>",
                reply_markup=after_game_keyboard()
            )
        except Exception as error:
            print(
                "CRASH FINAL EDIT ERROR:",
                repr(error)
            )

    except asyncio.CancelledError:
        print(
            "CRASH TASK CANCELLED:",
            user_id
        )
        return

    except Exception as error:
        print(
            "CRASH GAME ERROR:",
            repr(error)
        )


@dp.callback_query(F.data == "confirm_crash")
async def confirm_crash(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

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
        random.uniform(
            CRASH_MIN,
            CRASH_MAX
        ),
        2
    )

    game["multiplier"] = 1.00
    game["crash_point"] = crash_point
    game["cashed_out"] = False
    game["crash_finished"] = False

    await callback.answer(
        "🚀 CRASH НАЧАЛСЯ!"
    )

    message = await callback.message.answer(
        "╭────────────────────╮\n"
        "       🚀 <b>CRASH</b>\n"
        "╰────────────────────╯\n\n"
        "✈️ Самолёт взлетел!\n\n"
        "📈 Множитель: <b>x1.00</b>\n\n"
        "💰 Успейте забрать выигрыш!",
        reply_markup=crash_keyboard(1.00)
    )

    task = asyncio.create_task(
        run_crash_game(
            user_id,
            message,
            crash_point
        )
    )

    game["task"] = task


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "💥 CRASH уже произошёл.",
            show_alert=True
        )
        return

    if game.get("crash_finished"):
        await callback.answer(
            "💥 Слишком поздно!",
            show_alert=True
        )
        return

    multiplier = float(
        game.get(
            "multiplier",
            1.00
        )
    )

    stake = int(
        game["stake"]
    )

    game["cashed_out"] = True

    payout = int(
        round(
            stake * multiplier
        )
    )

    task = game.get("task")

    if task:
        task.cancel()

    change_balance(
        user_id,
        payout
    )

    record_game(
        user_id,
        "crash",
        stake,
        "win",
        multiplier,
        payout
    )

    games.pop(
        user_id,
        None
    )

    await callback.answer(
        "💰 Выигрыш забран!"
    )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🚀 <b>CRASH</b>\n"
        "╰────────────────────╯\n\n"
        "💰 <b>ВЫ ЗАБРАЛИ ВЫИГРЫШ</b>\n\n"
        f"📈 Множитель: "
        f"<b>x{multiplier:.2f}</b>\n"
        f"💵 Выигрыш: "
        f"<b>{money(payout)} ₽</b>\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>",
        after_game_keyboard()
    )


@dp.callback_query(F.data == "crash_giveup")
async def crash_giveup(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game = games.get(user_id)

    if not game:
        await callback.answer(
            "Игра уже завершена.",
            show_alert=True
        )
        return

    task = game.get("task")

    if task:
        task.cancel()

    stake = game["stake"]

    record_game(
        user_id,
        "crash",
        stake,
        "loss",
        0,
        0
    )

    games.pop(
        user_id,
        None
    )

    await callback.answer(
        "Ставка завершена."
    )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🚀 <b>CRASH</b>\n"
        "╰────────────────────╯\n\n"
        "❌ Ты остановил игру.\n"
        "Ставка проиграна.\n\n"
        f"💳 Баланс: "
        f"<b>{money(get_balance(user_id))} ₽</b>",
        after_game_keyboard()
    )


# =========================================================
# WITHDRAWAL
# =========================================================

def withdrawal_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="❌  ОТМЕНА",
        callback_data="wallet"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "withdraw")
async def withdraw_start(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    balance = get_balance(user_id)

    await callback.answer()

    if balance < MIN_WITHDRAWAL:
        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💸 <b>WITHDRAW</b>\n"
            "╰────────────────────╯\n\n"
            f"💰 Доступно: "
            f"<b>{money(balance)} ₽</b>\n\n"
            "Минимальная сумма вывода: "
            f"<b>{money(MIN_WITHDRAWAL)} ₽</b>\n"
            "(1 USDT)",
            wallet_keyboard()
        )
        return

    games[user_id] = {
        "withdraw_action": "amount"
    }

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💸 <b>WITHDRAW</b>\n"
        "╰────────────────────╯\n\n"
        f"💰 Доступно: "
        f"<b>{money(balance)} ₽</b>\n"
        f"📉 Минимум: "
        f"<b>{money(MIN_WITHDRAWAL)} ₽</b> "
        "(1 USDT)\n\n"
        "Введите сумму вывода в рублях.\n\n"
        "Например:\n"
        "<code>5000</code>",
        withdrawal_keyboard()
    )


# =========================================================
# USER WITHDRAWAL HISTORY
# =========================================================

@dp.callback_query(F.data == "my_withdrawals")
async def my_withdrawals_handler(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    await callback.answer()

    history = get_withdrawal_history(
        user_id,
        10
    )

    if not history:
        text = (
            "💸 <b>WITHDRAWALS</b>\n\n"
            "Заявок пока нет."
        )

    else:
        lines = [
            "💸 <b>MY WITHDRAWALS</b>\n"
        ]

        status_names = {
            "pending": "⏳ Ожидает",
            "approved": "✅ Подтверждён",
            "rejected": "❌ Отклонён",
            "paid": "💸 Выплачен",
        }

        for item in history:
            status = status_names.get(
                item["status"],
                item["status"]
            )

            lines.append(
                f"#{item['id']} — "
                f"<b>{money(item['amount_rub'])} ₽</b>\n"
                f"{status}"
            )

        text = "\n\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️  ПРОФИЛЬ",
        callback_data="profile"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_main_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤  НАЙТИ ПОЛЬЗОВАТЕЛЯ",
        callback_data="admin_find_user"
    )

    builder.button(
        text="💸  ЗАЯВКИ НА ВЫВОД",
        callback_data="admin_withdrawals"
    )

    builder.button(
        text="⬅️  ГЛАВНОЕ МЕНЮ",
        callback_data="back_main"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "admin")
async def admin_panel(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    await callback.answer()

    await edit_or_answer(
        callback,
        "╔══════════════════════╗\n"
        "      🛠 <b>ADMIN PANEL</b>\n"
        "╚══════════════════════╝\n\n"
        "Системное управление.\n\n"
        "Выберите действие:",
        admin_main_keyboard()
    )


# =========================================================
# ADMIN FIND USER
# =========================================================

@dp.callback_query(F.data == "admin_find_user")
async def admin_find_user(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    games[user_id] = {
        "admin_action": "find_user"
    }

    await callback.answer()

    await callback.message.answer(
        "👤 <b>USER SEARCH</b>\n\n"
        "Отправьте Telegram ID пользователя."
    )


def admin_user_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💰  ВЫДАТЬ БАЛАНС",
        callback_data="admin_add_balance"
    )

    builder.button(
        text="➖  СНЯТЬ С БАЛАНСА",
        callback_data="admin_remove_balance"
    )

    builder.button(
        text="📊  ОБНОВИТЬ",
        callback_data="admin_refresh"
    )

    builder.button(
        text="📜  ИСТОРИЯ ИГР",
        callback_data="admin_game_history"
    )

    builder.button(
        text="💳  ИСТОРИЯ ПЛАТЕЖЕЙ",
        callback_data="admin_payment_history"
    )

    builder.button(
        text="🛠  ADMIN PANEL",
        callback_data="admin"
    )

    builder.adjust(1)

    return builder.as_markup()


async def show_admin_user(
    message: Message,
    target_id: int
):
    balance = get_balance(target_id)

    games[message.from_user.id] = {
        "admin_action": "user_menu",
        "target_user": target_id
    }

    await message.answer(
        "╭────────────────────╮\n"
        "       👤 <b>USER</b>\n"
        "╰────────────────────╯\n\n"
        f"ID: <code>{target_id}</code>\n"
        f"💰 Баланс: "
        f"<b>{money(balance)} ₽</b>",
        reply_markup=admin_user_keyboard()
    )


# =========================================================
# ADMIN BALANCE
# =========================================================

@dp.callback_query(
    F.data.in_(
        {
            "admin_add_balance",
            "admin_remove_balance"
        }
    )
)
async def admin_amount_start(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "Пользователь не выбран",
            show_alert=True
        )
        return

    action = (
        "add"
        if callback.data == "admin_add_balance"
        else "remove"
    )

    state["admin_action"] = "amount"
    state["admin_amount_action"] = action

    await callback.answer()

    text = (
        "💰 Введите сумму для выдачи:"
        if action == "add"
        else "➖ Введите сумму для снятия:"
    )

    await callback.message.answer(text)


@dp.callback_query(F.data == "admin_refresh")
async def admin_refresh(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "Пользователь не выбран",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    balance = get_balance(target_id)

    await callback.answer(
        f"Баланс: {money(balance)} ₽"
    )


# =========================================================
# ADMIN GAME HISTORY
# =========================================================

@dp.callback_query(F.data == "admin_game_history")
async def admin_game_history(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "Пользователь не выбран",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    history = get_game_history(
        target_id,
        20
    )

    if not history:
        text = (
            "📜 <b>GAME HISTORY</b>\n\n"
            "Игр нет."
        )

    else:
        lines = [
            "📜 <b>GAME HISTORY</b>\n"
        ]

        for item in history:
            result = (
                "✅"
                if item["result"] == "win"
                else "❌"
            )

            lines.append(
                f"{result} {item['game']} | "
                f"{money(item['stake'])} ₽ → "
                f"{money(item['payout'])} ₽"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤  К ПОЛЬЗОВАТЕЛЮ",
        callback_data="admin_user_back"
    )

    builder.button(
        text="🛠  ADMIN PANEL",
        callback_data="admin"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


# =========================================================
# ADMIN PAYMENT HISTORY
# =========================================================

@dp.callback_query(F.data == "admin_payment_history")
async def admin_payment_history(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "Пользователь не выбран",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    history = get_payment_history(
        target_id,
        20
    )

    if not history:
        text = (
            "💳 <b>PAYMENT HISTORY</b>\n\n"
            "Платежей нет."
        )

    else:
        lines = [
            "💳 <b>PAYMENT HISTORY</b>\n"
        ]

        for item in history:
            lines.append(
                f"💵 {item['amount_usdt']} USDT → "
                f"{money(item['amount_rub'])} ₽\n"
                f"🧾 #{item['invoice_id']}"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤  К ПОЛЬЗОВАТЕЛЮ",
        callback_data="admin_user_back"
    )

    builder.button(
        text="🛠  ADMIN PANEL",
        callback_data="admin"
    )

    await edit_or_answer(
        callback,
        text,
        builder.as_markup()
    )


@dp.callback_query(F.data == "admin_user_back")
async def admin_user_back(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "Пользователь не выбран",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    await callback.answer()

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       👤 <b>USER</b>\n"
        "╰────────────────────╯\n\n"
        f"ID: <code>{target_id}</code>\n"
        f"💰 Баланс: "
        f"<b>{money(get_balance(target_id))} ₽</b>",
        admin_user_keyboard()
    )


# =========================================================
# ADMIN WITHDRAWALS
# =========================================================

def admin_withdrawal_list_keyboard(
    withdrawals
):
    builder = InlineKeyboardBuilder()

    for item in withdrawals:
        builder.button(
            text=(
                f"#{item['id']} — "
                f"{money(item['amount_rub'])} ₽"
            ),
            callback_data=(
                f"admin_withdraw_{item['id']}"
            )
        )

    builder.button(
        text="⬅️  ADMIN PANEL",
        callback_data="admin"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(F.data == "admin_withdrawals")
async def admin_withdrawals(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    await callback.answer()

    withdrawals = get_pending_withdrawals(20)

    if not withdrawals:
        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💸 <b>WITHDRAWALS</b>\n"
            "╰────────────────────╯\n\n"
            "Ожидающих заявок нет.",
            admin_main_keyboard()
        )
        return

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💸 <b>WITHDRAWALS</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите заявку:",
        admin_withdrawal_list_keyboard(
            withdrawals
        )
    )


def admin_withdrawal_keyboard(
    withdrawal
):
    builder = InlineKeyboardBuilder()

    status = withdrawal.get("status")

    if status == "pending":
        builder.button(
            text="✅  ПОДТВЕРДИТЬ",
            callback_data=(
                f"approve_withdraw_"
                f"{withdrawal['id']}"
            )
        )

        builder.button(
            text="❌  ОТКЛОНИТЬ",
            callback_data=(
                f"reject_withdraw_"
                f"{withdrawal['id']}"
            )
        )

    elif status == "approved":
        builder.button(
            text="💸  ВЫПЛАТА ОТПРАВЛЕНА",
            callback_data=(
                f"paid_withdraw_"
                f"{withdrawal['id']}"
            )
        )

    builder.button(
        text="⬅️  К ЗАЯВКАМ",
        callback_data="admin_withdrawals"
    )

    builder.button(
        text="🛠  ADMIN PANEL",
        callback_data="admin"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(
    F.data.startswith("admin_withdraw_")
)
async def admin_withdrawal_view(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "Заявка не найдена",
            show_alert=True
        )
        return

    await callback.answer()

    status_names = {
        "pending": "⏳ ОЖИДАЕТ",
        "approved": "✅ ПОДТВЕРЖДЕНА",
        "rejected": "❌ ОТКЛОНЕНА",
        "paid": "💸 ВЫПЛАЧЕНА",
    }

    status = status_names.get(
        withdrawal.get("status"),
        withdrawal.get("status")
    )

    destination = (
        withdrawal.get("payout_details")
        or "Не указаны"
    )

    text = (
        "╭────────────────────╮\n"
        "       💸 <b>WITHDRAWAL</b>\n"
        "╰────────────────────╯\n\n"
        f"🧾 Номер: "
        f"<b>#{withdrawal['id']}</b>\n"
        f"👤 User ID: "
        f"<code>{withdrawal['user_id']}</code>\n"
        f"💰 Сумма: "
        f"<b>{money(withdrawal['amount_rub'])} ₽</b>\n"
        f"💳 Метод: <b>manual</b>\n"
        f"📍 Реквизиты:\n"
        f"<code>{destination}</code>\n\n"
        f"📌 Статус: <b>{status}</b>"
    )

    await edit_or_answer(
        callback,
        text,
        admin_withdrawal_keyboard(
            withdrawal
        )
    )


# =========================================================
# ADMIN APPROVE WITHDRAWAL
# =========================================================

@dp.callback_query(
    F.data.startswith("approve_withdraw_")
)
async def admin_approve_withdrawal(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "Заявка не найдена",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "pending":
        await callback.answer(
            "Заявка уже обработана",
            show_alert=True
        )
        return

    result = approve_withdrawal(
        withdrawal_id
    )

    if result is None:
        await callback.answer(
            "Не удалось подтвердить заявку",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    try:
        await bot.send_message(
            withdrawal["user_id"],
            "✅ <b>ВЫВОД ПОДТВЕРЖДЁН</b>\n\n"
            f"🧾 Заявка: "
            f"<b>#{withdrawal_id}</b>\n"
            f"💰 Сумма: "
            f"<b>{money(withdrawal['amount_rub'])} ₽</b>\n\n"
            "Заявка подтверждена администратором.\n"
            "Выплата будет выполнена вручную."
        )
    except Exception as error:
        print(
            "WITHDRAW APPROVE USER "
            "NOTIFICATION ERROR:",
            repr(error)
        )

    await callback.answer(
        "Заявка подтверждена"
    )

    await admin_withdrawal_view(
        callback
    )


# =========================================================
# ADMIN REJECT WITHDRAWAL
# =========================================================

@dp.callback_query(
    F.data.startswith("reject_withdraw_")
)
async def admin_reject_withdrawal(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "Заявка не найдена",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "pending":
        await callback.answer(
            "Заявка уже обработана",
            show_alert=True
        )
        return

    result = reject_withdrawal(
        withdrawal_id
    )

    if result is None:
        await callback.answer(
            "Не удалось отклонить заявку",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    try:
        await bot.send_message(
            withdrawal["user_id"],
            "❌ <b>ВЫВОД ОТКЛОНЁН</b>\n\n"
            f"🧾 Заявка: "
            f"<b>#{withdrawal_id}</b>\n"
            f"💰 Сумма: "
            f"<b>{money(withdrawal['amount_rub'])} ₽</b>\n\n"
            "Заявка отклонена.\n"
            "Зарезервированные средства "
            "возвращены на баланс."
        )
    except Exception as error:
        print(
            "WITHDRAW REJECT USER "
            "NOTIFICATION ERROR:",
            repr(error)
        )

    await callback.answer(
        "Заявка отклонена, средства возвращены"
    )

    await admin_withdrawal_view(
        callback
    )


# =========================================================
# ADMIN MARK WITHDRAWAL AS PAID
# =========================================================

@dp.callback_query(
    F.data.startswith("paid_withdraw_")
)
async def admin_paid_withdrawal(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "Заявка не найдена",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "approved":
        await callback.answer(
            "Сначала подтвердите заявку",
            show_alert=True
        )
        return

    try:
        result = complete_withdrawal(
            withdrawal_id
        )

    except Exception as error:
        print(
            "COMPLETE WITHDRAWAL ERROR:",
            repr(error)
        )

        await callback.answer(
            "Ошибка завершения выплаты",
            show_alert=True
        )
        return

    if result is None:
        await callback.answer(
            "Не удалось завершить заявку",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    try:
        await bot.send_message(
            withdrawal["user_id"],
            "💸 <b>ВЫПЛАТА ОТПРАВЛЕНА</b>\n\n"
            f"🧾 Заявка: "
            f"<b>#{withdrawal_id}</b>\n"
            f"💰 Сумма: "
            f"<b>{money(withdrawal['amount_rub'])} ₽</b>\n\n"
            "Выплата отмечена администратором "
            "как выполненная."
        )
    except Exception as error:
        print(
            "WITHDRAW PAID USER "
            "NOTIFICATION ERROR:",
            repr(error)
        )

    await callback.answer(
        "Выплата отмечена как выполненная"
    )

    await admin_withdrawal_view(
        callback
    )


# =========================================================
# WITHDRAWAL MESSAGE INPUT
# =========================================================

async def handle_withdrawal_message(
    message: Message,
    state: dict
):
    user_id = message.from_user.id

    if state.get("withdraw_action") == "amount":

        text = (
            message.text or ""
        ).strip()

        try:
            amount = int(text)

            if amount < MIN_WITHDRAWAL:
                raise ValueError

        except Exception:
            await message.answer(
                "❌ Некорректная сумма.\n\n"
                f"Минимальный вывод: "
                f"<b>{money(MIN_WITHDRAWAL)} ₽</b>\n"
                "(1 USDT)"
            )
            return True

        balance = get_balance(user_id)

        if amount > balance:
            await message.answer(
                "❌ Недостаточно средств.\n\n"
                f"💰 Ваш баланс: "
                f"<b>{money(balance)} ₽</b>"
            )
            return True

        games[user_id] = {
            "withdraw_action": "destination",
            "withdraw_amount": amount
        }

        await message.answer(
            "💳 <b>РЕКВИЗИТЫ ДЛЯ ВЫВОДА</b>\n\n"
            f"💰 Сумма: "
            f"<b>{money(amount)} ₽</b>\n\n"
            "Отправьте реквизиты, на которые "
            "нужно выполнить выплату.\n\n"
            "Например, адрес кошелька "
            "USDT TRC20."
        )

        return True

    if state.get("withdraw_action") == "destination":

        destination = (
            message.text or ""
        ).strip()

        if len(destination) < 5:
            await message.answer(
                "❌ Реквизиты слишком короткие.\n"
                "Проверьте и отправьте ещё раз."
            )
            return True

        amount = state.get(
            "withdraw_amount"
        )

        if not amount:
            games.pop(
                user_id,
                None
            )

            await message.answer(
                "❌ Заявка устарела.\n"
                "Создайте вывод заново."
            )
            return True

        try:
            withdrawal = create_withdrawal(
                user_id=user_id,
                amount_rub=amount,
                payout_details=destination
            )

        except Exception as error:
            print(
                "CREATE WITHDRAWAL ERROR:",
                repr(error)
            )

            withdrawal = None

        if withdrawal is None:
            games.pop(
                user_id,
                None
            )

            await message.answer(
                "❌ Не удалось создать заявку.\n\n"
                "Возможно, недостаточно средств."
            )
            return True

        games.pop(
            user_id,
            None
        )

        await message.answer(
            "╭────────────────────╮\n"
            "       💸 <b>WITHDRAW</b>\n"
            "╰────────────────────╯\n\n"
            "✅ <b>ЗАЯВКА СОЗДАНА</b>\n\n"
            f"🧾 Номер: "
            f"<b>#{withdrawal['id']}</b>\n"
            f"💰 Сумма: "
            f"<b>{money(amount)} ₽</b>\n"
            "⏳ Статус: "
            "<b>ОЖИДАЕТ ПРОВЕРКИ</b>\n\n"
            "Средства зарезервированы до решения "
            "администратора.\n\n"
            "После проверки вы получите уведомление."
        )

        try:
            await bot.send_message(
                8244079903,
                "💸 <b>НОВАЯ ЗАЯВКА НА ВЫВОД</b>\n\n"
                f"🧾 Заявка: "
                f"<b>#{withdrawal['id']}</b>\n"
                f"👤 User ID: "
                f"<code>{user_id}</code>\n"
                f"💰 Сумма: "
                f"<b>{money(amount)} ₽</b>\n\n"
                "Открой ADMIN PANEL → "
                "ЗАЯВКИ НА ВЫВОД."
            )

        except Exception as error:
            print(
                "ADMIN WITHDRAW NOTIFICATION ERROR:",
                repr(error)
            )

        return True

    return False


# =========================================================
# ADMIN MESSAGE INPUT
# =========================================================

async def handle_admin_message(
    message: Message,
    state: dict
):
    user_id = message.from_user.id

    if not is_admin(user_id):
        return False

    action = state.get("admin_action")

    if action == "find_user":

        text = (
            message.text or ""
        ).strip()

        try:
            target_id = int(text)
        except Exception:
            await message.answer(
                "❌ ID должен быть числом."
            )
            return True

        await show_admin_user(
            message,
            target_id
        )

        return True

    if action == "amount":

        text = (
            message.text or ""
        ).strip()

        try:
            amount = int(text)

            if amount <= 0:
                raise ValueError

        except Exception:
            await message.answer(
                "❌ Введите положительное "
                "целое число."
            )
            return True

        target_id = state["target_user"]
        amount_action = state["admin_amount_action"]

        if amount_action == "add":

            new_balance = change_balance(
                target_id,
                amount
            )

            await message.answer(
                "╭────────────────────╮\n"
                "       💰 <b>BALANCE</b>\n"
                "╰────────────────────╯\n\n"
                "✅ <b>БАЛАНС ВЫДАН</b>\n\n"
                f"👤 ID: "
                f"<code>{target_id}</code>\n"
                f"💰 +{money(amount)} ₽\n"
                f"💳 Новый баланс: "
                f"<b>{money(new_balance)} ₽</b>",
                reply_markup=admin_user_keyboard()
            )

        else:

            success = subtract_balance(
                target_id,
                amount
            )

            if not success:
                await message.answer(
                    "❌ Недостаточно средств "
                    "на балансе пользователя."
                )
                return True

            new_balance = get_balance(
                target_id
            )

            await message.answer(
                "╭────────────────────╮\n"
                "       💰 <b>BALANCE</b>\n"
                "╰────────────────────╯\n\n"
                "✅ <b>БАЛАНС СНЯТ</b>\n\n"
                f"👤 ID: "
                f"<code>{target_id}</code>\n"
                f"➖ {money(amount)} ₽\n"
                f"💳 Новый баланс: "
                f"<b>{money(new_balance)} ₽</b>",
                reply_markup=admin_user_keyboard()
            )

        games[user_id] = {
            "admin_action": "user_menu",
            "target_user": target_id
        }

        return True

    return False


# =========================================================
# SINGLE MESSAGE HANDLER
# =========================================================

@dp.message()
async def text_message_handler(
    message: Message
):
    user_id = message.from_user.id

    state = games.get(user_id)

    if not state:
        return

    if state.get("withdraw_action"):
        handled = await handle_withdrawal_message(
            message,
            state
        )

        if handled:
            return

    if state.get("admin_action"):
        handled = await handle_admin_message(
            message,
            state
        )

        if handled:
            return


# =========================================================
# TELEGRAM WEBHOOK
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
                "WARNING: TELEGRAM WEBHOOK "
                "URL DOES NOT MATCH!"
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


@app.get("/")
async def root():
    return {
        "status": "ok",
        "bot": "Resonant Casino"
    }


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request
):
    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:
        return JSONResponse(
            {
                "ok": False,
                "error": "forbidden"
            },
            status_code=403
        )

    data = await request.json()

    print(
        "TELEGRAM UPDATE RECEIVED:",
        data.get("update_id")
    )

    try:
        update = Update.model_validate(data)

        if update.callback_query:
            print(
                "CALLBACK:",
                update.callback_query.data
            )

        await dp.feed_update(
            bot,
            update
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

    return {
        "ok": True
    }
