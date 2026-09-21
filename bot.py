import asyncio
import os
import random
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message,
    CallbackQuery,
    Update,
    InputMediaPhoto,
    FSInputFile,
    BotCommand,
    MenuButtonCommands,
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


# =========================================================
# ROULETTE RULES / ANIMATION
# =========================================================

# Коэффициенты НЕ МЕНЯТЬ:
# 🔴 Красное  x1.85
# ⚫️ Чёрное  x1.85
# 🟢 Зелёное x14
ROULETTE_MULTIPLIERS = {
    "red": 1.85,
    "black": 1.85,
    "zero": 14.0,
}

ROULETTE_NUMBERS = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6,
    27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
    16, 33, 1, 20, 14, 31, 9, 22, 18, 29,
    7, 28, 12, 35, 3, 26,
]

ROULETTE_RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25,
    27, 30, 32, 34, 36,
}


def roulette_result_color(number: int) -> str:
    if number == 0:
        return "zero"
    if number in ROULETTE_RED_NUMBERS:
        return "red"
    return "black"


def roulette_result_emoji(number: int) -> str:
    color = roulette_result_color(number)
    if color == "zero":
        return "🟢"
    if color == "red":
        return "🔴"
    return "⚫️"


def roulette_color_label(color: str) -> str:
    return {
        "red": "Красное 🔴",
        "black": "Чёрное ⚫️",
        "zero": "Зелёное 🟢",
    }.get(color, color)


def roulette_window(center_index: int, width: int = 5):
    """Возвращает окно чисел вокруг текущей позиции на колесе."""
    half = width // 2
    return [
        ROULETTE_NUMBERS[(center_index + offset) % len(ROULETTE_NUMBERS)]
        for offset in range(-half, half + 1)
    ]


def roulette_frame_text(numbers, result=None, final=False):
    cells = []
    center = len(numbers) // 2

    for i, number in enumerate(numbers):
        cell = f"{roulette_result_emoji(number)} {number}"
        if i == center:
            cell = f"<b>{cell}</b>"
        cells.append(cell)

    line = "  │  ".join(cells)

    if final and result is not None:
        return (
            "╭────────────────────────────╮\n"
            "        🎡 <b>ROULETTE</b>\n"
            "╰────────────────────────────╯\n\n"
            "              ▼\n"
            f"{line}\n"
            "              ▲"
        )

    return (
        "╭────────────────────────────╮\n"
        "        🎡 <b>ROULETTE</b>\n"
        "╰────────────────────────────╯\n\n"
        "              ▼\n"
        f"{line}\n\n"
        "        🔄 <b>ВРАЩЕНИЕ...</b>"
    )

CRASH_MIN = 1.05
CRASH_MAX = 20.0

# 1 USDT = 80 ₽
# Минимальный вывод = 1 USDT
MIN_WITHDRAWAL = 80


# =========================================================
# TELEGRAM PREMIUM CUSTOM EMOJI
# =========================================================

CUSTOM_EMOJI = {
    # IDs supplied for the new premium UI
    "profile": "5116116063188157350",
    "balance_currency": "5231449120635370684",
    "games": "5471952986970267163",
    "wins": "5426896538062332283",
    "losses": "5188344996356448758",
    "winrate": "5454350746407419714",
    "bets": "5298614648138919107",
    "winnings": "5431361968315332861",
    "max_win": "5375452661036358740",
    "withdraw": "5373174941095050893",
    "available": "6025976946083500432",
    "withdraw_currency": "5409048419211682843",
    "admin": "5462921117423384478",
    "wallet": "5471952986970267163",
    "wallet_topup": "5427173563452923041",
    "wallet_games": "5382150533685469668",
    "wallet_withdraw": "5445353829304387411",
    # Reuse supplied IDs for generic game/action icons so no ordinary emoji
    # remain in the user-facing text.
    "win": "5426896538062332283",
    "loss": "5188344996356448758",
    "stake": "5298614648138919107",
    "dice": "5471952986970267163",
    "slots": "5471952986970267163",
    "bowling": "5471952986970267163",
    "roulette": "5471952986970267163",
    "mines": "5471952986970267163",
    "crash": "5471952986970267163",
    "deposit": "5427173563452923041",
    "history": "5298614648138919107",
}



def tg_emoji(emoji_id: str, fallback: str) -> str:
    """
    Telegram Bot API: HTML <tg-emoji> is converted by Telegram into a
    custom_emoji MessageEntity with the supplied custom_emoji_id.
    """
    return (
        f'<tg-emoji emoji-id="{emoji_id}">'
        f'{fallback}'
        f'</tg-emoji>'
    )


def premiumize_text(text: str) -> str:
    """Convert ordinary emoji to Telegram custom emoji and apply the casino UI typography.

    All visible copy is bold; monetary amounts are rendered in monospace.
    Existing HTML tags are preserved.
    """
    if not text:
        return text

    replacements = {
        "💰": tg_emoji(CUSTOM_EMOJI["balance_currency"], "💰"),
        "🏆": tg_emoji(CUSTOM_EMOJI["wins"], "🏆"),
        "💥": tg_emoji(CUSTOM_EMOJI["losses"], "💥"),
        "🎲": tg_emoji(CUSTOM_EMOJI["games"], "🎲"),
        "🎰": tg_emoji(CUSTOM_EMOJI["games"], "🎰"),
        "🎳": tg_emoji(CUSTOM_EMOJI["games"], "🎳"),
        "🎡": tg_emoji(CUSTOM_EMOJI["games"], "🎡"),
        "💣": tg_emoji(CUSTOM_EMOJI["games"], "💣"),
        "🚀": tg_emoji(CUSTOM_EMOJI["games"], "🚀"),
        "💎": tg_emoji(CUSTOM_EMOJI["bets"], "💎"),
        "👤": tg_emoji(CUSTOM_EMOJI["profile"], "👤"),
        "📜": tg_emoji(CUSTOM_EMOJI["history"], "📜"),
        "💳": tg_emoji(CUSTOM_EMOJI["deposit"], "💳"),
        "💸": tg_emoji(CUSTOM_EMOJI["withdraw"], "💸"),
        "🛠": tg_emoji(CUSTOM_EMOJI["admin"], "🛠"),
        "❌": tg_emoji(CUSTOM_EMOJI["losses"], "❌"),
        "📈": tg_emoji(CUSTOM_EMOJI["winrate"], "📈"),
        "💵": tg_emoji(CUSTOM_EMOJI["bets"], "💵"),
        "🔥": tg_emoji(CUSTOM_EMOJI["max_win"], "🔥"),
        "🎉": tg_emoji(CUSTOM_EMOJI["wins"], "🎉"),
        "📉": tg_emoji(CUSTOM_EMOJI["withdraw"], "📉"),
        "🧾": tg_emoji(CUSTOM_EMOJI["history"], "🧾"),
        "✅": tg_emoji(CUSTOM_EMOJI["wins"], "✅"),
        "⚠️": tg_emoji(CUSTOM_EMOJI["losses"], "⚠️"),
        "⏳": tg_emoji(CUSTOM_EMOJI["withdraw"], "⏳"),
        "🔄": tg_emoji(CUSTOM_EMOJI["games"], "🔄"),
        "⬅️": tg_emoji(CUSTOM_EMOJI["games"], "⬅️"),
        "🏠": tg_emoji(CUSTOM_EMOJI["games"], "🏠"),
        "✕": tg_emoji(CUSTOM_EMOJI["losses"], "✕"),
        "❓": tg_emoji(CUSTOM_EMOJI["losses"], "❓"),
        "🖼": tg_emoji(CUSTOM_EMOJI["profile"], "🖼"),
        "📊": tg_emoji(CUSTOM_EMOJI["winrate"], "📊"),
        "➖": tg_emoji(CUSTOM_EMOJI["losses"], "➖"),
        "🎯": tg_emoji(CUSTOM_EMOJI["winrate"], "🎯"),
        "🔴": tg_emoji(CUSTOM_EMOJI["losses"], "🔴"),
        "⚫️": tg_emoji(CUSTOM_EMOJI["games"], "⚫️"),
        "🟢": tg_emoji(CUSTOM_EMOJI["wins"], "🟢"),
        "🔺": tg_emoji(CUSTOM_EMOJI["games"], "🔺"),
        "⬇️": tg_emoji(CUSTOM_EMOJI["games"], "⬇️"),
        "⬆️": tg_emoji(CUSTOM_EMOJI["games"], "⬆️"),
        "→": "→",
    }

    placeholders = {}
    for index, (source, replacement) in enumerate(replacements.items()):
        token = f"__CUSTOM_EMOJI_{index}__"
        text = text.replace(source, token)
        placeholders[token] = replacement
    for token, replacement in placeholders.items():
        text = text.replace(token, replacement)

    # Amounts / monetary values: 1 234 ₽, 80 ₽, 1 USDT, x1.85, etc.
    # Do not alter HTML attributes or already-monospace content.
    amount_pattern = re.compile(
        r'(?<![\w>])(?P<num>\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)'
        r'(?P<unit> ?(?:₽|USDT))'
    )
    text = amount_pattern.sub(lambda m: f'<code>{m.group("num")}</code>{m.group("unit")}', text)

    # Bold visible content without touching HTML tags. This deliberately keeps
    # the supplied <b>/<code>/<tg-emoji> markup valid.
    parts = re.split(r'(<[^>]+>)', text)
    visible = []
    for part in parts:
        if not part:
            continue
        if part.startswith('<') and part.endswith('>'):
            visible.append(part)
        else:
            visible.append(f'<b>{part}</b>')
    return ''.join(visible)


async def safe_callback_answer(callback: CallbackQuery, *args, **kwargs):
    """A stale Telegram callback must never turn the webhook into HTTP 500."""
    try:
        await callback.answer(*args, **kwargs)
    except TelegramBadRequest as error:
        message = str(error).lower()
        if 'query is too old' in message or 'query id is invalid' in message or 'response timeout expired' in message:
            print('STALE CALLBACK IGNORED:', repr(error))
            return
        raise

# =========================================================
# PREMIUM PHOTOS
# =========================================================
#
# Фотографии подключаются через Render Environment Variables.
# =========================================================
# LOCAL BANNERS
# =========================================================
# Все баннеры лежат прямо в корне репозитория, рядом с bot.py.
# Если локального файла нет, бот автоматически использует старый PHOTO_* из Render.

BASE_DIR = Path(__file__).resolve().parent


def local_banner(filename: str):
    path = BASE_DIR / filename
    if path.exists():
        return FSInputFile(str(path))
    return ""


PHOTO_MAIN = local_banner("main.png") or os.getenv("PHOTO_MAIN", "")
PHOTO_GAMES = local_banner("main.png") or os.getenv("PHOTO_GAMES", "")
PHOTO_WALLET = local_banner("balance.png") or os.getenv("PHOTO_WALLET", "")
PHOTO_DICE = local_banner("dice.png")
PHOTO_SLOTS = local_banner("slots.png")
PHOTO_BOWLING = local_banner("bowling.png")
PHOTO_ROULETTE = local_banner("roulette.png") or os.getenv("PHOTO_ROULETTE", "")
PHOTO_MINES = local_banner("mines.png") or os.getenv("PHOTO_MINES", "")
PHOTO_CRASH = local_banner("crash.png") or os.getenv("PHOTO_CRASH", "")
PHOTO_STAKE = local_banner("stake.png")
PHOTO_WIN = local_banner("win.png")
PHOTO_PROFILE = local_banner("profile.png")
PHOTO_HISTORY = local_banner("history.png")
PHOTO_TOPUP = local_banner("topup.png")
PHOTO_BALANCE = local_banner("balance.png")
PHOTO_VIP = local_banner("vip.png")
PHOTO_BONUSES = local_banner("bonuses.png")
PHOTO_SUPPORT = local_banner("support.png")
PHOTO_WITHDRAW = PHOTO_BALANCE or os.getenv("PHOTO_WITHDRAW", "")
PHOTO_ADMIN = os.getenv("PHOTO_ADMIN", "") or PHOTO_VIP

# =========================================================
# PREMIUM UI / HELPERS
# =========================================================

def money(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def safe_user_id(message: Message) -> int:
    return message.from_user.id


def auto_page_photo(text: str, explicit_photo=""):
    """Выбирает локальный баннер для страницы, если он не передан явно."""
    if explicit_photo:
        return explicit_photo

    upper = (text or "").upper()

    # Результаты показываем отдельным WIN-баннером.
    if "JACKPOT" in upper or "<B>WIN</B>" in upper or "ПОБЕД" in upper:
        return PHOTO_WIN

    if "PROFILE" in upper or "ПРОФИЛ" in upper:
        return PHOTO_PROFILE
    if "GAME HISTORY" in upper or "ИСТОРИЯ ИГР" in upper:
        return PHOTO_HISTORY
    if "PAYMENT HISTORY" in upper or "PAYMENTS" in upper or "ПЛАТЕЖ" in upper:
        return PHOTO_TOPUP
    if "DEPOSIT" in upper or "INVOICE" in upper or "ПОПОЛН" in upper:
        return PHOTO_TOPUP
    if "WITHDRAW" in upper or "ВЫВОД" in upper:
        return PHOTO_WITHDRAW
    if "ADMIN" in upper:
        return PHOTO_ADMIN
    if "ВВЕДИТЕ СТАВКУ" in upper or "ВВОД СТАВКИ" in upper:
        return PHOTO_STAKE
    if "WALLET" in upper or "BALANCE" in upper or "БАЛАНС" in upper:
        return PHOTO_BALANCE
    if "GAMES" in upper or "ВЫБЕРИТЕ ИГРУ" in upper:
        return PHOTO_GAMES

    if "DICE" in upper:
        return PHOTO_DICE
    if "SLOTS" in upper:
        return PHOTO_SLOTS
    if "BOWLING" in upper:
        return PHOTO_BOWLING
    if "ROULETTE" in upper:
        return PHOTO_ROULETTE
    if "MINES" in upper:
        return PHOTO_MINES
    if "CRASH" in upper:
        return PHOTO_CRASH

    return PHOTO_MAIN


async def edit_or_answer(
    callback: CallbackQuery,
    text: str,
    keyboard=None,
    photo=""
):
    """
    Универсальное переключение:
    text -> text
    text -> photo
    photo -> text
    photo -> photo
    """

    message = callback.message
    photo = auto_page_photo(text, photo)

    # -----------------------------------------------------
    # PHOTO MODE
    # -----------------------------------------------------

    if photo:
        try:
            if message.photo:
                await message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=premiumize_text(text),
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
                    caption=premiumize_text(text),
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
                premiumize_text(text),
                reply_markup=keyboard
            )
        else:
            await message.edit_text(
                premiumize_text(text),
                reply_markup=keyboard
            )

    except Exception as error:
        print(
            "EDIT TEXT ERROR:",
            repr(error)
        )

        try:
            await message.answer(
                premiumize_text(text),
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
                caption=premiumize_text(text),
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
        premiumize_text(text),
        reply_markup=keyboard
    )


def main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ИГРЫ",
        callback_data="games"
    )

    builder.button(
        text="БАЛАНС",
        callback_data="wallet"
    )

    builder.button(
        text="ПРОФИЛЬ",
        callback_data="profile"
    )

    builder.button(
        text="ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    builder.button(
        text="ВЫВЕСТИ",
        callback_data="withdraw"
    )

    builder.adjust(2)

    if is_admin(user_id):
        builder.button(
            text="ADMIN PANEL",
            callback_data="admin"
        )

    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="DICE",
        callback_data="game_dice"
    )

    builder.button(
        text="SLOTS",
        callback_data="game_slots"
    )

    builder.button(
        text="BOWLING",
        callback_data="game_bowling"
    )

    builder.button(
        text="ROULETTE",
        callback_data="game_roulette"
    )

    builder.button(
        text="MINES",
        callback_data="game_mines"
    )

    builder.button(
        text="CRASH",
        callback_data="game_crash"
    )

    builder.button(
        text="ГЛАВНОЕ МЕНЮ",
        callback_data="back_main"
    )

    builder.adjust(2)

    return builder.as_markup()


def stake_keyboard(prefix: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ВВЕСТИ СТАВКУ",
        callback_data=f"{prefix}_enter_stake"
    )

    builder.button(
        text="НАЗАД",
        callback_data="games"
    )

    builder.adjust(1)

    return builder.as_markup()


def confirm_bet_keyboard(game: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ПОДТВЕРДИТЬ СТАВКУ",
        callback_data=f"confirm_{game}"
    )

    builder.button(
        text="ОТМЕНА",
        callback_data="games"
    )

    builder.adjust(1)

    return builder.as_markup()


def wallet_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ПОПОЛНИТЬ",
        callback_data="deposit"
    )

    builder.button(
        text="ВЫВЕСТИ",
        callback_data="withdraw"
    )

    builder.button(
        text="НАЗАД",
        callback_data="back_main"
    )

    builder.adjust(1)

    return builder.as_markup()


def after_game_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ЕЩЁ РАЗ",
        callback_data="games"
    )

    builder.button(
        text="БАЛАНС",
        callback_data="wallet"
    )

    builder.button(
        text="ГЛАВНОЕ МЕНЮ",
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

    text = (
        "╔══════════════════════╗\n"
        "      🎰 <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "╚══════════════════════╝\n\n"

    )

    await answer_start_screen(
        message,
        text,
        main_keyboard(user_id),
        PHOTO_MAIN
    )


@dp.message(Command("menu"))
async def menu_handler(message: Message):
    """Открывает главное меню из Telegram Menu → /menu."""
    user_id = safe_user_id(message)
    ensure_user(user_id)

    text = (
        "╔══════════════════════╗\n"
        "      🎰 <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "╚══════════════════════╝\n\n"
        "Выберите раздел:"
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
        "🖼 <b>PHOTO FILE ID</b>\n\n"
        f"<code>{file_id}</code>\n\n"
        "Этот ID можно использовать в Render как PHOTO_* "
        "если позже захотите заменить локальный баннер."
    )


# =========================================================
# MAIN MENU
# =========================================================

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    user_id = callback.from_user.id

    await safe_callback_answer(callback, )

    text = (
        "╔══════════════════════╗\n"
        "      🎰 <b>RESONANT</b>\n"
        "        <b>CASINO</b>\n"
        "╚══════════════════════╝\n\n"
    
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
    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎰 <b>GAMES</b>\n"
        "╰────────────────────╯\n\n"
        "💎 <b>ВЫБЕРИТЕ ИГРУ</b>\n\n"
        "🎲 Азарт • 🎰 Удача • 🚀 Риск\n\n"
        "Ставка списывается только после подтверждения.",
        games_keyboard(),
        PHOTO_GAMES
    )


# =========================================================
# WALLET
# =========================================================

@dp.callback_query(F.data == "wallet")
async def wallet_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    ensure_user(user_id)

    await safe_callback_answer(callback, )

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        f"       {tg_emoji(CUSTOM_EMOJI['wallet'], '💳')} | WALLET\n"
        "╰────────────────────╯\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['available'], '💰')} | ДОСТУПНО: {money(balance)} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n"
        "_________________\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['wallet_topup'], '◆')} | Пополняйте баланс\n"
        f"{tg_emoji(CUSTOM_EMOJI['wallet_games'], '◆')} | Играйте в мини-игры\n"
        f"{tg_emoji(CUSTOM_EMOJI['wallet_withdraw'], '◆')} | Вывод от {money(80)} ₽",
        wallet_keyboard(),
        PHOTO_BALANCE
    )


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    ensure_user(user_id)

    await safe_callback_answer(callback, )

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
        text="НАЗАД",
        callback_data="back_main"
    )

    builder.adjust(1)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        f"       {tg_emoji(CUSTOM_EMOJI['profile'], '👤')} | PROFILE\n"
        "╰────────────────────╯\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')} | BALANCE: {money(stats['balance'])} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['games'], '🎮')} ИГРЫ        {stats['games_played']}\n"
        f"{tg_emoji(CUSTOM_EMOJI['wins'], '🏆')} ПОБЕДЫ      {stats['wins']}\n"
        f"{tg_emoji(CUSTOM_EMOJI['losses'], '❌')} ПОРАЖЕНИЯ   {stats['losses']}\n"
        f"{tg_emoji(CUSTOM_EMOJI['winrate'], '📈')} WINRATE     {winrate}%\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['bets'], '💵')} СТАВКИ      {money(stats['total_bet'])} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n"
        f"{tg_emoji(CUSTOM_EMOJI['winnings'], '🏆')} ВЫИГРАНО    {money(stats['total_won'])} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n"
        f"{tg_emoji(CUSTOM_EMOJI['max_win'], '🔥')} MAX WIN     {money(stats['biggest_win'])} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}",
        builder.as_markup()
    )


# =========================================================
# USER GAME HISTORY
# =========================================================

@dp.callback_query(F.data == "my_history")
async def my_history_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    await safe_callback_answer(callback, )

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

    await safe_callback_answer(callback, )

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
    await safe_callback_answer(callback, )

    builder = InlineKeyboardBuilder()

    for amount in [1, 5, 10, 25, 50, 100]:
        builder.button(
            text=f"💳  {amount} USDT",
            callback_data=f"deposit_{amount}"
        )

    builder.button(
        text="НАЗАД",
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
        builder.as_markup(),
        PHOTO_TOPUP
    )


@dp.callback_query(F.data.startswith("deposit_"))
async def deposit_create_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    amount_text = callback.data.split("_", 1)[1]

    try:
        amount_usdt = float(amount_text)
    except Exception:
        await safe_callback_answer(callback, 
            "Ошибка суммы",
            show_alert=True
        )
        return

    await safe_callback_answer(callback, )

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
        text="НАЗАД",
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

    await safe_callback_answer(callback, 
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

        await callback.message.answer(premiumize_text(text))
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
        text="НАЗАД",
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
        await safe_callback_answer(callback, 
            "Ошибка игры",
            show_alert=True
        )
        return

    games[user_id] = {
        "type": game_type,
        "awaiting_stake": True,
    }

    balance = get_balance(user_id)

    await safe_callback_answer(callback, )

    game_names = {
        "dice": "🎲 DICE",
        "slots": "🎰 SLOTS",
        "bowling": "🎳 BOWLING",
        "roulette": "🎡 ROULETTE",
        "mines": "💣 MINES",
        "crash": "🚀 CRASH",
    }

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        f"       {game_names[game_type]}\n"
        "╰────────────────────╯\n\n"
        "💎 <b>ВВЕДИТЕ СТАВКУ</b>\n\n"
        "Минимальная ставка: "
        "<b>50 ₽</b>\n"
        f"Максимальная ставка: "
        f"<b>{money(balance)} ₽</b>\n\n"
        "Отправьте сумму одним сообщением.\n\n"
        "Например:\n"
        "<code>350</code>",
        manual_stake_back_keyboard(),
        PHOTO_STAKE
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
            "❌ <b>Игра устарела.</b>\n\n"
            "Выберите игру заново."
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
            "❌ <b>НЕКОРРЕКТНАЯ СТАВКА</b>\n\n"
            "Введите целое число не меньше "
            "<b>50 ₽</b>.\n\n"
            "Например:\n"
            "<code>350</code>"
        )
        return True
    balance = get_balance(user_id)
    if stake > balance:
        await message.answer(
            "❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n\n"
            f"💳 Ваш баланс: "
            f"<b>{money(balance)} ₽</b>\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"
            "Введите сумму не больше "
            "текущего баланса."
        )
        return True
    games[user_id] = {
        "type": game_type,
        "stake": stake
    }
    # DICE
    if game_type == "dice":

        builder = InlineKeyboardBuilder()

        # БРОСОК 1 РАЗ
        builder.button(
            text="x1.85 | МЕНЬШЕ 4",
            callback_data="dice_single_less"
        )

        builder.button(
            text="x1.85 | БОЛЬШЕ 3",
            callback_data="dice_single_more"
        )

        # БРОСОК 2 РАЗА
        builder.button(
            text="x2.05 | МЕНЬШЕ 7",
            callback_data="dice_double_less"
        )

        builder.button(
            text="x2.05 | БОЛЬШЕ 7",
            callback_data="dice_double_more"
        )

        builder.button(
            text="x5 | РОВНО 7",
            callback_data="dice_double_seven"
        )

        builder.button(
            text="НАЗАД",
            callback_data="game_dice"
        )

        builder.adjust(1)

        await message.answer(
            "╭────────────────────╮\n"
            "       🎲 <b>| DICE</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"

            "<b>БРОСОК 1 РАЗ</b>\n"
            "x1.85 | Меньше 4\n"
            "x1.85 | Больше 3\n\n"

            "<b>БРОСОК 2 РАЗА</b>\n"
            "x2.05 | Меньше 7\n"
            "x2.05 | Больше 7\n"
            "x5 | Ровно 7\n\n"

            "Выберите прогноз:",

            reply_markup=builder.as_markup()
        )

        return True

    # SLOTS
    if game_type == "slots":
        await message.answer(
            "╭────────────────────╮\n"
            "       🎰 <b>SLOTS</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"
            "🍋🍋🍋 — ×10\n"
            "7️⃣7️⃣7️⃣ — ×50\n"
            "3 одинаковых — ×3.5\n"
            "2 одинаковых — ×1.85\n"
            "Другие комбинации — проигрыш.\n\n"
            "Подтвердить ставку?",
            reply_markup=confirm_bet_keyboard("slots")
        )
        return True
    # BOWLING
    if game_type == "bowling":
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
            text="НАЗАД",
            callback_data="game_bowling"
        )
        builder.adjust(1)
        await message.answer(
            "╭────────────────────╮\n"
            "       🎳 <b>BOWLING</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"
            "Выберите прогноз:",
            reply_markup=builder.as_markup()
        )
        return True
    # ROULETTE
    if game_type == "roulette":
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
            text="НАЗАД",
            callback_data="game_roulette"
        )
        builder.adjust(1)
        await message.answer(
            "╭────────────────────╮\n"
            "       🎡 <b>ROULETTE</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"
            "Выберите цвет:",
            reply_markup=builder.as_markup()
        )
        return True
    # MINES
    if game_type == "mines":
        await message.answer(
            "╭────────────────────╮\n"
            "       💣 <b>MINES</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"
            "Подтвердить ставку?",
            reply_markup=confirm_bet_keyboard("mines")
        )
        return True
    # CRASH
    if game_type == "crash":
        await message.answer(
            "╭────────────────────╮\n"
            "       🚀 <b>CRASH</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: "
            f"<b>{money(stake)} ₽</b>\n\n"
            "Самолёт будет набирать множитель.\n"
            "Ваша задача — забрать выигрыш "
            "до CRASH.\n\n"
            "Подтвердить ставку?",
            reply_markup=confirm_bet_keyboard("crash")
        )
        return True
    return True
    
@dp.callback_query(F.data == "game_dice")
async def dice_start(
    callback: CallbackQuery
):
    await safe_callback_answer(callback, )
    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎲 <b>| DICE</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите ставку:",
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
    # БРОСОК 1 РАЗ
    builder.button(
        text="x1.85 | МЕНЬШЕ 4",
        callback_data="dice_single_less"
    )
    builder.button(
        text="x1.85 | БОЛЬШЕ 3",
        callback_data="dice_single_more"
    )
    # БРОСОК 2 РАЗА
    builder.button(
        text="x2.05 | МЕНЬШЕ 7",
        callback_data="dice_double_less"
    )
    builder.button(
        text="x2.05 | БОЛЬШЕ 7",
        callback_data="dice_double_more"
    )
    builder.button(
        text="x5 | РОВНО 7",
        callback_data="dice_double_seven"
    )
    builder.button(
        text="НАЗАД",
        callback_data="game_dice"
    )
    builder.adjust(1)
    await safe_callback_answer(callback, )
    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎲 <b>| DICE</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "<b>БРОСОК 1 РАЗ</b>\n"
        "x1.85 | Меньше 4\n"
        "x1.85 | Больше 3\n\n"
        "<b>БРОСОК 2 РАЗА</b>\n"
        "x2.05 | Меньше 7\n"
        "x2.05 | Больше 7\n"
        "x5 | Ровно 7\n\n"
        "Выберите прогноз:",
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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return
    prediction = callback.data
    game["prediction"] = prediction
    stake = game["stake"]
    prediction_names = {
        "dice_single_less":
            "x1.85 | МЕНЬШЕ 4",
        "dice_single_more":
            "x1.85 | БОЛЬШЕ 3",
        "dice_double_less":
            "x2.05 | МЕНЬШЕ 7",
        "dice_double_more":
            "x2.05 | БОЛЬШЕ 7",
        "dice_double_seven":
            "x5 | РОВНО 7",
    }
    await safe_callback_answer(callback, )
    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎲 <b>| DICE</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n"
        f"🎯 Прогноз: "
        f"<b>{prediction_names[prediction]}</b>\n\n"
        "Подтвердить ставку?",
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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return
    stake = game["stake"]
    prediction = game["prediction"]
    if not subtract_balance(
        user_id,
        stake
    ):
        await safe_callback_answer(callback, 
            "Недостаточно средств",
            show_alert=True
        )
        return
    await safe_callback_answer(callback, )
    # =====================================
    # БРОСОК 1 РАЗ
    # =====================================
    if prediction in {
        "dice_single_less",
        "dice_single_more"
    }:
        dice = await callback.message.answer_dice(
            emoji="🎲"
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
        games.pop(
            user_id,
            None
        )
        await callback.message.answer(
            premiumize_text(text),
            reply_markup=after_game_keyboard()
        )
        return
    # =====================================
    # БРОСОК 2 РАЗА
    # =====================================
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
            f"🎲 {value1} + {value2} = "
            f"<b>{total}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )
    games.pop(
        user_id,
        None
    )
    await callback.message.answer(
        premiumize_text(text),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# SLOTS
# =========================================================

@dp.callback_query(F.data == "game_slots")
async def slots_start(
    callback: CallbackQuery
):
    await safe_callback_answer(callback, )

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

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return
    stake = game["stake"]
    if not subtract_balance(
        user_id,
        stake
    ):
        await safe_callback_answer(callback, 
            "Недостаточно средств",
            show_alert=True
        )
        return
    await safe_callback_answer(callback, )
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
    # 777 — JACKPOT ×50
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
    # 🍋🍋🍋 — ×10
    elif symbols == ["🍋", "🍋", "🍋"]:
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
    # Любые другие 3 одинаковых — ×3.5
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
            "╭────────────────────╮\n"
            "       🎰 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎰 <b>{display_result}</b>\n\n"
            "💎 <b>ТРИ ОДИНАКОВЫХ</b>\n"
            "×3.5\n\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )
    # Ровно 2 одинаковых — ×1.85
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
            "╭────────────────────╮\n"
            "       ✨ <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            f"🎰 <b>{display_result}</b>\n\n"
            "✨ <b>ДВА ОДИНАКОВЫХ</b>\n"
            "×1.85\n\n"
            f"💰 Выигрыш: "
            f"<b>+{money(payout)} ₽</b>\n"
            f"💳 Баланс: "
            f"<b>{money(get_balance(user_id))} ₽</b>"
        )
    # Остальные комбинации — проигрыш
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
        premiumize_text(text),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# BOWLING
# =========================================================

@dp.callback_query(F.data == "game_bowling")
async def bowling_start(
    callback: CallbackQuery
):
    await safe_callback_answer(callback, )

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
        text="НАЗАД",
        callback_data="game_bowling"
    )

    builder.adjust(1)

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return

    game["prediction"] = callback.data.replace(
        "bowling_",
        ""
    )

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await safe_callback_answer(callback, 
            "Недостаточно средств",
            show_alert=True
        )
        return

    await safe_callback_answer(callback, )

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
        premiumize_text(text),
        reply_markup=after_game_keyboard()
    )


# =========================================================
# ROULETTE
# =========================================================

@dp.callback_query(F.data == "game_roulette")
async def roulette_start(
    callback: CallbackQuery
):
    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎡 <b>ROULETTE</b>\n"
        "╰────────────────────╯\n\n"
        "<b>Коэффициенты:</b>\n"
        "🔴 Красное — <b>x1.85</b>\n"
        "⚫️ Чёрное — <b>x1.85</b>\n"
        "🟢 Зелёное — <b>x14</b>\n\n"
        "Выберите ставку:",
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
    ensure_user(user_id)

    stake = int(callback.data.split("_")[-1])

    games[user_id] = {
        "type": "roulette",
        "stake": stake,
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="🔴  КРАСНОЕ  x1.85", callback_data="roulette_red")
    builder.button(text="⚫️  ЧЁРНОЕ  x1.85", callback_data="roulette_black")
    builder.button(text="🟢  ЗЕЛЁНОЕ  x14", callback_data="roulette_zero")
    builder.button(text="НАЗАД", callback_data="game_roulette")
    builder.adjust(1)

    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        f"🎡 <b>ROULETTE</b>\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        "Выберите цвет:",
        builder.as_markup(),
        PHOTO_ROULETTE,
    )


@dp.callback_query(
    F.data.in_({"roulette_red", "roulette_black", "roulette_zero"})
)
async def roulette_color(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    game = games.get(user_id)

    if not game:
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return

    game["color"] = callback.data.replace("roulette_", "")

    await safe_callback_answer(callback, )

    multiplier = ROULETTE_MULTIPLIERS[game["color"]]

    await edit_or_answer(
        callback,
        f"🎡 <b>ROULETTE</b>\n\n"
        f"💎 Ставка: <b>{money(game['stake'])} ₽</b>\n"
        f"🎯 Выбор: <b>{roulette_color_label(game['color'])}</b>\n"
        f"📈 Множитель: <b>x{multiplier:g}</b>\n\n"
        "Подтвердить ставку?",
        confirm_bet_keyboard("roulette"),
        PHOTO_ROULETTE,
    )


@dp.callback_query(F.data == "confirm_roulette")
async def confirm_roulette(
    callback: CallbackQuery
):
    user_id = callback.from_user.id
    ensure_user(user_id)

    game = games.get(user_id)
    if not game:
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return

    stake = int(game["stake"])
    selected_color = game.get("color")

    if selected_color not in ROULETTE_MULTIPLIERS:
        await safe_callback_answer(callback, "Сначала выберите цвет", show_alert=True)
        return

    if not subtract_balance(user_id, stake):
        await safe_callback_answer(callback, "Недостаточно средств", show_alert=True)
        return

    # =====================================================
    # ВАЖНО: результат определяется ДО анимации.
    # Анимация только визуально доводит колесо до уже
    # выбранного случайного результата.
    # =====================================================
    result = random.choice(ROULETTE_NUMBERS)
    result_color = roulette_result_color(result)
    multiplier = ROULETTE_MULTIPLIERS[selected_color]
    won = selected_color == result_color
    payout = int(round(stake * multiplier)) if won else 0

    await safe_callback_answer(callback, )

    original_message = callback.message

    # Убираем экран ставки и запускаем отдельное анимируемое сообщение.
    try:
        await original_message.delete()
    except Exception as error:
        print("ROULETTE DELETE ERROR:", repr(error))

    animation_message = await bot.send_message(
        user_id,
        premiumize_text(
            "🎡 <b>ROULETTE</b>\n\n"
            f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Запускаем рулетку..."
        )
    )

    # Стартовая пауза — пользователь видит именно запуск.
    await asyncio.sleep(0.45)

    # Движение по реальному порядку чисел рулетки.
    # Последний кадр гарантированно ставит result в центр.
    result_index = ROULETTE_NUMBERS.index(result)

    # 26 кадров: первые 18 идут быстро, последние 8 плавно
    # замедляются. Стартовая позиция выбрана так, чтобы каждый
    # кадр проходил ровно следующий сектор и последний кадр
    # гарантированно останавливался на result.
    step_delays = (
        [0.075] * 6
        + [0.095] * 6
        + [0.12] * 6
        + [0.17, 0.23, 0.31, 0.40, 0.52, 0.65]
    )
    total_steps = len(step_delays)
    current_index = (result_index - total_steps) % len(ROULETTE_NUMBERS)

    for frame_index, delay in enumerate(step_delays):
        current_index = (current_index + 1) % len(ROULETTE_NUMBERS)

        numbers = roulette_window(current_index, 5)
        frame = roulette_frame_text(numbers)

        try:
            await animation_message.edit_text(
                premiumize_text(frame),
                parse_mode=ParseMode.HTML,
            )
        except Exception as error:
            print("ROULETTE ANIMATION ERROR:", repr(error))

        await asyncio.sleep(delay)

    # Финальный кадр с выделением результата.
    final_numbers = roulette_window(result_index, 5)
    final_frame = roulette_frame_text(
        final_numbers,
        result=result,
        final=True,
    )

    try:
        await animation_message.edit_text(
            premiumize_text(final_frame),
            parse_mode=ParseMode.HTML,
        )
    except Exception as error:
        print("ROULETTE FINAL FRAME ERROR:", repr(error))

    await asyncio.sleep(0.65)

    # =====================================================
    # РАСЧЁТ ПОСЛЕ ОСТАНОВКИ
    # =====================================================
    if won:
        change_balance(user_id, payout)

        record_game(
            user_id,
            "roulette",
            stake,
            "win",
            multiplier,
            payout,
        )

        text = (
            "╭────────────────────╮\n"
            "       🏆 <b>WIN</b>\n"
            "╰────────────────────╯\n\n"
            "🎡 <b>РУЛЕТКА</b>\n"
            f"        {roulette_result_emoji(result)} <b>{result}</b>\n\n"
            "🎉 <b>ВЫИГРЫШ!</b>\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n"
            f"Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"Множитель: <b>×{multiplier:g}</b>\n\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>"
        )
    else:
        record_game(
            user_id,
            "roulette",
            stake,
            "loss",
            0,
            0,
        )

        text = (
            "╭────────────────────╮\n"
            "       💥 <b>LOSS</b>\n"
            "╰────────────────────╯\n\n"
            "🎡 <b>РУЛЕТКА</b>\n"
            f"        {roulette_result_emoji(result)} <b>{result}</b>\n\n"
            "❌ <b>ПРОИГРЫШ</b>\n"
            f"Ставка: <b>{money(stake)} ₽</b>\n"
            f"Выпало: <b>{roulette_color_label(result_color)}</b>\n\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>"
        )

    games.pop(user_id, None)

    try:
        await animation_message.edit_text(
            premiumize_text(text),
            reply_markup=after_game_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    except Exception as error:
        print("ROULETTE RESULT ERROR:", repr(error))
        await bot.send_message(
            user_id,
            premiumize_text(text),
            reply_markup=after_game_keyboard(),
        )


# =========================================================
# MINES
# =========================================================

@dp.callback_query(F.data == "game_mines")
async def mines_start(
    callback: CallbackQuery
):
    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        "На поле 9 клеток.\n"
        "2 из них — мины.\n\n"
        "Выберите ставку:",
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

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
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

        await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
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

        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
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
    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🚀 <b>CRASH</b>\n"
        "╰────────────────────╯\n\n"
        "Множитель растёт каждую секунду.\n"
        "Нажмите «💰 ЗАБРАТЬ», "
        "пока самолёт не разбился.\n\n"
        "Выберите ставку:",
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

    await safe_callback_answer(callback, )

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
                    premiumize_text(
                        "╭────────────────────╮\n"
                        "       🚀 <b>CRASH</b>\n"
                        "╰────────────────────╯\n\n"
                        "✈️ Самолёт летит...\n\n"
                        f"📈 Множитель: "
                        f"<b>x{multiplier:.2f}</b>\n\n"
                        "💰 Успейте забрать выигрыш!"
                    ),
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
                premiumize_text(
                    "╭────────────────────╮\n"
                    "       💥 <b>CRASH</b>\n"
                    "╰────────────────────╯\n\n"
                    f"📈 Самолёт разбился на "
                    f"<b>x{crash_point:.2f}</b>\n\n"
                    "❌ <b>Слишком поздно.</b>\n"
                    "Ставка проиграна.\n\n"
                    f"💳 Баланс: "
                    f"<b>{money(get_balance(user_id))} ₽</b>"
                ),
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
        await safe_callback_answer(callback, 
            "Игра устарела",
            show_alert=True
        )
        return

    stake = game["stake"]

    if not subtract_balance(
        user_id,
        stake
    ):
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
        "🚀 CRASH НАЧАЛСЯ!"
    )

    message = await callback.message.answer(
        premiumize_text(
            "╭────────────────────╮\n"
            "       🚀 <b>CRASH</b>\n"
            "╰────────────────────╯\n\n"
            "✈️ Самолёт взлетел!\n\n"
            "📈 Множитель: <b>x1.00</b>\n\n"
            "💰 Успейте забрать выигрыш!"
        ),
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
        await safe_callback_answer(callback, 
            "💥 CRASH уже произошёл.",
            show_alert=True
        )
        return

    if game.get("crash_finished"):
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
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
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
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
    ensure_user(user_id)

    balance = get_balance(user_id)

    await safe_callback_answer(callback, )

    if balance < MIN_WITHDRAWAL:
        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            f"       {tg_emoji(CUSTOM_EMOJI['withdraw'], '💸')} | WITHDRAW\n"
            "╰────────────────────╯\n\n"
            f"{tg_emoji(CUSTOM_EMOJI['available'], '💰')} | Доступно: {money(balance)} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n\n"
            f"Минимальная сумма вывода: {money(1)} {tg_emoji(CUSTOM_EMOJI['withdraw_currency'], '💰')} ≈ {money(80)} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}",
            wallet_keyboard(),
            PHOTO_WITHDRAW
        )
        return

    games[user_id] = {
        "withdraw_action": "amount"
    }

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        f"       {tg_emoji(CUSTOM_EMOJI['withdraw'], '💸')} | WITHDRAW\n"
        "╰────────────────────╯\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['available'], '💰')} | Доступно: {money(balance)} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n"
        f"Минимальная сумма вывода: {money(1)} {tg_emoji(CUSTOM_EMOJI['withdraw_currency'], '💰')} ≈ {money(80)} {tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')}\n\n"
        "Введите сумму вывода в рублях.\n\n"
        "Например:\n"
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

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        "╔══════════════════════╗\n"
        f"      {tg_emoji(CUSTOM_EMOJI['admin'], '🛠')} | ADMIN PANEL\n"
        "╚══════════════════════╝\n\n"
        "Системное управление.\n\n"
        "Выберите действие:",
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    games[user_id] = {
        "admin_action": "find_user"
    }

    await safe_callback_answer(callback, )

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
    ensure_user(target_id)
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, )

    text = (
        "💰 Введите сумму для выдачи:"
        if action == "add"
        else "➖ Введите сумму для снятия:"
    )

    await callback.message.answer(premiumize_text(text))


@dp.callback_query(F.data == "admin_refresh")
async def admin_refresh(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await safe_callback_answer(callback, 
            "Пользователь не выбран",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    balance = get_balance(target_id)

    await safe_callback_answer(callback, 
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await safe_callback_answer(callback, 
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await safe_callback_answer(callback, 
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    state = games.get(user_id)

    if not state or "target_user" not in state:
        await safe_callback_answer(callback, 
            "Пользователь не выбран",
            show_alert=True
        )
        return

    target_id = state["target_user"]

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    await safe_callback_answer(callback, )

    withdrawals = get_pending_withdrawals(20)

    if not withdrawals:
        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💸 <b>WITHDRAWALS</b>\n"
            "╰────────────────────╯\n\n"
            "Ожидающих заявок нет.",
            admin_main_keyboard(),
            PHOTO_ADMIN
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await safe_callback_answer(callback, 
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await safe_callback_answer(callback, 
            "Заявка не найдена",
            show_alert=True
        )
        return

    await safe_callback_answer(callback, )

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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await safe_callback_answer(callback, 
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await safe_callback_answer(callback, 
            "Заявка не найдена",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "pending":
        await safe_callback_answer(callback, 
            "Заявка уже обработана",
            show_alert=True
        )
        return

    result = approve_withdrawal(
        withdrawal_id
    )

    if result is None:
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await safe_callback_answer(callback, 
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await safe_callback_answer(callback, 
            "Заявка не найдена",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "pending":
        await safe_callback_answer(callback, 
            "Заявка уже обработана",
            show_alert=True
        )
        return

    result = reject_withdrawal(
        withdrawal_id
    )

    if result is None:
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
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
        await safe_callback_answer(callback, 
            "Нет доступа",
            show_alert=True
        )
        return

    try:
        withdrawal_id = int(
            callback.data.split("_")[-1]
        )
    except Exception:
        await safe_callback_answer(callback, 
            "Ошибка заявки",
            show_alert=True
        )
        return

    withdrawal = get_withdrawal(
        withdrawal_id
    )

    if not withdrawal:
        await safe_callback_answer(callback, 
            "Заявка не найдена",
            show_alert=True
        )
        return

    if withdrawal.get("status") != "approved":
        await safe_callback_answer(callback, 
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

        await safe_callback_answer(callback, 
            "Ошибка завершения выплаты",
            show_alert=True
        )
        return

    if result is None:
        await safe_callback_answer(callback, 
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

    await safe_callback_answer(callback, 
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

@dp.message()
async def text_message_handler(message: Message):
    # =====================================================
    # PREMIUM CUSTOM EMOJI ID DETECTOR
    #
    # Send any Telegram Premium Custom Emoji to the bot.
    # The bot will reply with its custom_emoji_id.
    # =====================================================

    custom_emoji_ids = []

    for entity in (message.entities or []):
        if (
            entity.type == "custom_emoji"
            and entity.custom_emoji_id
        ):
            custom_emoji_ids.append(
                entity.custom_emoji_id
            )

    if custom_emoji_ids:
        unique_ids = list(dict.fromkeys(custom_emoji_ids))

        lines = [
            "🧩 <b>PREMIUM CUSTOM EMOJI</b>",
            "",
            "ID эмодзи:",
        ]

        for emoji_id in unique_ids:
            lines.append(
                f"<code>{emoji_id}</code>"
            )

        lines.extend([
            "",
            "Сохрани этот ID — он понадобится для",
            "подключения Premium Emoji в казино."
        ])

        await message.answer(
            "\n".join(lines)
        )
        return

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
        await bot.set_my_commands([
            BotCommand(command="menu", description="Открыть главное меню"),
            BotCommand(command="start", description="Запустить казино"),
        ])
        await bot.set_chat_menu_button(
            menu_button=MenuButtonCommands()
        )
        print("TELEGRAM MENU BUTTON: /menu")
    except Exception as error:
        print("TELEGRAM MENU BUTTON ERROR:", repr(error))

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
