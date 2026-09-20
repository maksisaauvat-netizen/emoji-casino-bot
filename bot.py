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


# =========================================================
# GAME STATE
# =========================================================

games = {}

STAKES = [50, 100, 250, 500, 1000]

SLOT_SEVEN_MULTIPLIER = 50

CRASH_MIN = 1.05
CRASH_MAX = 20.0


# =========================================================
# HELPERS
# =========================================================

def money(value):
    return (
        f"{float(value):,.2f}"
        .replace(",", " ")
        .replace(".", ",")
    )


def safe_user_id(callback: CallbackQuery):
    if callback.from_user:
        return callback.from_user.id
    return None


async def edit_or_answer(
    callback: CallbackQuery,
    text: str,
    reply_markup=None
):
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


def confirm_bet_keyboard(
    confirm_callback: str,
    cancel_callback: str
):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ ПОДТВЕРДИТЬ СТАВКУ",
        callback_data=confirm_callback
    )

    kb.button(
        text="❌ ОТМЕНА",
        callback_data=cancel_callback
    )

    kb.adjust(1)

    return kb.as_markup()


def stake_keyboard(prefix: str, back_callback: str):
    kb = InlineKeyboardBuilder()

    for stake in STAKES:
        kb.button(
            text=f"💰 {stake} ₽",
            callback_data=f"{prefix}_{stake}"
        )

    kb.button(
        text="◀️ НАЗАД",
        callback_data=back_callback
    )

    kb.adjust(2)

    return kb.as_markup()


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
            text="🛠 ADMIN PANEL",
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


# =========================================================
# ADMIN
# =========================================================

def admin_panel_keyboard():
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

    return kb.as_markup()


def admin_user_keyboard(target_id: int):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="💰 ВЫДАТЬ БАЛАНС",
        callback_data=f"admin_give_{target_id}"
    )

    kb.button(
        text="➖ СНЯТЬ С БАЛАНСА",
        callback_data=f"admin_take_{target_id}"
    )

    kb.button(
        text="📊 ОБНОВИТЬ",
        callback_data=f"admin_refresh_{target_id}"
    )

    kb.button(
        text="📜 ИСТОРИЯ ИГР",
        callback_data=f"admin_games_{target_id}"
    )

    kb.button(
        text="💳 ИСТОРИЯ ПЛАТЕЖЕЙ",
        callback_data=f"admin_payments_{target_id}"
    )

    kb.button(
        text="🛠 ADMIN PANEL",
        callback_data="admin"
    )

    kb.adjust(1)

    return kb.as_markup()


def admin_user_text(target_id: int):
    stats = get_user_stats(target_id)

    return (
        "👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"💳 Баланс: <b>{money(stats['balance'])} ₽</b>\n\n"
        f"🎮 Игр: <b>{stats['games_played']}</b>\n"
        f"🏆 Побед: <b>{stats['wins']}</b>\n"
        f"💰 Ставок: <b>{money(stats['total_bet'])} ₽</b>\n"
        f"💵 Выиграно: <b>{money(stats['total_won'])} ₽</b>\n"
        f"🏆 Максимальный выигрыш: "
        f"<b>{money(stats['biggest_win'])} ₽</b>"
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id

    balance = get_balance(user_id)

    text = (
        "🎰 <b>RESONANT CASINO</b>\n\n"
        "Добро пожаловать в казино.\n\n"
        f"💳 Ваш баланс: <b>{money(balance)} ₽</b>\n\n"
        "Выберите действие:"
    )

    await message.answer(
        text,
        reply_markup=main_keyboard(user_id)
    )


# =========================================================
# MAIN MENU
# =========================================================

@dp.callback_query(F.data == "main")
async def main_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    await callback.answer()

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        (
            "🎰 <b>RESONANT CASINO</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>\n\n"
            "Выберите действие:"
        ),
        main_keyboard(user_id)
    )


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "games")
async def games_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎰 <b>МИНИ-ИГРЫ</b>\n\n"
            "Выберите игру:"
        ),
        games_keyboard()
    )


# =========================================================
# WALLET
# =========================================================

@dp.callback_query(F.data == "wallet")
async def wallet_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    await callback.answer()

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        (
            "💳 <b>КОШЕЛЁК</b>\n\n"
            f"Баланс: <b>{money(balance)} ₽</b>\n\n"
            "Минимальное пополнение: 1 USDT."
        ),
        wallet_keyboard()
    )


@dp.callback_query(F.data == "deposit")
async def deposit_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "➕ <b>ПОПОЛНЕНИЕ</b>\n\n"
            "Выберите сумму:"
        ),
        deposit_keyboard()
    )


@dp.callback_query(F.data.startswith("deposit_"))
async def deposit_amount_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        amount = float(callback.data.split("_")[1])
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
            amount
        )

        pay_url = invoice.get("pay_url")

        kb = InlineKeyboardBuilder()

        if pay_url:
            kb.button(
                text="💳 ОПЛАТИТЬ",
                url=pay_url
            )

        kb.button(
            text="🔄 ПРОВЕРИТЬ ОПЛАТУ",
            callback_data=f"check_payment_{invoice['invoice_id']}"
        )

        kb.button(
            text="◀️ КОШЕЛЁК",
            callback_data="wallet"
        )

        kb.adjust(1)

        await callback.message.edit_text(
            (
                "💳 <b>СЧЁТ СОЗДАН</b>\n\n"
                f"💵 Сумма: <b>{amount:.2f} USDT</b>\n"
                f"🧾 Invoice: <code>{invoice['invoice_id']}</code>\n\n"
                "После оплаты нажмите «ПРОВЕРИТЬ ОПЛАТУ»."
            ),
            reply_markup=kb.as_markup()
        )

    except Exception as error:
        print("DEPOSIT ERROR:", repr(error))

        await callback.message.edit_text(
            (
                "❌ <b>НЕ УДАЛОСЬ СОЗДАТЬ СЧЁТ</b>\n\n"
                f"<code>{error}</code>"
            ),
            reply_markup=wallet_keyboard()
        )


@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        invoice_id = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка invoice",
            show_alert=True
        )
        return

    await callback.answer(
        "Проверяю оплату..."
    )

    try:
        result = await process_paid_invoice(
            invoice_id
        )

        if result is not None:
            await callback.message.edit_text(
                (
                    "✅ <b>ОПЛАТА ПОЛУЧЕНА</b>\n\n"
                    f"💵 Пополнение: "
                    f"<b>{money(result['amount_rub'])} ₽</b>\n"
                    f"💳 Баланс: "
                    f"<b>{money(result['balance'])} ₽</b>"
                ),
                reply_markup=wallet_keyboard()
            )
            return

        invoice = await get_invoice(
            invoice_id
        )

        if invoice and invoice.get("status") == "paid":
            balance = get_balance(user_id)

            await callback.message.edit_text(
                (
                    "✅ <b>ПЛАТЁЖ УЖЕ ОБРАБОТАН</b>\n\n"
                    f"💳 Баланс: <b>{money(balance)} ₽</b>"
                ),
                reply_markup=wallet_keyboard()
            )
        else:
            await callback.message.edit_text(
                (
                    "⏳ <b>ОПЛАТА ЕЩЁ НЕ ПОЛУЧЕНА</b>\n\n"
                    "Если вы уже оплатили счёт, "
                    "подождите немного и проверьте снова."
                ),
                reply_markup=wallet_keyboard()
            )

    except Exception as error:
        print(
            "CHECK PAYMENT ERROR:",
            repr(error)
        )

        await callback.message.edit_text(
            (
                "❌ <b>ОШИБКА ПРОВЕРКИ</b>\n\n"
                f"<code>{error}</code>"
            ),
            reply_markup=wallet_keyboard()
        )


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    await callback.answer()

    stats = get_user_stats(user_id)

    text = (
        "👤 <b>МОЙ ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💳 Баланс: <b>{money(stats['balance'])} ₽</b>\n\n"
        f"🎮 Игр сыграно: <b>{stats['games_played']}</b>\n"
        f"🏆 Побед: <b>{stats['wins']}</b>\n"
        f"❌ Поражений: <b>{stats['losses']}</b>\n\n"
        f"💰 Всего ставок: "
        f"<b>{money(stats['total_bet'])} ₽</b>\n"
        f"💵 Всего выиграно: "
        f"<b>{money(stats['total_won'])} ₽</b>\n"
        f"🏆 Максимальный выигрыш: "
        f"<b>{money(stats['biggest_win'])} ₽</b>"
    )

    await edit_or_answer(
        callback,
        text,
        profile_keyboard()
    )


@dp.callback_query(F.data == "history")
async def history_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    await callback.answer()

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
            "📜 <b>ПОСЛЕДНИЕ ИГРЫ</b>\n"
        ]

        for item in history:
            icon = (
                "🏆"
                if item["result"] == "win"
                else "❌"
            )

            lines.append(
                f"{icon} {item['game']} — "
                f"{money(item['stake'])} ₽ → "
                f"{money(item['payout'])} ₽"
            )

        text = "\n".join(lines)

    await edit_or_answer(
        callback,
        text,
        profile_keyboard()
    )


@dp.callback_query(F.data == "clear_history")
async def clear_history_callback(callback: CallbackQuery):
    await callback.answer(
        "История очищается автоматически по лимиту отображения.",
        show_alert=True
    )


# =========================================================
# DICE
# =========================================================

@dp.callback_query(F.data == "game_dice")
async def game_dice_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИКИ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "dice_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("dice_stake_"))
async def dice_stake_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        stake = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_pending",
        "stake": stake,
    }

    await callback.answer()

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬇️ МЕНЬШЕ 3",
        callback_data=f"dice_confirm_{stake}_less"
    )

    kb.button(
        text="⬆️ БОЛЬШЕ 3",
        callback_data=f"dice_confirm_{stake}_more"
    )

    kb.button(
        text="🎲 ДВА КУБИКА",
        callback_data=f"dice_confirm_{stake}_two"
    )

    kb.button(
        text="❌ ОТМЕНА",
        callback_data="dice_pending_cancel"
    )

    kb.adjust(1)

    await callback.message.edit_text(
        (
            "🎲 <b>КУБИКИ</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n\n"
            "Выберите режим:"
        ),
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "dice_pending_cancel")
async def dice_pending_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИКИ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "dice_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("dice_confirm_"))
async def dice_confirm_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    parts = callback.data.split("_")

    if len(parts) != 4:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    try:
        stake = int(parts[2])
        choice = parts[3]
    except Exception:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    game = games.get(user_id)

    if not game or game.get("type") != "dice_pending":
        await callback.answer(
            "Эта ставка уже недействительна.",
            show_alert=True
        )
        return

    games.pop(user_id, None)

    if choice == "two":
        games[user_id] = {
            "type": "dice_two_pending",
            "stake": stake,
        }

        kb = InlineKeyboardBuilder()

        kb.button(
            text="⬇️ СУММА МЕНЬШЕ 7",
            callback_data=f"dice_two_choice_{stake}_less"
        )

        kb.button(
            text="⬆️ СУММА БОЛЬШЕ 7",
            callback_data=f"dice_two_choice_{stake}_more"
        )

        kb.button(
            text="🎯 СУММА РОВНО 7",
            callback_data=f"dice_two_choice_{stake}_equal"
        )

        kb.button(
            text="❌ ОТМЕНА",
            callback_data="dice_two_cancel"
        )

        kb.adjust(1)

        await callback.answer()

        await callback.message.edit_text(
            (
                "🎲 <b>ДВА КУБИКА</b>\n\n"
                f"💰 Ставка: <b>{stake} ₽</b>\n\n"
                "Какую сумму выбираете?"
            ),
            reply_markup=kb.as_markup()
        )

        return

    if choice == "less":
        multiplier = 2.0
        title = "⬇️ МЕНЬШЕ 3"
    else:
        multiplier = 2.0
        title = "⬆️ БОЛЬШЕ 3"

    games[user_id] = {
        "type": "dice_pending_final",
        "stake": stake,
        "choice": choice,
        "multiplier": multiplier,
        "title": title,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎲 <b>ПОДТВЕРЖДЕНИЕ</b>\n\n"
            f"{title}\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 При выигрыше: <b>{money(stake * multiplier)} ₽</b>\n\n"
            "Деньги будут списаны после подтверждения."
        ),
        reply_markup=confirm_bet_keyboard(
            "dice_start",
            "dice_final_cancel"
        )
    )


@dp.callback_query(F.data == "dice_final_cancel")
async def dice_final_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИКИ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "dice_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "dice_start")
async def dice_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "dice_pending_final":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]
    choice = game["choice"]
    multiplier = game["multiplier"]
    title = game["title"]

    games.pop(user_id, None)

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        await callback.message.edit_text(
            (
                "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
                f"Нужно: <b>{stake} ₽</b>\n"
                f"Баланс: <b>{money(get_balance(user_id))} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎲 <b>БРОСОК...</b>\n\n"
            f"{title}\n"
            f"💰 Ставка: <b>{stake} ₽</b>"
        )
    )

    dice_message = await bot.send_dice(
        user_id,
        emoji="🎲"
    )

    value = dice_message.dice.value

    win = (
        value < 3
        if choice == "less"
        else value > 3
    )

    payout = (
        int(stake * multiplier)
        if win
        else 0
    )

    result = "win" if win else "loss"

    record_game(
        user_id=user_id,
        game="dice",
        stake=stake,
        result=result,
        multiplier=multiplier if win else 0,
        payout=payout
    )

    if payout:
        change_balance(
            user_id,
            payout
        )

    balance = get_balance(user_id)

    if win:
        text = (
            "🎉 <b>ПОБЕДА!</b>\n\n"
            f"🎲 Выпало: <b>{value}</b>\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )
    else:
        text = (
            "❌ <b>ПРОИГРЫШ</b>\n\n"
            f"🎲 Выпало: <b>{value}</b>\n"
            f"💰 Потеряно: <b>{stake} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    await bot.send_message(
        user_id,
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# TWO DICE
# =========================================================

@dp.callback_query(F.data.startswith("dice_two_choice_"))
async def dice_two_choice_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    parts = callback.data.split("_")

    if len(parts) != 4:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    try:
        stake = int(parts[3])
        choice = parts[2]
    except Exception:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    game = games.get(user_id)

    if not game or game.get("type") != "dice_two_pending":
        await callback.answer(
            "Ставка недействительна.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "dice_two_pending_final",
        "stake": stake,
        "choice": choice,
    }

    names = {
        "less": "⬇️ СУММА МЕНЬШЕ 7",
        "more": "⬆️ СУММА БОЛЬШЕ 7",
        "equal": "🎯 СУММА РОВНО 7",
    }

    multipliers = {
        "less": 1.8,
        "more": 1.8,
        "equal": 5.0,
    }

    multiplier = multipliers[choice]

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎲 <b>ДВА КУБИКА</b>\n\n"
            f"{names[choice]}\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 При выигрыше: "
            f"<b>{money(stake * multiplier)} ₽</b>\n\n"
            "Подтвердить ставку?"
        ),
        reply_markup=confirm_bet_keyboard(
            "dice_two_start",
            "dice_two_final_cancel"
        )
    )


@dp.callback_query(F.data == "dice_two_cancel")
async def dice_two_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИКИ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "dice_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "dice_two_final_cancel")
async def dice_two_final_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎲 <b>КУБИКИ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "dice_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "dice_two_start")
async def dice_two_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "dice_two_pending_final":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]
    choice = game["choice"]

    multipliers = {
        "less": 1.8,
        "more": 1.8,
        "equal": 5.0,
    }

    multiplier = multipliers[choice]

    games.pop(user_id, None)

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        await callback.message.edit_text(
            (
                "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
                f"Нужно: <b>{stake} ₽</b>\n"
                f"Баланс: <b>{money(get_balance(user_id))} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎲 <b>ДВА КУБИКА БРОСАЮТСЯ...</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>"
        )
    )

    dice1 = await bot.send_dice(
        user_id,
        emoji="🎲"
    )

    await asyncio.sleep(0.7)

    dice2 = await bot.send_dice(
        user_id,
        emoji="🎲"
    )

    value1 = dice1.dice.value
    value2 = dice2.dice.value
    total = value1 + value2

    if choice == "less":
        win = total < 7
    elif choice == "more":
        win = total > 7
    else:
        win = total == 7

    payout = (
        int(stake * multiplier)
        if win
        else 0
    )

    result = "win" if win else "loss"

    record_game(
        user_id=user_id,
        game="dice_two",
        stake=stake,
        result=result,
        multiplier=multiplier if win else 0,
        payout=payout
    )

    if payout:
        change_balance(
            user_id,
            payout
        )

    balance = get_balance(user_id)

    if win:
        text = (
            "🎉 <b>ПОБЕДА!</b>\n\n"
            f"🎲 {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )
    else:
        text = (
            "❌ <b>ПРОИГРЫШ</b>\n\n"
            f"🎲 {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            f"💰 Потеряно: <b>{stake} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    await bot.send_message(
        user_id,
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# SLOTS
# =========================================================

def slot_symbols_from_value(value: int):
    """
    Telegram slot value:
    1..64.

    According to Telegram's official dice specification,
    the value consists of three 2-bit values.

    64 is the special 777 result.
    """

    if value == 64:
        return ["7️⃣", "7️⃣", "7️⃣"]

    symbol_pool = [
        "🍋",
        "🍇",
        "🍸",
        "🍒",
    ]

    raw = value - 1

    left = (raw & 3)
    center = ((raw >> 2) & 3)
    right = ((raw >> 4) & 3)

    return [
        symbol_pool[left],
        symbol_pool[center],
        symbol_pool[right],
    ]


def slots_payout(
    symbols,
    stake
):
    if symbols == ["7️⃣", "7️⃣", "7️⃣"]:
        return stake * SLOT_SEVEN_MULTIPLIER, 50.0

    if (
        symbols[0] == symbols[1]
        and symbols[1] == symbols[2]
    ):
        if symbols[0] == "🍇":
            return stake * 8, 8.0

        if symbols[0] == "🍋":
            return stake * 10, 10.0

        if symbols[0] == "🍸":
            return stake * 5, 5.0

        if symbols[0] == "🍒":
            return stake * 5, 5.0

    if (
        symbols[0] == symbols[1]
        or symbols[1] == symbols[2]
        or symbols[0] == symbols[2]
    ):
        return int(stake * 1.85), 1.85

    return 0, 0


@dp.callback_query(F.data == "game_slots")
async def game_slots_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎰 <b>СЛОТЫ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "slots_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("slots_stake_"))
async def slots_stake_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        stake = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "slots_pending",
        "stake": stake,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎰 <b>СЛОТЫ</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n\n"
            "Запустить слот?"
        ),
        reply_markup=confirm_bet_keyboard(
            "slots_start",
            "slots_cancel"
        )
    )


@dp.callback_query(F.data == "slots_cancel")
async def slots_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎰 <b>СЛОТЫ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "slots_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "slots_start")
async def slots_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "slots_pending":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]

    games.pop(user_id, None)

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        await callback.message.edit_text(
            (
                "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
                f"Нужно: <b>{stake} ₽</b>\n"
                f"Баланс: <b>{money(get_balance(user_id))} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎰 <b>ВРАЩЕНИЕ...</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>"
        )
    )

    slot_message = await bot.send_dice(
        user_id,
        emoji="🎰"
    )

    value = slot_message.dice.value

    symbols = slot_symbols_from_value(value)

    payout, multiplier = slots_payout(
        symbols,
        stake
    )

    win = payout > 0

    result = "win" if win else "loss"

    record_game(
        user_id=user_id,
        game="slots",
        stake=stake,
        result=result,
        multiplier=multiplier,
        payout=payout
    )

    if payout:
        change_balance(
            user_id,
            payout
        )

    balance = get_balance(user_id)

    if win:
        text = (
            "🎉 <b>СЛОТЫ — ПОБЕДА!</b>\n\n"
            f"🎰 {' '.join(symbols)}\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"✖️ Множитель: <b>x{multiplier}</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )
    else:
        text = (
            "❌ <b>СЛОТЫ — ПРОИГРЫШ</b>\n\n"
            f"🎰 {' '.join(symbols)}\n\n"
            f"💰 Потеряно: <b>{stake} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    await bot.send_message(
        user_id,
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# ROULETTE
# =========================================================

def roulette_color(number):
    if number == 0:
        return "zero"

    red_numbers = {
        1, 3, 5, 7, 9,
        12, 14, 16, 18,
        19, 21, 23, 25, 27,
        30, 32, 34, 36
    }

    return "red" if number in red_numbers else "black"


def roulette_choice_keyboard(stake):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🔴 КРАСНОЕ x2",
        callback_data=f"roulette_choice_{stake}_red"
    )

    kb.button(
        text="⚫ ЧЁРНОЕ x2",
        callback_data=f"roulette_choice_{stake}_black"
    )

    kb.button(
        text="🟢 ZERO x35",
        callback_data=f"roulette_choice_{stake}_zero"
    )

    kb.button(
        text="❌ ОТМЕНА",
        callback_data="roulette_cancel"
    )

    kb.adjust(1)

    return kb.as_markup()


@dp.callback_query(F.data == "game_roulette")
async def game_roulette_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "roulette_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("roulette_stake_"))
async def roulette_stake_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        stake = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "roulette_pending",
        "stake": stake,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n\n"
            "Выберите цвет:"
        ),
        reply_markup=roulette_choice_keyboard(
            stake
        )
    )


@dp.callback_query(F.data == "roulette_cancel")
async def roulette_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "roulette_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("roulette_choice_"))
async def roulette_choice_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    parts = callback.data.split("_")

    if len(parts) != 4:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    try:
        stake = int(parts[2])
        choice = parts[3]
    except Exception:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    game = games.get(user_id)

    if not game or game.get("type") != "roulette_pending":
        await callback.answer(
            "Ставка недействительна.",
            show_alert=True
        )
        return

    multipliers = {
        "red": 2,
        "black": 2,
        "zero": 35,
    }

    games[user_id] = {
        "type": "roulette_pending_final",
        "stake": stake,
        "choice": choice,
        "multiplier": multipliers[choice],
    }

    names = {
        "red": "🔴 КРАСНОЕ",
        "black": "⚫ ЧЁРНОЕ",
        "zero": "🟢 ZERO",
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎯 <b>ПОДТВЕРЖДЕНИЕ РУЛЕТКИ</b>\n\n"
            f"{names[choice]}\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 При выигрыше: "
            f"<b>{money(stake * multipliers[choice])} ₽</b>\n\n"
            "Подтвердить?"
        ),
        reply_markup=confirm_bet_keyboard(
            "roulette_start",
            "roulette_final_cancel"
        )
    )


@dp.callback_query(F.data == "roulette_final_cancel")
async def roulette_final_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎯 <b>РУЛЕТКА</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "roulette_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "roulette_start")
async def roulette_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "roulette_pending_final":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]
    choice = game["choice"]
    multiplier = game["multiplier"]

    games.pop(user_id, None)

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        await callback.message.edit_text(
            (
                "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
                f"Нужно: <b>{stake} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )
        return

    await callback.answer()

    result_number = random.randint(
        0,
        36
    )

    result_color = roulette_color(
        result_number
    )

    colors = {
        "red": "🔴",
        "black": "⚫",
        "zero": "🟢",
    }

    animation = [
        7,
        18,
        31,
        4,
        22,
        13,
        35,
        9,
        27,
        16,
        3,
        29,
        11,
        24,
        6,
        result_number,
    ]

    for number in animation:
        icon = (
            colors[roulette_color(number)]
        )

        try:
            await callback.message.edit_text(
                (
                    "🎯 <b>РУЛЕТКА</b>\n\n"
                    f"🎡 {icon} <b>{number}</b>\n\n"
                    "Вращение..."
                )
            )
        except Exception:
            pass

        await asyncio.sleep(0.22)

    win = result_color == choice

    payout = (
        int(stake * multiplier)
        if win
        else 0
    )

    record_game(
        user_id=user_id,
        game="roulette",
        stake=stake,
        result="win" if win else "loss",
        multiplier=multiplier if win else 0,
        payout=payout
    )

    if payout:
        change_balance(
            user_id,
            payout
        )

    balance = get_balance(user_id)

    icon = colors[result_color]

    if win:
        text = (
            "🎉 <b>РУЛЕТКА — ПОБЕДА!</b>\n\n"
            f"🎡 Выпало: {icon} "
            f"<b>{result_number}</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"✖️ Множитель: <b>x{multiplier}</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )
    else:
        text = (
            "❌ <b>РУЛЕТКА — ПРОИГРЫШ</b>\n\n"
            f"🎡 Выпало: {icon} "
            f"<b>{result_number}</b>\n\n"
            f"💰 Потеряно: <b>{stake} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# BOWLING
# =========================================================

@dp.callback_query(F.data == "game_bowling")
async def game_bowling_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "bowling_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("bowling_stake_"))
async def bowling_stake_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        stake = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "bowling_pending",
        "stake": stake,
    }

    await callback.answer()

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬇️ МЕНЬШЕ 4",
        callback_data=f"bowling_choice_{stake}_less"
    )

    kb.button(
        text="⬆️ 4 И БОЛЬШЕ",
        callback_data=f"bowling_choice_{stake}_more"
    )

    kb.button(
        text="❌ ОТМЕНА",
        callback_data="bowling_cancel"
    )

    kb.adjust(1)

    await callback.message.edit_text(
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n\n"
            "Сколько кеглей должно быть сбито?"
        ),
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "bowling_cancel")
async def bowling_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "bowling_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("bowling_choice_"))
async def bowling_choice_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    parts = callback.data.split("_")

    try:
        stake = int(parts[2])
        choice = parts[3]
    except Exception:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    game = games.get(user_id)

    if not game or game.get("type") != "bowling_pending":
        await callback.answer(
            "Ставка недействительна.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "bowling_pending_final",
        "stake": stake,
        "choice": choice,
    }

    title = (
        "⬇️ МЕНЬШЕ 4"
        if choice == "less"
        else "⬆️ 4 И БОЛЬШЕ"
    )

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎳 <b>ПОДТВЕРЖДЕНИЕ</b>\n\n"
            f"{title}\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 При выигрыше: "
            f"<b>{money(stake * 2)} ₽</b>\n\n"
            "Подтвердить?"
        ),
        reply_markup=confirm_bet_keyboard(
            "bowling_start",
            "bowling_final_cancel"
        )
    )


@dp.callback_query(F.data == "bowling_final_cancel")
async def bowling_final_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "bowling_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "bowling_start")
async def bowling_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "bowling_pending_final":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]
    choice = game["choice"]

    games.pop(user_id, None)

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
        )

        await callback.message.edit_text(
            (
                "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
                f"Нужно: <b>{stake} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        (
            "🎳 <b>БОУЛИНГ</b>\n\n"
            "Бросок..."
        )
    )

    dice_message = await bot.send_dice(
        user_id,
        emoji="🎳"
    )

    pins = dice_message.dice.value

    if choice == "less":
        win = pins < 4
    else:
        win = pins >= 4

    multiplier = 2.0

    payout = (
        int(stake * multiplier)
        if win
        else 0
    )

    record_game(
        user_id=user_id,
        game="bowling",
        stake=stake,
        result="win" if win else "loss",
        multiplier=multiplier if win else 0,
        payout=payout
    )

    if payout:
        change_balance(
            user_id,
            payout
        )

    balance = get_balance(user_id)

    if win:
        text = (
            "🎉 <b>БОУЛИНГ — ПОБЕДА!</b>\n\n"
            f"🎳 Сбито кеглей: <b>{pins}</b>\n\n"
            f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )
    else:
        text = (
            "❌ <b>БОУЛИНГ — ПРОИГРЫШ</b>\n\n"
            f"🎳 Сбито кеглей: <b>{pins}</b>\n\n"
            f"💰 Потеряно: <b>{stake} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        )

    await bot.send_message(
        user_id,
        text,
        reply_markup=after_game_keyboard()
    )


# =========================================================
# MINES
# =========================================================

def mines_keyboard(
    opened,
    mines,
    user_id
):
    kb = InlineKeyboardBuilder()

    for index in range(9):
        if index in opened:
            text = "💎"
        else:
            text = "⬜"

        kb.button(
            text=text,
            callback_data=f"mine_open_{index}"
        )

    kb.button(
        text="💰 ЗАБРАТЬ",
        callback_data="mine_cashout"
    )

    kb.button(
        text="❌ ЗАКОНЧИТЬ",
        callback_data="mine_finish"
    )

    kb.adjust(3)

    return kb.as_markup()


@dp.callback_query(F.data == "game_mines")
async def game_mines_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "💣 <b>MINES</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "mines_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("mines_stake_"))
async def mines_stake_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        stake = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "mines_pending",
        "stake": stake,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "💣 <b>MINES</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n\n"
            "На поле 9 клеток.\n"
            "Откройте безопасные клетки и заберите выигрыш.\n\n"
            "Начать игру?"
        ),
        reply_markup=confirm_bet_keyboard(
            "mines_start",
            "mines_cancel"
        )
    )


@dp.callback_query(F.data == "mines_cancel")
async def mines_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "💣 <b>MINES</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "mines_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "mines_start")
async def mines_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "mines_pending":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
            show_alert=True
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
        "multiplier": 1.0,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "💣 <b>MINES</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            "✖️ Мин: <b>2</b>\n\n"
            "Открывайте клетки:"
        ),
        reply_markup=mines_keyboard(
            set(),
            mines,
            user_id
        )
    )


@dp.callback_query(F.data.startswith("mine_open_"))
async def mine_open_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        index = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка",
            show_alert=True
        )
        return

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "Игра завершена.",
            show_alert=True
        )
        return

    opened = game["opened"]
    mines = game["mines"]

    if index in opened:
        await callback.answer(
            "Эта клетка уже открыта."
        )
        return

    if index in mines:
        games.pop(user_id, None)

        stake = game["stake"]

        record_game(
            user_id=user_id,
            game="mines",
            stake=stake,
            result="loss",
            multiplier=0,
            payout=0
        )

        balance = get_balance(user_id)

        await callback.answer(
            "💣 МИНА!",
            show_alert=True
        )

        await callback.message.edit_text(
            (
                "💣 <b>МИНА!</b>\n\n"
                "Вы проиграли.\n\n"
                f"💰 Потеряно: <b>{stake} ₽</b>\n"
                f"💳 Баланс: <b>{money(balance)} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )

        return

    opened.add(index)

    game["multiplier"] += 0.35

    if len(opened) >= 6:
        payout = int(
            game["stake"] * game["multiplier"]
        )

        stake = game["stake"]
        multiplier = game["multiplier"]

        games.pop(user_id, None)

        record_game(
            user_id=user_id,
            game="mines",
            stake=stake,
            result="win",
            multiplier=multiplier,
            payout=payout
        )

        change_balance(
            user_id,
            payout
        )

        balance = get_balance(user_id)

        await callback.answer(
            "🎉 Все безопасные клетки!"
        )

        await callback.message.edit_text(
            (
                "🎉 <b>MINES — ПОБЕДА!</b>\n\n"
                f"💎 Открыто: <b>{len(opened)}</b>\n"
                f"✖️ Множитель: <b>x{multiplier:.2f}</b>\n\n"
                f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n"
                f"💳 Баланс: <b>{money(balance)} ₽</b>"
            ),
            reply_markup=after_game_keyboard()
        )

        return

    await callback.answer(
        f"💎 Безопасно! x{game['multiplier']:.2f}"
    )

    await callback.message.edit_reply_markup(
        reply_markup=mines_keyboard(
            opened,
            mines,
            user_id
        )
    )


@dp.callback_query(F.data == "mine_cashout")
async def mine_cashout_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "Игра завершена.",
            show_alert=True
        )
        return

    payout = int(
        game["stake"] * game["multiplier"]
    )

    stake = game["stake"]
    multiplier = game["multiplier"]

    games.pop(user_id, None)

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

    await callback.answer(
        "💰 Выигрыш забран!"
    )

    await callback.message.edit_text(
        (
            "💰 <b>MINES — ЗАБОР</b>\n\n"
            f"💎 Открыто: <b>{len(game['opened'])}</b>\n"
            f"✖️ Множитель: <b>x{multiplier:.2f}</b>\n\n"
            f"🏆 Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


@dp.callback_query(F.data == "mine_finish")
async def mine_finish_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await callback.answer(
            "Игра завершена.",
            show_alert=True
        )
        return

    stake = game["stake"]

    games.pop(user_id, None)

    record_game(
        user_id=user_id,
        game="mines",
        stake=stake,
        result="loss",
        multiplier=0,
        payout=0
    )

    balance = get_balance(user_id)

    await callback.answer(
        "Игра завершена."
    )

    await callback.message.edit_text(
        (
            "❌ <b>MINES — ИГРА ЗАКОНЧЕНА</b>\n\n"
            f"💰 Ставка потеряна: <b>{stake} ₽</b>\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# CRASH
# =========================================================

def crash_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="💰 ЗАБРАТЬ ВЫИГРЫШ",
        callback_data="crash_cashout"
    )

    kb.adjust(1)

    return kb.as_markup()


@dp.callback_query(F.data == "game_crash")
async def game_crash_callback(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "📈 <b>CRASH</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "crash_stake",
            "games"
        )
    )


@dp.callback_query(F.data.startswith("crash_stake_"))
async def crash_stake_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    try:
        stake = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ставки",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "crash_pending",
        "stake": stake,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "📈 <b>CRASH</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n\n"
            "Множитель начнёт расти.\n"
            "Заберите деньги до краша.\n\n"
            "Начать?"
        ),
        reply_markup=confirm_bet_keyboard(
            "crash_start",
            "crash_cancel"
        )
    )


@dp.callback_query(F.data == "crash_cancel")
async def crash_cancel(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    games.pop(user_id, None)

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "📈 <b>CRASH</b>\n\n"
            "Выберите ставку:"
        ),
        stake_keyboard(
            "crash_stake",
            "games"
        )
    )


@dp.callback_query(F.data == "crash_start")
async def crash_start(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "crash_pending":
        await callback.answer(
            "Ставка уже недействительна.",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(user_id, stake):
        await callback.answer(
            "Недостаточно средств.",
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

    games[user_id] = {
        "type": "crash",
        "stake": stake,
        "multiplier": 1.00,
        "crash_point": crash_point,
        "message_id": callback.message.message_id,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "📈 <b>CRASH</b>\n\n"
            "🚀 <b>x1.00</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>"
        ),
        reply_markup=crash_keyboard()
    )

    asyncio.create_task(
        crash_loop(user_id)
    )


async def crash_loop(user_id: int):
    while True:
        await asyncio.sleep(0.65)

        game = games.get(user_id)

        if not game:
            return

        if game.get("type") != "crash":
            return

        multiplier = game["multiplier"]
        crash_point = game["crash_point"]
        message_id = game["message_id"]

        next_multiplier = round(
            multiplier * 1.045,
            2
        )

        if next_multiplier < multiplier + 0.02:
            next_multiplier = round(
                multiplier + 0.02,
                2
            )

        if next_multiplier >= crash_point:
            games.pop(user_id, None)

            stake = game["stake"]

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
                    (
                        "💥 <b>CRASH!</b>\n\n"
                        f"📈 Краш на: "
                        f"<b>x{crash_point:.2f}</b>\n\n"
                        f"💰 Потеряно: "
                        f"<b>{stake} ₽</b>\n"
                        f"💳 Баланс: "
                        f"<b>{money(balance)} ₽</b>"
                    ),
                    chat_id=user_id,
                    message_id=message_id,
                    reply_markup=after_game_keyboard()
                )
            except Exception as error:
                print(
                    "CRASH EDIT ERROR:",
                    repr(error)
                )

            return

        game["multiplier"] = next_multiplier

        try:
            await bot.edit_message_text(
                (
                    "📈 <b>CRASH</b>\n\n"
                    f"🚀 <b>x{next_multiplier:.2f}</b>\n\n"
                    f"💰 Ставка: "
                    f"<b>{game['stake']} ₽</b>\n\n"
                    "Заберите выигрыш до краша!"
                ),
                chat_id=user_id,
                message_id=message_id,
                reply_markup=crash_keyboard()
            )
        except Exception as error:
            print(
                "CRASH LOOP EDIT ERROR:",
                repr(error)
            )


@dp.callback_query(F.data == "crash_cashout")
async def crash_cashout(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    game = games.get(user_id)

    if not game or game.get("type") != "crash":
        await callback.answer(
            "Игра уже закончилась.",
            show_alert=True
        )
        return

    games.pop(user_id, None)

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

    await callback.answer(
        "💰 Выигрыш забран!"
    )

    await callback.message.edit_text(
        (
            "🎉 <b>CRASH — ВЫИГРЫШ!</b>\n\n"
            f"🚀 Забрали на: "
            f"<b>x{multiplier:.2f}</b>\n\n"
            f"💰 Ставка: <b>{stake} ₽</b>\n"
            f"🏆 Выигрыш: "
            f"<b>{money(payout)} ₽</b>\n\n"
            f"💳 Баланс: <b>{money(balance)} ₽</b>"
        ),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# ADMIN PANEL
# =========================================================

@dp.callback_query(F.data == "admin")
async def admin_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    await callback.answer()

    await edit_or_answer(
        callback,
        (
            "🛠 <b>ADMIN PANEL</b>\n\n"
            "Выберите действие:"
        ),
        admin_panel_keyboard()
    )


@dp.callback_query(F.data == "admin_search")
async def admin_search_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "admin_search"
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "👤 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
            "Отправьте Telegram ID пользователя."
        )
    )


@dp.message()
async def text_message_handler(message: Message):
    user_id = message.from_user.id

    game = games.get(user_id)

    if not game:
        return

    if game.get("type") == "admin_search":
        if not is_admin(user_id):
            return

        try:
            target_id = int(
                message.text.strip()
            )
        except Exception:
            await message.answer(
                "❌ Введите корректный Telegram ID."
            )
            return

        games[user_id] = {
            "type": "admin_user",
            "target_id": target_id,
        }

        await message.answer(
            admin_user_text(target_id),
            reply_markup=admin_user_keyboard(
                target_id
            )
        )

        return

    if game.get("type") in (
        "admin_give",
        "admin_take"
    ):
        if not is_admin(user_id):
            return

        try:
            amount = int(
                message.text.strip()
            )
        except Exception:
            await message.answer(
                "❌ Введите целое число."
            )
            return

        if amount <= 0:
            await message.answer(
                "❌ Сумма должна быть больше нуля."
            )
            return

        target_id = game["target_id"]
        action = game["type"]

        if action == "admin_give":
            new_balance = change_balance(
                target_id,
                amount
            )

            text = (
                "✅ <b>БАЛАНС ВЫДАН</b>\n\n"
                f"👤 ID: <code>{target_id}</code>\n"
                f"➕ Сумма: <b>{money(amount)} ₽</b>\n"
                f"💳 Баланс: "
                f"<b>{money(new_balance)} ₽</b>"
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

                text = (
                    "✅ <b>БАЛАНС СНЯТ</b>\n\n"
                    f"👤 ID: <code>{target_id}</code>\n"
                    f"➖ Сумма: <b>{money(amount)} ₽</b>\n"
                    f"💳 Баланс: "
                    f"<b>{money(new_balance)} ₽</b>"
                )
            else:
                text = (
                    "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
                    f"👤 ID: <code>{target_id}</code>"
                )

        games[user_id] = {
            "type": "admin_user",
            "target_id": target_id,
        }

        await message.answer(
            text,
            reply_markup=admin_user_keyboard(
                target_id
            )
        )

        return


@dp.callback_query(F.data.startswith("admin_give_"))
async def admin_give_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    try:
        target_id = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ID",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "admin_give",
        "target_id": target_id,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "💰 <b>ВЫДАТЬ БАЛАНС</b>\n\n"
            f"👤 ID: <code>{target_id}</code>\n\n"
            "Введите сумму в рублях:"
        )
    )


@dp.callback_query(F.data.startswith("admin_take_"))
async def admin_take_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    try:
        target_id = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ID",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": "admin_take",
        "target_id": target_id,
    }

    await callback.answer()

    await callback.message.edit_text(
        (
            "➖ <b>СНЯТЬ С БАЛАНСА</b>\n\n"
            f"👤 ID: <code>{target_id}</code>\n\n"
            "Введите сумму в рублях:"
        )
    )


@dp.callback_query(F.data.startswith("admin_refresh_"))
async def admin_refresh_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    try:
        target_id = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ID",
            show_alert=True
        )
        return

    await callback.answer(
        "Обновлено"
    )

    await callback.message.edit_text(
        admin_user_text(target_id),
        reply_markup=admin_user_keyboard(
            target_id
        )
    )


@dp.callback_query(F.data.startswith("admin_games_"))
async def admin_games_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    try:
        target_id = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ID",
            show_alert=True
        )
        return

    history = get_game_history(
        target_id,
        20
    )

    if not history:
        text = (
            "📜 <b>ИСТОРИЯ ИГР</b>\n\n"
            "История пустая."
        )
    else:
        lines = [
            "📜 <b>ИСТОРИЯ ИГР</b>\n"
        ]

        for item in history:
            icon = (
                "🏆"
                if item["result"] == "win"
                else "❌"
            )

            lines.append(
                f"{icon} {item['game']} | "
                f"{money(item['stake'])} ₽ → "
                f"{money(item['payout'])} ₽"
            )

        text = "\n".join(lines)

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=admin_user_keyboard(
            target_id
        )
    )


@dp.callback_query(F.data.startswith("admin_payments_"))
async def admin_payments_callback(callback: CallbackQuery):
    user_id = safe_user_id(callback)

    if not is_admin(user_id):
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    try:
        target_id = int(
            callback.data.split("_")[2]
        )
    except Exception:
        await callback.answer(
            "Ошибка ID",
            show_alert=True
        )
        return

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
                f"💵 {item['amount_usdt']} USDT → "
                f"{money(item['amount_rub'])} ₽\n"
                f"🧾 <code>{item['invoice_id']}</code>\n"
                f"📌 {item['status']}"
            )

        text = "\n\n".join(lines)

    await callback.answer()

    await callback.message.edit_text(
        text,
        reply_markup=admin_user_keyboard(
            target_id
        )
    )


# =========================================================
# WEBHOOK
# =========================================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "emoji-casino-bot"
    }


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

        print(
            "TELEGRAM UPDATE:",
            data.get("update_id")
        )

        update = Update.model_validate(
            data
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

        return {
            "ok": True
        }

    except Exception as error:
        print(
            "WEBHOOK ERROR:",
            repr(error)
        )

        return JSONResponse(
            {
                "ok": False,
                "error": str(error)
            },
            status_code=500
        )


# =========================================================
# STARTUP / SHUTDOWN
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
