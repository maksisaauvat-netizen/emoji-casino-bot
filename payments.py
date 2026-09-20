import os
import aiohttp

from database import change_balance, get_balance


CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")

# ТЕСТОВЫЙ КУРС
USDT_TO_RUB = 80

# Минимальная сумма пополнения
MIN_DEPOSIT_USDT = 1

# Crypto Pay API
CRYPTO_PAY_API = "https://pay.crypt.bot/api"


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


async def get_crypto_app():
    return await crypto_request(
        "GET",
        "getMe"
    )


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
        "pay_url": invoice.get("pay_url"),
        "bot_invoice_url": invoice.get(
            "bot_invoice_url"
        ),
        "status": invoice.get("status"),
    }


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


async def check_invoice_paid(
    invoice_id: int
):
    invoice = await get_invoice(
        invoice_id
    )

    if invoice is None:
        return False

    return invoice.get("status") == "paid"


async def process_paid_invoice(
    invoice_id: int
):
    """
    Проверяет оплату инвойса.

    ВАЖНО:
    Защита от повторного зачисления
    будет добавлена в database.py
    перед запуском реальных платежей.
    """

    invoice = await get_invoice(
        invoice_id
    )

    if invoice is None:
        return None

    if invoice.get("status") != "paid":
        return None

    payload = invoice.get("payload")

    if not payload:
        return None

    try:
        user_id = int(payload)
    except (TypeError, ValueError):
        return None

    amount_usdt = float(
        invoice.get("amount", 0)
    )

    amount_rub = int(
        amount_usdt * USDT_TO_RUB
    )

    new_balance = change_balance(
        user_id,
        amount_rub
    )

    return {
        "user_id": user_id,
        "invoice_id": invoice_id,
        "amount_usdt": amount_usdt,
        "amount_rub": amount_rub,
        "balance": new_balance,
    }


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


def get_payment_info(
    user_id: int
):
    balance = get_balance(user_id)

    return {
        "balance": balance,
        "rate": USDT_TO_RUB,
        "min_deposit_usdt": MIN_DEPOSIT_USDT,
    }
