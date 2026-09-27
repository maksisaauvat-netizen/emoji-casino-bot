import os
from typing import Optional

import aiohttp

from database import create_payment, mark_payment_paid, log_event

CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "").strip()
CRYPTOBOT_API = os.getenv("CRYPTOBOT_API", "https://pay.crypt.bot/api")
CRYPTOBOT_ASSET = os.getenv("CRYPTOBOT_ASSET", "USDT").strip().upper()
MIN_DEPOSIT_USD = float(os.getenv("MIN_DEPOSIT_USD", "0.10"))
MIN_WITHDRAW_USD = float(os.getenv("MIN_WITHDRAW_USD", "1.00"))


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
    if amount_usdt < MIN_DEPOSIT_USD:
        raise ValueError("Minimum deposit is $0.10")
    if not CRYPTOBOT_TOKEN:
        if os.getenv("REAL_ECONOMY", "true").lower() == "true":
            raise RuntimeError("CRYPTOBOT_TOKEN is required when REAL_ECONOMY=true")
        invoice_id = abs(hash((int(user_id), amount_usdt))) % 2_000_000_000
        return {"invoice_id": invoice_id, "status": "demo", "amount": str(amount_usdt), "asset": CRYPTOBOT_ASSET, "pay_url": ""}
    result = await _api("createInvoice", {
        "currency_type": "crypto",
        "asset": CRYPTOBOT_ASSET,
        "amount": f"{amount_usdt:.2f}",
        "description": f"Resonant deposit for {user_id}",
    })
    invoice = {
        "invoice_id": int(result["invoice_id"]),
        "status": result.get("status", "active"),
        "amount": result.get("amount", str(amount_usdt)),
        "asset": result.get("asset", CRYPTOBOT_ASSET),
        "pay_url": result.get("pay_url") or result.get("bot_invoice_url") or result.get("mini_app_invoice_url"),
    }
    create_payment(user_id, invoice["invoice_id"], amount_usdt, amount_usdt, invoice["status"])
    log_event(user_id, "deposit_invoice_created", f"invoice={invoice['invoice_id']} amount_usd={amount_usdt}")
    return invoice


async def get_transfers(spend_id: str) -> list[dict]:
    if not CRYPTOBOT_TOKEN:
        return []
    result = await _api("getTransfers", {"spend_id": str(spend_id), "count": 10})
    return result if isinstance(result, list) else []


async def get_invoice(invoice_id: int) -> Optional[dict]:
    if not CRYPTOBOT_TOKEN:
        return {"invoice_id": int(invoice_id), "status": "demo"}
    result = await _api("getInvoices", {"invoice_ids": str(int(invoice_id))})
    if isinstance(result, list):
        return result[0] if result else None
    if isinstance(result, dict):
        items = result.get("items", [])
        return items[0] if items else None
    return None


async def process_paid_invoice(invoice_id: int):
    invoice = await get_invoice(invoice_id)
    if not invoice or invoice.get("status") != "paid":
        return None
    result = mark_payment_paid(int(invoice_id))
    if result:
        log_event(int(result["user_id"]), "deposit_paid", f"invoice={invoice_id} amount_usd={result['amount_usd']}")
    return result


async def create_withdrawal_payout(user_id: int, amount_usd: float, spend_id: str, comment: str = "Resonant withdrawal") -> dict:
    amount_usd = round(float(amount_usd), 2)
    if amount_usd < MIN_WITHDRAW_USD:
        raise ValueError("Minimum withdrawal is $1.00")
    return await _api("transfer", {
        "user_id": int(user_id),
        "asset": CRYPTOBOT_ASSET,
        "amount": f"{amount_usd:.2f}",
        "spend_id": str(spend_id),
        "comment": comment[:255],
    })
