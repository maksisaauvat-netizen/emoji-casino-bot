import os
import aiohttp

from database import process_payment


CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")

USDT_TO_RUB = 80
MIN_DEPOSIT_USDT = 1

CRYPTO_PAY_API = "https://pay.crypt.bot/api"


async def crypto_request(
    method: str,
    data: dict | None = None
):
    if not CRYPTO_PAY_TOKEN:
        raise RuntimeError("CRYPTO_PAY_TOKEN is not set")

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN,
        "Content-Type": "application/json",
    }

    url = f"{CRYPTO_PAY_API}/{method}"

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            url,
            headers=headers,
            json=data or {}
        ) as response:

            text = await response.text()

            print(
                "CRYPTO PAY RESPONSE:",
                method,
                response.status,
                text
            )

            if response.status != 200:
                raise RuntimeError(
                    f"Crypto Pay HTTP {response.status}: {text}"
                )

            try:
                result = await response.json()
            except Exception:
                raise RuntimeError(
                    f"Crypto Pay returned invalid JSON: {text}"
                )

            if not result.get("ok"):
                raise RuntimeError(
                    f"Crypto Pay API error: {result}"
                )

            return result.get("result")


# =========================================================
# GET APP
# =========================================================

async def get_crypto_app():
    return await crypto_request(
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
            f"Minimum deposit is {MIN_DEPOSIT_USDT} USDT"
        )

    result = await crypto_request(
        "createInvoice",
        {
            "currency_type": "crypto",
            "asset": "USDT",
            "amount": str(amount_usdt),
            "payload": str(user_id),
            "description": "Resonant Casino deposit",
        }
    )

    print(
        "CREATED INVOICE:",
        result
    )

    return {
        "invoice_id": int(result["invoice_id"]),
        "pay_url": (
            result.get("pay_url")
            or result.get("bot_invoice_url")
            or result.get("mini_app_invoice_url")
        ),
        "status": result.get("status"),
        "amount": result.get("amount"),
        "asset": result.get("asset"),
        "payload": result.get("payload"),
    }


# =========================================================
# GET INVOICE
# =========================================================

async def get_invoice(
    invoice_id: int
):
    result = await crypto_request(
        "getInvoices",
        {
            "invoice_ids": str(invoice_id)
        }
    )

    print(
        "GET INVOICE RESULT:",
        invoice_id,
        result
    )

    if not result:
        return None

    invoice = result[0]

    return invoice


# =========================================================
# CHECK PAYMENT
# =========================================================

async def check_invoice_paid(
    invoice_id: int
):
    invoice = await get_invoice(
        invoice_id
    )

    if not invoice:
        return False

    status = invoice.get("status")

    print(
        "INVOICE STATUS:",
        invoice_id,
        status
    )

    return status == "paid"


# =========================================================
# PROCESS PAID INVOICE
# =========================================================

async def process_paid_invoice(
    invoice_id: int
):
    invoice = await get_invoice(
        invoice_id
    )

    if not invoice:
        print(
            "PROCESS PAYMENT: invoice not found",
            invoice_id
        )
        return None

    status = invoice.get("status")

    print(
        "PROCESS PAYMENT STATUS:",
        invoice_id,
        status
    )

    if status != "paid":
        return None

    payload = invoice.get("payload")

    if payload is None:
        raise RuntimeError(
            "Paid invoice has no payload"
        )

    try:
        user_id = int(payload)
    except Exception:
        raise RuntimeError(
            f"Invalid invoice payload: {payload}"
        )

    try:
        amount_usdt = float(
            invoice.get("amount", 0)
        )
    except Exception:
        raise RuntimeError(
            f"Invalid invoice amount: {invoice.get('amount')}"
        )

    amount_rub = usdt_to_rub(
        amount_usdt
    )

    print(
        "PROCESSING PAID INVOICE:",
        {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "amount_usdt": amount_usdt,
            "amount_rub": amount_rub,
        }
    )

    result = process_payment(
        invoice_id=invoice_id,
        user_id=user_id,
        amount_usdt=amount_usdt,
        amount_rub=amount_rub
    )

    if result is None:
        print(
            "PAYMENT ALREADY PROCESSED:",
            invoice_id
        )
        return None

    print(
        "PAYMENT PROCESSED SUCCESSFULLY:",
        result
    )

    return result


# =========================================================
# CURRENCY
# =========================================================

def usdt_to_rub(
    amount_usdt: float
) -> int:

    return int(
        round(
            amount_usdt * USDT_TO_RUB
        )
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

async def get_payment_info(
    invoice_id: int
):
    invoice = await get_invoice(
        invoice_id
    )

    if not invoice:
        return None

    try:
        amount_usdt = float(
            invoice.get("amount", 0)
        )
    except Exception:
        amount_usdt = 0

    return {
        "invoice_id": int(
            invoice.get("invoice_id")
        ),
        "user_id": (
            int(invoice["payload"])
            if invoice.get("payload")
            else None
        ),
        "amount_usdt": amount_usdt,
        "amount_rub": usdt_to_rub(
            amount_usdt
        ),
        "status": invoice.get("status"),
        "asset": invoice.get("asset"),
        "created_at": invoice.get("created_at"),
        "paid_at": invoice.get("paid_at"),
    }
