import asyncio
import os
import random

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    Update,
    InputMediaPhoto,
)
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

# 1 USDT = 80 â½
# ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½ÑÐ¹ Ð²ÑÐ²Ð¾Ð´ = 1 USDT
MIN_WITHDRAWAL = 80

# =========================================================
# PREMIUM PHOTOS
# =========================================================
#
# Ð¤Ð¾ÑÐ¾Ð³ÑÐ°ÑÐ¸Ð¸ Ð¿Ð¾Ð´ÐºÐ»ÑÑÐ°ÑÑÑÑ ÑÐµÑÐµÐ· Render Environment Variables.
#
# ÐÑÐ»Ð¸ Ð¿ÐµÑÐµÐ¼ÐµÐ½Ð½Ð°Ñ Ð¿ÑÑÑÐ°Ñ â Ð±Ð¾Ñ Ð°Ð²ÑÐ¾Ð¼Ð°ÑÐ¸ÑÐµÑÐºÐ¸ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑ
# Ð¾Ð±ÑÑÐ½ÑÐ¹ ÑÐµÐºÑÑÐ¾Ð²ÑÐ¹ Ð¸Ð½ÑÐµÑÑÐµÐ¹Ñ.
#
# ÐÐ¾Ð·Ð¶Ðµ ÑÑÐ´Ð° Ð¼Ð¾Ð¶Ð½Ð¾ Ð´Ð¾Ð±Ð°Ð²Ð¸ÑÑ Telegram file_id ÑÐ¾ÑÐ¾Ð³ÑÐ°ÑÐ¸Ð¹.
#

PHOTO_MAIN = os.getenv("PHOTO_MAIN", "")
PHOTO_GAMES = os.getenv("PHOTO_GAMES", "")
PHOTO_WALLET = os.getenv("PHOTO_WALLET", "")
PHOTO_ROULETTE = os.getenv("PHOTO_ROULETTE", "")
PHOTO_MINES = os.getenv("PHOTO_MINES", "")
PHOTO_CRASH = os.getenv("PHOTO_CRASH", "")
PHOTO_WITHDRAW = os.getenv("PHOTO_WITHDRAW", "")
PHOTO_ADMIN = os.getenv("PHOTO_ADMIN", "")

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
    keyboard=None,
    photo: str = ""
):
    """
    Ð£Ð½Ð¸Ð²ÐµÑÑÐ°Ð»ÑÐ½Ð¾Ðµ Ð¿ÐµÑÐµÐºÐ»ÑÑÐµÐ½Ð¸Ðµ:
    text -> text
    text -> photo
    photo -> text
    photo -> photo
    """

    message = callback.message

    # -----------------------------------------------------
    # PHOTO MODE
    # -----------------------------------------------------

    if photo:
        try:
            if message.photo:
                await message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=keyboard
                )
            else:
                try:
                    await message.delete()
                except Exception:
                    pass

                await message.answer_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

            return

        except Exception as error:
            print(
                "PHOTO EDIT ERROR:",
                repr(error)
            )

    # -----------------------------------------------------
    # TEXT MODE
    # -----------------------------------------------------

    try:
        if message.photo:
            try:
                await message.delete()
            except Exception:
                pass

            await message.answer(
                text,
                reply_markup=keyboard
            )
        else:
            await message.edit_text(
                text,
                reply_markup=keyboard
            )

    except Exception as error:
        print(
            "EDIT TEXT ERROR:",
            repr(error)
        )

        try:
            await message.answer(
                text,
                reply_markup=keyboard
            )
        except Exception as answer_error:
            print(
                "ANSWER ERROR:",
                repr(answer_error)
            )


async def answer_start_screen(
    message: Message,
    text: str,
    keyboard,
    photo: str = ""
):
    if photo:
        try:
            await message.answer_photo(
                photo=photo,
                caption=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return
        except Exception as error:
            print(
                "START PHOTO ERROR:",
                repr(error)
            )

    await message.answer(
        text,
        reply_markup=keyboard
    )


def main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð° | ÐÐÐ Ð«",
        callback_data="games"
    )

    builder.button(
        text="ð° | ÐÐÐÐÐÐ¡",
        callback_data="wallet"
    )

    builder.button(
        text="ð¤ | ÐÐ ÐÐ¤ÐÐÐ¬",
        callback_data="profile"
    )

    builder.button(
        text="ð³ | ÐÐÐÐÐÐÐÐ¢Ð¬",
        callback_data="deposit"
    )

    builder.button(
        text="ð¸ | ÐÐ«ÐÐÐ¡Ð¢Ð",
        callback_data="withdraw"
    )

    builder.adjust(2)

    if is_admin(user_id):
        builder.button(
            text="ð  | ADMIN PANEL",
            callback_data="admin"
        )

    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()

builder.button(
    text="ð² | DICE",
    callback_data="game_dice"
)

    builder.button(
        text="ð° | SLOTS",
        callback_data="game_slots"
    )

    builder.button(
        text="ð³ | BOWLING",
        callback_data="game_bowling"
    )

    builder.button(
        text="ð¡ | ROULLETE",
        callback_data="game_roulette"
    )

    builder.button(
        text="ð£ | MINES",
        callback_data="game_mines"
    )

    builder.button(
        text="ð | CRASH",
        callback_data="game_crash"
    )

    builder.button(
        text="â¬ï¸ | ÐÐÐÐÐÐÐ ÐÐÐÐ®",
        callback_data="back_main"
    )

    builder.adjust(2)

    return builder.as_markup()


def stake_keyboard(prefix: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð | ÐÐÐÐ¡Ð¢Ð Ð¡Ð¢ÐÐÐÐ£",
        callback_data=f"{prefix}_enter_stake"
    )

    builder.button(
        text="â¬ï¸ | ÐÐÐÐÐ",
        callback_data="games"
    )

    builder.adjust(1)

    return builder.as_markup()


def confirm_bet_keyboard(game: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð | ÐÐÐÐ¢ÐÐÐ ÐÐÐ¢Ð¬ Ð¡Ð¢ÐÐÐÐ£",
        callback_data=f"confirm_{game}"
    )

    builder.button(
        text="â  ÐÐ¢ÐÐÐÐ",
        callback_data="games"
    )

    builder.adjust(1)

    return builder.as_markup()


def wallet_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð³  ÐÐÐÐÐÐÐÐ¢Ð¬",
        callback_data="deposit"
    )

    builder.button(
        text="ð¸  ÐÐ«ÐÐÐ¡Ð¢Ð",
        callback_data="withdraw"
    )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="back_main"
    )

    builder.adjust(1)

    return builder.as_markup()


def after_game_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð  ÐÐ©Ð Ð ÐÐ",
        callback_data="games"
    )

    builder.button(
        text="ð°  ÐÐÐÐÐÐ¡",
        callback_data="wallet"
    )

    builder.button(
        text="ð   ÐÐÐÐÐÐÐ ÐÐÐÐ®",
        callback_data="back_main"
    )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# SLOT DECODER
# =========================================================

def slot_symbols_from_value(value: int):
    """
    ÐÐ¾Ð³Ð¸ÐºÐ° Telegram Ð´Ð»Ñ ð°.

    value == 64:
        777

    ÐÐ»Ñ Ð¾ÑÑÐ°Ð»ÑÐ½ÑÑ Ð·Ð½Ð°ÑÐµÐ½Ð¸Ð¹ Telegram
    Ð¸Ð·Ð²Ð»ÐµÐºÐ°ÐµÑ ÑÑÐ¸ 2-Ð±Ð¸ÑÐ½ÑÑ Ð·Ð½Ð°ÑÐµÐ½Ð¸Ñ.

    raw 0 -> BAR
    raw 1 -> BERRIES
    raw 2 -> LEMON
    raw 3 -> SEVEN
    """

    value = int(value)

    if value < 1 or value > 64:
        return ["â", "â", "â"]

    if value == 64:
        return [
            "7ï¸â£",
            "7ï¸â£",
            "7ï¸â£",
        ]

    symbols = [
        "ð¸",
        "ð",
        "ð",
        "7ï¸â£",
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

    text = (
        "ââââââââââââââââââââââââ\n"
        "      ð° <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "ââââââââââââââââââââââââ\n\n"
        "ð <b>VIP GAMING CLUB</b>\n\n"
        "ð° <b>ÐÐÐ¡Ð¢Ð£ÐÐÐ«Ð ÐÐÐÐÐÐ¡</b>\n"
        f"<b>{money(get_balance(user_id))} â½</b>\n\n"
        "â ÐÐÐ Ð«\n"
        "â Ð¡Ð¢ÐÐÐÐ\n"
        "â ÐÐ«ÐÐÐ Ð«Ð¨Ð\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ ð"
    )

    await answer_start_screen(
        message,
        text,
        main_keyboard(user_id),
        PHOTO_MAIN
    )


# =========================================================
# ADMIN PHOTO ID HELPER
# =========================================================

@dp.message(F.photo)
async def admin_photo_id_handler(
    message: Message
):
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    file_id = message.photo[-1].file_id

    await message.answer(
        "ð¼ <b>PHOTO FILE ID</b>\n\n"
        f"<code>{file_id}</code>\n\n"
        "Ð¡ÐºÐ¾Ð¿Ð¸ÑÑÐ¹ÑÐµ ÑÑÐ¾Ñ ID Ð¸ Ð´Ð¾Ð±Ð°Ð²ÑÑÐµ ÐµÐ³Ð¾ "
        "Ð² ÑÐ¾Ð¾ÑÐ²ÐµÑÑÑÐ²ÑÑÑÑÑ Ð¿ÐµÑÐµÐ¼ÐµÐ½Ð½ÑÑ Render."
    )


# =========================================================
# MAIN MENU
# =========================================================

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    user_id = callback.from_user.id

    await callback.answer()

    text = (
        "ââââââââââââââââââââââââ\n"
        "      ð° <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "ââââââââââââââââââââââââ\n\n"
        "ð <b>VIP GAMING CLUB</b>\n\n"
        "ð° <b>ÐÐÐ¡Ð¢Ð£ÐÐÐ«Ð ÐÐÐÐÐÐ¡</b>\n"
        f"<b>{money(get_balance(user_id))} â½</b>\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ ð"
    )

    await edit_or_answer(
        callback,
        text,
        main_keyboard(user_id),
        PHOTO_MAIN
    )


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "games")
async def games_handler(callback: CallbackQuery):
    await callback.answer()

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð° <b>GAMES</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ð <b>ÐÐ«ÐÐÐ ÐÐ¢Ð ÐÐÐ Ð£</b>\n\n"
        "ð² ÐÐ·Ð°ÑÑ â¢ ð° Ð£Ð´Ð°ÑÐ° â¢ ð Ð Ð¸ÑÐº\n\n"
        "Ð¡ÑÐ°Ð²ÐºÐ° ÑÐ¿Ð¸ÑÑÐ²Ð°ÐµÑÑÑ ÑÐ¾Ð»ÑÐºÐ¾ Ð¿Ð¾ÑÐ»Ðµ Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÐµÐ½Ð¸Ñ.",
        games_keyboard(),
        PHOTO_GAMES
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
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>WALLET</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ð° <b>ÐÐÐ¡Ð¢Ð£ÐÐÐ</b>\n\n"
        f"      <b>{money(balance)} â½</b>\n\n"
        "â ÐÐ¾Ð¿Ð¾Ð»Ð½ÑÐ¹ÑÐµ Ð±Ð°Ð»Ð°Ð½Ñ\n"
        "â ÐÐ³ÑÐ°Ð¹ÑÐµ Ð² Ð¼Ð¸Ð½Ð¸-Ð¸Ð³ÑÑ\n"
        "â ÐÑÐ²Ð¾Ð´ Ð¾Ñ 80 â½",
        wallet_keyboard(),
        PHOTO_WALLET
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
        text="ð  ÐÐ¡Ð¢ÐÐ ÐÐ¯ ÐÐÐ ",
        callback_data="my_history"
    )

    builder.button(
        text="ð³  ÐÐÐÐ¢ÐÐÐ",
        callback_data="my_payments"
    )

    builder.button(
        text="ð¸  ÐÐÐ ÐÐ«ÐÐÐÐ«",
        callback_data="my_withdrawals"
    )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="back_main"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð¤ <b>PROFILE</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ð <b>BALANCE</b>\n"
        f"<b>{money(stats['balance'])} â½</b>\n\n"
        f"ð® ÐÐÐ Ð«        <b>{stats['games_played']}</b>\n"
        f"ð ÐÐÐÐÐÐ«      <b>{stats['wins']}</b>\n"
        f"â ÐÐÐ ÐÐÐÐÐÐ¯   <b>{stats['losses']}</b>\n"
        f"ð WINRATE     <b>{winrate}%</b>\n\n"
        f"ðµ Ð¡Ð¢ÐÐÐÐ      <b>{money(stats['total_bet'])} â½</b>\n"
        f"ð ÐÐ«ÐÐÐ ÐÐÐ    <b>{money(stats['total_won'])} â½</b>\n"
        f"ð¥ MAX WIN     <b>{money(stats['biggest_win'])} â½</b>",
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
            "ð <b>GAME HISTORY</b>\n\n"
            "ÐÐ¾ÐºÐ° Ð¸Ð³Ñ Ð½ÐµÑ."
        )
    else:
        lines = [
            "ð <b>GAME HISTORY</b>\n"
        ]

        for item in history:
            result = (
                "â"
                if item["result"] == "win"
                else "â"
            )

            lines.append(
                f"{result} "
                f"{item['game']} â "
                f"{money(item['stake'])} â½ â "
                f"{money(item['payout'])} â½"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="â¬ï¸  ÐÐ ÐÐ¤ÐÐÐ¬",
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
            "ð³ <b>PAYMENTS</b>\n\n"
            "ÐÐ»Ð°ÑÐµÐ¶ÐµÐ¹ Ð¿Ð¾ÐºÐ° Ð½ÐµÑ."
        )
    else:
        lines = [
            "ð³ <b>PAYMENT HISTORY</b>\n"
        ]

        for item in history:
            lines.append(
                f"ðµ {item['amount_usdt']} USDT â "
                f"{money(item['amount_rub'])} â½\n"
                f"ð§¾ #{item['invoice_id']}"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="â¬ï¸  ÐÐ ÐÐ¤ÐÐÐ¬",
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
            text=f"ð³  {amount} USDT",
            callback_data=f"deposit_{amount}"
        )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="wallet"
    )

    builder.adjust(2)

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð³ <b>DEPOSIT</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ Ð² USDT.\n\n"
        "ð ÐÑÑÑ Ð±Ð¾ÑÐ°: <b>1 USDT = 80 â½</b>",
        builder.as_markup(),
        PHOTO_WALLET
    )


@dp.callback_query(F.data.startswith("deposit_"))
async def deposit_create_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    amount_text = callback.data.split("_", 1)[1]

    try:
        amount_usdt = float(amount_text)
    except Exception:
        await callback.answer(
            "ÐÑÐ¸Ð±ÐºÐ° ÑÑÐ¼Ð¼Ñ",
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
            "â ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ ÑÑÑÑ.\n"
            "ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ÑÐµ ÐµÑÑ ÑÐ°Ð·."
        )
        return

    pay_url = invoice.get("pay_url")

    builder = InlineKeyboardBuilder()

    if pay_url:
        builder.button(
            text="ð³  ÐÐÐÐÐ¢ÐÐ¢Ð¬",
            url=pay_url
        )

    builder.button(
        text="ð  ÐÐ ÐÐÐÐ ÐÐ¢Ð¬ ÐÐÐÐÐ¢Ð£",
        callback_data=(
            f"check_payment_{invoice['invoice_id']}"
        )
    )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="wallet"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð³ <b>INVOICE</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ðµ Ð¡ÑÐ¼Ð¼Ð°: <b>{amount_usdt} USDT</b>\n"
        f"ð° ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¸Ðµ: "
        f"<b>{money(int(round(amount_usdt * 80)))} â½</b>\n\n"
        f"ð§¾ Invoice ID: "
        f"<code>{invoice['invoice_id']}</code>\n\n"
        "ÐÐ¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°ÑÑ Ð½Ð°Ð¶Ð¼Ð¸ÑÐµ "
        "Â«ÐÐ ÐÐÐÐ ÐÐ¢Ð¬ ÐÐÐÐÐ¢Ð£Â».",
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
        "ÐÑÐ¾Ð²ÐµÑÑÑ Ð¾Ð¿Ð»Ð°ÑÑ..."
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
            "â ÐÑÐ¸Ð±ÐºÐ° Ð¿ÑÐ¾Ð²ÐµÑÐºÐ¸ Ð¿Ð»Ð°ÑÐµÐ¶Ð°."
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
                "â ï¸ <b>ÐÐÐÐ¢ÐÐ Ð£ÐÐ ÐÐÐ ÐÐÐÐ¢ÐÐ</b>\n\n"
                "ÐÑÐ»Ð¸ Ð±Ð°Ð»Ð°Ð½Ñ Ð½Ðµ Ð¾Ð±Ð½Ð¾Ð²Ð¸Ð»ÑÑ, "
                "Ð¾Ð±ÑÐ°ÑÐ¸ÑÐµÑÑ Ðº Ð°Ð´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾ÑÑ."
            )
        else:
            text = (
                "â³ <b>ÐÐÐÐÐ¢Ð ÐÐ ÐÐÐÐÐÐÐ</b>\n\n"
                f"Ð¡ÑÐ°ÑÑÑ: <code>{status}</code>\n\n"
                "ÐÑÐ»Ð¸ Ð²Ñ ÑÐ¶Ðµ Ð¾Ð¿Ð»Ð°ÑÐ¸Ð»Ð¸, "
                "Ð¿Ð¾Ð´Ð¾Ð¶Ð´Ð¸ÑÐµ Ð½ÐµÑÐºÐ¾Ð»ÑÐºÐ¾ ÑÐµÐºÑÐ½Ð´ "
                "Ð¸ Ð¿ÑÐ¾Ð²ÐµÑÑÑÐµ ÑÐ½Ð¾Ð²Ð°."
            )

        await callback.message.answer(text)
        return

    await callback.message.answer(
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>PAYMENT OK</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "â <b>ÐÐÐÐÐ¢Ð ÐÐÐÐ£Ð§ÐÐÐ</b>\n\n"
        f"ðµ {result['amount_usdt']} USDT\n"
        f"ð° ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¾: "
        f"<b>{money(result['amount_rub'])} â½</b>\n"
        f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
        f"<b>{money(result['balance'])} â½</b>",
        reply_markup=main_keyboard(
            callback.from_user.id
        )
    )

# =========================================================
# MANUAL STAKE INPUT
# =========================================================

GAME_STAKE_TYPES = {
    "dice",
    "slots",
    "bowling",
    "roulette",
    "mines",
    "crash",
}


def manual_stake_back_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="games"
    )

    builder.adjust(1)

    return builder.as_markup()


@dp.callback_query(
    F.data.endswith("_enter_stake")
)
async def manual_stake_start(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    game_type = callback.data.replace(
        "_enter_stake",
        ""
    )

    if game_type not in GAME_STAKE_TYPES:
        await callback.answer(
            "ÐÑÐ¸Ð±ÐºÐ° Ð¸Ð³ÑÑ",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": game_type,
        "awaiting_stake": True,
    }

    balance = get_balance(user_id)

    await callback.answer()

    game_names = {
        "dice": "ð² DICE",
        "slots": "ð° SLOTS",
        "bowling": "ð³ BOWLING",
        "roulette": "ð¡ ROULETTE",
        "mines": "ð£ MINES",
        "crash": "ð CRASH",
    }

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        f"       {game_names[game_type]}\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ð <b>ÐÐÐÐÐÐ¢Ð Ð¡Ð¢ÐÐÐÐ£</b>\n\n"
        "ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ ÑÑÐ°Ð²ÐºÐ°: "
        "<b>50 â½</b>\n"
        f"ÐÐ°ÐºÑÐ¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ ÑÑÐ°Ð²ÐºÐ°: "
        f"<b>{money(balance)} â½</b>\n\n"
        "ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ ÑÑÐ¼Ð¼Ñ Ð¾Ð´Ð½Ð¸Ð¼ ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸ÐµÐ¼.\n\n"
        "ÐÐ°Ð¿ÑÐ¸Ð¼ÐµÑ:\n"
        "<code>350</code>",
        manual_stake_back_keyboard()
    )


async def handle_stake_message(
    message: Message,
    state: dict
):
    user_id = message.from_user.id
    if not state.get("awaiting_stake"):
        return False
    game_type = state.get("type")
    allowed_games = {
        "dice",
            "slots",
        "bowling",
        "roulette",
        "mines",
        "crash",
    }
    if game_type not in allowed_games:
        games.pop(
            user_id,
            None
        )
        await message.answer(
            "â <b>ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°.</b>\n\n"
            "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¸Ð³ÑÑ Ð·Ð°Ð½Ð¾Ð²Ð¾."
        )
        return True
    text = (
        message.text or ""
    ).strip()
    try:
        stake = int(text)
        if stake < 50:
            raise ValueError
    except (TypeError, ValueError):
        await message.answer(
            "â <b>ÐÐÐÐÐ Ð ÐÐÐ¢ÐÐÐ¯ Ð¡Ð¢ÐÐÐÐ</b>\n\n"
            "ÐÐ²ÐµÐ´Ð¸ÑÐµ ÑÐµÐ»Ð¾Ðµ ÑÐ¸ÑÐ»Ð¾ Ð½Ðµ Ð¼ÐµÐ½ÑÑÐµ "
            "<b>50 â½</b>.\n\n"
            "ÐÐ°Ð¿ÑÐ¸Ð¼ÐµÑ:\n"
            "<code>350</code>"
        )
        return True
    balance = get_balance(user_id)
    if stake > balance:
        await message.answer(
            "â <b>ÐÐÐÐÐ¡Ð¢ÐÐ¢ÐÐ§ÐÐ Ð¡Ð ÐÐÐ¡Ð¢Ð</b>\n\n"
            f"ð³ ÐÐ°Ñ Ð±Ð°Ð»Ð°Ð½Ñ: "
            f"<b>{money(balance)} â½</b>\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"
            "ÐÐ²ÐµÐ´Ð¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð½Ðµ Ð±Ð¾Ð»ÑÑÐµ "
            "ÑÐµÐºÑÑÐµÐ³Ð¾ Ð±Ð°Ð»Ð°Ð½ÑÐ°."
        )
        return True
    games[user_id] = {
        "type": game_type,
        "stake": stake
    }
    # DICE
    if game_type == "dice":

        builder = InlineKeyboardBuilder()

        # ÐÐ ÐÐ¡ÐÐ 1 Ð ÐÐ
        builder.button(
            text="x1.85 | ÐÐÐÐ¬Ð¨Ð 4",
            callback_data="dice_single_less"
        )

        builder.button(
            text="x1.85 | ÐÐÐÐ¬Ð¨Ð 3",
            callback_data="dice_single_more"
        )

        # ÐÐ ÐÐ¡ÐÐ 2 Ð ÐÐÐ
        builder.button(
            text="x2.05 | ÐÐÐÐ¬Ð¨Ð 7",
            callback_data="dice_double_less"
        )

        builder.button(
            text="x2.05 | ÐÐÐÐ¬Ð¨Ð 7",
            callback_data="dice_double_more"
        )

        builder.button(
            text="x5 | Ð ÐÐÐÐ 7",
            callback_data="dice_double_seven"
        )

        builder.button(
            text="â¬ï¸  ÐÐÐÐÐ",
            callback_data="game_dice"
        )

        builder.adjust(1)

        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð² <b>| DICE</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"

            "<b>ÐÐ ÐÐ¡ÐÐ 1 Ð ÐÐ</b>\n"
            "x1.85 | ÐÐµÐ½ÑÑÐµ 4\n"
            "x1.85 | ÐÐ¾Ð»ÑÑÐµ 3\n\n"

            "<b>ÐÐ ÐÐ¡ÐÐ 2 Ð ÐÐÐ</b>\n"
            "x2.05 | ÐÐµÐ½ÑÑÐµ 7\n"
            "x2.05 | ÐÐ¾Ð»ÑÑÐµ 7\n"
            "x5 | Ð Ð¾Ð²Ð½Ð¾ 7\n\n"

            "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¿ÑÐ¾Ð³Ð½Ð¾Ð·:",

            reply_markup=builder.as_markup()
        )

        return True

    # SLOTS
    if game_type == "slots":
        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð° <b>SLOTS</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"
            "ððð â Ã10\n"
            "7ï¸â£7ï¸â£7ï¸â£ â Ã50\n"
            "3 Ð¾Ð´Ð¸Ð½Ð°ÐºÐ¾Ð²ÑÑ â Ã3.5\n"
            "2 Ð¾Ð´Ð¸Ð½Ð°ÐºÐ¾Ð²ÑÑ â Ã1.85\n"
            "ÐÑÑÐ³Ð¸Ðµ ÐºÐ¾Ð¼Ð±Ð¸Ð½Ð°ÑÐ¸Ð¸ â Ð¿ÑÐ¾Ð¸Ð³ÑÑÑ.\n\n"
            "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
            reply_markup=confirm_bet_keyboard("slots")
        )
        return True
    # BOWLING
    if game_type == "bowling":
        builder = InlineKeyboardBuilder()
        builder.button(
            text="ð³  ÐÐÐÐÐ",
            callback_data="bowling_hit"
        )
        builder.button(
            text="ð¨  ÐÐ ÐÐÐÐ¥",
            callback_data="bowling_miss"
        )
        builder.button(
            text="â¬ï¸  ÐÐÐÐÐ",
            callback_data="game_bowling"
        )
        builder.adjust(1)
        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð³ <b>BOWLING</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"
            "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¿ÑÐ¾Ð³Ð½Ð¾Ð·:",
            reply_markup=builder.as_markup()
        )
        return True
    # ROULETTE
    if game_type == "roulette":
        builder = InlineKeyboardBuilder()
        builder.button(
            text="ð´  ÐÐ ÐÐ¡ÐÐÐ",
            callback_data="roulette_red"
        )
        builder.button(
            text="â«  Ð§ÐÐ ÐÐÐ",
            callback_data="roulette_black"
        )
        builder.button(
            text="ð¢  ZERO",
            callback_data="roulette_zero"
        )
        builder.button(
            text="â¬ï¸  ÐÐÐÐÐ",
            callback_data="game_roulette"
        )
        builder.adjust(1)
        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð¡ <b>ROULETTE</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"
            "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÐ²ÐµÑ:",
            reply_markup=builder.as_markup()
        )
        return True
    # MINES
    if game_type == "mines":
        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð£ <b>MINES</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"
            "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
            reply_markup=confirm_bet_keyboard("mines")
        )
        return True
    # CRASH
    if game_type == "crash":
        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð <b>CRASH</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
            f"<b>{money(stake)} â½</b>\n\n"
            "Ð¡Ð°Ð¼Ð¾Ð»ÑÑ Ð±ÑÐ´ÐµÑ Ð½Ð°Ð±Ð¸ÑÐ°ÑÑ Ð¼Ð½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ.\n"
            "ÐÐ°ÑÐ° Ð·Ð°Ð´Ð°ÑÐ° â Ð·Ð°Ð±ÑÐ°ÑÑ Ð²ÑÐ¸Ð³ÑÑÑ "
            "Ð´Ð¾ CRASH.\n\n"
            "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
            reply_markup=confirm_bet_keyboard("crash")
        )
        return True
    return True
    
@dp.callback_query(F.data == "game_dice")
async def dice_start(
    callback: CallbackQuery
):
    await callback.answer()
    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð² <b>| DICE</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ°Ð²ÐºÑ:",
        stake_keyboard("dice")
    )
@dp.callback_query(
    F.data.startswith("dice_stake_")
)
async def dice_stake(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    stake = int(
        callback.data.split("_")[-1]
    )
    games[user_id] = {
        "type": "dice",
        "stake": stake
    }
    builder = InlineKeyboardBuilder()
    # ÐÐ ÐÐ¡ÐÐ 1 Ð ÐÐ
    builder.button(
        text="x1.85 | ÐÐÐÐ¬Ð¨Ð 4",
        callback_data="dice_single_less"
    )
    builder.button(
        text="x1.85 | ÐÐÐÐ¬Ð¨Ð 3",
        callback_data="dice_single_more"
    )
    # ÐÐ ÐÐ¡ÐÐ 2 Ð ÐÐÐ
    builder.button(
        text="x2.05 | ÐÐÐÐ¬Ð¨Ð 7",
        callback_data="dice_double_less"
    )
    builder.button(
        text="x2.05 | ÐÐÐÐ¬Ð¨Ð 7",
        callback_data="dice_double_more"
    )
    builder.button(
        text="x5 | Ð ÐÐÐÐ 7",
        callback_data="dice_double_seven"
    )
    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="game_dice"
    )
    builder.adjust(1)
    await callback.answer()
    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð² <b>| DICE</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: <b>{money(stake)} â½</b>\n\n"
        "<b>ÐÐ ÐÐ¡ÐÐ 1 Ð ÐÐ</b>\n"
        "x1.85 | ÐÐµÐ½ÑÑÐµ 4\n"
        "x1.85 | ÐÐ¾Ð»ÑÑÐµ 3\n\n"
        "<b>ÐÐ ÐÐ¡ÐÐ 2 Ð ÐÐÐ</b>\n"
        "x2.05 | ÐÐµÐ½ÑÑÐµ 7\n"
        "x2.05 | ÐÐ¾Ð»ÑÑÐµ 7\n"
        "x5 | Ð Ð¾Ð²Ð½Ð¾ 7\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¿ÑÐ¾Ð³Ð½Ð¾Ð·:",
        builder.as_markup()
    )
@dp.callback_query(
    F.data.in_(
        {
            "dice_single_less",
            "dice_single_more",
            "dice_double_less",
            "dice_double_more",
            "dice_double_seven"
        }
    )
)
async def dice_prediction(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game:
        await callback.answer(
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return
    prediction = callback.data
    game["prediction"] = prediction
    stake = game["stake"]
    prediction_names = {
        "dice_single_less":
            "x1.85 | ÐÐÐÐ¬Ð¨Ð 4",
        "dice_single_more":
            "x1.85 | ÐÐÐÐ¬Ð¨Ð 3",
        "dice_double_less":
            "x2.05 | ÐÐÐÐ¬Ð¨Ð 7",
        "dice_double_more":
            "x2.05 | ÐÐÐÐ¬Ð¨Ð 7",
        "dice_double_seven":
            "x5 | Ð ÐÐÐÐ 7",
    }
    await callback.answer()
    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð² <b>| DICE</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: <b>{money(stake)} â½</b>\n"
        f"ð¯ ÐÑÐ¾Ð³Ð½Ð¾Ð·: "
        f"<b>{prediction_names[prediction]}</b>\n\n"
        "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
        confirm_bet_keyboard("dice")
    )
@dp.callback_query(
    F.data == "confirm_dice"
)
async def confirm_dice(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game:
        await callback.answer(
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return
    stake = game["stake"]
    prediction = game["prediction"]
    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²",
            show_alert=True
        )
        return
    await callback.answer()
    # =====================================
    # ÐÐ ÐÐ¡ÐÐ 1 Ð ÐÐ
    # =====================================
    if prediction in {
        "dice_single_less",
        "dice_single_more"
    }:
        dice = await callback.message.answer_dice(
            emoji="ð²"
        )
        await asyncio.sleep(3)
        value = dice.dice.value
        if prediction == "dice_single_less":
            won = value < 4
            multiplier = 1.85
        else:
            won = value > 3
            multiplier = 1.85
        if won:
            payout = int(
                stake * multiplier
            )
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
                "â­âââââââââââââââââââââ®\n"
                "       ð <b>WIN</b>\n"
                "â°âââââââââââââââââââââ¯\n\n"
                f"ð² ÐÑÐ¿Ð°Ð»Ð¾: <b>{value}</b>\n\n"
                "â <b>ÐÐÐÐÐÐ</b>\n"
                f"ð° ÐÑÐ¸Ð³ÑÑÑ: "
                f"<b>+{money(payout)} â½</b>\n"
                f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
                f"<b>{money(get_balance(user_id))} â½</b>"
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
                "â­âââââââââââââââââââââ®\n"
                "       ð¥ <b>LOSS</b>\n"
                "â°âââââââââââââââââââââ¯\n\n"
                f"ð² ÐÑÐ¿Ð°Ð»Ð¾: <b>{value}</b>\n\n"
                "â <b>ÐÐ ÐÐÐÐ Ð«Ð¨</b>\n"
                f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
                f"<b>{money(get_balance(user_id))} â½</b>"
            )
        games.pop(
            user_id,
            None
        )
        await callback.message.answer(
            text,
            reply_markup=after_game_keyboard()
        )
        return
    # =====================================
    # ÐÐ ÐÐ¡ÐÐ 2 Ð ÐÐÐ
    # =====================================
    dice1 = await callback.message.answer_dice(
        emoji="ð²"
    )
    dice2 = await callback.message.answer_dice(
        emoji="ð²"
    )
    await asyncio.sleep(3)
    value1 = dice1.dice.value
    value2 = dice2.dice.value
    total = value1 + value2
    if prediction == "dice_double_less":
        won = total < 7
        multiplier = 2.05
    elif prediction == "dice_double_more":
        won = total > 7
        multiplier = 2.05
    else:
        won = total == 7
        multiplier = 5
    if won:
        payout = int(
            stake * multiplier
        )
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
            "â­âââââââââââââââââââââ®\n"
            "       ð <b>WIN</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð² {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            "â <b>ÐÐÐÐÐÐ</b>\n"
            f"ð° ÐÑÐ¸Ð³ÑÑÑ: "
            f"<b>+{money(payout)} â½</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
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
            "â­âââââââââââââââââââââ®\n"
            "       ð¥ <b>LOSS</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð² {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            "â <b>ÐÐ ÐÐÐÐ Ð«Ð¨</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
        )
    games.pop(
        user_id,
        None
    )
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
        "â­âââââââââââââââââââââ®\n"
        "       ð° <b>SLOTS</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "Ð¢ÑÐ¸ ÑÐ¸Ð¼Ð²Ð¾Ð»Ð° Ð²ÑÐ°ÑÐ°ÑÑÑÑ Ð¿ÑÑÐ¼Ð¾ "
        "Ð² Telegram.\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ°Ð²ÐºÑ:",
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
        "â­âââââââââââââââââââââ®\n"
        "       ð° <b>SLOTS</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: <b>{money(stake)} â½</b>\n\n"
        "ððð â Ã10\n"
        "7ï¸â£7ï¸â£7ï¸â£ â Ã50\n"
        "ÐÑÑÐ³Ð¸Ðµ ÐºÐ¾Ð¼Ð±Ð¸Ð½Ð°ÑÐ¸Ð¸ â Ð¿ÑÐ¾Ð¸Ð³ÑÑÑ.\n\n"
        "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return
    stake = game["stake"]
    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²",
            show_alert=True
        )
        return
    await callback.answer()
    dice = await callback.message.answer_dice(
        emoji="ð°"
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
    # 777 â JACKPOT Ã50
    if value == 64:
        multiplier = 50
        payout = round(stake * multiplier)
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
            "ââââââââââââââââââââââââ\n"
            "       ð¥ <b>JACKPOT</b>\n"
            "ââââââââââââââââââââââââ\n\n"
            f"ð° <b>{display_result}</b>\n\n"
            "ð¥ <b>777 â ÐÐÐÐÐÐÐ¢!</b>\n\n"
            f"ð° ÐÑÐ¸Ð³ÑÑÑ: "
            f"<b>+{money(payout)} â½</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
        )
    # ððð â Ã10
    elif symbols == ["ð", "ð", "ð"]:
        multiplier = 10
        payout = round(stake * multiplier)
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
            "â­âââââââââââââââââââââ®\n"
            "       ð <b>WIN</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð° <b>{display_result}</b>\n\n"
            "ð <b>Ð¢Ð Ð ÐÐÐÐÐÐ</b>\n\n"
            f"ð° ÐÑÐ¸Ð³ÑÑÑ: "
            f"<b>+{money(payout)} â½</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
        )
    # ÐÑÐ±ÑÐµ Ð´ÑÑÐ³Ð¸Ðµ 3 Ð¾Ð´Ð¸Ð½Ð°ÐºÐ¾Ð²ÑÑ â Ã3.5
    elif (
        symbols[0] == symbols[1]
        and symbols[1] == symbols[2]
    ):
        multiplier = 3.5
        payout = round(stake * multiplier)
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
            "â­âââââââââââââââââââââ®\n"
            "       ð° <b>WIN</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð° <b>{display_result}</b>\n\n"
            "ð <b>Ð¢Ð Ð ÐÐÐÐÐÐÐÐÐ«Ð¥</b>\n"
            "Ã3.5\n\n"
            f"ð° ÐÑÐ¸Ð³ÑÑÑ: "
            f"<b>+{money(payout)} â½</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
        )
    # Ð Ð¾Ð²Ð½Ð¾ 2 Ð¾Ð´Ð¸Ð½Ð°ÐºÐ¾Ð²ÑÑ â Ã1.85
    elif (
        symbols[0] == symbols[1]
        or symbols[0] == symbols[2]
        or symbols[1] == symbols[2]
    ):
        multiplier = 1.85
        payout = round(stake * multiplier)
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
            "â­âââââââââââââââââââââ®\n"
            "       â¨ <b>WIN</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð° <b>{display_result}</b>\n\n"
            "â¨ <b>ÐÐÐ ÐÐÐÐÐÐÐÐÐ«Ð¥</b>\n"
            "Ã1.85\n\n"
            f"ð° ÐÑÐ¸Ð³ÑÑÑ: "
            f"<b>+{money(payout)} â½</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
        )
    # ÐÑÑÐ°Ð»ÑÐ½ÑÐµ ÐºÐ¾Ð¼Ð±Ð¸Ð½Ð°ÑÐ¸Ð¸ â Ð¿ÑÐ¾Ð¸Ð³ÑÑÑ
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
            "â­âââââââââââââââââââââ®\n"
            "       ð¥ <b>LOSS</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð° <b>{display_result}</b>\n\n"
            "â <b>ÐÐ ÐÐÐÐ Ð«Ð¨</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
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
        "â­âââââââââââââââââââââ®\n"
        "       ð³ <b>BOWLING</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ°Ð²ÐºÑ:",
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
        text="ð³  ÐÐÐÐÐ",
        callback_data="bowling_hit"
    )

    builder.button(
        text="ð¨  ÐÐ ÐÐÐÐ¥",
        callback_data="bowling_miss"
    )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="game_bowling"
    )

    builder.adjust(1)

    await callback.answer()

    await edit_or_answer(
        callback,
        f"ð³ <b>BOWLING</b>\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: <b>{money(stake)} â½</b>\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¿ÑÐ¾Ð³Ð½Ð¾Ð·:",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
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
        f"ð³ <b>BOWLING</b>\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
        f"<b>{money(game['stake'])} â½</b>\n"
        f"ð¯ ÐÑÐ¾Ð³Ð½Ð¾Ð·: <b>{game['prediction']}</b>\n\n"
        "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ?",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²",
            show_alert=True
        )
        return

    await callback.answer()

    dice = await callback.message.answer_dice(
        emoji="ð³"
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
            "â­âââââââââââââââââââââ®\n"
            "       ð <b>WIN</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð³ Ð ÐµÐ·ÑÐ»ÑÑÐ°Ñ: <b>{value}</b>\n\n"
            "â <b>ÐÐÐÐÐÐ</b>\n"
            f"ð° +{money(payout)} â½\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
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
            "â­âââââââââââââââââââââ®\n"
            "       ð¥ <b>LOSS</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð³ Ð ÐµÐ·ÑÐ»ÑÑÐ°Ñ: <b>{value}</b>\n\n"
            "â <b>ÐÐ ÐÐÐÐ Ð«Ð¨</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
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
        "â­âââââââââââââââââââââ®\n"
        "       ð¡ <b>ROULETTE</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ°Ð²ÐºÑ:",
        stake_keyboard("roulette"),
        PHOTO_ROULETTE
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
        text="ð´  ÐÐ ÐÐ¡ÐÐÐ",
        callback_data="roulette_red"
    )

    builder.button(
        text="â«  Ð§ÐÐ ÐÐÐ",
        callback_data="roulette_black"
    )

    builder.button(
        text="ð¢  ZERO",
        callback_data="roulette_zero"
    )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐ",
        callback_data="game_roulette"
    )

    builder.adjust(1)

    await callback.answer()

    await edit_or_answer(
        callback,
        f"ð¡ <b>ROULETTE</b>\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
        f"<b>{money(stake)} â½</b>\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÐ²ÐµÑ:",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
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
        f"ð¡ <b>ROULETTE</b>\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
        f"<b>{money(game['stake'])} â½</b>\n"
        f"ð¯ ÐÑÐ±Ð¾Ñ: <b>{game['color']}</b>\n\n"
        "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ?",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²",
            show_alert=True
        )
        return

    await callback.answer()

    message = callback.message

    animation = [
        "ð¡ ð´ â« ð¢ â« ð´",
        "ð¡ â« ð´ â« ð¢ ð´",
        "ð¡ ð´ ð¢ â« ð´ â«",
        "ð¡ â« ð´ ð¢ â« ð´",
        "ð¡ ð´ â« ð´ ð¢ â«",
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
            "ð¢"
            if result_color == "zero"
            else "ð´"
            if result_color == "red"
            else "â«"
        )

        text = (
            "â­âââââââââââââââââââââ®\n"
            "       ð <b>WIN</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð¡ ÐÑÐ¿Ð°Ð»Ð¾: <b>{number}</b> "
            f"{emoji}\n\n"
            "â <b>ÐÐÐÐÐÐ</b>\n"
            f"ð° +{money(payout)} â½\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
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
            "â­âââââââââââââââââââââ®\n"
            "       ð¥ <b>LOSS</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð¡ ÐÑÐ¿Ð°Ð»Ð¾: <b>{number}</b>\n\n"
            "â <b>ÐÐ ÐÐÐÐ Ð«Ð¨</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>"
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
        "â­âââââââââââââââââââââ®\n"
        "       ð£ <b>MINES</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÐ° Ð¿Ð¾Ð»Ðµ 9 ÐºÐ»ÐµÑÐ¾Ðº.\n"
        "2 Ð¸Ð· Ð½Ð¸Ñ â Ð¼Ð¸Ð½Ñ.\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ°Ð²ÐºÑ:",
        stake_keyboard("mines"),
        PHOTO_MINES
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
        "â­âââââââââââââââââââââ®\n"
        "       ð£ <b>MINES</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: <b>{money(stake)} â½</b>\n\n"
        "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
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
            "ð"
            if i in opened
            else "â¬"
        )

        builder.button(
            text=text,
            callback_data=f"mine_{i}"
        )

    builder.button(
        text="ð°  ÐÐÐÐ ÐÐ¢Ð¬",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²",
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
        "â­âââââââââââââââââââââ®\n"
        "       ð£ <b>MINES</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: <b>{money(stake)} â½</b>\n"
        "ð ÐÑÐºÑÑÐ²Ð°Ð¹ÑÐµ ÐºÐ»ÐµÑÐºÐ¸ ð",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
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
            "â­âââââââââââââââââââââ®\n"
            "       ð <b>MINES</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            "ð° <b>ÐÐ« ÐÐÐÐ ÐÐÐ ÐÐ«ÐÐÐ Ð«Ð¨</b>\n\n"
            f"ð ÐÐ½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ: "
            f"<b>x{multiplier:.2f}</b>\n"
            f"ðµ ÐÑÐ¸Ð³ÑÑÑ: "
            f"<b>{money(payout)} â½</b>\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>",
            after_game_keyboard()
        )

        return

    index = int(action)

    if index in game["opened"]:
        await callback.answer(
            "Ð­ÑÐ° ÐºÐ»ÐµÑÐºÐ° ÑÐ¶Ðµ Ð¾ÑÐºÑÑÑÐ°"
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
            "ð¥ ÐÐ£Ð!",
            show_alert=True
        )

        await edit_or_answer(
            callback,
            "â­âââââââââââââââââââââ®\n"
            "       ð¥ <b>MINES</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            "ð£ <b>ÐÐÐÐ!</b>\n\n"
            "â Ð¢Ñ Ð¿ÑÐ¾Ð¸Ð³ÑÐ°Ð».\n\n"
            f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
            f"<b>{money(get_balance(user_id))} â½</b>",
            after_game_keyboard()
        )

        return

    game["opened"].append(index)

    game["multiplier"] += 0.35

    await callback.answer(
        f"ð x{game['multiplier']:.2f}"
    )

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð£ <b>MINES</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð ÐÐ½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ: "
        f"<b>x{game['multiplier']:.2f}</b>\n"
        f"ð° ÐÐ°Ð±ÑÐ°ÑÑ: "
        f"<b>{money(int(game['stake'] * game['multiplier']))} â½</b>",
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
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>CRASH</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÐ½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ ÑÐ°ÑÑÑÑ ÐºÐ°Ð¶Ð´ÑÑ ÑÐµÐºÑÐ½Ð´Ñ.\n"
        "ÐÐ°Ð¶Ð¼Ð¸ÑÐµ Â«ð° ÐÐÐÐ ÐÐ¢Ð¬Â», "
        "Ð¿Ð¾ÐºÐ° ÑÐ°Ð¼Ð¾Ð»ÑÑ Ð½Ðµ ÑÐ°Ð·Ð±Ð¸Ð»ÑÑ.\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ°Ð²ÐºÑ:",
        stake_keyboard("crash"),
        PHOTO_CRASH
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
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>CRASH</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð Ð¡ÑÐ°Ð²ÐºÐ°: "
        f"<b>{money(stake)} â½</b>\n\n"
        "Ð¡Ð°Ð¼Ð¾Ð»ÑÑ Ð±ÑÐ´ÐµÑ Ð½Ð°Ð±Ð¸ÑÐ°ÑÑ Ð¼Ð½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ.\n"
        "ÐÐ°ÑÐ° Ð·Ð°Ð´Ð°ÑÐ° â Ð·Ð°Ð±ÑÐ°ÑÑ Ð²ÑÐ¸Ð³ÑÑÑ "
        "Ð´Ð¾ CRASH.\n\n"
        "ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ ÑÑÐ°Ð²ÐºÑ?",
        confirm_bet_keyboard("crash")
    )


def crash_keyboard(multiplier: float):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"ð°  ÐÐÐÐ ÐÐ¢Ð¬ x{multiplier:.2f}",
        callback_data="crash_cashout"
    )

    builder.button(
        text="â  Ð¡ÐÐÐ¢Ð¬Ð¡Ð¯",
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
                    "â­âââââââââââââââââââââ®\n"
                    "       ð <b>CRASH</b>\n"
                    "â°âââââââââââââââââââââ¯\n\n"
                    "âï¸ Ð¡Ð°Ð¼Ð¾Ð»ÑÑ Ð»ÐµÑÐ¸Ñ...\n\n"
                    f"ð ÐÐ½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ: "
                    f"<b>x{multiplier:.2f}</b>\n\n"
                    "ð° Ð£ÑÐ¿ÐµÐ¹ÑÐµ Ð·Ð°Ð±ÑÐ°ÑÑ Ð²ÑÐ¸Ð³ÑÑÑ!",
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
                "â­âââââââââââââââââââââ®\n"
                "       ð¥ <b>CRASH</b>\n"
                "â°âââââââââââââââââââââ¯\n\n"
                f"ð Ð¡Ð°Ð¼Ð¾Ð»ÑÑ ÑÐ°Ð·Ð±Ð¸Ð»ÑÑ Ð½Ð° "
                f"<b>x{crash_point:.2f}</b>\n\n"
                "â <b>Ð¡Ð»Ð¸ÑÐºÐ¾Ð¼ Ð¿Ð¾Ð·Ð´Ð½Ð¾.</b>\n"
                "Ð¡ÑÐ°Ð²ÐºÐ° Ð¿ÑÐ¾Ð¸Ð³ÑÐ°Ð½Ð°.\n\n"
                f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
                f"<b>{money(get_balance(user_id))} â½</b>",
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
            "ÐÐ³ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await callback.answer(
            "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²",
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
        "ð CRASH ÐÐÐ§ÐÐÐ¡Ð¯!"
    )

    message = await callback.message.answer(
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>CRASH</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "âï¸ Ð¡Ð°Ð¼Ð¾Ð»ÑÑ Ð²Ð·Ð»ÐµÑÐµÐ»!\n\n"
        "ð ÐÐ½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ: <b>x1.00</b>\n\n"
        "ð° Ð£ÑÐ¿ÐµÐ¹ÑÐµ Ð·Ð°Ð±ÑÐ°ÑÑ Ð²ÑÐ¸Ð³ÑÑÑ!",
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
            "ð¥ CRASH ÑÐ¶Ðµ Ð¿ÑÐ¾Ð¸Ð·Ð¾ÑÑÐ».",
            show_alert=True
        )
        return

    if game.get("crash_finished"):
        await callback.answer(
            "ð¥ Ð¡Ð»Ð¸ÑÐºÐ¾Ð¼ Ð¿Ð¾Ð·Ð´Ð½Ð¾!",
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
        "ð° ÐÑÐ¸Ð³ÑÑÑ Ð·Ð°Ð±ÑÐ°Ð½!"
    )

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>CRASH</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ð° <b>ÐÐ« ÐÐÐÐ ÐÐÐ ÐÐ«ÐÐÐ Ð«Ð¨</b>\n\n"
        f"ð ÐÐ½Ð¾Ð¶Ð¸ÑÐµÐ»Ñ: "
        f"<b>x{multiplier:.2f}</b>\n"
        f"ðµ ÐÑÐ¸Ð³ÑÑÑ: "
        f"<b>{money(payout)} â½</b>\n"
        f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
        f"<b>{money(get_balance(user_id))} â½</b>",
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
            "ÐÐ³ÑÐ° ÑÐ¶Ðµ Ð·Ð°Ð²ÐµÑÑÐµÐ½Ð°.",
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
        "Ð¡ÑÐ°Ð²ÐºÐ° Ð·Ð°Ð²ÐµÑÑÐµÐ½Ð°."
    )

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð <b>CRASH</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "â Ð¢Ñ Ð¾ÑÑÐ°Ð½Ð¾Ð²Ð¸Ð» Ð¸Ð³ÑÑ.\n"
        "Ð¡ÑÐ°Ð²ÐºÐ° Ð¿ÑÐ¾Ð¸Ð³ÑÐ°Ð½Ð°.\n\n"
        f"ð³ ÐÐ°Ð»Ð°Ð½Ñ: "
        f"<b>{money(get_balance(user_id))} â½</b>",
        after_game_keyboard()
    )


# =========================================================
# WITHDRAWAL
# =========================================================

def withdrawal_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="â  ÐÐ¢ÐÐÐÐ",
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
            "â­âââââââââââââââââââââ®\n"
            "       ð¸ <b>WITHDRAW</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            f"ð° ÐÐ¾ÑÑÑÐ¿Ð½Ð¾: "
            f"<b>{money(balance)} â½</b>\n\n"
            "ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ ÑÑÐ¼Ð¼Ð° Ð²ÑÐ²Ð¾Ð´Ð°: "
            f"<b>{money(MIN_WITHDRAWAL)} â½</b>\n"
            "(1 USDT)",
            wallet_keyboard(),
            PHOTO_WITHDRAW
        )
        return

    games[user_id] = {
        "withdraw_action": "amount"
    }

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð¸ <b>WITHDRAW</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð° ÐÐ¾ÑÑÑÐ¿Ð½Ð¾: "
        f"<b>{money(balance)} â½</b>\n"
        f"ð ÐÐ¸Ð½Ð¸Ð¼ÑÐ¼: "
        f"<b>{money(MIN_WITHDRAWAL)} â½</b> "
        "(1 USDT)\n\n"
        "ÐÐ²ÐµÐ´Ð¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð²ÑÐ²Ð¾Ð´Ð° Ð² ÑÑÐ±Ð»ÑÑ.\n\n"
        "ÐÐ°Ð¿ÑÐ¸Ð¼ÐµÑ:\n"
        "<code>5000</code>",
        withdrawal_keyboard(),
        PHOTO_WITHDRAW
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
            "ð¸ <b>WITHDRAWALS</b>\n\n"
            "ÐÐ°ÑÐ²Ð¾Ðº Ð¿Ð¾ÐºÐ° Ð½ÐµÑ."
        )

    else:
        lines = [
            "ð¸ <b>MY WITHDRAWALS</b>\n"
        ]

        status_names = {
            "pending": "â³ ÐÐ¶Ð¸Ð´Ð°ÐµÑ",
            "approved": "â ÐÐ¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÑÐ½",
            "rejected": "â ÐÑÐºÐ»Ð¾Ð½ÑÐ½",
            "paid": "ð¸ ÐÑÐ¿Ð»Ð°ÑÐµÐ½",
        }

        for item in history:
            status = status_names.get(
                item["status"],
                item["status"]
            )

            lines.append(
                f"#{item['id']} â "
                f"<b>{money(item['amount_rub'])} â½</b>\n"
                f"{status}"
            )

        text = "\n\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="â¬ï¸  ÐÐ ÐÐ¤ÐÐÐ¬",
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
        text="ð¤  ÐÐÐÐ¢Ð ÐÐÐÐ¬ÐÐÐÐÐ¢ÐÐÐ¯",
        callback_data="admin_find_user"
    )

    builder.button(
        text="ð¸  ÐÐÐ¯ÐÐÐ ÐÐ ÐÐ«ÐÐÐ",
        callback_data="admin_withdrawals"
    )

    builder.button(
        text="â¬ï¸  ÐÐÐÐÐÐÐ ÐÐÐÐ®",
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    await callback.answer()

    await edit_or_answer(
        callback,
        "ââââââââââââââââââââââââ\n"
        "      ð  <b>ADMIN PANEL</b>\n"
        "ââââââââââââââââââââââââ\n\n"
        "Ð¡Ð¸ÑÑÐµÐ¼Ð½Ð¾Ðµ ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½Ð¸Ðµ.\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ:",
        admin_main_keyboard(),
        PHOTO_ADMIN
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    games[user_id] = {
        "admin_action": "find_user"
    }

    await callback.answer()

    await callback.message.answer(
        "ð¤ <b>USER SEARCH</b>\n\n"
        "ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ Telegram ID Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ."
    )


def admin_user_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð°  ÐÐ«ÐÐÐ¢Ð¬ ÐÐÐÐÐÐ¡",
        callback_data="admin_add_balance"
    )

    builder.button(
        text="â  Ð¡ÐÐ¯Ð¢Ð¬ Ð¡ ÐÐÐÐÐÐ¡Ð",
        callback_data="admin_remove_balance"
    )

    builder.button(
        text="ð  ÐÐÐÐÐÐÐ¢Ð¬",
        callback_data="admin_refresh"
    )

    builder.button(
        text="ð  ÐÐ¡Ð¢ÐÐ ÐÐ¯ ÐÐÐ ",
        callback_data="admin_game_history"
    )

    builder.button(
        text="ð³  ÐÐ¡Ð¢ÐÐ ÐÐ¯ ÐÐÐÐ¢ÐÐÐÐ",
        callback_data="admin_payment_history"
    )

    builder.button(
        text="ð   ADMIN PANEL",
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
        "â­âââââââââââââââââââââ®\n"
        "       ð¤ <b>USER</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ID: <code>{target_id}</code>\n"
        f"ð° ÐÐ°Ð»Ð°Ð½Ñ: "
        f"<b>{money(balance)} â½</b>",
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð½Ðµ Ð²ÑÐ±ÑÐ°Ð½",
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
        "ð° ÐÐ²ÐµÐ´Ð¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð´Ð»Ñ Ð²ÑÐ´Ð°ÑÐ¸:"
        if action == "add"
        else "â ÐÐ²ÐµÐ´Ð¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð´Ð»Ñ ÑÐ½ÑÑÐ¸Ñ:"
    )

    await callback.message.answer(text)


@dp.callback_query(F.data == "admin_refresh")
async def admin_refresh(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer(
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð½Ðµ Ð²ÑÐ±ÑÐ°Ð½",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    balance = get_balance(target_id)

    await callback.answer(
        f"ÐÐ°Ð»Ð°Ð½Ñ: {money(balance)} â½"
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð½Ðµ Ð²ÑÐ±ÑÐ°Ð½",
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
            "ð <b>GAME HISTORY</b>\n\n"
            "ÐÐ³Ñ Ð½ÐµÑ."
        )

    else:
        lines = [
            "ð <b>GAME HISTORY</b>\n"
        ]

        for item in history:
            result = (
                "â"
                if item["result"] == "win"
                else "â"
            )

            lines.append(
                f"{result} {item['game']} | "
                f"{money(item['stake'])} â½ â "
                f"{money(item['payout'])} â½"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð¤  Ð ÐÐÐÐ¬ÐÐÐÐÐ¢ÐÐÐ®",
        callback_data="admin_user_back"
    )

    builder.button(
        text="ð   ADMIN PANEL",
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð½Ðµ Ð²ÑÐ±ÑÐ°Ð½",
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
            "ð³ <b>PAYMENT HISTORY</b>\n\n"
            "ÐÐ»Ð°ÑÐµÐ¶ÐµÐ¹ Ð½ÐµÑ."
        )

    else:
        lines = [
            "ð³ <b>PAYMENT HISTORY</b>\n"
        ]

        for item in history:
            lines.append(
                f"ðµ {item['amount_usdt']} USDT â "
                f"{money(item['amount_rub'])} â½\n"
                f"ð§¾ #{item['invoice_id']}"
            )

        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()

    builder.button(
        text="ð¤  Ð ÐÐÐÐ¬ÐÐÐÐÐ¢ÐÐÐ®",
        callback_data="admin_user_back"
    )

    builder.button(
        text="ð   ADMIN PANEL",
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await callback.answer(
            "ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð½Ðµ Ð²ÑÐ±ÑÐ°Ð½",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    await callback.answer()

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð¤ <b>USER</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ID: <code>{target_id}</code>\n"
        f"ð° ÐÐ°Ð»Ð°Ð½Ñ: "
        f"<b>{money(get_balance(target_id))} â½</b>",
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
                f"#{item['id']} â "
                f"{money(item['amount_rub'])} â½"
            ),
            callback_data=(
                f"admin_withdraw_{item['id']}"
            )
        )

    builder.button(
        text="â¬ï¸  ADMIN PANEL",
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    await callback.answer()

    withdrawals = get_pending_withdrawals(20)

    if not withdrawals:
        await edit_or_answer(
            callback,
            "â­âââââââââââââââââââââ®\n"
            "       ð¸ <b>WITHDRAWALS</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            "ÐÐ¶Ð¸Ð´Ð°ÑÑÐ¸Ñ Ð·Ð°ÑÐ²Ð¾Ðº Ð½ÐµÑ.",
            admin_main_keyboard(),
            PHOTO_ADMIN
        )
        return

    await edit_or_answer(
        callback,
        "â­âââââââââââââââââââââ®\n"
        "       ð¸ <b>WITHDRAWALS</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð·Ð°ÑÐ²ÐºÑ:",
        admin_withdrawal_list_keyboard(
            withdrawals
        ),
        PHOTO_ADMIN
    )


def admin_withdrawal_keyboard(
    withdrawal
):
    builder = InlineKeyboardBuilder()

    status = withdrawal.get("status")

    if status == "pending":
        builder.button(
            text="â  ÐÐÐÐ¢ÐÐÐ ÐÐÐ¢Ð¬",
            callback_data=(
                f"approve_withdraw_"
                f"{withdrawal['id']}"
            )
        )

        builder.button(
            text="â  ÐÐ¢ÐÐÐÐÐÐ¢Ð¬",
            callback_data=(
                f"reject_withdraw_"
                f"{withdrawal['id']}"
            )
        )

    elif status == "approved":
        builder.button(
            text="ð¸  ÐÐ«ÐÐÐÐ¢Ð ÐÐ¢ÐÐ ÐÐÐÐÐÐ",
            callback_data=(
                f"paid_withdraw_"
                f"{withdrawal['id']}"
            )
        )

    builder.button(
        text="â¬ï¸  Ð ÐÐÐ¯ÐÐÐÐ",
        callback_data="admin_withdrawals"
    )

    builder.button(
        text="ð   ADMIN PANEL",
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "ÐÑÐ¸Ð±ÐºÐ° Ð·Ð°ÑÐ²ÐºÐ¸",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "ÐÐ°ÑÐ²ÐºÐ° Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð°",
            show_alert=True
        )
        return

    await callback.answer()

    status_names = {
        "pending": "â³ ÐÐÐÐÐÐÐ¢",
        "approved": "â ÐÐÐÐ¢ÐÐÐ ÐÐÐÐÐ",
        "rejected": "â ÐÐ¢ÐÐÐÐÐÐÐ",
        "paid": "ð¸ ÐÐ«ÐÐÐÐ§ÐÐÐ",
    }

    status = status_names.get(
        withdrawal.get("status"),
        withdrawal.get("status")
    )

    destination = (
        withdrawal.get("payout_details")
        or "ÐÐµ ÑÐºÐ°Ð·Ð°Ð½Ñ"
    )

    text = (
        "â­âââââââââââââââââââââ®\n"
        "       ð¸ <b>WITHDRAWAL</b>\n"
        "â°âââââââââââââââââââââ¯\n\n"
        f"ð§¾ ÐÐ¾Ð¼ÐµÑ: "
        f"<b>#{withdrawal['id']}</b>\n"
        f"ð¤ User ID: "
        f"<code>{withdrawal['user_id']}</code>\n"
        f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
        f"<b>{money(withdrawal['amount_rub'])} â½</b>\n"
        f"ð³ ÐÐµÑÐ¾Ð´: <b>manual</b>\n"
        f"ð Ð ÐµÐºÐ²Ð¸Ð·Ð¸ÑÑ:\n"
        f"<code>{destination}</code>\n\n"
        f"ð Ð¡ÑÐ°ÑÑÑ: <b>{status}</b>"
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "ÐÑÐ¸Ð±ÐºÐ° Ð·Ð°ÑÐ²ÐºÐ¸",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "ÐÐ°ÑÐ²ÐºÐ° Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð°",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "pending":
        await callback.answer(
            "ÐÐ°ÑÐ²ÐºÐ° ÑÐ¶Ðµ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐ°Ð½Ð°",
            show_alert=True
        )
        return

    result = approve_withdrawal(
        withdrawal_id
    )

    if result is None:
        await callback.answer(
            "ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ Ð·Ð°ÑÐ²ÐºÑ",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    try:
        await bot.send_message(
            withdrawal["user_id"],
            "â <b>ÐÐ«ÐÐÐ ÐÐÐÐ¢ÐÐÐ ÐÐÐÐ</b>\n\n"
            f"ð§¾ ÐÐ°ÑÐ²ÐºÐ°: "
            f"<b>#{withdrawal_id}</b>\n"
            f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
            f"<b>{money(withdrawal['amount_rub'])} â½</b>\n\n"
            "ÐÐ°ÑÐ²ÐºÐ° Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÐµÐ½Ð° Ð°Ð´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾ÑÐ¾Ð¼.\n"
            "ÐÑÐ¿Ð»Ð°ÑÐ° Ð±ÑÐ´ÐµÑ Ð²ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð° Ð²ÑÑÑÐ½ÑÑ."
        )
    except Exception as error:
        print(
            "WITHDRAW APPROVE USER "
            "NOTIFICATION ERROR:",
            repr(error)
        )

    await callback.answer(
        "ÐÐ°ÑÐ²ÐºÐ° Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÐµÐ½Ð°"
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "ÐÑÐ¸Ð±ÐºÐ° Ð·Ð°ÑÐ²ÐºÐ¸",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "ÐÐ°ÑÐ²ÐºÐ° Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð°",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "pending":
        await callback.answer(
            "ÐÐ°ÑÐ²ÐºÐ° ÑÐ¶Ðµ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐ°Ð½Ð°",
            show_alert=True
        )
        return

    result = reject_withdrawal(
        withdrawal_id
    )

    if result is None:
        await callback.answer(
            "ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¾ÑÐºÐ»Ð¾Ð½Ð¸ÑÑ Ð·Ð°ÑÐ²ÐºÑ",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    try:
        await bot.send_message(
            withdrawal["user_id"],
            "â <b>ÐÐ«ÐÐÐ ÐÐ¢ÐÐÐÐÐÐ</b>\n\n"
            f"ð§¾ ÐÐ°ÑÐ²ÐºÐ°: "
            f"<b>#{withdrawal_id}</b>\n"
            f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
            f"<b>{money(withdrawal['amount_rub'])} â½</b>\n\n"
            "ÐÐ°ÑÐ²ÐºÐ° Ð¾ÑÐºÐ»Ð¾Ð½ÐµÐ½Ð°.\n"
            "ÐÐ°ÑÐµÐ·ÐµÑÐ²Ð¸ÑÐ¾Ð²Ð°Ð½Ð½ÑÐµ ÑÑÐµÐ´ÑÑÐ²Ð° "
            "Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ Ð½Ð° Ð±Ð°Ð»Ð°Ð½Ñ."
        )
    except Exception as error:
        print(
            "WITHDRAW REJECT USER "
            "NOTIFICATION ERROR:",
            repr(error)
        )

    await callback.answer(
        "ÐÐ°ÑÐ²ÐºÐ° Ð¾ÑÐºÐ»Ð¾Ð½ÐµÐ½Ð°, ÑÑÐµÐ´ÑÑÐ²Ð° Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ"
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
            "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await callback.answer(
            "ÐÑÐ¸Ð±ÐºÐ° Ð·Ð°ÑÐ²ÐºÐ¸",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await callback.answer(
            "ÐÐ°ÑÐ²ÐºÐ° Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð°",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "approved":
        await callback.answer(
            "Ð¡Ð½Ð°ÑÐ°Ð»Ð° Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÐµ Ð·Ð°ÑÐ²ÐºÑ",
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
            "ÐÑÐ¸Ð±ÐºÐ° Ð·Ð°Ð²ÐµÑÑÐµÐ½Ð¸Ñ Ð²ÑÐ¿Ð»Ð°ÑÑ",
            show_alert=True
        )
        return

    if result is None:
        await callback.answer(
            "ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð²ÐµÑÑÐ¸ÑÑ Ð·Ð°ÑÐ²ÐºÑ",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    try:
        await bot.send_message(
            withdrawal["user_id"],
            "ð¸ <b>ÐÐ«ÐÐÐÐ¢Ð ÐÐ¢ÐÐ ÐÐÐÐÐÐ</b>\n\n"
            f"ð§¾ ÐÐ°ÑÐ²ÐºÐ°: "
            f"<b>#{withdrawal_id}</b>\n"
            f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
            f"<b>{money(withdrawal['amount_rub'])} â½</b>\n\n"
            "ÐÑÐ¿Ð»Ð°ÑÐ° Ð¾ÑÐ¼ÐµÑÐµÐ½Ð° Ð°Ð´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾ÑÐ¾Ð¼ "
            "ÐºÐ°Ðº Ð²ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð½Ð°Ñ."
        )
    except Exception as error:
        print(
            "WITHDRAW PAID USER "
            "NOTIFICATION ERROR:",
            repr(error)
        )

    await callback.answer(
        "ÐÑÐ¿Ð»Ð°ÑÐ° Ð¾ÑÐ¼ÐµÑÐµÐ½Ð° ÐºÐ°Ðº Ð²ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð½Ð°Ñ"
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
                "â ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½Ð°Ñ ÑÑÐ¼Ð¼Ð°.\n\n"
                f"ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½ÑÐ¹ Ð²ÑÐ²Ð¾Ð´: "
                f"<b>{money(MIN_WITHDRAWAL)} â½</b>\n"
                "(1 USDT)"
            )
            return True

        balance = get_balance(user_id)

        if amount > balance:
            await message.answer(
                "â ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ².\n\n"
                f"ð° ÐÐ°Ñ Ð±Ð°Ð»Ð°Ð½Ñ: "
                f"<b>{money(balance)} â½</b>"
            )
            return True

        games[user_id] = {
            "withdraw_action": "destination",
            "withdraw_amount": amount
        }

        await message.answer(
            "ð³ <b>Ð ÐÐÐÐÐÐÐ¢Ð« ÐÐÐ¯ ÐÐ«ÐÐÐÐ</b>\n\n"
            f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
            f"<b>{money(amount)} â½</b>\n\n"
            "ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ ÑÐµÐºÐ²Ð¸Ð·Ð¸ÑÑ, Ð½Ð° ÐºÐ¾ÑÐ¾ÑÑÐµ "
            "Ð½ÑÐ¶Ð½Ð¾ Ð²ÑÐ¿Ð¾Ð»Ð½Ð¸ÑÑ Ð²ÑÐ¿Ð»Ð°ÑÑ.\n\n"
            "ÐÐ°Ð¿ÑÐ¸Ð¼ÐµÑ, Ð°Ð´ÑÐµÑ ÐºÐ¾ÑÐµÐ»ÑÐºÐ° "
            "USDT TRC20."
        )

        return True

    if state.get("withdraw_action") == "destination":

        destination = (
            message.text or ""
        ).strip()

        if len(destination) < 5:
            await message.answer(
                "â Ð ÐµÐºÐ²Ð¸Ð·Ð¸ÑÑ ÑÐ»Ð¸ÑÐºÐ¾Ð¼ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ðµ.\n"
                "ÐÑÐ¾Ð²ÐµÑÑÑÐµ Ð¸ Ð¾ÑÐ¿ÑÐ°Ð²ÑÑÐµ ÐµÑÑ ÑÐ°Ð·."
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
                "â ÐÐ°ÑÐ²ÐºÐ° ÑÑÑÐ°ÑÐµÐ»Ð°.\n"
                "Ð¡Ð¾Ð·Ð´Ð°Ð¹ÑÐµ Ð²ÑÐ²Ð¾Ð´ Ð·Ð°Ð½Ð¾Ð²Ð¾."
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
                "â ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ Ð·Ð°ÑÐ²ÐºÑ.\n\n"
                "ÐÐ¾Ð·Ð¼Ð¾Ð¶Ð½Ð¾, Ð½ÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ²."
            )
            return True

        games.pop(
            user_id,
            None
        )

        await message.answer(
            "â­âââââââââââââââââââââ®\n"
            "       ð¸ <b>WITHDRAW</b>\n"
            "â°âââââââââââââââââââââ¯\n\n"
            "â <b>ÐÐÐ¯ÐÐÐ Ð¡ÐÐÐÐÐÐ</b>\n\n"
            f"ð§¾ ÐÐ¾Ð¼ÐµÑ: "
            f"<b>#{withdrawal['id']}</b>\n"
            f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
            f"<b>{money(amount)} â½</b>\n"
            "â³ Ð¡ÑÐ°ÑÑÑ: "
            "<b>ÐÐÐÐÐÐÐ¢ ÐÐ ÐÐÐÐ ÐÐ</b>\n\n"
            "Ð¡ÑÐµÐ´ÑÑÐ²Ð° Ð·Ð°ÑÐµÐ·ÐµÑÐ²Ð¸ÑÐ¾Ð²Ð°Ð½Ñ Ð´Ð¾ ÑÐµÑÐµÐ½Ð¸Ñ "
            "Ð°Ð´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾ÑÐ°.\n\n"
            "ÐÐ¾ÑÐ»Ðµ Ð¿ÑÐ¾Ð²ÐµÑÐºÐ¸ Ð²Ñ Ð¿Ð¾Ð»ÑÑÐ¸ÑÐµ ÑÐ²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ðµ."
        )

        try:
            await bot.send_message(
                8244079903,
                "ð¸ <b>ÐÐÐÐÐ¯ ÐÐÐ¯ÐÐÐ ÐÐ ÐÐ«ÐÐÐ</b>\n\n"
                f"ð§¾ ÐÐ°ÑÐ²ÐºÐ°: "
                f"<b>#{withdrawal['id']}</b>\n"
                f"ð¤ User ID: "
                f"<code>{user_id}</code>\n"
                f"ð° Ð¡ÑÐ¼Ð¼Ð°: "
                f"<b>{money(amount)} â½</b>\n\n"
                "ÐÑÐºÑÐ¾Ð¹ ADMIN PANEL â "
                "ÐÐÐ¯ÐÐÐ ÐÐ ÐÐ«ÐÐÐ."
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
                "â ID Ð´Ð¾Ð»Ð¶ÐµÐ½ Ð±ÑÑÑ ÑÐ¸ÑÐ»Ð¾Ð¼."
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
                "â ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð¿Ð¾Ð»Ð¾Ð¶Ð¸ÑÐµÐ»ÑÐ½Ð¾Ðµ "
                "ÑÐµÐ»Ð¾Ðµ ÑÐ¸ÑÐ»Ð¾."
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
                "â­âââââââââââââââââââââ®\n"
                "       ð° <b>BALANCE</b>\n"
                "â°âââââââââââââââââââââ¯\n\n"
                "â <b>ÐÐÐÐÐÐ¡ ÐÐ«ÐÐÐ</b>\n\n"
                f"ð¤ ID: "
                f"<code>{target_id}</code>\n"
                f"ð° +{money(amount)} â½\n"
                f"ð³ ÐÐ¾Ð²ÑÐ¹ Ð±Ð°Ð»Ð°Ð½Ñ: "
                f"<b>{money(new_balance)} â½</b>",
                reply_markup=admin_user_keyboard()
            )

        else:

            success = subtract_balance(
                target_id,
                amount
            )

            if not success:
                await message.answer(
                    "â ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ² "
                    "Ð½Ð° Ð±Ð°Ð»Ð°Ð½ÑÐµ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ."
                )
                return True

            new_balance = get_balance(
                target_id
            )

            await message.answer(
                "â­âââââââââââââââââââââ®\n"
                "       ð° <b>BALANCE</b>\n"
                "â°âââââââââââââââââââââ¯\n\n"
                "â <b>ÐÐÐÐÐÐ¡ Ð¡ÐÐ¯Ð¢</b>\n\n"
                f"ð¤ ID: "
                f"<code>{target_id}</code>\n"
                f"â {money(amount)} â½\n"
                f"ð³ ÐÐ¾Ð²ÑÐ¹ Ð±Ð°Ð»Ð°Ð½Ñ: "
                f"<b>{money(new_balance)} â½</b>",
                reply_markup=admin_user_keyboard()
            )

        games[user_id] = {
            "admin_action": "user_menu",
            "target_user": target_id
        }

        return True

    return False

@dp.message()
async def text_message_handler(message: Message):
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

    if state.get("awaiting_stake"):
        handled = await handle_stake_message(
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
