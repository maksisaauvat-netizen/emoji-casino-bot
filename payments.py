import os
from typing import Optional

import aiohttp

from database import create_payment, mark_payment_paid, log_event

CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "").strip()
CRYPTOBOT_API = os.getenv("CRYPTOBOT_API", "https://pay.crypt.bot/api")
USDT_TO_RUB = float(os.getenv("USDT_TO_RUB", "80"))


async def _api(method: str, payload: dict | None = None) -> dict:
    if not CRYPTOBOT_TOKEN:
        raise RuntimeError("CRYPTOBOT_TOKEN is not set")
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{CRYPTOBOT_API}/{method}", json=payload or {}, headers=headers) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400 or not data.get("ok"):
                raise RuntimeError(f"CryptoBot API error: {data}")
            return data["result"]


async def create_invoice(user_id: int, amount_usdt: float) -> dict:
    amount_usdt = round(float(amount_usdt), 2)
    if amount_usdt <= 0:
        raise ValueError("amount_usdt must be positive")
    if not CRYPTOBOT_TOKEN:
        # Development mode: never credits balance automatically; gives a clear placeholder.
        invoice_id = abs(hash((int(user_id), amount_usdt))) % 2_000_000_000
        return {"invoice_id": invoice_id, "status": "demo", "amount": str(amount_usdt), "asset": "USDT", "pay_url": ""}
    result = await _api("createInvoice", {"currency_type": "crypto", "asset": "USDT", "amount": str(amount_usdt), "description": f"Resonant deposit for {user_id}"})
    invoice = {
        "invoice_id": int(result["invoice_id"]),
        "status": result.get("status", "active"),
        "amount": result.get("amount", str(amount_usdt)),
        "asset": result.get("asset", "USDT"),
        "pay_url": result.get("pay_url") or result.get("bot_invoice_url") or result.get("mini_app_invoice_url"),
    }
    create_payment(user_id, invoice["invoice_id"], amount_usdt, int(round(amount_usdt * USDT_TO_RUB)), invoice["status"])
    log_event(user_id, "deposit_invoice_created", f"invoice={invoice['invoice_id']} amount_usdt={amount_usdt}")
    return invoice


async def get_invoice(invoice_id: int) -> Optional[dict]:
    if not CRYPTOBOT_TOKEN:
        return {"invoice_id": int(invoice_id), "status": "demo"}
    result = await _api("getInvoices", {"invoice_ids": str(int(invoice_id))})
    items = result.get("items", []) if isinstance(result, dict) else []
    return items[0] if items else None


async def process_paid_invoice(invoice_id: int):
    invoice = await get_invoice(invoice_id)
    if not invoice:
        return None
    if invoice.get("status") != "paid":
        return None
    result = mark_payment_paid(int(invoice_id))
    if result: log_event(int(result['user_id']), "deposit_paid", f"invoice={invoice_id} amount_rub={result['amount_rub']}")
    return result
