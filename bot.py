import asyncio
import os
import random
import re
import sqlite3
import hashlib
import hmac
import json
import time
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi import HTTPException
from pydantic import BaseModel, Field

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

BASE_URL = os.getenv("BASE_URL", "https://emoji-casino-bot.onrender.com")
REAL_ECONOMY = os.getenv("REAL_ECONOMY", "false").lower() == "true"
WEBAPP_AUTH_MAX_AGE = int(os.getenv("WEBAPP_AUTH_MAX_AGE", "86400"))

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

# Последний выбранный режим MINES для кнопки «ЕЩЁ РАЗ».
last_mines_count = {}
# Надёжно храним выбранное количество мин между экранами ввода ставки.
pending_mines_count = {}

STAKES = [
    50,
    100,
    250,
    500,
    1000,
]

SLOT_SEVEN_MULTIPLIER = 50

# MINES: 5x5 = 25 клеток, от 2 до 24 мин.
MINES_SIZE = 25
MINES_MIN = 2
MINES_MAX = 24
MINES_HOUSE_EDGE = float(os.getenv("MINES_HOUSE_EDGE", "0.97"))

# REFERRAL SYSTEM.
REFERRAL_CHANNEL = "@resonant_casino"
REFERRAL_MIN_DEPOSIT_USDT = 1.0
# Размер бонуса не был задан в ТЗ. Можно задать через Render ENV.
REFERRAL_REWARD_RUB = 25  # 25 ₽ за каждого квалифицированного (действующего) реферала


# =========================================================
# ROULETTE RULES / ANIMATION
# =========================================================

# Коэффициенты рулетки. Анимация ниже не изменяется.
ROULETTE_MULTIPLIERS = {
    "red": 1.9,
    "black": 1.9,
    "zero": 35.0,
    "even": 1.9,
    "odd": 1.9,
    "low": 1.9,
    "high": 1.9,
    "dozen1": 2.7,
    "dozen2": 2.7,
    "dozen3": 2.7,
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
        "zero": "Zero 🟢",
        "even": "Чётное ⚖️",
        "odd": "Нечётное 🔰",
        "low": "1-18 🔽",
        "high": "19-36 🔼",
        "dozen1": "1-12 1️⃣",
        "dozen2": "13-24 2️⃣",
        "dozen3": "25-36 3️⃣",
    }.get(color, color)


def roulette_bet_wins(selection: str, number: int) -> bool:
    if selection == "red":
        return roulette_result_color(number) == "red"
    if selection == "black":
        return roulette_result_color(number) == "black"
    if selection == "zero":
        return number == 0
    if selection == "even":
        return number != 0 and number % 2 == 0
    if selection == "odd":
        return number != 0 and number % 2 == 1
    if selection == "low":
        return 1 <= number <= 18
    if selection == "high":
        return 19 <= number <= 36
    if selection == "dozen1":
        return 1 <= number <= 12
    if selection == "dozen2":
        return 13 <= number <= 24
    if selection == "dozen3":
        return 25 <= number <= 36
    return False


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


# 1 USDT = 80 ₽
# Минимальный вывод = 1 USDT
MIN_WITHDRAWAL = 80


# =========================================================
# TELEGRAM PREMIUM CUSTOM EMOJI
# =========================================================

CUSTOM_EMOJI = {
    # IDs for the PROFILE screen supplied by the user.
    "profile": "5116116063188157350",
    "balance_currency": "5471952986970267163",
    "games": "5426896538062332283",
    "wins": "5188344996356448758",
    "losses": "5454350746407419714",
    "winrate": "6033106828018062225",
    "bets": "5429651785352501917",
    "winnings": "5278467510604160626",
    "max_win": "5375452661036358740",
    "withdraw": "5373174941095050893",
    "available": "6025976946083500432",
    "withdraw_currency": "5409048419211682843",
    "admin": "5462921117423384478",
    "wallet": "5471952986970267163",
    "wallet_topup": "5427173563452923041",
    "wallet_games": "5382150533685469668",
    "wallet_withdraw": "5445353829304387411",
    "win": "5188344996356448758",
    "loss": "5454350746407419714",
    "stake": "5429651785352501917",
    # Premium emoji supplied for the games / multiplier by the user.
    "multiplier": "5280569974404966639",
    "dice": "5427373081863691990",
    "slots": "5384509325429463744",
    "bowling": "5427210886718727705",
    "roulette": "5382150533685469668",
    "mines": "5226813248900187912",
    "deposit": "5427173563452923041",
    "history": "5429651785352501917",
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
        "🎲": tg_emoji(CUSTOM_EMOJI["dice"], "🎲"),
        "🎰": tg_emoji(CUSTOM_EMOJI["slots"], "🎰"),
        "🎳": tg_emoji(CUSTOM_EMOJI["bowling"], "🎳"),
        "🎡": tg_emoji(CUSTOM_EMOJI["roulette"], "🎡"),
        "💣": tg_emoji(CUSTOM_EMOJI["mines"], "💣"),
        "💎": tg_emoji(CUSTOM_EMOJI["bets"], "💎"),
        "👤": tg_emoji(CUSTOM_EMOJI["profile"], "👤"),
        "📜": tg_emoji(CUSTOM_EMOJI["history"], "📜"),
        "💳": tg_emoji(CUSTOM_EMOJI["deposit"], "💳"),
        "💸": tg_emoji(CUSTOM_EMOJI["withdraw"], "💸"),
        "🛠": tg_emoji(CUSTOM_EMOJI["admin"], "🛠"),
        "❌": tg_emoji(CUSTOM_EMOJI["losses"], "❌"),
        "📈": tg_emoji(CUSTOM_EMOJI["multiplier"], "📈"),
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

# Persistent Telegram profile metadata. The existing `database` module remains
# the source of truth for balance, game history, payments and withdrawals.
PROFILE_DB_PATH = BASE_DIR / "profiles.sqlite3"

# Activity log. It is intentionally separate from game state and game history.
def init_activity_store():
    PROFILE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at "
            "ON activity_logs(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id "
            "ON activity_logs(user_id, created_at DESC)"
        )
        conn.commit()



def init_webapp_guard_store():
    PROFILE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS webapp_compliance (
                user_id INTEGER PRIMARY KEY,
                age_verified INTEGER NOT NULL DEFAULT 0,
                kyc_verified INTEGER NOT NULL DEFAULT 0,
                jurisdiction_allowed INTEGER NOT NULL DEFAULT 0,
                self_excluded INTEGER NOT NULL DEFAULT 0,
                deposit_enabled INTEGER NOT NULL DEFAULT 0,
                withdrawal_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def get_webapp_guard(user_id: int):
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT age_verified, kyc_verified, jurisdiction_allowed, self_excluded, deposit_enabled, withdrawal_enabled "
            "FROM webapp_compliance WHERE user_id=?", (int(user_id),)
        ).fetchone()
    if not row:
        return {"age_verified": False, "kyc_verified": False, "jurisdiction_allowed": False,
                "self_excluded": False, "deposit_enabled": False, "withdrawal_enabled": False}
    keys = ["age_verified", "kyc_verified", "jurisdiction_allowed", "self_excluded", "deposit_enabled", "withdrawal_enabled"]
    return {k: bool(v) for k, v in zip(keys, row)}


def require_real_money_access(user_id: int, action: str):
    if not REAL_ECONOMY:
        raise HTTPException(status_code=409, detail="REAL_ECONOMY is disabled")
    guard = get_webapp_guard(user_id)
    if guard["self_excluded"]:
        raise HTTPException(status_code=403, detail="Account is self-excluded")
    if not guard["age_verified"] or not guard["kyc_verified"] or not guard["jurisdiction_allowed"]:
        raise HTTPException(status_code=403, detail="Account verification is required")
    if action == "deposit" and not guard["deposit_enabled"]:
        raise HTTPException(status_code=403, detail="Deposits are not enabled for this account")
    if action == "withdrawal" and not guard["withdrawal_enabled"]:
        raise HTTPException(status_code=403, detail="Withdrawals are not enabled for this account")


def validate_telegram_webapp_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Telegram initData is required")
    try:
        from urllib.parse import parse_qsl
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            raise ValueError("missing hash")
        check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            raise ValueError("bad hash")
        auth_date = int(pairs.get("auth_date", "0"))
        if not auth_date or time.time() - auth_date > WEBAPP_AUTH_MAX_AGE:
            raise ValueError("expired initData")
        user = json.loads(pairs.get("user", "{}"))
        if not user.get("id"):
            raise ValueError("missing user")
        return user
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Telegram initData: {exc}")


class WebAppAuth(BaseModel):
    init_data: str = Field(min_length=1)

class DepositRequest(WebAppAuth):
    amount_usdt: float = Field(gt=0, le=100000)

class WithdrawRequest(WebAppAuth):
    amount_rub: int = Field(gt=0, le=100000000)
    payout_details: str = Field(min_length=5, max_length=1000)

class GameRoundRequest(WebAppAuth):
    game: str = Field(min_length=1, max_length=64)
    stake_rub: int = Field(gt=0, le=1000000)

def init_referral_store():
    """Persistent referral links and qualification state."""
    PROFILE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                referred_id INTEGER PRIMARY KEY,
                referrer_id INTEGER NOT NULL,
                qualified INTEGER NOT NULL DEFAULT 0,
                qualified_at TEXT,
                reward_paid INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_referrals_referrer "
            "ON referrals(referrer_id)"
        )
        conn.commit()


def register_referral(referred_id: int, referrer_id: int) -> bool:
    """Store a referral once; self-referrals and reassignments are rejected."""
    referred_id = int(referred_id)
    referrer_id = int(referrer_id)
    if referred_id == referrer_id:
        return False

    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT referred_id FROM referrals WHERE referred_id = ?",
            (referred_id,),
        ).fetchone()
        if row:
            return False

        conn.execute(
            "INSERT INTO referrals (referred_id, referrer_id) VALUES (?, ?)",
            (referred_id, referrer_id),
        )
        conn.commit()
    return True


def get_referral_stats(referrer_id: int):
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
            (int(referrer_id),),
        ).fetchone()[0]
        qualified = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND qualified = 1",
            (int(referrer_id),),
        ).fetchone()[0]
        return int(total), int(qualified)


async def is_referral_channel_member(user_id: int) -> bool:
    """A referral is eligible only after joining the required channel."""
    try:
        member = await bot.get_chat_member(
            chat_id=REFERRAL_CHANNEL,
            user_id=int(user_id),
        )
        return member.status in {"member", "administrator", "creator"} or (
            member.status == "restricted" and bool(getattr(member, "is_member", False))
        )
    except Exception as error:
        print("REFERRAL SUBSCRIPTION CHECK ERROR:", repr(error))
        return False


async def qualify_referral(referred_id: int, amount_usdt: float) -> bool:
    """Qualify a referral after a >=1 USDT deposit and channel subscription."""
    if float(amount_usdt) < REFERRAL_MIN_DEPOSIT_USDT:
        return False

    if not await is_referral_channel_member(referred_id):
        return False

    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT referrer_id, qualified
            FROM referrals
            WHERE referred_id = ?
            """,
            (int(referred_id),),
        ).fetchone()

        if not row or int(row[1]) == 1:
            return False

        referrer_id = int(row[0])
        reward_paid = 0

        if REFERRAL_REWARD_RUB > 0:
            ensure_user(referrer_id)
            change_balance(referrer_id, REFERRAL_REWARD_RUB)
            reward_paid = 1

        conn.execute(
            """
            UPDATE referrals
            SET qualified = 1,
                qualified_at = CURRENT_TIMESTAMP,
                reward_paid = ?
            WHERE referred_id = ?
            """,
            (reward_paid, int(referred_id)),
        )
        conn.commit()

    return True


def log_activity(user_id, username, first_name, event_type, action, details=""):
    try:
        with sqlite3.connect(PROFILE_DB_PATH) as conn:
            conn.execute(
                '''
                INSERT INTO activity_logs
                    (user_id, username, first_name, event_type, action, details)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    int(user_id),
                    username or "",
                    first_name or "",
                    event_type,
                    str(action)[:500],
                    str(details or "")[:2000],
                ),
            )
            conn.commit()
    except Exception as error:
        # Logging must never break the game/webhook.
        print("ACTIVITY LOG ERROR:", repr(error))


def get_activity_logs(limit=30, user_id=None):
    limit = max(1, min(int(limit), 100))
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if user_id is None:
            rows = conn.execute(
                '''
                SELECT id, user_id, username, first_name, event_type, action,
                       details, created_at
                FROM activity_logs
                ORDER BY id DESC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT id, user_id, username, first_name, event_type, action,
                       details, created_at
                FROM activity_logs
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                ''',
                (int(user_id), limit),
            ).fetchall()
    return rows


def init_profile_store():
    PROFILE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def save_user_profile(user):
    if not user:
        return
    with sqlite3.connect(PROFILE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO user_profiles
                (user_id, username, first_name, last_name, language_code, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                language_code=excluded.language_code,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                int(user.id),
                user.username,
                user.first_name,
                user.last_name,
                user.language_code,
            ),
        )
        conn.commit()


def ensure_user_persisted(user):
    """Create the casino user and persist the current Telegram profile fields."""
    ensure_user(int(user.id))
    save_user_profile(user)


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
    """Главное меню: Профиль / Играть + Кошелек / Помощь."""
    builder = InlineKeyboardBuilder()
    builder.button(text="ПРОФИЛЬ", callback_data="profile")
    builder.button(text="ИГРАТЬ", callback_data="games")
    builder.button(text="КОШЕЛЕК", callback_data="wallet")
    builder.button(text="ПОМОЩЬ", url="https://t.me/narotan7")
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()
    # Основные игры
    for text, data in [
        ("🎰 SLOTS", "game_slots"),
        ("🎯 DARTS", "game_darts"),
        ("⚽ FOOTBALL", "game_football"),
        ("🎳 BOWLING", "game_bowling"),
        ("🏀 BASKETBALL", "game_basketball"),
        ("🔴 PLINKO", "game_plinko"),
        ("🎲 DICE", "game_dice"),
    ]:
        builder.button(text=text, callback_data=data)
    # Разделитель специальных игр.
    builder.button(text="СПЕЦИАЛЬНЫЕ ИГРЫ", callback_data="noop")

    for text, data in [
        ("💣 MINES", "game_mines"),
        ("🏗 TOWER", "game_tower"),
        ("✊ КНБ", "game_knb"),
        ("🔫 Рус.рул.", "game_russian_roulette"),
        ("🎡 ROULETTE", "game_roulette"),
        ("🃏 21", "game_21"),
        ("🐸 Жаба", "game_frog"),
    ]:
        builder.button(text=text, callback_data=data)
    builder.adjust(3, 3, 1)
    builder.button(text="ГЛАВНОЕ МЕНЮ", callback_data="back_main")
    builder.adjust(3, 3, 1, 1, 3, 3, 1, 1)
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
    builder.button(text="ПОПОЛНИТЬ", callback_data="deposit")
    builder.button(text="ВЫВЕСТИ", callback_data="withdraw")
    builder.button(text="НАЗАД", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def after_game_keyboard(game_type: str = "games"):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="ЕЩЁ РАЗ",
        callback_data=(
            f"{game_type}_enter_stake"
            if game_type in GAME_STAKE_TYPES
            else "games"
        )
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

    ensure_user_persisted(message.from_user)

    # /start ref_<telegram_id>
    args = (message.text or "").split(maxsplit=1)
    if len(args) == 2:
        payload = args[1].strip()
        if payload.startswith("ref_"):
            try:
                register_referral(user_id, int(payload[4:]))
            except (TypeError, ValueError):
                pass

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
    ensure_user_persisted(message.from_user)

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
    save_user_profile(callback.from_user)
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
    save_user_profile(callback.from_user)
    await safe_callback_answer(callback, )

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       🎮 <b>ИГРЫ</b>\n"
        "╰────────────────────╯\n\n"
        "Выберите игру:",
        games_keyboard(),
        PHOTO_GAMES
    )


# =========================================================
# REFERRAL SYSTEM
# =========================================================

@dp.callback_query(F.data == "referral")
async def referral_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    ensure_user(user_id)
    save_user_profile(callback.from_user)
    await safe_callback_answer(callback)

    try:
        me = await bot.get_me()
        bot_username = me.username
        referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    except Exception as error:
        print("REFERRAL LINK ERROR:", repr(error))
        referral_link = f"t.me/your_bot?start=ref_{user_id}"

    total, qualified = get_referral_stats(user_id)

    reward_line = (
        f"Бонус за квалифицированного реферала: <b>{money(REFERRAL_REWARD_RUB)} ₽</b>\n"
        if REFERRAL_REWARD_RUB > 0
        else "Бонус не задан: укажите REFERRAL_REWARD_RUB в Render.\n"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📋  МОЯ ССЫЛКА", callback_data="referral_link")
    builder.button(text="НАЗАД", callback_data="profile")
    builder.adjust(1)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n"
        "╰────────────────────╯\n\n"
        f"👥 Всего приглашено: <b>{total}</b>\n"
        f"✅ Засчитано: <b>{qualified}</b>\n\n"
        "Чтобы реферал был засчитан:\n"
        f"• подписка на {REFERRAL_CHANNEL}\n"
        f"• депозит от <b>{REFERRAL_MIN_DEPOSIT_USDT:g} USDT</b>\n\n"
        + reward_line +
        "После выполнения условий реферал фиксируется автоматически.",
        builder.as_markup(),
    )


@dp.callback_query(F.data == "referral_link")
async def referral_link_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    await safe_callback_answer(callback)

    me = await bot.get_me()
    referral_link = f"https://t.me/{me.username}?start=ref_{user_id}"

    builder = InlineKeyboardBuilder()
    builder.button(text="НАЗАД", callback_data="referral")

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       👥 <b>РЕФЕРАЛЬНАЯ ССЫЛКА</b>\n"
        "╰────────────────────╯\n\n"
        f"<code>{referral_link}</code>\n\n"
        f"Реферал засчитывается после подписки на {REFERRAL_CHANNEL} "
        f"и депозита от <b>{REFERRAL_MIN_DEPOSIT_USDT:g} USDT</b>.",
        builder.as_markup(),
    )


# =========================================================
# WALLET
# =========================================================

@dp.callback_query(F.data == "wallet")
async def wallet_handler(callback: CallbackQuery):
    save_user_profile(callback.from_user)
    user_id = callback.from_user.id
    ensure_user(user_id)

    await safe_callback_answer(callback, )

    balance = get_balance(user_id)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        f"       {tg_emoji(CUSTOM_EMOJI['wallet'], '💳')} | WALLET\n"
        "╰────────────────────╯\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['available'], '💰')} | БАЛАНС: {money(balance)} ₽\n\n"
        "Минимальный депозит: <b>1 USDT (80 ₽)</b>\n"
        "Минимальный вывод: <b>1 USDT (80 ₽)</b>\n"
        "Курс: <b>1$ ≈ 80 ₽</b>",
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
    save_user_profile(callback.from_user)

    await safe_callback_answer(callback)

    stats = get_user_stats(user_id)

    games_played = int(stats.get("games_played", 0) or 0)
    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)
    balance = int(stats.get("balance", 0) or 0)
    total_bet = int(stats.get("total_bet", 0) or 0)
    total_won = int(stats.get("total_won", 0) or 0)
    biggest_win = int(stats.get("biggest_win", 0) or 0)
    winrate = round(wins / games_played * 100, 1) if games_played else 0

    builder = InlineKeyboardBuilder()
    builder.button(text="📜  ИСТОРИЯ ИГР", callback_data="my_history")
    builder.button(text="👥  РЕФЕРАЛЬНАЯ СИСТЕМА", callback_data="referral")
    if is_admin(user_id):
        # Hidden admin entry: it is shown only to users recognized by is_admin().
        builder.button(text="ADMIN PANEL", callback_data="admin")
    builder.button(text="НАЗАД", callback_data="back_main")
    builder.adjust(1)

    profile_text = (
        "╭────────────────────╮\n"
        f"       {tg_emoji(CUSTOM_EMOJI['profile'], '👤')} | PROFILE\n"
        "╰────────────────────╯\n\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['balance_currency'], '💰')} | BALANCE:\n"
        f"└ ‘{money(balance)} ₽’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['games'], '🎮')} | ИГРЫ\n"
        f"└ ‘{games_played}’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['wins'], '🏆')} | ПОБЕДЫ\n"
        f"└ ‘{wins}’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['losses'], '❌')} | ПОРАЖЕНИЯ\n"
        f"└ ‘{losses}’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['winrate'], '📈')} | WINRATE\n"
        f"└ ‘{winrate}%’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['bets'], '💵')} | СТАВКИ\n"
        f"└ ‘{money(total_bet)} ₽’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['winnings'], '🏆')} | ВЫИГРАНО\n"
        f"└ ‘{money(total_won)} ₽’\n\n"
        f"{tg_emoji(CUSTOM_EMOJI['max_win'], '🔥')} | MAX WIN\n"
        f"└ ‘{money(biggest_win)} ₽’"
    )

    await edit_or_answer(
        callback,
        profile_text,
        builder.as_markup(),
        PHOTO_PROFILE
    )


# =========================================================
# USER GAME HISTORY
# =========================================================

@dp.callback_query(F.data == "my_history")
async def my_history_handler(callback: CallbackQuery):
    save_user_profile(callback.from_user)
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
    save_user_profile(callback.from_user)
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
    save_user_profile(callback.from_user)
    user_id = callback.from_user.id
    ensure_user(user_id)

    await safe_callback_answer(callback)

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

    try:
        qualified = await qualify_referral(
            callback.from_user.id,
            float(result.get("amount_usdt", 0) or 0),
        )
        if qualified:
            print("REFERRAL QUALIFIED:", callback.from_user.id)
    except Exception as error:
        print("REFERRAL QUALIFICATION ERROR:", repr(error))

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
    "darts",
    "football",
    "basketball",
    "plinko",
    "knb",
    "russian_roulette",
    "21",
    "frog",
    "tower",
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

    state = {
        "type": game_type,
        "awaiting_stake": True,
    }

    # После «ЕЩЁ РАЗ» в MINES сразу открываем ввод ставки,
    # сохраняя количество мин из предыдущей партии.
    if game_type == "mines":
        state["mines_count"] = int(pending_mines_count.get(
            user_id, last_mines_count.get(user_id, 2)
        ))

    games[user_id] = state

    balance = get_balance(user_id)

    await safe_callback_answer(callback, )

    game_names = {
        "dice": "🎲 DICE",
        "slots": "🎰 SLOTS",
        "bowling": "🎳 BOWLING",
        "roulette": "🎡 ROULETTE",
        "mines": "💣 MINES",
        "darts": "🎯 DARTS",
        "football": "⚽ FOOTBALL",
        "basketball": "🏀 BASKETBALL",
        "plinko": "🔴 PLINKO",
        "knb": "✊ КНБ",
        "russian_roulette": "🔫 РУССКАЯ РУЛЕТКА",
        "21": "🃏 21",
        "frog": "🐸 ЖАБА",
        "tower": "🗼 TOWER",
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
        "darts",
        "football",
        "basketball",
        "plinko",
        "knb",
        "russian_roulette",
        "21",
        "frog",
        "tower",
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

    if game_type == "mines":
        selected_mines = int(state.get(
            "mines_count", pending_mines_count.get(user_id, last_mines_count.get(user_id, 2))
        ))
        games[user_id]["mines_count"] = selected_mines
        pending_mines_count[user_id] = selected_mines
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
        choices = [
            ("🔴  КРАСНОЕ", "roulette_red"),
            ("⚫️  ЧЁРНОЕ", "roulette_black"),
            ("🟢  ZERO", "roulette_zero"),
            ("⚖️  ЧЁТНОЕ", "roulette_even"),
            ("🔰  НЕЧЁТНОЕ", "roulette_odd"),
            ("🔽  1-18", "roulette_low"),
            ("🔼  19-36", "roulette_high"),
            ("1️⃣  1-12", "roulette_dozen1"),
            ("2️⃣  13-24", "roulette_dozen2"),
            ("3️⃣  25-36", "roulette_dozen3"),
        ]
        for label, data in choices:
            builder.button(text=label, callback_data=data)
        builder.button(text="НАЗАД", callback_data="game_roulette")
        builder.adjust(2, 2, 2, 3, 1)
        await message.answer(
            "╭────────────────────╮\n"
            "       🎡 <b>ROULETTE</b>\n"
            "╰────────────────────╯\n\n"
            f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
            "Выберите вариант ставки:",
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
    # SPECIAL / NEW GAMES
    if game_type in NEW_GAME_TYPES:
        await show_new_game_bet_choices(message, game_type, stake)
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
            reply_markup=after_game_keyboard("dice")
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
        reply_markup=after_game_keyboard("dice")
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
        reply_markup=after_game_keyboard("slots")
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
        reply_markup=after_game_keyboard("bowling")
    )



# =========================================================
# NEW GAMES: DARTS / FOOTBALL / BASKETBALL / PLINKO / KНБ / RUSSIAN ROULETTE / 21 / FROG
# =========================================================

NEW_GAME_TYPES = {
    "darts", "football", "basketball", "plinko", "knb",
    "russian_roulette", "21", "frog", "tower",
}

NEW_GAME_INFO = {
    "darts": ("🎯 DARTS", [
        ("🔴 Красное — x2.3", "darts_red"),
        ("⚪️ Белое — x2.3", "darts_white"),
        ("🎯 Центр — x4.7", "darts_center"),
        ("❌ Мимо — x4.7", "darts_miss"),
    ]),
    "football": ("⚽ FOOTBALL", [
        ("✅ Гол — x1.5", "football_goal"),
        ("💨 Мимо — x2.3", "football_miss"),
        ("🥅 Штанга — x4.7", "football_post"),
    ]),
    "basketball": ("🏀 BASKETBALL", [
        ("🏀 Гол — x2.3", "basketball_goal"),
        ("💨 Мимо — x2.3", "basketball_miss"),
        ("❌ Застрянет — x4.7", "basketball_stuck"),
    ]),
    "plinko": ("🔴 PLINKO", [
        ("🎲 Запустить PLINKO", "plinko_roll"),
    ]),
    "knb": ("✊ КНБ", [
        ("🪨 Камень — x2.8", "knb_rock"),
        ("✂️ Ножницы — x2.8", "knb_scissors"),
        ("📄 Бумага — x2.8", "knb_paper"),
    ]),
    "russian_roulette": ("🔫 РУССКАЯ РУЛЕТКА", [
        ("💀 1 пуля — x1.14", "rr_1"),
        ("💀 2 пули — x1.4", "rr_2"),
        ("💀 3 пули — x1.9", "rr_3"),
        ("💀 4 пули — x2.8", "rr_4"),
        ("💀 5 пуль — x5.7", "rr_5"),
    ]),
    "21": ("🃏 21", [
        ("▶️ Начать игру — x1.8", "21_start"),
    ]),
    "frog": ("🐸 ЖАБА", [
        ("🐸 Начать прыжок", "frog_start"),
    ]),
    "tower": ("🗼 TOWER", [
        ("💣 Выбрать количество бомб", "tower_bombs"),
    ]),
}

NEW_GAME_COEFFICIENTS = {
    "darts_red": 2.3, "darts_white": 2.3, "darts_center": 4.7, "darts_miss": 4.7,
    "football_goal": 1.5, "football_miss": 2.3, "football_post": 4.7,
    "basketball_goal": 2.3, "basketball_miss": 2.3, "basketball_stuck": 4.7,
    "knb_rock": 2.8, "knb_scissors": 2.8, "knb_paper": 2.8,
    "rr_1": 1.14, "rr_2": 1.4, "rr_3": 1.9, "rr_4": 2.8, "rr_5": 5.7,
}

# Коэффициенты TOWER. Для 2–4 мин они рассчитаны от таблицы 1 мины
# с сохранением той же поправки к вероятности безопасного выбора.
TOWER_COEFFICIENTS = {
    1: [1.21, 1.51, 1.88, 2.36, 2.94, 3.68, 4.60, 5.75, 7.19, 8.99],
    2: [1.61, 2.01, 2.51, 3.15, 3.92, 4.91, 6.13, 7.67, 9.59, 11.99],
    3: [2.42, 3.02, 3.76, 4.72, 5.88, 7.36, 9.20, 11.50, 14.38, 17.98],
    4: [4.84, 6.04, 7.52, 9.44, 11.76, 14.72, 18.40, 23.00, 28.76, 35.96],
}



def new_game_choice_keyboard(game_type: str):
    builder = InlineKeyboardBuilder()
    _, choices = NEW_GAME_INFO[game_type]
    for label, data in choices:
        builder.button(text=label, callback_data=data)
    builder.button(text="НАЗАД", callback_data="games")
    builder.adjust(1)
    return builder.as_markup()


async def show_new_game_bet_choices(message: Message, game_type: str, stake: int):
    title, _ = NEW_GAME_INFO[game_type]
    descriptions = {
        "darts": "🔴 Красное x2.3\n⚪️ Белое x2.3\n🎯 Центр x4.7\n❌ Мимо x4.7",
        "football": "✅ Гол x1.5\n💨 Мимо x2.3\n🥅 Штанга x4.7",
        "basketball": "🏀 Гол x2.3\n💨 Мимо x2.3\n❌ Застрянет x4.7",
        "plinko": "1 — проигрыш\n2 — x0.3\n3 — x0.9\n4 — x1.1\n5 — x1.4\n6 — x1.95",
        "knb": "Победа — x2.8\nНичья — проигрыш",
        "russian_roulette": "1 пуля x1.14\n2 пули x1.4\n3 пули x1.9\n4 пули x2.8\n5 пуль x5.7",
        "21": "Соберите как можно ближе к 21, не превышая его.\nКоэффициент выигрыша: x1.8",
        "frog": "Выбирайте одну из 5 кувшинок для следующего прыжка.\nМножители: x1.14 → x1.87 → x4.68 → x23.43.",
        "tower": "10 уровней × 5 ячеек. На каждом уровне от 1 до 4 мин. Выберите количество бомб перед началом.",
    }
    await message.answer(
        f"╭────────────────────╮\n       {title}\n╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n\n"
        f"{descriptions[game_type]}\n\nВыберите действие:",
        reply_markup=new_game_choice_keyboard(game_type),
    )


@dp.callback_query(F.data.in_({"game_darts", "game_football", "game_basketball", "game_plinko", "game_knb", "game_russian_roulette", "game_21", "game_frog"}))
async def new_game_start(callback: CallbackQuery):
    game_type = callback.data.replace("game_", "")
    await safe_callback_answer(callback)
    title, _ = NEW_GAME_INFO[game_type]
    await edit_or_answer(
        callback,
        f"╭────────────────────╮\n       <b>{title}</b>\n╰────────────────────╯\n\nВыберите ставку:",
        stake_keyboard(game_type),
        PHOTO_GAMES,
    )


@dp.callback_query(F.data.regexp(r"^(darts|football|basketball|plinko|knb|russian_roulette|21|frog|tower)_stake_\d+$"))
async def new_game_stake(callback: CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("_stake_")
    game_type = parts[0]
    stake = int(parts[1])
    games[user_id] = {"type": game_type, "stake": stake}
    await safe_callback_answer(callback)
    title, _ = NEW_GAME_INFO[game_type]
    await edit_or_answer(
        callback,
        f"╭────────────────────╮\n       <b>{title}</b>\n╰────────────────────╯\n\n💎 Ставка: <b>{money(stake)} ₽</b>\n\nВыберите вариант:",
        new_game_choice_keyboard(game_type),
        PHOTO_GAMES,
    )


def _knb_result(player: str, bot: str) -> str:
    if player == bot:
        return "draw"
    wins = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
    return "win" if (player, bot) in wins else "loss"


def _card_value(card: str) -> int:
    if card.startswith("10"):
        return 10
    rank = card[0]
    if rank == "A":
        return 11
    if rank == "J":
        return 2
    if rank == "Q":
        return 3
    if rank == "K":
        return 4
    return int(rank)


def _hand_value(cards):
    total = sum(_card_value(c) for c in cards)
    aces = sum(1 for c in cards if c.startswith("A"))
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _tower_coeff_text(value: float) -> str:
    return f"x{value:g}"


def _frog_text(level: int, selected=None, failed=False):
    mults = [1.14, 1.87, 4.68, 23.43]
    rows = []
    for idx in range(3, -1, -1):
        cells = ["🍀"] * 5
        if selected is not None and idx == level:
            cells[selected] = "💦" if failed else "🐸"
        rows.append("|".join(cells) + f"| ({mults[idx]:g}x)")
    current = ["◾️"] * 5
    if selected is not None and not failed:
        current[selected] = "🐸"
    else:
        current[2] = "🐸"
    rows.append("|".join(current) + "| (1x)")
    next_text = f"x{mults[level]:g}" if level < 4 else "ФИНИШ"
    return (
        "🐸 <b>ЖАБА</b>\n\n"
        f"🚀 <b>Следующий множитель:</b> {next_text}\n\n" +
        "\n".join(rows) + "\n\n"
        "🍀 Выберите кувшинку для следующего прыжка"
    )


async def _render_tower(message: Message, game: dict):
    level = int(game.get("level", 0))
    bombs = int(game.get("bombs", 1))
    coeffs = TOWER_COEFFICIENTS[bombs]
    current = coeffs[level - 1] if level > 0 else 1.0
    text = (
        f"🗼 <b>Башня · {level + 1}</b> | 💠 {level} из ◻️ 10\n\n"
        f"💵 <b>Выигрыш:</b> <b>x{current:g}</b>\n\n"
        f"💣 Бомб на уровне: <b>{bombs} шт.</b>\n"
        f"Следующий коэффициент: <b>x{coeffs[level]:g}</b>"
    )
    builder = InlineKeyboardBuilder()
    for i in range(5):
        builder.button(text="◻️", callback_data=f"tower_pick_{i}")
    builder.button(text=f"💣 {bombs} шт.", callback_data="tower_change_bombs")
    builder.button(text="💰 ЗАБРАТЬ", callback_data="tower_cashout")
    builder.adjust(5, 1, 1)
    await message.edit_text(text, reply_markup=builder.as_markup())


@dp.callback_query(F.data.in_(set(NEW_GAME_COEFFICIENTS) | {"plinko_roll", "21_start", "frog_start", "tower_bombs", "tower_bombs_1", "tower_bombs_2", "tower_bombs_3", "tower_bombs_4"}))
async def new_game_play(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") not in NEW_GAME_TYPES:
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    game_type = game["type"]
    stake = int(game["stake"])
    action = callback.data
    # В TOWER сначала выбирается количество мин, ставка списывается только после выбора.
    if game_type == "tower" and action == "tower_bombs":
        await safe_callback_answer(callback)
        builder = InlineKeyboardBuilder()
        for bombs in range(1, 5):
            builder.button(text=f"💣 {bombs} шт.", callback_data=f"tower_bombs_{bombs}")
        builder.button(text="НАЗАД", callback_data="games")
        builder.adjust(2, 2, 1)
        await callback.message.edit_text(
            "🗼 <b>TOWER</b>\n\n"
            "💣 Выберите количество бомб на каждом уровне:\n"
            "1 — x1.21 на первом уровне\n"
            "2 — x1.61 на первом уровне\n"
            "3 — x2.42 на первом уровне\n"
            "4 — x4.84 на первом уровне",
            reply_markup=builder.as_markup(),
        )
        return
    if game_type == "tower" and action.startswith("tower_bombs_"):
        bombs = int(action.rsplit("_", 1)[1])
        if bombs not in TOWER_COEFFICIENTS:
            await safe_callback_answer(callback, "Неверное количество бомб", show_alert=True)
            return
        game["bombs"] = bombs
        if not subtract_balance(user_id, stake):
            await safe_callback_answer(callback, "Недостаточно средств", show_alert=True)
            return
        game["level"] = 0
        game["started"] = True
        game["tower_bombs"] = [random.sample(range(5), bombs) for _ in range(10)]
        await safe_callback_answer(callback)
        await _render_tower(callback.message, game)
        return
    if not subtract_balance(user_id, stake):
        await safe_callback_answer(callback, "Недостаточно средств", show_alert=True)
        return

    # DARTS / FOOTBALL / BASKETBALL: сохраняем Telegram-анимацию броска.
    # Не используем DiceEmoji.DARTS/FOOTBALL/BASKETBALL: в некоторых версиях
    # aiogram этих атрибутов нет. Telegram Bot API принимает emoji как строку.
    dice_emojis = {
        "darts": "🎯",
        "football": "⚽",
        "basketball": "🏀",
    }
    if game_type in dice_emojis:
        dice = await callback.message.answer_dice(emoji=dice_emojis[game_type])
        value = dice.dice.value
        if game_type == "darts":
            outcome = {1: "miss", 2: "miss", 3: "white", 4: "white", 5: "red", 6: "center"}[value]
            wanted = action.replace("darts_", "")
            won = outcome == wanted
        elif game_type == "football":
            outcome = {1: "miss", 2: "miss", 3: "goal", 4: "post", 5: "goal"}[value]
            wanted = action.replace("football_", "")
            won = outcome == wanted
        else:
            outcome = {1: "miss", 2: "miss", 3: "miss", 4: "stuck", 5: "goal"}[value]
            wanted = action.replace("basketball_", "")
            won = outcome == wanted
        labels = {
            "red": "🔴 Красное", "white": "⚪️ Белое", "center": "🎯 Центр", "miss": "❌ Мимо",
            "goal": "✅ Гол", "post": "🥅 Штанга", "stuck": "❌ Застрянет",
        }
        actual = labels[outcome]
        multiplier = NEW_GAME_COEFFICIENTS[action] if won else 0
        payout = int(round(stake * multiplier)) if won else 0
        if won: change_balance(user_id, payout)
        record_game(user_id, game_type, stake, "win" if won else "loss", multiplier, payout)
        games.pop(user_id, None)
        await safe_callback_answer(callback)
        await callback.message.answer(
            f"🎮 <b>{game_type.upper()}</b>\n\nРезультат: <b>{actual}</b>\n" +
            (f"🎉 Выигрыш: <b>{money(payout)} ₽</b> (x{multiplier:g})" if won else "❌ <b>Проигрыш</b>") +
            f"\n\n💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard(game_type),
        )
        return

    # PLINKO
    if game_type == "plinko":
        result = random.randint(1, 6)
        multipliers = {1: 0, 2: .3, 3: .9, 4: 1.1, 5: 1.4, 6: 1.95}
        multiplier = multipliers[result]
        payout = int(round(stake * multiplier)) if multiplier else 0
        if payout: change_balance(user_id, payout)
        record_game(user_id, "plinko", stake, "win" if payout else "loss", multiplier, payout)
        games.pop(user_id, None)
        await safe_callback_answer(callback)
        await callback.message.answer(
            f"🔴 <b>PLINKO</b>\n\n🎲 Результат: <b>{result}</b>\n" +
            (f"💰 Выплата: <b>{money(payout)} ₽</b> (x{multiplier:g})" if payout else "❌ <b>Проигрыш</b>") +
            f"\n\n💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard("plinko"),
        )
        return

    # КНБ — короткая анимация дуэли
    if game_type == "knb":
        player = action.replace("knb_", "")
        bot_choice = random.choice(["rock", "scissors", "paper"])
        result = _knb_result(player, bot_choice)
        payout = int(round(stake * 2.8)) if result == "win" else 0
        names = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
        await safe_callback_answer(callback)
        animation = await callback.message.answer("✊ <b>КНБ</b>\n\n⚔️ <b>ДУЭЛЬ!</b>\n\n🪨  ✂️  📄\n\nГотовимся...")
        for frame in ("✊ <b>КНБ</b>\n\n⚔️ Камень...", "✊ <b>КНБ</b>\n\n⚔️ Ножницы...", "✊ <b>КНБ</b>\n\n⚔️ Бумага...", "✊ <b>КНБ</b>\n\n🥊 <b>РАЗ!</b>"):
            await asyncio.sleep(0.45)
            try:
                await animation.edit_text(frame)
            except TelegramBadRequest:
                pass
        await asyncio.sleep(0.35)
        if payout: change_balance(user_id, payout)
        record_game(user_id, "knb", stake, "win" if result == "win" else "loss", 2.8 if result == "win" else 0, payout)
        games.pop(user_id, None)
        status = "🏆 Победа" if result == "win" else ("⚖️ Ничья — проигрыш" if result == "draw" else "❌ Проигрыш")
        await animation.edit_text(
            f"✊ <b>КНБ</b>\n\nТы: {names[player]}\nБот: {names[bot_choice]}\n\n<b>{status}</b>" +
            (f"\n💰 Выигрыш: <b>{money(payout)} ₽</b> (x2.8)" if payout else "") +
            f"\n\n💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard("knb"),
        )
        return

    # Русская рулетка — анимация вращения барабана и спуска курка
    if game_type == "russian_roulette":
        bullets = int(action.replace("rr_", ""))
        multiplier = NEW_GAME_COEFFICIENTS[action]
        fired = random.randrange(6) < bullets
        await safe_callback_answer(callback)
        animation = await callback.message.answer("🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n🔄 Барабан вращается...\n🔘 🔘 🔘 🔘 🔘 🔘")
        frames = [
            "🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n🔄 Барабан вращается...\n🔘 🟡 🔘 🔘 🔘 🔘",
            "🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n🔄 Барабан вращается...\n🔘 🔘 🟡 🔘 🔘 🔘",
            "🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n🔄 Барабан остановился.\n🔘 🔘 🔘 🟡 🔘 🔘",
            "🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n🎯 Курок спускается...\n💥 ...",
        ]
        for frame in frames:
            await asyncio.sleep(0.55)
            try:
                await animation.edit_text(frame)
            except TelegramBadRequest:
                pass
        await asyncio.sleep(0.45)
        payout = 0 if fired else int(round(stake * multiplier))
        if payout: change_balance(user_id, payout)
        record_game(user_id, "russian_roulette", stake, "win" if payout else "loss", multiplier if payout else 0, payout)
        games.pop(user_id, None)
        await animation.edit_text(
            f"🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n💀 Пуль: <b>{bullets}</b>\n" +
            (f"😮 Камера пустая. Выигрыш: <b>{money(payout)} ₽</b> (x{multiplier:g})" if payout else "💥 <b>Выстрел. Ставка проиграна.</b>") +
            f"\n\n💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard("russian_roulette"),
        )
        return

    # 21
    if game_type == "21" and action == "21_start":
        suits = ["♥️", "♠️", "♦️", "♣️"]
        ranks = ["A", "K", "Q", "J"] + [str(i) for i in range(6, 11)]
        deck = [f"{rank}{suit}" for suit in suits for rank in ranks]
        random.shuffle(deck)
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        game.update({"deck": deck, "player": player, "dealer": dealer})
        game["started"] = True
        await safe_callback_answer(callback)
        builder = InlineKeyboardBuilder()
        builder.button(text="🃏 ВЗЯТЬ КАРТУ", callback_data="21_hit")
        builder.button(text="✋ ОСТАНОВИТЬСЯ", callback_data="21_stand")
        builder.adjust(1)
        await callback.message.answer(
            f"🃏 <b>21</b>\n            \n💵 Ставка: <b>{money(stake)} ₽</b>\n\n"
            f"🤵‍♂ <b>Дилер:</b>\n{' • '.join(dealer)} | <b>{_hand_value(dealer)}</b>\n"
            "-----------------\n"
            f"🫵 <b>Ты:</b>\n{' • '.join(player)} | <b>{_hand_value(player)}</b>\n",
            reply_markup=builder.as_markup(),
        )
        return

    # Жаба — пошаговая анимация прыжков по 5 кувшинкам
    if game_type == "frog" and action == "frog_start":
        game.update({
            "level": 0,
            "frog_safe": [random.randrange(5) for _ in range(4)],
            "started": True,
        })
        await safe_callback_answer(callback)
        builder = InlineKeyboardBuilder()
        for i in range(5):
            builder.button(text="🍀", callback_data=f"frog_jump_{i}")
        builder.adjust(5)
        await callback.message.answer(_frog_text(0), reply_markup=builder.as_markup())
        return



@dp.callback_query(F.data.regexp(r"^frog_jump_[0-4]$"))
async def frog_jump(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") != "frog" or not game.get("started"):
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    level = int(game.get("level", 0))
    pos = int(callback.data.rsplit("_", 1)[1])
    safe_pos = game["frog_safe"][level]
    if pos != safe_pos:
        record_game(user_id, "frog", int(game["stake"]), "loss", 0, 0)
        games.pop(user_id, None)
        await safe_callback_answer(callback)
        await callback.message.edit_text(_frog_text(level, pos, True) + "\n\n🌊 <b>Жаба упала в воду.</b>\n❌ Ставка проиграна.", reply_markup=after_game_keyboard("frog"))
        return
    game["level"] = level + 1
    await safe_callback_answer(callback, "Прыжок успешен!")
    if game["level"] >= 4:
        multiplier = 23.43
        payout = int(round(int(game["stake"]) * multiplier))
        change_balance(user_id, payout)
        record_game(user_id, "frog", int(game["stake"]), "win", multiplier, payout)
        games.pop(user_id, None)
        await callback.message.edit_text(_frog_text(3, pos, False) + f"\n\n🏆 <b>Финиш!</b>\n💰 Выигрыш: <b>{money(payout)} ₽</b> (x{multiplier:g})\n\n💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>", reply_markup=after_game_keyboard("frog"))
        return
    builder = InlineKeyboardBuilder()
    for i in range(5):
        builder.button(text="🍀", callback_data=f"frog_jump_{i}")
    builder.adjust(5)
    await callback.message.edit_text(_frog_text(game["level"], pos, False), reply_markup=builder.as_markup())


@dp.callback_query(F.data.regexp(r"^tower_pick_[0-4]$"))
async def tower_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") != "tower" or not game.get("started"):
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    level = int(game.get("level", 0))
    bombs = int(game.get("bombs", 1))
    if level >= 10:
        await safe_callback_answer(callback, "Башня уже пройдена", show_alert=True)
        return
    pos = int(callback.data.rsplit("_", 1)[1])
    mine_positions = game["tower_bombs"][level]
    if pos in mine_positions:
        stake = int(game["stake"])
        record_game(user_id, "tower", stake, "loss", 0, 0)
        games.pop(user_id, None)
        await safe_callback_answer(callback)
        await callback.message.edit_text(
            f"🗼 <b>TOWER</b>\n\n"
            f"💥 Уровень {level + 1}: <b>БОМБА</b>\n"
            f"❌ Ставка проиграна.\n\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard("tower"),
        )
        return
    game["level"] = level + 1
    await safe_callback_answer(callback, "Безопасно!")
    if game["level"] >= 10:
        multiplier = TOWER_COEFFICIENTS[bombs][-1]
        payout = int(round(int(game["stake"]) * multiplier))
        change_balance(user_id, payout)
        record_game(user_id, "tower", int(game["stake"]), "win", multiplier, payout)
        games.pop(user_id, None)
        await callback.message.edit_text(
            f"🗼 <b>TOWER</b>\n\n🏆 Все 10 уровней пройдены!\n"
            f"💰 Выигрыш: <b>{money(payout)} ₽</b> (x{multiplier:g})\n\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard("tower"),
        )
        return
    await _render_tower(callback.message, game)


@dp.callback_query(F.data == "tower_change_bombs")
async def tower_change_bombs(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") != "tower" or not game.get("started"):
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    await safe_callback_answer(callback)
    builder = InlineKeyboardBuilder()
    for bombs in range(1, 5):
        builder.button(text=f"💣 {bombs} шт.", callback_data=f"tower_restart_bombs_{bombs}")
    builder.adjust(2)
    await callback.message.edit_text("🗼 <b>TOWER</b>\n\nВыберите количество бомб для новой игры:", reply_markup=builder.as_markup())


@dp.callback_query(F.data.regexp(r"^tower_restart_bombs_[1-4]$"))
async def tower_restart_bombs(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") != "tower" or not game.get("started"):
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    bombs = int(callback.data.rsplit("_", 1)[1])
    game["bombs"] = bombs
    game["level"] = 0
    game["tower_bombs"] = [random.sample(range(5), bombs) for _ in range(10)]
    await safe_callback_answer(callback)
    await _render_tower(callback.message, game)


@dp.callback_query(F.data == "tower_cashout")
async def tower_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") != "tower" or not game.get("started"):
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    level = int(game.get("level", 0))
    if level <= 0:
        await safe_callback_answer(callback, "Сначала пройдите хотя бы один уровень", show_alert=True)
        return
    bombs = int(game.get("bombs", 1))
    multiplier = TOWER_COEFFICIENTS[bombs][level - 1]
    payout = int(round(int(game["stake"]) * multiplier))
    change_balance(user_id, payout)
    record_game(user_id, "tower", int(game["stake"]), "win", multiplier, payout)
    games.pop(user_id, None)
    await safe_callback_answer(callback)
    await callback.message.edit_text(
        f"🗼 <b>TOWER</b>\n\n💠 Пройдено: <b>{level}/10</b>\n"
        f"💰 Вы забрали: <b>{money(payout)} ₽</b> (x{multiplier:g})\n\n"
        f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
        reply_markup=after_game_keyboard("tower"),
    )


@dp.callback_query(F.data.in_({"21_hit", "21_stand"}))
async def game_21_action(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)
    if not game or game.get("type") != "21" or not game.get("started"):
        await safe_callback_answer(callback, "Игра устарела", show_alert=True)
        return
    if callback.data == "21_hit":
        game["player"].append(game["deck"].pop())
        value = _hand_value(game["player"])
        if value > 21:
            stake = game["stake"]
            record_game(user_id, "21", stake, "loss", 0, 0)
            games.pop(user_id, None)
            await safe_callback_answer(callback)
            await callback.message.answer(
                f"🃏 <b>21</b>\n\n💵 Ставка: <b>{money(stake)} ₽</b>\n\n🤵‍♂ <b>Дилер:</b>\n{' • '.join(game['dealer'])} | <b>{_hand_value(game['dealer'])}</b>\n-----------------\n🫵 <b>Ты:</b>\n{' • '.join(game['player'])} | <b>{value}</b>\n\n💥 <b>Перебор. Проигрыш.</b>",
                reply_markup=after_game_keyboard("21"),
            )
            return
    else:
        value = _hand_value(game["player"])
        while _hand_value(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        dealer_value = _hand_value(game["dealer"])
        won = value <= 21 and (dealer_value > 21 or value > dealer_value)
        stake = game["stake"]
        payout = int(round(stake * 1.8)) if won else 0
        if payout: change_balance(user_id, payout)
        record_game(user_id, "21", stake, "win" if won else "loss", 1.8 if won else 0, payout)
        games.pop(user_id, None)
        await safe_callback_answer(callback)
        await callback.message.answer(
            f"🃏 <b>21</b>\n\n💵 Ставка: <b>{money(stake)} ₽</b>\n\n"
            f"🤵‍♂ <b>Дилер:</b>\n{' • '.join(game['dealer'])} | <b>{dealer_value}</b>\n"
            "-----------------\n"
            f"🫵 <b>Ты:</b>\n{' • '.join(game['player'])} | <b>{value}</b>\n\n"
            + (f"🏆 Победа! Выигрыш: <b>{money(payout)} ₽</b> (x1.8)" if won else "❌ Проигрыш") +
            f"\n\n💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            reply_markup=after_game_keyboard("21"),
        )
        return
    await safe_callback_answer(callback)
    builder = InlineKeyboardBuilder()
    builder.button(text="🃏 ВЗЯТЬ КАРТУ", callback_data="21_hit")
    builder.button(text="✋ ОСТАНОВИТЬСЯ", callback_data="21_stand")
    builder.adjust(1)
    await callback.message.edit_text(
        f"🃏 <b>21</b>\n\n💵 Ставка: <b>{money(game['stake'])} ₽</b>\n\n"
        f"🤵‍♂ <b>Дилер:</b>\n{' • '.join(game['dealer'])} | <b>{_hand_value(game['dealer'])}</b>\n"
        "-----------------\n"
        f"🫵 <b>Ты:</b>\n{' • '.join(game['player'])} | <b>{_hand_value(game['player'])}</b>\n",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "game_tower")
async def tower_placeholder(callback: CallbackQuery):
    await safe_callback_answer(callback, "TOWER пока не настроен", show_alert=True)


@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await safe_callback_answer(callback)

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
        "🟢 Zero — <b>x35</b>\n"
        "🔴 Красное — <b>x1.9</b>\n"
        "⚫️ Чёрное — <b>x1.9</b>\n"
        "⚖️ Чётное — <b>x1.9</b>\n"
        "🔰 Нечётное — <b>x1.9</b>\n"
        "🔽 1-18 — <b>x1.9</b>\n"
        "🔼 19-36 — <b>x1.9</b>\n"
        "1️⃣ 1-12 — <b>x2.7</b>\n"
        "2️⃣ 13-24 — <b>x2.7</b>\n"
        "3️⃣ 25-36 — <b>x2.7</b>\n\n"
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
    choices = [
        ("🔴  КРАСНОЕ  x1.9", "roulette_red"),
        ("⚫️  ЧЁРНОЕ  x1.9", "roulette_black"),
        ("🟢  ZERO  x35", "roulette_zero"),
        ("⚖️  ЧЁТНОЕ  x1.9", "roulette_even"),
        ("🔰  НЕЧЁТНОЕ  x1.9", "roulette_odd"),
        ("🔽  1-18  x1.9", "roulette_low"),
        ("🔼  19-36  x1.9", "roulette_high"),
        ("1️⃣  1-12  x2.7", "roulette_dozen1"),
        ("2️⃣  13-24  x2.7", "roulette_dozen2"),
        ("3️⃣  25-36  x2.7", "roulette_dozen3"),
    ]
    for label, data in choices:
        builder.button(text=label, callback_data=data)
    builder.button(text="НАЗАД", callback_data="game_roulette")
    builder.adjust(2, 2, 2, 3, 1)

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
    F.data.in_({
        "roulette_red", "roulette_black", "roulette_zero",
        "roulette_even", "roulette_odd",
        "roulette_low", "roulette_high",
        "roulette_dozen1", "roulette_dozen2", "roulette_dozen3",
    })
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
    won = roulette_bet_wins(selected_color, result)
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
            reply_markup=after_game_keyboard("roulette"),
            parse_mode=ParseMode.HTML,
        )
    except Exception as error:
        print("ROULETTE RESULT ERROR:", repr(error))
        await bot.send_message(
            user_id,
            premiumize_text(text),
            reply_markup=after_game_keyboard("roulette"),
        )


# =========================================================
# MINES
# =========================================================

def mines_count_keyboard():
    builder = InlineKeyboardBuilder()
    for mine_count in range(MINES_MIN, MINES_MAX + 1):
        builder.button(
            text=f"💣 {mine_count}",
            callback_data=f"mines_count_{mine_count}",
        )
    builder.button(text="НАЗАД", callback_data="games")
    builder.adjust(6, 6, 6, 5, 1)
    return builder.as_markup()


def mines_multiplier(mine_count: int, opened_count: int) -> float:
    """Combinatorial Mines multiplier with a small configurable edge."""
    if opened_count <= 0:
        return 1.0

    safe_cells = MINES_SIZE - mine_count
    if opened_count > safe_cells:
        return 0.0

    multiplier = 1.0
    for i in range(opened_count):
        multiplier *= (MINES_SIZE - i) / (safe_cells - i)

    return round(multiplier * MINES_HOUSE_EDGE, 4)


def mines_keyboard(user_id: int):
    game = games.get(user_id)
    builder = InlineKeyboardBuilder()
    opened = game.get("opened", []) if game else []

    for i in range(MINES_SIZE):
        text = "💎" if i in opened else "⬜"
        builder.button(text=text, callback_data=f"mine_{i}")

    builder.button(
        text="💰  ЗАБРАТЬ",
        callback_data="mine_cashout",
    )
    builder.adjust(5, 5, 5, 5, 5, 1)
    return builder.as_markup()


@dp.callback_query(F.data == "game_mines")
async def mines_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    # Не сбрасываем ранее выбранное количество мин при повторном открытии меню.
    pending_mines_count.setdefault(user_id, int(last_mines_count.get(user_id, 2)))
    games[user_id] = {"type": "mines_setup", "mines_count": pending_mines_count[user_id]}

    await safe_callback_answer(callback)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        "Поле: <b>5 × 5</b> — 25 клеток.\n"
        "Выберите количество мин <b>от 2 до 24</b>:",
        mines_count_keyboard(),
        PHOTO_MINES,
    )


@dp.callback_query(F.data.startswith("mines_count_"))
async def mines_count(callback: CallbackQuery):
    user_id = callback.from_user.id
    mine_count = int(callback.data.split("_")[-1])

    if not (MINES_MIN <= mine_count <= MINES_MAX):
        await safe_callback_answer(
            callback,
            "Недопустимое количество мин",
            show_alert=True,
        )
        return

    # Сохраняем выбор отдельно от состояния ставки, чтобы он не терялся.
    pending_mines_count[user_id] = mine_count
    last_mines_count[user_id] = mine_count
    games[user_id] = {
        "type": "mines",
        "mines_count": mine_count,
    }

    await safe_callback_answer(callback)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        "Поле: <b>5 × 5</b> — 25 клеток.\n"
        f"💣 Мин: <b>{mine_count}</b>\n"
        f"💎 Безопасных клеток: <b>{MINES_SIZE - mine_count}</b>\n\n"
        "Выберите ставку:",
        stake_keyboard("mines"),
        PHOTO_MINES,
    )


@dp.callback_query(F.data.startswith("mines_stake_"))
async def mines_stake(callback: CallbackQuery):
    user_id = callback.from_user.id
    stake = int(callback.data.split("_")[-1])

    game = games.get(user_id, {})
    mine_count = int(pending_mines_count.get(
        user_id, game.get("mines_count", last_mines_count.get(user_id, 2))
    ))

    games[user_id] = {
        "type": "mines",
        "stake": stake,
        "mines_count": mine_count,
    }

    await safe_callback_answer(callback)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n"
        f"💣 Мин: <b>{mine_count}</b>\n\n"
        "Подтвердить ставку?",
        confirm_bet_keyboard("mines"),
    )


@dp.callback_query(F.data == "confirm_mines")
async def confirm_mines(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)

    if not game or game.get("type") != "mines":
        await safe_callback_answer(
            callback,
            "Игра устарела",
            show_alert=True,
        )
        return

    stake = int(game["stake"])
    mine_count = int(game.get("mines_count", pending_mines_count.get(user_id, 2)))
    if not (MINES_MIN <= mine_count <= MINES_MAX):
        await safe_callback_answer(callback, "Недопустимое количество мин", show_alert=True)
        return
    game["mines_count"] = mine_count
    pending_mines_count[user_id] = mine_count

    if not subtract_balance(user_id, stake):
        await safe_callback_answer(
            callback,
            "Недостаточно средств",
            show_alert=True,
        )
        return

    mines = random.sample(range(MINES_SIZE), mine_count)

    game["mines"] = mines
    game["opened"] = []
    game["multiplier"] = 1.0
    game["settled"] = False
    last_mines_count[user_id] = mine_count

    await safe_callback_answer(callback)

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        f"💎 Ставка: <b>{money(stake)} ₽</b>\n"
        f"💣 Мин: <b>{mine_count}</b>\n"
        "📈 Коэффициент: <b>x1.00</b>\n"
        f"💰 Забрать: <b>{money(stake)} ₽</b>\n\n"
        "Открывайте клетки 👇",
        mines_keyboard(user_id),
    )


@dp.callback_query(F.data.startswith("mine_"))
async def mine_click(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = games.get(user_id)

    if not game or game.get("type") != "mines" or "mines" not in game:
        await safe_callback_answer(
            callback,
            "Игра устарела",
            show_alert=True,
        )
        return

    action = callback.data.split("_")[1]

    if action == "cashout":
        if game.get("settled"):
            await safe_callback_answer(
                callback,
                "Игра уже завершена",
                show_alert=True,
            )
            return

        multiplier = float(game["multiplier"])
        stake = int(game["stake"])
        payout = int(round(stake * multiplier))

        change_balance(user_id, payout)
        record_game(
            user_id,
            "mines",
            stake,
            "win",
            multiplier,
            payout,
        )

        game["settled"] = True
        games.pop(user_id, None)

        await safe_callback_answer(callback)

        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💎 <b>MINES</b>\n"
            "╰────────────────────╯\n\n"
            "💰 <b>ВЫ ЗАБРАЛИ ВЫИГРЫШ</b>\n\n"
            f"📈 Коэффициент: <b>x{multiplier:.2f}</b>\n"
            f"💵 Выигрыш: <b>{money(payout)} ₽</b>\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            after_game_keyboard("mines"),
        )
        return

    index = int(action)

    if index in game["opened"]:
        await safe_callback_answer(callback, "Эта клетка уже открыта")
        return

    if index in game["mines"]:
        stake = int(game["stake"])

        record_game(
            user_id,
            "mines",
            stake,
            "loss",
            0,
            0,
        )

        game["settled"] = True
        games.pop(user_id, None)

        await safe_callback_answer(callback, "💥 БУМ!", show_alert=True)

        await edit_or_answer(
            callback,
            "╭────────────────────╮\n"
            "       💥 <b>MINES</b>\n"
            "╰────────────────────╯\n\n"
            "💣 <b>МИНА!</b>\n\n"
            "❌ Ты проиграл.\n\n"
            f"💳 Баланс: <b>{money(get_balance(user_id))} ₽</b>",
            after_game_keyboard("mines"),
        )
        return

    game["opened"].append(index)
    opened_count = len(game["opened"])
    game["multiplier"] = mines_multiplier(
        int(game["mines_count"]),
        opened_count,
    )

    multiplier = float(game["multiplier"])
    payout = int(round(game["stake"] * multiplier))

    await safe_callback_answer(callback, f"💎 x{multiplier:.2f}")

    await edit_or_answer(
        callback,
        "╭────────────────────╮\n"
        "       💣 <b>MINES</b>\n"
        "╰────────────────────╯\n\n"
        f"💣 Мин: <b>{game['mines_count']}</b>\n"
        f"📈 Коэффициент: <b>x{multiplier:.2f}</b>\n"
        f"💰 Забрать: <b>{money(payout)} ₽</b>\n"
        f"🔓 Открыто: <b>{opened_count}/{MINES_SIZE - game['mines_count']}</b>",
        mines_keyboard(user_id),
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
        text="📋  ЛОГИ АКТИВНОСТИ",
        callback_data="admin_activity"
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
# ADMIN ACTIVITY LOGS
# =========================================================

def format_activity_rows(rows, title="📋 <b>ЛОГИ АКТИВНОСТИ</b>"):
    if not rows:
        return f"{title}\n\nЛог пока пуст."

    lines = [title, ""]
    for row in rows:
        username = row[2] or ""
        display = f"@{username.lstrip('@')}" if username else (row[3] or "Без имени")
        line = (
            f"🕒 <code>{row[7]}</code> | <b>{display}</b> "
            f"(<code>{row[1]}</code>)\n"
            f"   <b>{row[4]}</b>: <code>{row[5]}</code>"
        )
        if row[6]:
            line += f"\n   └ {row[6]}"
        lines.append(line)

    return "\n".join(lines)


@dp.callback_query(F.data == "admin_activity")
async def admin_activity(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback, "Нет доступа", show_alert=True)
        return

    await safe_callback_answer(callback)
    rows = get_activity_logs(30)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 ОБНОВИТЬ", callback_data="admin_activity")
    builder.button(text="👤 ЛОГИ ИГРОКА", callback_data="admin_activity_user")
    builder.button(text="⬅️ ADMIN PANEL", callback_data="admin")
    builder.adjust(1)

    await edit_or_answer(
        callback,
        format_activity_rows(rows),
        builder.as_markup(),
        PHOTO_ADMIN,
    )


@dp.callback_query(F.data == "admin_activity_user")
async def admin_activity_user_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback, "Нет доступа", show_alert=True)
        return

    games[callback.from_user.id] = {"admin_action": "activity_user"}
    await safe_callback_answer(callback)
    await callback.message.answer(
        "👤 <b>ЛОГИ ИГРОКА</b>\n\n"
        "Отправьте Telegram ID пользователя."
    )


@dp.callback_query(F.data.startswith("admin_activity_user_"))
async def admin_activity_user_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback, "Нет доступа", show_alert=True)
        return

    try:
        target_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await safe_callback_answer(callback, "Некорректный ID", show_alert=True)
        return

    await safe_callback_answer(callback)
    rows = get_activity_logs(50, target_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ ВСЕ ЛОГИ", callback_data="admin_activity")
    builder.button(text="⬅️ ADMIN PANEL", callback_data="admin")
    builder.adjust(1)

    await edit_or_answer(
        callback,
        format_activity_rows(
            rows,
            f"📋 <b>АКТИВНОСТЬ ИГРОКА</b>\nID: <code>{target_id}</code>",
        ),
        builder.as_markup(),
        PHOTO_ADMIN,
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

    if action == "activity_user":
        raw_id = (message.text or "").strip()
        try:
            target_id = int(raw_id)
        except ValueError:
            await message.answer("❌ ID должен быть числом.")
            return True

        rows = get_activity_logs(50, target_id)
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ ВСЕ ЛОГИ", callback_data="admin_activity")
        builder.button(text="⬅️ ADMIN PANEL", callback_data="admin")
        builder.adjust(1)

        await message.answer(
            format_activity_rows(
                rows,
                f"📋 <b>АКТИВНОСТЬ ИГРОКА</b>\nID: <code>{target_id}</code>",
            ),
            reply_markup=builder.as_markup(),
        )
        games.pop(user_id, None)
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
    init_profile_store()
    init_activity_store()
    init_referral_store()
    init_webapp_guard_store()

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
    return FileResponse(str(BASE_DIR / "index.html"))


@app.get("/api/config")
async def api_config():
    return {"real_economy": REAL_ECONOMY, "rtp": 0.965, "currency": "RUB"}


@app.post("/api/me")
async def api_me(payload: WebAppAuth):
    user = validate_telegram_webapp_data(payload.init_data)
    uid = int(user["id"])
    ensure_user(uid)
    guard = get_webapp_guard(uid)
    return {"user": user, "balance": get_balance(uid), "guard": guard}


@app.post("/api/history")
async def api_history(payload: WebAppAuth):
    user = validate_telegram_webapp_data(payload.init_data)
    uid = int(user["id"])
    return {
        "games": get_game_history(uid),
        "payments": get_payment_history(uid),
        "withdrawals": get_withdrawal_history(uid, 20),
    }


@app.post("/api/deposit")
async def api_deposit(payload: DepositRequest):
    user = validate_telegram_webapp_data(payload.init_data)
    uid = int(user["id"])
    require_real_money_access(uid, "deposit")
    ensure_user(uid)
    invoice = await create_invoice(uid, float(payload.amount_usdt))
    return {"invoice": invoice}


@app.post("/api/deposit/{invoice_id}/check")
async def api_deposit_check(invoice_id: int, payload: WebAppAuth):
    user = validate_telegram_webapp_data(payload.init_data)
    uid = int(user["id"])
    require_real_money_access(uid, "deposit")
    invoice = await get_invoice(invoice_id)
    if not invoice or int(invoice.get("user_id", -1)) != uid:
        raise HTTPException(status_code=404, detail="Invoice not found")
    result = await process_paid_invoice(invoice_id)
    return {"processed": result is not None, "invoice": await get_invoice(invoice_id), "balance": get_balance(uid)}


@app.post("/api/withdraw")
async def api_withdraw(payload: WithdrawRequest):
    user = validate_telegram_webapp_data(payload.init_data)
    uid = int(user["id"])
    require_real_money_access(uid, "withdrawal")
    ensure_user(uid)
    withdrawal = create_withdrawal(user_id=uid, amount_rub=payload.amount_rub, payout_details=payload.payout_details)
    if withdrawal is None:
        raise HTTPException(status_code=400, detail="Unable to create withdrawal")
    return {"withdrawal": withdrawal, "balance": get_balance(uid)}


@app.post("/api/game/round")
async def api_game_round(payload: GameRoundRequest):
    user = validate_telegram_webapp_data(payload.init_data)
    uid = int(user["id"])
    require_real_money_access(uid, "game")
    # Do not expose a client-side RNG. Existing game handlers remain the authoritative
    # implementation; this endpoint is intentionally conservative until a game-specific
    # server routine is selected and audited.
    raise HTTPException(status_code=501, detail="Game API requires an audited game-specific server routine")


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

        # Passive logging before dispatch: game handlers remain unchanged.
        try:
            if update.callback_query and update.callback_query.from_user:
                u = update.callback_query.from_user
                chat_id = (
                    update.callback_query.message.chat.id
                    if update.callback_query.message
                    else ""
                )
                log_activity(
                    u.id,
                    u.username,
                    u.first_name,
                    "CALLBACK",
                    update.callback_query.data or "",
                    f"chat_id={chat_id}",
                )
                print("CALLBACK:", update.callback_query.data)
            elif update.message and update.message.from_user:
                u = update.message.from_user
                msg_text = (
                    update.message.text
                    or update.message.caption
                    or "[media/service message]"
                )
                log_activity(
                    u.id,
                    u.username,
                    u.first_name,
                    "MESSAGE",
                    msg_text,
                    f"chat_id={update.message.chat.id}",
                )
        except Exception as log_error:
            print("ACTIVITY PARSE ERROR:", repr(log_error))

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
