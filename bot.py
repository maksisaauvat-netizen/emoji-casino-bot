import os

from fastapi import FastAPI, Request, Header, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import (
    init_db,
    get_balance,
    change_balance,
    subtract_balance,
)


TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is not set")

if not RENDER_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL is not set")


bot = Bot(TOKEN)
dp = Dispatcher()
app = FastAPI()


# Активные игры пользователей.
# Деньги хранятся в SQLite.
games = {}


# =========================
# КЛАВИАТУРЫ
# =========================

def games_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | Кубики",
                    callback_data="game_dice",
                )
            ]
        ]
    )


def dice_modes():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 1 бросок",
                    callback_data="dice_mode_1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎲 2 броска",
                    callback_data="dice_mode_2",
                )
            ],
        ]
    )


def dice_one_predictions():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="x1.85 | Меньше 3",
                    callback_data="dice_one_less",
                )
            ],
            [
                InlineKeyboardButton(
                    text="x1.85 | Больше 3",
                    callback_data="dice_one_more",
                )
            ],
        ]
    )


def dice_two_predictions():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="x1.85 | Меньше 7",
                    callback_data="dice_two_less",
                )
            ],
            [
                InlineKeyboardButton(
                    text="x5.00 | Равно 7",
                    callback_data="dice_two_equal",
                )
            ],
            [
                InlineKeyboardButton(
                    text="x1.85 | Больше 7",
                    callback_data="dice_two_more",
                )
            ],
        ]
    )


def after_game_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 | Бросить ещё раз",
                    callback_data="dice_again",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ | К играм",
                    callback_data="games_menu",
                )
            ],
        ]
    )


# =========================
# НАЧАЛО ИГРЫ В КУБИКИ
# =========================

async def start_dice_game(callback):
    user_id = callback.from_user.id

    # Не разрешаем создать второй раунд.
    if user_id in games:
        await callback.answer(
            "🎲 У тебя уже есть активная игра.",
            show_alert=True,
        )
        return

    balance = get_balance(user_id)

    if balance < 100:
        await callback.answer(
            "❌ Недостаточно монет.",
            show_alert=True,
        )
        return

    # Списываем ставку.
    success = subtract_balance(user_id, 100)

    if not success:
        await callback.answer(
            "❌ Недостаточно монет.",
            show_alert=True,
        )
        return

    # Создаём активную игру.
    games[user_id] = {
        "stake": 100,
        "mode": None,
        "prediction": None,
        "completed": False,
    }

    new_balance = get_balance(user_id)

    await callback.answer()

    await callback.message.answer(
        f"🎲 Кубики\n\n"
        f"Ставка: 100 💎\n"
        f"💎 Баланс: {new_balance} 💎\n\n"
        f"Выбери режим:",
        reply_markup=dice_modes(),
    )


# =========================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================

@dp.message()
async def message_handler(message):
    user_id = message.from_user.id

    # -------------------------
    # /start
    # -------------------------

    if message.text == "/start":
        balance = get_balance(user_id)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎰 Играть",
                        callback_data="play",
                    )
                ]
            ]
        )

        await message.answer(
            f"🎰 Привет!\n\n"
            f"Добро пожаловать в Emoji Casino!\n\n"
            f"💰 Твой баланс: {balance} монет",
            reply_markup=keyboard,
        )
        return

    # -------------------------
    # НАСТОЯЩИЙ TELEGRAM DICE
    # -------------------------
    #
    # Telegram присылает кубик
    # не в message.text,
    # а в message.dice.
    #

    if message.dice is not None:
        dice = message.dice

        # Нас интересует именно 🎲.
        if dice.emoji != "🎲":
            return

        game = games.get(user_id)

        if not game:
            return

        if game["completed"]:
            return

        if game["mode"] is None:
            return

        if game["prediction"] is None:
            return

        # Значение настоящего Telegram Dice.
        result = dice.value

        # Сразу закрываем раунд.
        # Это предотвращает повторную выплату.
        game["completed"] = True

        # =========================
        # 1 КУБИК
        # =========================

        if game["mode"] == 1:

            prediction = game["prediction"]

            if prediction == "less":
                win = result < 3
            else:
                win = result > 3

            coefficient = 1.85

            if win:
                payout = 185
            else:
                payout = 0

            if payout > 0:
                balance = change_balance(
                    user_id,
                    payout,
                )
            else:
                balance = get_balance(user_id)

            games.pop(user_id, None)

            await message.answer(
                f"🎲 Результат: {result}\n\n"
                f"Ставка: 100 💎\n"
                f"Коэффициент: x{coefficient:.2f}\n"
                f"Выплата: {payout} 💎\n\n"
                f"💎 Баланс: {balance} 💎",
                reply_markup=after_game_keyboard(),
            )

            return

        # =========================
        # 2 КУБИКА
        # =========================
        #
        # Первый настоящий Telegram Dice
        # уже пришёл.
        #
        # Для режима 2 бросков сохраняем
        # первый результат и ждём второй.
        #

        if game["mode"] == 2:

            # Если это первый кубик.
            if "first_dice" not in game:

                game["first_dice"] = result

                # Первый бросок не завершает игру.
                game["completed"] = False

                await message.answer(
                    f"🎲 Первый кубик: {result}\n\n"
                    f"Теперь отправь 🎲 ещё раз — "
                    f"это будет второй кубик."
                )

                return

            # Второй кубик.
            first = game["first_dice"]
            second = result

            total = first + second

            prediction = game["prediction"]

            if prediction == "less":
                win = total < 7
                coefficient = 1.85

            elif prediction == "equal":
                win = total == 7
                coefficient = 5.00

            else:
                win = total > 7
                coefficient = 1.85

            if win:
                if coefficient == 5.00:
                    payout = 500
                else:
                    payout = 185
            else:
                payout = 0

            if payout > 0:
                balance = change_balance(
                    user_id,
                    payout,
                )
            else:
                balance = get_balance(user_id)

            games.pop(user_id, None)

            await message.answer(
                f"🎲 Результат: {first} + {second} = {total}\n\n"
                f"Ставка: 100 💎\n"
                f"Коэффициент: x{coefficient:.2f}\n"
                f"Выплата: {payout} 💎\n\n"
                f"💎 Баланс: {balance} 💎",
                reply_markup=after_game_keyboard(),
            )

            return


# =========================
# CALLBACK-КНОПКИ
# =========================

@dp.callback_query()
async def callback_handler(callback):
    print("CALLBACK RECEIVED:", callback.data)

    user_id = callback.from_user.id

    # -------------------------
    # ИГРАТЬ
    # -------------------------

    if callback.data == "play":

        balance = get_balance(user_id)

        await callback.answer()

        await callback.message.answer(
            f"🎰 Игры\n\n"
            f"💎 Баланс: {balance} 💎\n\n"
            f"Выбери игру:",
            reply_markup=games_menu(),
        )

        return

    # -------------------------
    # КУБИКИ
    # -------------------------

    if callback.data == "game_dice":
        await start_dice_game(callback)
        return

    # -------------------------
    # 1 БРОСОК
    # -------------------------

    if callback.data == "dice_mode_1":

        game = games.get(user_id)

        if not game:
            await callback.answer(
                "❌ Игра не найдена.",
                show_alert=True,
            )
            return

        game["mode"] = 1

        await callback.answer()

        await callback.message.answer(
            "🎲 1 бросок\n\n"
            "Выбери прогноз:",
            reply_markup=dice_one_predictions(),
        )

        return

    # -------------------------
    # 2 БРОСКА
    # -------------------------

    if callback.data == "dice_mode_2":

        game = games.get(user_id)

        if not game:
            await callback.answer(
                "❌ Игра не найдена.",
                show_alert=True,
            )
            return

        game["mode"] = 2

        await callback.answer()

        await callback.message.answer(
            "🎲 2 броска\n\n"
            "Выбери прогноз:",
            reply_markup=dice_two_predictions(),
        )

        return

    # -------------------------
    # ПРОГНОЗ
    # -------------------------

    if callback.data in (
        "dice_one_less",
        "dice_one_more",
        "dice_two_less",
        "dice_two_equal",
        "dice_two_more",
    ):

        game = games.get(user_id)

        if not game:
            await callback.answer(
                "❌ Игра не найдена.",
                show_alert=True,
            )
            return

        if game["mode"] == 1:

            if callback.data == "dice_one_less":
                game["prediction"] = "less"
            else:
                game["prediction"] = "more"

        elif game["mode"] == 2:

            if callback.data == "dice_two_less":
                game["prediction"] = "less"

            elif callback.data == "dice_two_equal":
                game["prediction"] = "equal"

            else:
                game["prediction"] = "more"

        # Для двух кубиков
        # очищаем первый результат,
        # если он вдруг остался.
        game.pop("first_dice", None)

        await callback.answer()

        if game["mode"] == 1:

            await callback.message.answer(
                "🎲 Отправь эмодзи 🎲, "
                "чтобы бросить кубик."
            )

        else:

            await callback.message.answer(
                "🎲 Отправь эмодзи 🎲, "
                "чтобы бросить первый кубик."
            )

        return

    # -------------------------
    # БРОСИТЬ ЕЩЁ РАЗ
    # -------------------------

    if callback.data == "dice_again":
        await start_dice_game(callback)
        return

    # -------------------------
    # К ИГРАМ
    # -------------------------

    if callback.data == "games_menu":

        games.pop(user_id, None)

        balance = get_balance(user_id)

        await callback.answer()

        await callback.message.answer(
            f"🎰 Игры\n\n"
            f"💎 Баланс: {balance} 💎\n\n"
            f"Выбери игру:",
            reply_markup=games_menu(),
        )

        return

    await callback.answer()


# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def startup():

    init_db()

    webhook_url = (
        f"{RENDER_URL}/webhook/{WEBHOOK_SECRET}"
    )

    print(
        "SETTING WEBHOOK:",
        webhook_url,
    )

    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=False,
        allowed_updates=[
            "message",
            "callback_query",
        ],
    )

    info = await bot.get_webhook_info()

    print(
        "WEBHOOK URL:",
        info.url,
    )

    print(
        "PENDING UPDATES:",
        info.pending_update_count,
    )

    print(
        "LAST ERROR:",
        info.last_error_message,
    )


# =========================
# SHUTDOWN
# =========================

@app.on_event("shutdown")
async def shutdown():

    # НЕ удаляем webhook.
    # Иначе старый экземпляр Render
    # может удалить webhook после запуска нового.

    await bot.session.close()


# =========================
# HEALTH CHECK
# =========================

@app.get("/")
async def home():
    return {
        "status": "ok"
    }


# =========================
# TELEGRAM WEBHOOK
# =========================

@app.post("/webhook/{secret}")
async def webhook(
    secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None
    ),
):

    print("=== WEBHOOK ===")

    if secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=403
        )

    if (
        x_telegram_bot_api_secret_token
        != WEBHOOK_SECRET
    ):
        raise HTTPException(
            status_code=403
        )

    data = await request.json()

    print(
        "UPDATE RECEIVED:",
        data,
    )

    update = Update.model_validate(
        data,
        context={
            "bot": bot
        },
    )

    await dp.feed_update(
        bot,
        update,
    )

    return {
        "ok": True
    }
