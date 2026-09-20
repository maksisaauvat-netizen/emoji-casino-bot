import os
import aiohttp

from database import (
    process_payment,
    get_balance,
)


CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")

USDT_TO_RUB = 80

MIN_DEPOSIT_USDT = 1

CRYPTO_PAY_API = "https://pay.crypt.bot/api"


# =========================================================
# CRYPTO PAY API
# =========================================================

async def crypto_request(
    method: str,
    endpoint: str,
    data: dict | None = None
):
    if not CRYPTO_PAY_TOKEN:
        raise RuntimeError(
            "CRYPTO_PAY_TOKEN is not configured"
        )

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN,
        "Content-Type": "application/json",
    }

    url = f"{CRYPTO_PAY_API}/{endpoint}"

    async with aiohttp.ClientSession() as session:

        async with session.request(
            method,
            url,
            headers=headers,
            json=data or {}
        ) as response:

            result = await response.json()

            if not result.get("ok"):

                raise RuntimeError(
                    result.get(
                        "error",
                        "Crypto Pay API error"
                    )
                )

            return result.get("result")


# =========================================================
# CRYPTO PAY APP
# =========================================================

async def get_crypto_app():

    return await crypto_request(
        "GET",
        "getMe"
    )


# =========================================================
# CREATE INVOICE
# =========================================================

async def create_invoice(
    user_id: int,
    amount_usdt: float
):

    if amount_usdt < MIN_DEPOSIT_USDT:

        raise ValueError(
            f"Минимальное пополнение: "
            f"{MIN_DEPOSIT_USDT} USDT"
        )

    amount_rub = int(
        amount_usdt * USDT_TO_RUB
    )

    invoice = await crypto_request(
        "POST",
        "createInvoice",
        {
            "currency_type": "crypto",

            "asset": "USDT",

            "amount": str(amount_usdt),

            "description": (
                f"Пополнение Resonant Casino: "
                f"{amount_rub} ₽"
            ),

            # Передаём Telegram user_id
            # внутрь invoice.
            # Потом он используется
            # для определения владельца платежа.
            "payload": str(user_id),

            "allow_comments": False,

            "allow_anonymous": False,

            "expires_in": 3600,
        }
    )

    return {
        "invoice_id": invoice["invoice_id"],

        "amount_usdt": amount_usdt,

        "amount_rub": amount_rub,

        "pay_url": invoice.get(
            "pay_url"
        ),

        "bot_invoice_url": invoice.get(
            "bot_invoice_url"
        ),

        "status": invoice.get(
            "status"
        ),
    }


# =========================================================
# GET INVOICE
# =========================================================

async def get_invoice(
    invoice_id: int
):

    invoices = await crypto_request(
        "GET",
        "getInvoices",
        {
            "invoice_ids": str(invoice_id)
        }
    )

    if not invoices:

        return None

    return invoices[0]


# =========================================================
# CHECK PAYMENT STATUS
# =========================================================

async def check_invoice_paid(
    invoice_id: int
):

    invoice = await get_invoice(
        invoice_id
    )

    if invoice is None:

        return False

    return (
        invoice.get("status")
        == "paid"
    )


# =========================================================
# PROCESS PAID INVOICE
# =========================================================

async def process_paid_invoice(
    invoice_id: int
):
    """
    Проверяет invoice в Crypto Pay.

    Если invoice действительно оплачен,
    деньги зачисляются пользователю.

    ВАЖНО:

    Повторная обработка одного invoice
    НЕ зачисляет деньги повторно.

    Защита находится в database.process_payment().
    """

    # -----------------------------------------------------
    # Получаем invoice из Crypto Pay
    # -----------------------------------------------------

    invoice = await get_invoice(
        invoice_id
    )

    if invoice is None:

        return None

    # -----------------------------------------------------
    # Проверяем статус
    # -----------------------------------------------------

    if invoice.get("status") != "paid":

        return None

    # -----------------------------------------------------
    # Получаем payload
    # -----------------------------------------------------

    payload = invoice.get(
        "payload"
    )

    if not payload:

        return None

    # -----------------------------------------------------
    # В payload должен находиться user_id
    # -----------------------------------------------------

    try:

        user_id = int(
            payload
        )

    except (
        TypeError,
        ValueError
    ):

        return None

    # -----------------------------------------------------
    # Получаем сумму
    # -----------------------------------------------------

    try:

        amount_usdt = float(
            invoice.get(
                "amount",
                0
            )
        )

    except (
        TypeError,
        ValueError
    ):

        return None

    # -----------------------------------------------------
    # Проверяем сумму
    # -----------------------------------------------------

    if amount_usdt <= 0:

        return None

    # -----------------------------------------------------
    # Переводим USDT → RUB
    # -----------------------------------------------------

    amount_rub = int(
        amount_usdt * USDT_TO_RUB
    )

    if amount_rub <= 0:

        return None

    # -----------------------------------------------------
    # БЕЗОПАСНОЕ ЗАЧИСЛЕНИЕ
    # -----------------------------------------------------

    # process_payment():
    #
    # 1. Проверяет invoice_id.
    # 2. Если invoice уже был обработан —
    #    возвращает None.
    # 3. Если новый —
    #    записывает платёж.
    # 4. Начисляет баланс.
    # 5. Делает всё одной транзакцией SQLite.
    #
    # Поэтому один invoice невозможно
    # нормально зачислить дважды.

    result = process_payment(
        invoice_id=invoice_id,

        user_id=user_id,

        amount_usdt=amount_usdt,

        amount_rub=amount_rub
    )

    return result


# =========================================================
# CURRENCY CONVERSION
# =========================================================

def usdt_to_rub(
    amount_usdt: float
) -> int:

    return int(
        amount_usdt * USDT_TO_RUB
    )


def rub_to_usdt(
    amount_rub: int
) -> float:

    return round(
        amount_rub / USDT_TO_RUB,
        2
    )


# =========================================================
# PAYMENT INFO
# =========================================================

def get_payment_info(
    user_id: int
):

    balance = get_balance(
        user_id
    )

    return {
        "balance": balance,

        "rate": USDT_TO_RUB,

        "min_deposit_usdt":
            MIN_DEPOSIT_USDT,
    }
