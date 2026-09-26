import hashlib
import hmac
import json
import os
import random
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton

from admin import is_admin
from database import (
    init_db, ensure_user, sync_profile, get_balance, change_balance, subtract_balance,
    get_user_stats, get_game_history, get_payment_history,
    get_withdrawal_history, create_withdrawal, record_game,
    get_audit_logs, get_all_users, get_all_payments, get_user_profile, get_user_ledger, get_ledger_activity, log_event,
    approve_withdrawal, reject_withdrawal,
)
from payments import create_invoice, process_paid_invoice, get_invoice


BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://example.com").rstrip("/")
WEBAPP_URL = os.getenv("WEBAPP_URL", BASE_URL)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", secrets.token_urlsafe(24))
WEBAPP_AUTH_MAX_AGE = int(os.getenv("WEBAPP_AUTH_MAX_AGE", "86400"))
REAL_ECONOMY = os.getenv("REAL_ECONOMY", "false").lower() == "true"
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = FastAPI(title="Resonant Casino")
# Images are kept in the project root (not in an assets/ directory).
ROOT_DIR = Path(__file__).resolve().parent

@app.get("/start.jpg")
@app.get("/assets/start.jpg")
async def start_image():
    candidates = [
        ROOT_DIR / "start.jpg",
        ROOT_DIR / "start.jpeg",
        ROOT_DIR / "IMG_2135.jpeg",
        ROOT_DIR / "IMG_2135.jpg",
    ]
    for path in candidates:
        if path.exists():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="Start image not found")

@app.get("/custom-emoji/{emoji_id}")
async def custom_emoji(emoji_id: str):
    """Proxy a Telegram custom emoji sticker so the Mini App can display premium emoji by ID."""
    import aiohttp
    from fastapi.responses import Response
    if not emoji_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid custom emoji id")
    api=f"https://api.telegram.org/bot{BOT_TOKEN}"
    timeout=aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(api + "/getCustomEmojiStickers", json={"custom_emoji_ids":[emoji_id]}) as r:
            data=await r.json()
        stickers=data.get("result") or []
        if not stickers:
            raise HTTPException(status_code=404, detail="Custom emoji not found")
        file_id=stickers[0].get("file_id")
        async with session.post(api + "/getFile", json={"file_id":file_id}) as r:
            fd=await r.json()
        file_path=(fd.get("result") or {}).get("file_path")
        if not file_path:
            raise HTTPException(status_code=404, detail="Custom emoji file not found")
        async with session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}") as r:
            if r.status != 200:
                raise HTTPException(status_code=502, detail="Unable to fetch custom emoji")
            body=await r.read()
            content_type=r.headers.get("Content-Type", "image/webp")
    return Response(content=body, media_type=content_type, headers={"Cache-Control":"public, max-age=86400"})

@app.get("/upgrader_spin.gif")
@app.get("/assets/upgrader_spin.gif")
async def upgrader_gif():
    candidates = [ROOT_DIR / "upgrader_spin.gif", ROOT_DIR / "upgrader.gif"]
    for path in candidates:
        if path.exists():
            return FileResponse(path, media_type="image/gif")
    raise HTTPException(status_code=404, detail="Upgrader GIF not found")
active_games: dict[int, dict] = {}

GAME_NAMES = {"slot", "x50", "crash", "dice", "mines", "upgrader", "slot_buy"}
RNG = random.SystemRandom()
UPGRADE_HOUSE_EDGE = float(os.getenv("UPGRADE_HOUSE_EDGE", "0.04"))
UPGRADE_GIF = Path(os.getenv("UPGRADE_GIF", str(ROOT_DIR / "upgrader_spin.gif")))
START_IMAGE = Path(os.getenv("START_IMAGE", str(ROOT_DIR / "start.jpg")))
HELP_USERNAME = os.getenv("HELP_USERNAME", "narotan7").lstrip("@")
# Premium custom emoji used as the currency/amount marker in bot messages.
M = "<tg-emoji emoji-id='5231449120635370684'>₽</tg-emoji>"
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")
upgrade_sessions: dict[int, dict] = {}
bot_sessions: dict[int, dict] = {}
bot_active_games: dict[int, dict] = {}



# ============================================================
# PROVABLY FAIR / ROUND HASH
# Commit hash is shown before the round. The server seed is revealed
# after the result so the player can independently verify it.
# ============================================================

def new_round(game: str, user_id: int) -> dict:
    seed = secrets.token_hex(32)
    return {
        "game": game,
        "nonce": 0,
        "server_seed": seed,
        "round_hash": hashlib.sha256(seed.encode()).hexdigest(),
        "client_seed": str(user_id),
    }

def pf_digest(state: dict, label: str, nonce: int = 0) -> bytes:
    raw = f"{state['server_seed']}:{state.get('client_seed','')}:{state['game']}:{label}:{nonce}".encode()
    return hashlib.sha256(raw).digest()

def pf_u64(state: dict, label: str, nonce: int = 0) -> int:
    return int.from_bytes(pf_digest(state, label, nonce)[:8], 'big')

def pf_unit(state: dict, label: str, nonce: int = 0) -> float:
    return pf_u64(state, label, nonce) / 2**64

def pf_index(state: dict, label: str, size: int, nonce: int = 0) -> int:
    return pf_u64(state, label, nonce) % size

def round_public(state: dict) -> dict:
    return {"round_hash": state["round_hash"], "hash_algorithm": "SHA-256", "verification": "SHA256(server_seed) == round_hash"}

def round_reveal(state: dict) -> dict:
    return {**round_public(state), "server_seed": state["server_seed"], "client_seed": state.get("client_seed", "")}


def validate_telegram_webapp_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Telegram initData is required")
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
        if time.time() - int(pairs.get("auth_date", "0")) > WEBAPP_AUTH_MAX_AGE:
            raise ValueError("expired initData")
        user = json.loads(pairs.get("user", "{}"))
        if not user.get("id"):
            raise ValueError("missing user")
        return user
    except Exception as e:
        raise HTTPException(401, f"Invalid Telegram initData: {e}")


class Auth(BaseModel):
    init_data: str = Field(min_length=1)


class StartGame(Auth):
    game: str
    stake_rub: int = Field(gt=0, le=1_000_000)
    option: Optional[str] = None
    mines_count: Optional[int] = Field(default=None, ge=2, le=24)
    upgrade_percent: Optional[float] = Field(default=None, ge=1, le=80)
    upgrade_multiplier: Optional[float] = Field(default=None, ge=1.01, le=100)


class Action(Auth):
    action: str


class Deposit(Auth):
    amount_usdt: float = Field(gt=0, le=100000)


class Withdraw(Auth):
    amount_rub: int = Field(gt=0, le=100000000)
    payout_details: str = Field(min_length=5, max_length=1000)


def bal(uid: int) -> int:
    ensure_user(uid)
    return int(get_balance(uid))


def finish(uid: int, game: str, stake: int, won: bool, multiplier: float,
           extra: Optional[dict] = None, payout_override: Optional[int] = None,
           round_state: Optional[dict] = None):
    payout = int(round(stake * multiplier)) if won else 0
    if payout_override is not None:
        payout = int(payout_override)
    if payout:
        change_balance(uid, payout)
    rh = round_state.get("round_hash", "") if round_state else ""
    ss = round_state.get("server_seed", "") if round_state else ""
    record_game(uid, game, stake, "win" if won else "loss",
                float(multiplier if won else 0), payout, rh, ss)
    log_event(uid, f"game_{game}", f"stake={stake} result={'win' if won else 'loss'} payout={payout}")
    active_games.pop(uid, None)
    result = {
        "status": "finished", "game": game, "stake": stake,
        "won": bool(won), "multiplier": float(multiplier if won else 0),
        "payout": payout, "balance": bal(uid),
    }
    if round_state:
        result.update(round_reveal(round_state))
    if extra:
        result.update(extra)
    return result


# ============================================================
# SLOT — 5x3, 16 paylines, wild, scatter/free spins.
# This is an original implementation inspired by the observed
# flow in the supplied recording, not a copy of Rakes source/assets.
# ============================================================

SLOT_SYMBOLS = ["10", "J", "Q", "K", "A", "CROWN", "REAPER", "SKULL", "WILD", "SCATTER"]

# Paytable for 3/4/5 consecutive symbols from the left.
SLOT_PAYS = {
    "10": {3: 2, 4: 5, 5: 12},
    "J": {3: 2, 4: 5, 5: 14},
    "Q": {3: 3, 4: 7, 5: 18},
    "K": {3: 4, 4: 10, 5: 24},
    "A": {3: 5, 4: 14, 5: 35},
    "CROWN": {3: 7, 4: 18, 5: 50},
    "REAPER": {3: 10, 4: 30, 5: 100},
    "SKULL": {3: 15, 4: 45, 5: 180},
}
SLOT_WEIGHTS = {
    "10": 18, "J": 17, "Q": 15, "K": 13, "A": 11,
    "CROWN": 7, "REAPER": 4, "SKULL": 2,
    "WILD": 2, "SCATTER": 1,
}

# 16 visible paylines. Values are row indexes for 5 reels.
PAYLINES = [
    [1,1,1,1,1], [0,0,0,0,0], [2,2,2,2,2],
    [0,1,2,1,0], [2,1,0,1,2], [0,0,1,2,2], [2,2,1,0,0],
    [1,0,0,0,1], [1,2,2,2,1], [0,1,1,1,0], [2,1,1,1,2],
    [0,1,0,1,0], [2,1,2,1,2], [1,0,1,0,1], [1,2,1,2,1],
    [0,2,1,0,2],
]


def weighted_symbol():
    names = list(SLOT_WEIGHTS)
    return RNG.choices(names, weights=[SLOT_WEIGHTS[x] for x in names], k=1)[0]


def slot_grid(round_state=None, spin_no=0):
    # rows x reels. Deterministic from the committed round seed when supplied.
    if not round_state:
        return [[weighted_symbol() for _ in range(5)] for _ in range(3)]
    names = list(SLOT_WEIGHTS)
    weights = [SLOT_WEIGHTS[x] for x in names]
    grid=[]
    for r in range(3):
        row=[]
        for c in range(5):
            total=sum(weights)
            n=pf_u64(round_state, f"slot:{spin_no}:{r}:{c}") % total
            acc=0
            chosen=names[-1]
            for name,w in zip(names,weights):
                acc += w
                if n < acc:
                    chosen=name; break
            row.append(chosen)
        grid.append(row)
    return grid


def slot_eval(grid):
    total_mult = 0.0
    wins = []
    for line_no, pattern in enumerate(PAYLINES, 1):
        cells = [grid[pattern[reel]][reel] for reel in range(5)]
        first = next((s for s in cells if s not in {"WILD"}), None)
        if first in (None, "SCATTER"):
            continue
        count = 0
        for s in cells:
            if s == first or s == "WILD":
                count += 1
            else:
                break
        if count >= 3 and first in SLOT_PAYS:
            mult = SLOT_PAYS[first][count]
            total_mult += mult / len(PAYLINES)
            wins.append({"line": line_no, "symbol": first, "count": count,
                         "multiplier": mult / len(PAYLINES)})
    scatters = sum(row.count("SCATTER") for row in grid)
    wilds = sum(row.count("WILD") for row in grid)
    scatter_mult = {3: 2, 4: 5, 5: 20}.get(scatters, 0)
    if scatter_mult:
        total_mult += scatter_mult
    return round(total_mult, 4), wins, scatters, wilds


def slot_spin(round_state=None, spin_no=0):
    grid = slot_grid(round_state, spin_no)
    mult, wins, scatters, wilds = slot_eval(grid)
    # Rarely award a 3-scatter trigger; the paytable itself remains visible.
    free_spins = 16 if scatters >= 3 else 0
    return grid, mult, wins, scatters, wilds, free_spins


# ============================================================
# X50 — observed flow: ~16s betting countdown, wheel spin,
# result among x2/x3/x5/x50. Client animation never decides result.
# ============================================================

X50 = ["x2", "x3", "x5", "x50", "bonus"]
X50_MULT = {"x2": 2, "x3": 3, "x5": 5, "x50": 50}
# Wheel outcome distribution. "bonus" opens Diamond. The RNG is server-side.
X50_WEIGHTS = [54, 30, 12, 1, 3]


# ============================================================
# CRASH
# ============================================================

def crash_point(round_state=None):
    u = pf_unit(round_state, "crash") if round_state else RNG.random()
    return round(max(1.0, min(1000.0, 0.98 / max(1e-12, 1-u))), 2)


def crash_current(state):
    elapsed = max(0, time.time() - state["started_at"])
    return round(1 + (2 ** (elapsed * 0.55) - 1), 2)


# ============================================================
# MINES
# ============================================================

def mines_multiplier(mine_count, opened):
    if opened <= 0:
        return 1.0
    safe = 25 - mine_count
    if opened > safe:
        return 0
    p = 1.0
    for i in range(opened):
        p *= (safe-i)/(25-i)
    return round(0.98/p, 4)


# ============================================================
# BLACKJACK
# ============================================================

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]

def deck(round_state=None):
    d = [r+s for s in SUITS for r in RANKS]
    if round_state:
        # Fisher-Yates with SHA-256-derived indices.
        for i in range(len(d)-1, 0, -1):
            j = pf_index(round_state, "bj-shuffle", len(d), i) % (i+1)
            d[i], d[j] = d[j], d[i]
    else:
        RNG.shuffle(d)
    return d


def cv(c):
    r=c[:-1]
    return 11 if r=="A" else 10 if r in {"J","Q","K"} else int(r)


def hv(hand):
    total=sum(cv(c) for c in hand)
    aces=sum(c[:-1]=="A" for c in hand)
    while total>21 and aces:
        total-=10; aces-=1
    return total


# ============================================================
# API
# ============================================================

@app.get("/")
async def root():
    return FileResponse(str(Path(__file__).with_name("index.html")))


@app.get("/api/config")
async def config():
    return {"games":[
        {"id":"slot","name":"SLOT","icon":"<tg-emoji emoji-id='5384509325429463744'>🎰</tg-emoji>"},
        {"id":"x50","name":"x50","icon":"<tg-emoji emoji-id='5382150533685469668'>🎡</tg-emoji>"},
        {"id":"crash","name":"CRASH","icon":"<tg-emoji emoji-id='5426896125745471534'>🚀</tg-emoji>"},
        {"id":"dice","name":"DICE","icon":"🎲"},
        {"id":"mines","name":"Mines","icon":"<tg-emoji emoji-id='5280569974404966639'>💣</tg-emoji>"},
        {"id":"upgrader","name":"Upgrader","icon":"⚡"},
    ], "real_economy": REAL_ECONOMY,
        "upgrader": {"preset_multipliers": [2,5,10], "preset_percentages": [35,70], "custom_percent_min": 1, "custom_percent_max": 80, "house_edge": UPGRADE_HOUSE_EDGE}}


@app.post("/api/me")
async def me(p: Auth):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"]); ensure_user(uid)
    return {"user":u,"balance":bal(uid),"stats":get_user_stats(uid),"is_admin":is_admin(uid)}


@app.post("/api/history")
async def history(p: Auth):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"]); ensure_user(uid)
    return {"games":get_game_history(uid),"payments":get_payment_history(uid),
            "withdrawals":get_withdrawal_history(uid,20),"stats":get_user_stats(uid)}



@app.post("/api/admin/overview")
async def admin_overview(p: Auth):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"])
    if not is_admin(uid): raise HTTPException(403,"Admin only")
    return {"users":get_all_users(100),"payments":get_all_payments(100),
            "withdrawals":__import__('database').get_pending_withdrawals(100),
            "logs":get_audit_logs(100)}

@app.post("/api/admin/adjust")
async def admin_adjust(payload: dict):
    u=validate_telegram_webapp_data(str(payload.get("init_data",""))); uid=int(u["id"])
    if not is_admin(uid): raise HTTPException(403,"Admin only")
    target=int(payload.get("user_id",0)); amount=int(payload.get("amount_rub",0))
    if not target or amount==0: raise HTTPException(400,"user_id and non-zero amount required")
    ensure_user(target); new_balance=change_balance(target,amount)
    log_event(uid,"admin_balance_adjust",f"target={target} amount={amount}")
    log_event(target,"admin_balance_changed",f"amount={amount}")
    return {"user_id":target,"balance":new_balance}

@app.post("/api/game/start")
async def start(p: StartGame):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"]); ensure_user(uid)
    game=p.game.lower().strip(); stake=int(p.stake_rub)
    if game not in GAME_NAMES: raise HTTPException(400,"Unknown game")
    if uid in active_games: raise HTTPException(409,"Сначала завершите текущую игру")
    if not subtract_balance(uid,stake): raise HTTPException(400,"Недостаточно средств")
    round_state=new_round(game, uid)

    if game=="slot_buy":
        price=stake*100
        # /api/game/start already charged stake; for a buy-bonus request, return it
        # and atomically charge the actual 100x price instead.
        change_balance(uid,stake)
        if not subtract_balance(uid,price):
            raise HTTPException(400,"Недостаточно средств для покупки бонуса")
        active_games[uid]={"type":"slot","stake":stake,"grid":None,"free_spins":16,
                           "total_payout":0,"paid_spin_mult":0,"free_win":0,"spin_no":0,
                           "round":round_state,"bonus_bought":True,"bonus_price":price}
        return {"status":"free_spins","game":"slot","grid":None,"multiplier":0,"wins":[],"scatters":0,"wilds":0,
                "free_spins":16,"free_total":0,"payout":0,"balance":bal(uid),"bonus_bought":True,"bonus_price":price,
                **round_public(round_state)}

    if game=="slot":
        grid,mult,wins,scatters,wilds,free=slot_spin(round_state, 0)
        if free:
            active_games[uid]={
                "type":"slot","stake":stake,"grid":grid,"free_spins":free,
                "total_payout":int(round(stake*mult)),
                "paid_spin_mult":mult,"free_win":0,"spin_no":1,"round":round_state
            }
            if mult:
                change_balance(uid,int(round(stake*mult)))
            return {"status":"free_spins","game":"slot","grid":grid,"multiplier":mult,
                    "wins":wins,"scatters":scatters,"wilds":wilds,"free_spins":free,
                    "payout":int(round(stake*mult)),"balance":bal(uid), **round_public(round_state)}
        return finish(uid,"slot",stake,mult>0,mult,
                       {"grid":grid,"wins":wins,"scatters":scatters,"wilds":wilds}, round_state=round_state)

    if game=="upgrader":
        # Either choose a target multiplier (x2/x5/x10) or a win percentage (1-80%).
        pct=p.upgrade_percent
        mult=p.upgrade_multiplier
        if mult is not None and pct is not None:
            change_balance(uid,stake); raise HTTPException(400,"Выберите коэффициент ИЛИ процент")
        if mult is not None:
            # House edge is applied to the fair inverse probability.
            chance=min(0.80, max(0.01, (1.0-UPGRADE_HOUSE_EDGE)/float(mult)))
            mode=f"x{mult:g}"
        elif pct is not None:
            chance=float(pct)/100.0
            mult=(1.0-UPGRADE_HOUSE_EDGE)/chance
            mode=f"{pct:g}%"
        else:
            change_balance(uid,stake); raise HTTPException(400,"Укажите коэффициент или процент")
        u=pf_unit(round_state,"upgrade")
        won=u<chance
        payout=int(round(stake*mult)) if won else 0
        result=finish(uid,"upgrader",stake,won,mult if won else 0,
                      {"mode":mode,"chance_percent":round(chance*100,2),"roll_percent":round(u*100,4)},
                      round_state=round_state)
        result["upgrade_target_multiplier"]=round(mult,4)
        return result

    if game=="x50":
        opt=(p.option or "").lower()
        if opt not in X50:
            change_balance(uid,stake); raise HTTPException(400,"Выберите x2, x3, x5, x50 или Diamond")
        n=pf_u64(round_state,"x50") % sum(X50_WEIGHTS)
        acc=0; result=X50[-1]
        for name,w in zip(X50,X50_WEIGHTS):
            acc+=w
            if n<acc: result=name; break
        active_games[uid]={"type":"x50","stake":stake,"selected":opt,"result":result,
                           "started_at":time.time(),"round_seconds":16,"round":round_state}
        return {"status":"playing","game":"x50","selected":opt,"round_seconds":16,
                "balance":bal(uid), **round_public(round_state)}

    if game=="crash":
        active_games[uid]={"type":"crash","stake":stake,"crash_point":crash_point(round_state),
                           "started_at":time.time(),"round":round_state}
        return {"status":"playing","game":"crash","stake":stake,
                "started_at":active_games[uid]["started_at"],"speed":0.55,"balance":bal(uid), **round_public(round_state)}

    if game=="dice":
        mode=(p.option or "one").lower()
        if mode not in {"one","two"}:
            change_balance(uid,stake); raise HTTPException(400,"Режим DICE: one или two")
        bet=(p.mines_count and str(p.mines_count)) or ""
        # option format: one:lt3 / one:gt3 / two:eq7 / two:lt7 / two:gt7
        parts=mode.split(":")
        if len(parts)==2:
            mode,bet=parts
        else:
            change_balance(uid,stake); raise HTTPException(400,"Выберите условие DICE")
        d1=1+pf_index(round_state,"dice1",6)
        d2=1+pf_index(round_state,"dice2",6)
        total=d1 if mode=="one" else d1+d2
        won=(total<3 if bet=="lt3" else total>3 if bet=="gt3" else total==7 if bet=="eq7" else total<7 if bet=="lt7" else total>7 if bet=="gt7" else False)
        mult=5.0 if bet=="eq7" else 1.85
        return finish(uid,"dice",stake,won,mult if won else 0,{"mode":mode,"bet":bet,"dice":[d1,d2],"total":total},round_state=round_state)

    if game=="blackjack":
        d=deck(round_state); player=[d.pop(),d.pop()]; dealer=[d.pop(),d.pop()]
        active_games[uid]={"type":"blackjack","stake":stake,"deck":d,
                           "player":player,"dealer":dealer,"round":round_state}
        pv,dv=hv(player),hv(dealer)
        if pv==21:
            if dv==21:
                return finish(uid,"blackjack",stake,False,0,
                    {"push":True,"player":player,"dealer":dealer,
                     "player_value":pv,"dealer_value":dv,"payout":stake},
                    payout_override=stake)
            return finish(uid,"blackjack",stake,True,2.5,
                    {"blackjack":True,"player":player,"dealer":dealer,
                     "player_value":pv,"dealer_value":dv}, round_state=round_state)
        return {"status":"playing","game":"blackjack","player":player,
                "dealer":[dealer[0],"🂠"],"player_value":pv,"balance":bal(uid), **round_public(round_state)}

    if game=="mines":
        mc=int(p.mines_count or 5)
        if not 2<=mc<=24:
            change_balance(uid,stake); raise HTTPException(400,"Количество мин: 2–24")
        pool=list(range(25))
        for i in range(len(pool)-1, 0, -1):
            j=pf_index(round_state, "mines-shuffle", len(pool), i)%(i+1)
            pool[i],pool[j]=pool[j],pool[i]
        mines=pool[:mc]
        active_games[uid]={"type":"mines","stake":stake,"mines":mines,
                           "opened":[],"multiplier":1.0,"round":round_state}
        return {"status":"playing","game":"mines","stake":stake,"mines_count":mc,
                "opened":[],"multiplier":1.0,"balance":bal(uid), **round_public(round_state)}


@app.post("/api/game/action")
async def action(p: Action):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"]); ensure_user(uid)
    g=active_games.get(uid)
    if not g: raise HTTPException(409,"Нет активной игры")
    a=p.action

    if g["type"]=="slot":
        if a!="spin":
            raise HTTPException(400,"Нажмите spin")
        if g["free_spins"]<=0:
            raise HTTPException(409,"Free spins закончились")
        grid,mult,wins,scatters,wilds,more=slot_spin(g["round"], g.get("spin_no",1))
        g["spin_no"]=g.get("spin_no",1)+1
        g["free_spins"]-=1
        payout=int(round(g["stake"]*mult))
        g["free_win"]+=payout
        if payout: change_balance(uid,payout, f"game_payout:{game}" if "game" in locals() else "game_payout")
        if more: g["free_spins"]+=4
        if g["free_spins"]==0:
            total=g["total_payout"]+g["free_win"]
            record_game(uid,"slot",g["stake"],"win" if total else "loss",
                        total/g["stake"] if g["stake"] else 0,total,
                        g["round"]["round_hash"],g["round"]["server_seed"])
            active_games.pop(uid,None)
            return {"status":"finished","game":"slot","grid":grid,"multiplier":mult,
                    "wins":wins,"scatters":scatters,"wilds":wilds,
                    "free_spins":0,"free_total":g["free_win"],
                    "payout":total,"balance":bal(uid), **round_reveal(g["round"])}
        return {"status":"free_spins","game":"slot","grid":grid,"multiplier":mult,
                "wins":wins,"scatters":scatters,"wilds":wilds,
                "free_spins":g["free_spins"],"free_total":g["free_win"],
                "balance":bal(uid), **round_public(g["round"])}

    if g["type"]=="x50":
        if a!="reveal": raise HTTPException(400,"Раунд ещё не завершён")
        if time.time()-g["started_at"] < g["round_seconds"]:
            raise HTTPException(409,"Раунд ещё идёт")
        result=g["result"]
        if result=="bonus":
            g["diamond_pending"]=True
            return {"status":"diamond","game":"x50","selected":g["selected"],"result":"bonus",
                    "cells":[5,5,5,7,7,7,10,10,25],"balance":bal(uid), **round_public(g["round"])}
        won=result==g["selected"]
        return finish(uid,"x50",g["stake"],won,X50_MULT[result] if won else 0,
                      {"selected":g["selected"],"result":result,"round_seconds":g["round_seconds"]},
                      round_state=g["round"])

    if g["type"]=="x50" and g.get("diamond_pending"):
        if not a.startswith("diamond:"): raise HTTPException(400,"Выберите ячейку Diamond")
        try: idx=int(a.split(":",1)[1])
        except: raise HTTPException(400,"Некорректная ячейка")
        cells=[5,5,5,7,7,7,10,10,25]
        if not 0<=idx<len(cells): raise HTTPException(400,"Некорректная ячейка")
        mult=cells[idx]
        # Diamond only pays a bonus bet; a non-bonus selection loses this round.
        won=g["selected"]=="bonus"
        return finish(uid,"x50",g["stake"],won,mult if won else 0,
                      {"selected":g["selected"],"result":"bonus","diamond_multiplier":mult,"diamond_index":idx},
                      round_state=g["round"])

    if g["type"]=="crash":
        if a!="cashout": raise HTTPException(400,"Неизвестное действие")
        cur=crash_current(g); cp=g["crash_point"]
        if cur>=cp:
            return finish(uid,"crash",g["stake"],False,0,{"crash_point":cp,"at":cp}, round_state=g["round"])
        return finish(uid,"crash",g["stake"],True,cur,{"crash_point":cp,"at":cur}, round_state=g["round"])

    if g["type"]=="mines":
        if a=="cashout":
            if not g["opened"]: raise HTTPException(400,"Откройте клетку")
            return finish(uid,"mines",g["stake"],True,g["multiplier"],
                          {"opened":g["opened"],"mines":g["mines"]}, round_state=g["round"])
        if not a.startswith("open:"): raise HTTPException(400,"Неизвестное действие")
        try:i=int(a.split(":",1)[1])
        except: raise HTTPException(400,"Некорректная клетка")
        if not 0<=i<25 or i in g["opened"]: raise HTTPException(400,"Некорректная клетка")
        if i in g["mines"]:
            return finish(uid,"mines",g["stake"],False,0,
                          {"hit_mine":i,"opened":g["opened"],"mines":g["mines"]}, round_state=g["round"])
        g["opened"].append(i); g["multiplier"]=mines_multiplier(len(g["mines"]),len(g["opened"]))
        if len(g["opened"])>=25-len(g["mines"]):
            return finish(uid,"mines",g["stake"],True,g["multiplier"],
                          {"opened":g["opened"],"mines":g["mines"]}, round_state=g["round"])
        return {"status":"playing","game":"mines","opened":g["opened"],
                "multiplier":g["multiplier"],
                "payout":int(round(g["stake"]*g["multiplier"])),"balance":bal(uid)}

    if g["type"]=="blackjack":
        if a=="hit":
            g["player"].append(g["deck"].pop()); pv=hv(g["player"])
            if pv>21:
                return finish(uid,"blackjack",g["stake"],False,0,
                    {"player":g["player"],"dealer":g["dealer"],
                     "player_value":pv,"dealer_value":hv(g["dealer"])}, round_state=g["round"])
            return {"status":"playing","game":"blackjack","player":g["player"],
                    "dealer":[g["dealer"][0],"🂠"],"player_value":pv,"balance":bal(uid)}
        if a=="stand":
            while hv(g["dealer"])<17:g["dealer"].append(g["deck"].pop())
            pv,dv=hv(g["player"]),hv(g["dealer"])
            if dv>21 or pv>dv:
                return finish(uid,"blackjack",g["stake"],True,2,
                    {"player":g["player"],"dealer":g["dealer"],
                     "player_value":pv,"dealer_value":dv})
            if pv==dv:
                return finish(uid,"blackjack",g["stake"],False,0,
                    {"push":True,"player":g["player"],"dealer":g["dealer"],
                     "player_value":pv,"dealer_value":dv,"payout":g["stake"]},
                    payout_override=g["stake"])
            return finish(uid,"blackjack",g["stake"],False,0,
                {"player":g["player"],"dealer":g["dealer"],
                 "player_value":pv,"dealer_value":dv})
        raise HTTPException(400,"Неизвестное действие")

    raise HTTPException(400,"Игра не поддерживает действие")


@app.post("/api/deposit")
async def deposit(p: Deposit):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"])
    return {"invoice":await create_invoice(uid,float(p.amount_usdt))}


@app.post("/api/deposit/{invoice_id}/check")
async def deposit_check(invoice_id:int,p:Auth):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"])
    inv=await get_invoice(invoice_id)
    if not inv: raise HTTPException(404,"Invoice not found")
    result=await process_paid_invoice(invoice_id)
    return {"processed":result is not None,"invoice":await get_invoice(invoice_id),"balance":bal(uid)}


@app.post("/api/withdraw")
async def withdraw(p: Withdraw):
    u=validate_telegram_webapp_data(p.init_data); uid=int(u["id"])
    result=create_withdrawal(uid,p.amount_rub,p.payout_details)
    if result is None: raise HTTPException(400,"Unable to create withdrawal")
    return {"withdrawal":result,"balance":bal(uid)}


def _menu_keyboard(user_id: int):
    rows = [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile")],
        [InlineKeyboardButton(text="💰 Кошелек", callback_data="menu:wallet"),
         InlineKeyboardButton(text="🎁 Бонусы", callback_data="menu:bonuses")],
        [InlineKeyboardButton(text="🎮 Играть", callback_data="menu:games")],
        [InlineKeyboardButton(text="🆘 Помощь", url=f"https://t.me/{HELP_USERNAME}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _bottom_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤡 Play & Win")],
            [KeyboardButton(text="🧳 Кошелёк"), KeyboardButton(text="💵 Профиль")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def _profile_keyboard(user_id: int):
    rows = [
        [InlineKeyboardButton(text="История игр", callback_data="profile:games"),
         InlineKeyboardButton(text="Реферальная система", callback_data="profile:ref")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton(text="ADMIN PANEL", callback_data="admin:home")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _wallet_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить", callback_data="wallet:deposit"),
         InlineKeyboardButton(text="Вывод", callback_data="wallet:withdraw")],
        [InlineKeyboardButton(text="История", callback_data="wallet:history")],
        [InlineKeyboardButton(text="🎮 Играть", callback_data="menu:games"),
         InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")],
    ])

def _games_keyboard():
    # Telegram bot mirrors the supplied reference: games live in the bot,
    # while the Mini App button is intentionally not shown here.
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Mines", callback_data="refgame:mines"), InlineKeyboardButton(text="🗼 Tower", callback_data="refgame:tower"), InlineKeyboardButton(text="✊ КНБ", callback_data="refgame:knb")],
        [InlineKeyboardButton(text="🔢 Keno", callback_data="refgame:keno"), InlineKeyboardButton(text="🔻 Plinko", callback_data="refgame:plinko"), InlineKeyboardButton(text="⚖️ Even", callback_data="refgame:even")],
        [InlineKeyboardButton(text="🎡 Сектор", callback_data="refgame:sector"), InlineKeyboardButton(text="⚔️ Дуэль", callback_data="refgame:duel")],
        [InlineKeyboardButton(text="↕️ Больше-Меньше", callback_data="refgame:higher_lower")],
        [InlineKeyboardButton(text="🏹 Hi-Lo", callback_data="refgame:hilo"), InlineKeyboardButton(text="🥅 Пенальти", callback_data="refgame:penalty")],
        [InlineKeyboardButton(text="🃏 Blackjack", callback_data="refgame:blackjack"), InlineKeyboardButton(text="🃏 Baccarat", callback_data="refgame:baccarat")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")],
    ])

async def _edit_menu(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup):
    try:
        await callback.message.edit_caption(caption=text, reply_markup=markup)
    except Exception:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            await callback.message.answer(text, reply_markup=markup)

def _profile_text(uid: int) -> str:
    s=get_user_stats(uid); b=get_balance(uid); p=get_user_profile(uid) or {}
    username=p.get("username") or "—"
    app_id=p.get("id") or "—"
    return (
        "╭────────────────────╮\n"
        "       👤 | PROFILE\n"
        "╰────────────────────╯\n\n"
        f"👤 Username: <b>@{username}</b>\n"
        f"🆔 Telegram ID: <code>{uid}</code>\n"
        f"🗃 App User ID: <code>{app_id}</code>\n\n"
        f"💰 BALANCE: <b>{b:,} ₽</b>\n\n"
        f"🎮 ИГРЫ: <b>{s['games']}</b>\n"
        f"🏆 ПОБЕДЫ: <b>{s['wins']}</b>\n"
        f"❌ ПОРАЖЕНИЯ: <b>{s['losses']}</b>\n"
        f"📈 WINRATE: <b>{s['winrate']}%</b>\n\n"
        f"💵 СТАВКИ: <b>{s['turnover']:,} ₽</b>\n"
        f"🏆 ВЫИГРАНО: <b>{s['payouts']:,} ₽</b>\n"
        f"🔥 MAX WIN: <b>{s['max_win']:,} ₽</b>"
    ).replace(",", " ")

def _wallet_text(uid: int) -> str:
    b=get_balance(uid); s=get_user_stats(uid)
    return (
        "╭────────────────────╮\n"
        "       <tg-emoji emoji-id='5278467510604160626'>💰</tg-emoji> | WALLET\n"
        "╰────────────────────╯\n\n"
        f"Баланс: <b>{b:,} {M}</b>\n"
        f"Оборот: <b>{s['turnover']:,} {M}</b>\n\n"
        "Пополнение и вывод доступны через меню ниже."
    ).replace(",", " ")

def _games_text() -> str:
    return ("╭────────────────────╮\n       🎮 | PLAY & WIN\n╰────────────────────╯\n\n"
            "🎯 Игра с Telegram Emojis — бросает бот\n\n"
            "💣 Mines — открывайте безопасные клетки\n"
            "🗼 Tower — поднимайтесь по этажам\n"
            "✊ КНБ — камень, ножницы, бумага\n"
            "🔢 Keno — выбирайте числа\n"
            "🔻 Plinko — больше значение → больше коэффициент\n"
            "⚖️ Even — чётное или нечётное\n"
            "🎡 Сектор — три сектора по два исхода\n"
            "⚔️ Дуэль — выбор стороны\n"
            "↕️ Больше-Меньше — угадайте направление\n"
            "🏹 Hi-Lo — угадайте следующую карту\n"
            "🥅 Пенальти — забейте гол\n"
            "🃏 Blackjack / Baccarat — карточные игры\n\n"
            "Выберите игру:")

@dp.message(CommandStart())
async def start_handler(message: Message):
    if not message.from_user: return
    uid=message.from_user.id
    sync_profile(uid, message.from_user.username); log_event(uid, "bot_start")
    caption=(
        "╔══════════════════════╗\n"
        "      <tg-emoji emoji-id='5384509325429463744'>🎰</tg-emoji> RESONANT\n"
        "        CASINO\n"
        "╚══════════════════════╝"
    )
    if START_IMAGE.exists():
        await message.answer_photo(FSInputFile(START_IMAGE), caption=caption, reply_markup=_menu_keyboard(uid))
        await message.answer("Выберите раздел:", reply_markup=_bottom_keyboard())
    else:
        await message.answer(caption, reply_markup=_menu_keyboard(uid))
        await message.answer("Выберите раздел:", reply_markup=_bottom_keyboard())

@dp.callback_query(lambda c: c.data and c.data.startswith("menu:"))
async def menu_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; ensure_user(uid)
    parts=callback.data.split(":")
    action=parts[1]
    if action=="adjust":
        bot_sessions[uid]={"step":"admin_target"}
        await callback.message.answer("Введите Telegram ID пользователя.")
        await callback.answer(); return
    if action=="home":
        await _edit_menu(callback, "╔══════════════════════╗\n      <tg-emoji emoji-id='5384509325429463744'>🎰</tg-emoji> RESONANT\n        CASINO\n╚══════════════════════╝", _menu_keyboard(uid))
    elif action=="profile":
        await _edit_menu(callback, _profile_text(uid), _profile_keyboard(uid))
    elif action=="wallet":
        await _edit_menu(callback, _wallet_text(uid), _wallet_keyboard())
    elif action=="bonuses":
        await _edit_menu(callback,
            "╭────────────────────╮\n       🎁 | BONUS\n╰────────────────────╯\n\n"
            "Бонусы и реферальная система доступны в приложении.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")]
            ]))
    elif action=="games":
        await _edit_menu(callback, _games_text(), _games_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("profile:"))
async def profile_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; action=callback.data.split(":",1)[1]
    if action=="games":
        rows=get_game_history(uid,10)
        text="╭────────────────────╮\n       <tg-emoji emoji-id='5426896538062332283'>🎮</tg-emoji> | ИСТОРИЯ ИГР\n╰────────────────────╯\n\n"
        text += "\n".join(f"#{r['id']} {r['game']} · {r['stake']} ₽ · {r['result']} · {r['payout']} ₽" for r in rows) or "История пуста."
    else:
        code=f"ref_{uid}"
        link=f"https://t.me/{BOT_USERNAME}?start={code}" if BOT_USERNAME else f"Код: {code}"
        text=f"╭────────────────────╮\n       🤝 | REFERRAL\n╰────────────────────╯\n\nВаша реферальная ссылка:\n<code>{link}</code>"
    await _edit_menu(callback,text,_profile_keyboard(uid)); await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("wallet:"))
async def wallet_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; action=callback.data.split(":",1)[1]
    if action=="history":
        p=get_payment_history(uid,10); w=get_withdrawal_history(uid,10)
        text="╭────────────────────╮\n       📜 | ИСТОРИЯ\n╰────────────────────╯\n\n"
        text+="Пополнения:\n"+("\n".join(f"#{x['id']} {x['amount_rub']} ₽ · {x['status']}" for x in p) or "—")
        text+="\n\nВыводы:\n"+("\n".join(f"#{x['id']} {x['amount_rub']} ₽ · {x['status']}" for x in w) or "—")
        await _edit_menu(callback,text,_wallet_keyboard())
    elif action=="deposit":
        bot_sessions[uid]={"step":"deposit_amount"}
        await callback.message.answer("Введите сумму пополнения в USDT. После этого бот создаст Crypto Pay invoice.")
    elif action=="withdraw":
        bot_sessions[uid]={"step":"withdraw_amount"}
        await callback.message.answer("Введите сумму вывода в ₽.")
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("game:"))
async def game_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; g=callback.data.split(":",1)[1]; ensure_user(uid)
    if g=="slot":
        bot_sessions[uid]={"step":"slot_amount"}
        await callback.message.answer("╭────────────────────╮\n       <tg-emoji emoji-id='5384509325429463744'>🎰</tg-emoji> SLOTS\n╰────────────────────╯\n\n💎 Ставка:\n\nМинимальная ставка: <b>10 ₽</b>\nМаксимальная ставка: <b>5000 ₽</b>\n\nОтправьте сумму одним сообщением.")
    elif g=="mines":
        bot_sessions[uid]={"step":"mines_amount"}
        await callback.message.answer("╭────────────────────╮\n       <tg-emoji emoji-id='5280569974404966639'>💣</tg-emoji> MINES\n╰────────────────────╯\n\n💎 ВВЕДИТЕ СТАВКУ\n\nМинимальная ставка: <b>10 ₽</b>\nМаксимальная ставка: <b>5000 ₽</b>\n\nОтправьте сумму одним сообщением.\n\nНапример: <b>10</b>")
    elif g=="dice":
        await callback.message.answer("╭────────────────────╮\n       🎲 DICE\n╰────────────────────╯\n\nВыберите режим:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Один бросок",callback_data="dice:one")],[InlineKeyboardButton(text="Два броска",callback_data="dice:two")],[InlineKeyboardButton(text="⬅️ Игры",callback_data="menu:games")]]))
    elif g=="upgrader":
        upgrade_sessions[uid]={"step":"amount"}; await callback.message.answer("⚡ UPGRADER\nВведите сумму ставки (10–5000 ₽).")
    elif g in {"crash","x50"}:
        game_title = "<tg-emoji emoji-id='5426896125745471534'>🚀</tg-emoji> CRASH" if g == "crash" else "<tg-emoji emoji-id='5382150533685469668'>🎡</tg-emoji> x50"
        await callback.message.answer(f"╭────────────────────╮\n       {game_title}\n╰────────────────────╯\n\nЭтот режим доступен в приложении.\nДля запуска откройте его через кнопку «🎰 • Играть в приложении» в разделе GAMES.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Игры",callback_data="menu:games")]]))
    else:
        await callback.message.answer("Неизвестная игра.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Игры",callback_data="menu:games")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("dice:"))
async def dice_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; mode=callback.data.split(":",1)[1]
    if mode not in {"one","two"}: await callback.answer("Неизвестный режим",show_alert=True); return
    bot_sessions[uid]={"step":"dice_bet_type","mode":mode}
    rows=([[InlineKeyboardButton(text="x1.85 | Меньше 3",callback_data="dicebet:one:lt3")],[InlineKeyboardButton(text="x1.85 | Больше 3",callback_data="dicebet:one:gt3")]] if mode=="one" else [[InlineKeyboardButton(text="x5.00 | Равно 7",callback_data="dicebet:two:eq7")],[InlineKeyboardButton(text="x1.85 | Меньше 7",callback_data="dicebet:two:lt7")],[InlineKeyboardButton(text="x1.85 | Больше 7",callback_data="dicebet:two:gt7")]])
    rows.append([InlineKeyboardButton(text="⬅️ DICE",callback_data="game:dice")]); await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("dicebet:"))
async def dice_bet_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; _,mode,bet=callback.data.split(":",2); bot_sessions[uid]={"step":"dice_amount","mode":mode,"bet":bet}
    await callback.message.answer("🎲 Введите сумму ставки от <b>10</b> до <b>5000 ₽</b>."); await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("slotconfirm:"))
async def slot_confirm(callback: CallbackQuery):
    uid=callback.from_user.id; s=bot_sessions.get(uid,{})
    if s.get("step")!="slot_confirm": await callback.answer("Сессия не найдена",show_alert=True); return
    if callback.data.endswith(":cancel"): bot_sessions.pop(uid,None); await callback.message.answer("Ставка отменена."); await callback.answer(); return
    stake=int(s["stake"])
    if not subtract_balance(uid,stake): bot_sessions.pop(uid,None); await callback.message.answer("Недостаточно средств на балансе."); await callback.answer(); return
    rs=new_round("slots_bot",uid); roll=pf_unit(rs,"slot")
    if roll<0.003: combo="7️⃣7️⃣7️⃣"; mult=50.0
    elif roll<0.013: combo="🍋🍋🍋"; mult=10.0
    elif roll<0.093: sym=RNG.choice(["🍒","🔔","💎","🍀"]); combo=sym*3; mult=3.5
    elif roll<0.343: sym=RNG.choice(["🍒","🔔","💎","🍀"]); combo=sym+sym+RNG.choice(["🍋","7️⃣","⭐"]); mult=1.85
    else: combo=RNG.choice(["🍋⭐🍒","🔔🍋💎","🍒7️⃣🔔","⭐🍀🍋"]); mult=0.0
    payout=int(round(stake*mult)) if mult else 0
    if payout: change_balance(uid,payout, f"game_payout:{game}" if "game" in locals() else "game_payout")
    record_game(uid,"slots_bot",stake,"win" if payout else "loss",mult,payout,rs["round_hash"],rs["server_seed"]); log_event(uid,"game_slots_bot",f"stake={stake} combo={combo} payout={payout}"); bot_sessions.pop(uid,None)
    result=f"🎉 Выигрыш: <b>{payout} ₽</b>" if payout else "<tg-emoji emoji-id='5454350746407419714'>❌</tg-emoji> Проигрыш"
    await callback.message.answer(f"╭────────────────────╮\n       <tg-emoji emoji-id='5384509325429463744'>🎰</tg-emoji> SLOTS\n╰────────────────────╯\n\n💎 Ставка: <b>{stake} ₽</b>\n\n<code>{combo}</code>\n\n{result}\n\nХэш раунда: <code>{rs['round_hash']}</code>\nServer seed: <code>{rs['server_seed']}</code>\n\n🍋🍋🍋 — ×10\n7️⃣7️⃣7️⃣ — ×50\n3 одинаковых — ×3.5\n2 одинаковых — ×1.85\nДругие комбинации — проигрыш.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎰 Ещё раз",callback_data="game:slot")],[InlineKeyboardButton(text="⬅️ Игры",callback_data="menu:games")]])); await callback.answer()

def mines_bot_keyboard(opened):
    rows=[]
    for r in range(5): rows.append([InlineKeyboardButton(text="💎" if i in opened else "·",callback_data=f"bmines:cell:{i}") for i in range(r*5,r*5+5)])
    rows.append([InlineKeyboardButton(text="💰 Забрать",callback_data="bmines:cashout")]); return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(lambda c: c.data and c.data.startswith("mines:"))
async def mines_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id; parts=callback.data.split(":")
    if parts[1]=="count":
        s=bot_sessions.get(uid,{})
        if s.get("step")!="mines_count": await callback.answer("Сессия не найдена",show_alert=True); return
        s.update({"step":"mines_confirm","mines_count":int(parts[2])})
        await callback.message.answer(f"<tg-emoji emoji-id='5280569974404966639'>💣</tg-emoji> MINES\n\nСтавка: <b>{s['stake']} ₽</b>\nБомб: <b>{s['mines_count']}</b>\n\nПодтвердить ставку?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подтвердить ставку",callback_data="minesconfirm:yes"),InlineKeyboardButton(text="Отмена",callback_data="minesconfirm:no")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("minesconfirm:"))
async def mines_confirm(callback: CallbackQuery):
    uid=callback.from_user.id; s=bot_sessions.get(uid,{})
    if s.get("step")!="mines_confirm": await callback.answer("Сессия не найдена",show_alert=True); return
    if callback.data.endswith(":no"): bot_sessions.pop(uid,None); await callback.message.answer("Ставка отменена."); await callback.answer(); return
    stake=int(s["stake"]); mc=int(s["mines_count"])
    if not subtract_balance(uid,stake): bot_sessions.pop(uid,None); await callback.message.answer("Недостаточно средств на балансе."); await callback.answer(); return
    rs=new_round("mines_bot",uid); pool=list(range(25))
    for i in range(24,0,-1): j=pf_index(rs,"mines",25,i)%(i+1); pool[i],pool[j]=pool[j],pool[i]
    bot_active_games[uid]={"type":"mines","stake":stake,"mines":pool[:mc],"opened":[],"multiplier":1.0,"round":rs}; bot_sessions.pop(uid,None)
    await callback.message.answer("╭────────────────────╮\n       <tg-emoji emoji-id='5280569974404966639'>💣</tg-emoji> MINES\n╰────────────────────╯\n\nОткройте клетку:",reply_markup=mines_bot_keyboard([])); await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("bmines:"))
async def bot_mines_play(callback: CallbackQuery):
    uid=callback.from_user.id; g=bot_active_games.get(uid)
    if not g: await callback.answer("Нет активной игры",show_alert=True); return
    action=callback.data.split(":",1)[1]
    if action=="cashout":
        if not g["opened"]: await callback.answer("Сначала откройте клетку",show_alert=True); return
        payout=int(round(g["stake"]*g["multiplier"])); change_balance(uid,payout, f"game_payout:{game}" if "game" in locals() else "game_payout"); rs=g["round"]
        record_game(uid,"mines_bot",g["stake"],"win",g["multiplier"],payout,rs["round_hash"],rs["server_seed"]); log_event(uid,"game_mines_bot",f"stake={g['stake']} payout={payout}"); bot_active_games.pop(uid,None)
        await callback.message.answer(f"🎉 Вы забрали <b>{payout} ₽</b> · x{g['multiplier']:.2f}\nХэш раунда: <code>{rs['round_hash']}</code>\nServer seed: <code>{rs['server_seed']}</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣 Ещё раз",callback_data="game:mines")]])); await callback.answer(); return
    idx=int(action.split(":",1)[1])
    if idx in g["opened"]: await callback.answer("Клетка уже открыта",show_alert=True); return
    rs=g["round"]
    if idx in g["mines"]:
        record_game(uid,"mines_bot",g["stake"],"loss",0,0,rs["round_hash"],rs["server_seed"]); log_event(uid,"game_mines_bot",f"stake={g['stake']} mine={idx}"); bot_active_games.pop(uid,None)
        await callback.message.answer(f"💥 Мина! Вы проиграли <b>{g['stake']} ₽</b>.\nХэш раунда: <code>{rs['round_hash']}</code>\nServer seed: <code>{rs['server_seed']}</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣 Ещё раз",callback_data="game:mines")]])); await callback.answer(); return
    g["opened"].append(idx); g["multiplier"]=mines_multiplier(len(g["mines"]),len(g["opened"]))
    await callback.message.edit_reply_markup(reply_markup=mines_bot_keyboard(g["opened"])); await callback.answer(f"Безопасно · x{g['multiplier']:.2f}")

@dp.callback_query(lambda c: c.data and c.data.startswith("diceconfirm:"))
async def dice_confirm(callback: CallbackQuery):
    uid=callback.from_user.id; s=bot_sessions.get(uid,{})
    if s.get("step")!="dice_confirm": await callback.answer("Сессия не найдена",show_alert=True); return
    if callback.data.endswith(":no"): bot_sessions.pop(uid,None); await callback.message.answer("Ставка отменена."); await callback.answer(); return
    stake=int(s["stake"])
    if not subtract_balance(uid,stake): bot_sessions.pop(uid,None); await callback.message.answer("Недостаточно средств на балансе."); await callback.answer(); return
    rs=new_round("dice_bot",uid); mode=s["mode"]; bet=s["bet"]; d1=1+pf_index(rs,"dice1",6); d2=1+pf_index(rs,"dice2",6); total=d1 if mode=="one" else d1+d2
    won=(total<3 if bet=="lt3" else total>3 if bet=="gt3" else total==7 if bet=="eq7" else total<7 if bet=="lt7" else total>7); mult=5.0 if bet=="eq7" else 1.85; payout=int(round(stake*mult)) if won else 0
    if payout: change_balance(uid,payout, f"game_payout:{game}" if "game" in locals() else "game_payout")
    record_game(uid,"dice_bot",stake,"win" if won else "loss",mult if won else 0,payout,rs["round_hash"],rs["server_seed"]); log_event(uid,"game_dice_bot",f"stake={stake} dice={d1},{d2} bet={bet} payout={payout}"); bot_sessions.pop(uid,None)
    rolls=f"🎲 {d1}" if mode=="one" else f"🎲 {d1} + {d2} = <b>{total}</b>"; result=f"🎉 Выигрыш: <b>{payout} ₽</b>" if payout else "<tg-emoji emoji-id='5454350746407419714'>❌</tg-emoji> Проигрыш"
    await callback.message.answer(f"╭────────────────────╮\n       🎲 DICE\n╰────────────────────╯\n\n{rolls}\n\n{result}\n\nХэш раунда: <code>{rs['round_hash']}</code>\nServer seed: <code>{rs['server_seed']}</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎲 Ещё раз",callback_data="game:dice")],[InlineKeyboardButton(text="⬅️ Игры",callback_data="menu:games")]])); await callback.answer()


# ============================================================
# Telegram bot: reference games (the games from the supplied video)
# ============================================================

REF_GAMES = {
    "tower": "🗼 Tower", "knb": "✊ КНБ", "keno": "🔢 Keno", "blackjack": "🃏 Blackjack",
    "baccarat": "🃏 Baccarat", "plinko": "🔻 Plinko", "even": "⚖️ Even", "sector": "🎡 Сектор",
    "duel": "⚔️ Дуэль", "higher_lower": "↕️ Больше-Меньше", "hilo": "🏹 Hi-Lo", "penalty": "🥅 Пенальти",
}


def ref_amount_keyboard(game: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 ₽", callback_data=f"refstake:{game}:10"), InlineKeyboardButton(text="50 ₽", callback_data=f"refstake:{game}:50"), InlineKeyboardButton(text="100 ₽", callback_data=f"refstake:{game}:100")],
        [InlineKeyboardButton(text="500 ₽", callback_data=f"refstake:{game}:500"), InlineKeyboardButton(text="1000 ₽", callback_data=f"refstake:{game}:1000")],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")],
    ])


def _card_value(card: str) -> int:
    return cv(card)


def _ref_finish(uid: int, game: str, stake: int, won: bool, multiplier: float, rs: dict, details: dict | None = None):
    payout = int(round(stake * multiplier)) if won else 0
    if payout:
        change_balance(uid, payout, f"game_{game}_win")
    record_game(uid, game, stake, "win" if won else "loss", multiplier if won else 0, payout, rs["round_hash"], rs["server_seed"], details or {})
    log_event(uid, f"game_{game}", f"stake={stake} result={'win' if won else 'loss'} payout={payout}")
    return payout


def _result_keyboard(game: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Ещё раз", callback_data=f"refgame:{game}")],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")],
    ])


def _cards_text(cards):
    return " ".join(cards)


@dp.callback_query(lambda c: c.data and c.data.startswith("refgame:"))
async def reference_game_start(callback: CallbackQuery):
    uid = callback.from_user.id
    game = callback.data.split(":", 1)[1]
    if game not in REF_GAMES:
        await callback.answer("Игра недоступна", show_alert=True); return
    if uid in bot_active_games:
        await callback.answer("Сначала завершите текущую игру", show_alert=True); return
    if game == "mines":
        bot_sessions[uid] = {"step": "mines_amount"}
        await callback.message.answer("💣 <b>MINES</b>\n\nВведите ставку: <b>10–5000 ₽</b>.", reply_markup=ref_amount_keyboard(game))
        await callback.answer()
        return
    bot_sessions[uid] = {"step": "ref_amount", "game": game}
    await callback.message.answer(
        f"<b>{REF_GAMES[game]}</b>\n\nВведите ставку одним сообщением или выберите сумму ниже.\nМинимум: <b>10 ₽</b> · максимум: <b>5000 ₽</b>",
        reply_markup=ref_amount_keyboard(game),
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("refstake:"))
async def reference_stake(callback: CallbackQuery):
    _, game, raw = callback.data.split(":", 2)
    uid = callback.from_user.id
    try: stake = int(raw)
    except ValueError: await callback.answer("Некорректная ставка", show_alert=True); return
    if game not in REF_GAMES or not 10 <= stake <= 5000:
        await callback.answer("Некорректная ставка", show_alert=True); return
    if game == "mines":
        bot_sessions[uid] = {"step": "mines_count", "stake": stake}
        rows=[[InlineKeyboardButton(text=str(a),callback_data=f"mines:count:{a}") for a in range(2,14)], [InlineKeyboardButton(text=str(a),callback_data=f"mines:count:{a}") for a in range(14,25)]]
        await callback.message.answer(f"💣 <b>MINES</b>\nСтавка: <b>{stake} ₽</b>\nВыберите количество бомб:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await callback.answer()
        return
    bot_sessions[uid] = {"step": "ref_options", "game": game, "stake": stake}
    await _show_ref_options(callback.message, uid, game, stake)
    await callback.answer()


async def _show_ref_options(message: Message, uid: int, game: str, stake: int):
    if game == "tower":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 2 уровня", callback_data="refopt:tower:2"), InlineKeyboardButton(text="🟡 3 уровня", callback_data="refopt:tower:3")], [InlineKeyboardButton(text="🔴 4 уровня", callback_data="refopt:tower:4")]])
    elif game == "knb":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🪨 Камень", callback_data="refopt:knb:rock"), InlineKeyboardButton(text="📄 Бумага", callback_data="refopt:paper")], [InlineKeyboardButton(text="✂️ Ножницы", callback_data="refopt:knb:scissors")]])
    elif game == "keno":
        kb = None
    elif game == "blackjack":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🃏 Начать", callback_data="refopt:blackjack:start")]])
    elif game == "baccarat":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 Игрок", callback_data="refopt:baccarat:player"), InlineKeyboardButton(text="🏦 Банкир", callback_data="refopt:baccarat:banker")], [InlineKeyboardButton(text="⚖️ Ничья", callback_data="refopt:baccarat:tie")]])
    elif game == "plinko":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 Low", callback_data="refopt:plinko:low"), InlineKeyboardButton(text="🟡 Medium", callback_data="refopt:plinko:medium"), InlineKeyboardButton(text="🔴 High", callback_data="refopt:plinko:high")]])
    elif game == "even":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="2️⃣ Чёт", callback_data="refopt:even:even"), InlineKeyboardButton(text="1️⃣ Нечёт", callback_data="refopt:even:odd")]])
    elif game == "sector":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="1️⃣ Сектор 1", callback_data="refopt:sector:1"), InlineKeyboardButton(text="2️⃣ Сектор 2", callback_data="refopt:sector:2")], [InlineKeyboardButton(text="3️⃣ Сектор 3", callback_data="refopt:sector:3")]])
    elif game == "duel":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔵 Сторона A", callback_data="refopt:duel:a"), InlineKeyboardButton(text="🔴 Сторона B", callback_data="refopt:duel:b")]])
    elif game in {"higher_lower", "hilo"}:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬆️ Выше", callback_data=f"refopt:{game}:higher"), InlineKeyboardButton(text="⬇️ Ниже", callback_data=f"refopt:{game}:lower")]])
    elif game == "penalty":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Лево", callback_data="refopt:penalty:left"), InlineKeyboardButton(text="⬆️ Центр", callback_data="refopt:penalty:center"), InlineKeyboardButton(text="➡️ Право", callback_data="refopt: right")]])
        # Telegram callback data must not contain spaces; rebuild the last button.
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Лево", callback_data="refopt:penalty:left"), InlineKeyboardButton(text="⬆️ Центр", callback_data="refopt:penalty:center"), InlineKeyboardButton(text="➡️ Право", callback_data="refopt:penalty:right")]])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[])
    if game == "keno":
        bot_sessions[uid]["step"] = "ref_keno_numbers"
        await message.answer(f"🔢 <b>Keno</b>\n\nСтавка: <b>{stake} ₽</b>\nОтправьте 5 разных чисел от 1 до 40 через пробел.\nНапример: <code>3 7 12 21 38</code>")
    else:
        await message.answer(f"<b>{REF_GAMES[game]}</b>\nСтавка: <b>{stake} ₽</b>\n\nВыберите действие:", reply_markup=kb)


@dp.callback_query(lambda c: c.data and c.data.startswith("refopt:"))
async def reference_game_option(callback: CallbackQuery):
    uid = callback.from_user.id
    _, game, option = callback.data.split(":", 2)
    s = bot_sessions.get(uid, {})
    if s.get("game") != game or "stake" not in s:
        await callback.answer("Сессия не найдена", show_alert=True); return
    stake = int(s["stake"])
    if not subtract_balance(uid, stake, f"game_{game}_bet"):
        bot_sessions.pop(uid, None); await callback.answer("Недостаточно средств", show_alert=True); return
    rs = new_round(game, uid)

    if game == "tower":
        levels = int(option)
        safe = [pf_index(rs, "tower", 2, i) for i in range(levels)]
        bot_active_games[uid] = {"type":"tower","stake":stake,"levels":levels,"floor":0,"safe":safe,"round":rs}
        bot_sessions.pop(uid,None)
        await callback.message.answer(f"🗼 <b>Tower</b>\nСтавка: <b>{stake} ₽</b>\nУровень 1 из {levels}. Выберите дверь:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Левая",callback_data="reftower:left"),InlineKeyboardButton(text="Правая ▶️",callback_data="reftower:right")],[InlineKeyboardButton(text="💰 Забрать",callback_data="reftower:cashout")]]))
    elif game == "knb":
        choices=["rock","paper","scissors"]; bot_choice=choices[pf_index(rs,"knb",3)]; win=(option != bot_choice and ((option,bot_choice) in {("rock","scissors"),("paper","rock"),("scissors","paper")})); tie=option==bot_choice; mult=1.9 if win else (1.0 if tie else 0)
        if tie:
            change_balance(uid, stake, "game_knb_refund")
            payout=stake
            record_game(uid,game,stake,"win",1.0,payout,rs["round_hash"],rs["server_seed"],{"player":option,"bot":bot_choice})
        else:
            payout=_ref_finish(uid,game,stake,win,mult,rs,{"player":option,"bot":bot_choice})
        bot_sessions.pop(uid,None); result="🤝 Ничья — ставка возвращена" if tie else (f"🎉 Выигрыш: <b>{payout} ₽</b>" if win else "❌ Проигрыш")
        await callback.message.answer(f"✊ <b>КНБ</b>\nВы: {option}\nБот: {bot_choice}\n\n{result}\n\nХэш: <code>{rs['round_hash']}</code>\nSeed: <code>{rs['server_seed']}</code>",reply_markup=_result_keyboard(game))
    elif game == "baccarat":
        d=deck(rs); player=d[:2]; banker=d[2:4]; pv=sum(_card_value(c) for c in player)%10; bv=sum(_card_value(c) for c in banker)%10
        winner="tie" if pv==bv else ("player" if pv>bv else "banker")
        won=option==winner; mult=8.0 if option=="tie" else 1.95; payout=_ref_finish(uid,game,stake,won,mult,rs,{"player":player,"banker":banker,"player_value":pv,"banker_value":bv,"winner":winner})
        bot_sessions.pop(uid,None); await callback.message.answer(f"🃏 <b>Baccarat</b>\nИгрок: {_cards_text(player)} = <b>{pv}</b>\nБанкир: {_cards_text(banker)} = <b>{bv}</b>\n\nПобедитель: <b>{winner}</b>\n" + (f"🎉 Выигрыш: <b>{payout} ₽</b>" if won else "❌ Проигрыш") + f"\n\nХэш: <code>{rs['round_hash']}</code>\nSeed: <code>{rs['server_seed']}</code>",reply_markup=_result_keyboard(game))
    elif game == "plinko":
        tables={"low":[0.5,0.8,1.0,1.2,1.5,2.0],"medium":[0.2,0.5,1.0,1.8,3.0,5.0],"high":[0.1,0.3,0.7,2.0,5.0,10.0]}; vals=tables[option]; mult=vals[pf_index(rs,"plinko",len(vals))]; won=mult>=1; payout=_ref_finish(uid,game,stake,won,mult,rs,{"risk":option,"multiplier":mult})
        bot_sessions.pop(uid,None); await callback.message.answer(f"🔻 <b>Plinko</b>\nРиск: <b>{option}</b>\nКоэффициент: <b>x{mult:.2f}</b>\n\n"+(f"🎉 Выигрыш: <b>{payout} ₽</b>" if payout else "❌ Проигрыш"),reply_markup=_result_keyboard(game))
    elif game == "even":
        n=1+pf_index(rs,"even",100); won=(n%2==0)==(option=="even"); payout=_ref_finish(uid,game,stake,won,1.9,rs,{"number":n,"choice":option}); bot_sessions.pop(uid,None); await callback.message.answer(f"⚖️ <b>Even</b>\nВыпало: <b>{n}</b>\n\n"+(f"🎉 Выигрыш: <b>{payout} ₽</b>" if won else "❌ Проигрыш"),reply_markup=_result_keyboard(game))
    elif game == "sector":
        n=1+pf_index(rs,"sector",3); won=int(option)==n; payout=_ref_finish(uid,game,stake,won,2.8,rs,{"sector":n}); bot_sessions.pop(uid,None); await callback.message.answer(f"🎡 <b>Сектор</b>\nВыпал сектор: <b>{n}</b>\n\n"+(f"🎉 Выигрыш: <b>{payout} ₽</b>" if won else "❌ Проигрыш"),reply_markup=_result_keyboard(game))
    elif game == "duel":
        n=pf_index(rs,"duel",2); winner="a" if n==0 else "b"; won=option==winner; payout=_ref_finish(uid,game,stake,won,1.9,rs,{"winner":winner}); bot_sessions.pop(uid,None); await callback.message.answer(f"⚔️ <b>Дуэль</b>\nПобедила сторона: <b>{winner.upper()}</b>\n\n"+(f"🎉 Выигрыш: <b>{payout} ₽</b>" if won else "❌ Проигрыш"),reply_markup=_result_keyboard(game))
    elif game == "penalty":
        keeper=["left","center","right"][pf_index(rs,"keeper",3)]; won=option!=keeper; payout=_ref_finish(uid,game,stake,won,2.7,rs,{"shot":option,"keeper":keeper}); bot_sessions.pop(uid,None); await callback.message.answer(f"🥅 <b>Пенальти</b>\nВратарь прыгнул: <b>{keeper}</b>\n\n"+(f"⚽ Гол! Выигрыш: <b>{payout} ₽</b>" if won else "🧤 Вратарь отбил удар"),reply_markup=_result_keyboard(game))
    elif game in {"higher_lower","hilo"}:
        d=deck(rs); first=d[0]; bot_active_games[uid]={"type":game,"stake":stake,"card":first,"deck":d[1:],"round":rs}; bot_sessions.pop(uid,None)
        await callback.message.answer(f"{REF_GAMES[game]}\nПервая карта: <b>{first}</b>\n\nВыберите, следующая будет выше или ниже:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬆️ Выше",callback_data=f"refhl:{game}:higher"),InlineKeyboardButton(text="⬇️ Ниже",callback_data=f"refhl:{game}:lower")],[InlineKeyboardButton(text="💰 Забрать",callback_data=f"refhl:{game}:cashout")]]))
    elif game == "blackjack":
        d=deck(rs); player=d[:2]; dealer=d[2:4]; bot_active_games[uid]={"type":"blackjack_ref","stake":stake,"player":player,"dealer":dealer,"deck":d[4:],"round":rs}; bot_sessions.pop(uid,None)
        await callback.message.answer(f"🃏 <b>Blackjack</b>\nВаши карты: {_cards_text(player)} = <b>{hv(player)}</b>\nДилер: <b>{dealer[0]} ❓</b>\n\nВыберите действие:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Ещё",callback_data="refbj:hit"),InlineKeyboardButton(text="✋ Стоп",callback_data="refbj:stand")]]))
    await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("reftower:"))
async def reference_tower(callback: CallbackQuery):
    uid=callback.from_user.id; g=bot_active_games.get(uid)
    if not g or g.get("type")!="tower": await callback.answer("Игра не найдена",show_alert=True); return
    action=callback.data.split(":")[1]
    if action=="cashout":
        floor=g["floor"]
        if floor<=0: await callback.answer("Сначала пройдите уровень",show_alert=True); return
        mult=round(1.25**floor,4); payout=_ref_finish(uid,"tower",g["stake"],True,mult,g["round"],{"levels":g["levels"],"floor":floor}); bot_active_games.pop(uid,None)
        await callback.message.answer(f"🗼 Cash Out · <b>x{mult:.2f}</b>\nВыигрыш: <b>{payout} ₽</b>",reply_markup=_result_keyboard("tower")); await callback.answer(); return
    pick=0 if action=="left" else 1
    if pick!=g["safe"][g["floor"]]:
        rs=g["round"]; record_game(uid,"tower",g["stake"],"loss",0,0,rs["round_hash"],rs["server_seed"],{"floor":g["floor"]}); bot_active_games.pop(uid,None); await callback.message.answer(f"💥 <b>Tower</b>\nВы выбрали неверную дверь. Ставка проиграна.\n\nХэш: <code>{rs['round_hash']}</code>\nSeed: <code>{rs['server_seed']}</code>",reply_markup=_result_keyboard("tower")); await callback.answer(); return
    g["floor"]+=1
    if g["floor"]>=g["levels"]:
        mult=round(1.25**g["floor"],4); payout=_ref_finish(uid,"tower",g["stake"],True,mult,g["round"],{"floor":g["floor"]}); bot_active_games.pop(uid,None); await callback.message.answer(f"🏆 <b>Tower пройден!</b>\nx{mult:.2f} · Выигрыш <b>{payout} ₽</b>",reply_markup=_result_keyboard("tower")); await callback.answer(); return
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Левая",callback_data="reftower:left"),InlineKeyboardButton(text="Правая ▶️",callback_data="reftower:right")],[InlineKeyboardButton(text=f"💰 Забрать x{1.25**g['floor']:.2f}",callback_data="reftower:cashout")]])); await callback.answer("Безопасно")


@dp.callback_query(lambda c: c.data and c.data.startswith("refhl:"))
async def reference_hilo(callback: CallbackQuery):
    uid=callback.from_user.id; _,game,action=callback.data.split(":")
    g=bot_active_games.get(uid)
    if not g or g.get("type")!=game: await callback.answer("Игра не найдена",show_alert=True); return
    if action=="cashout":
        # One correct prediction is enough to cash out; otherwise keep current stake.
        await callback.answer("Сделайте прогноз",show_alert=True); return
    current=g["card"]; nxt=g["deck"].pop(0); a=_card_value(current); b=_card_value(nxt)
    won=(b>a if action=="higher" else b<a)
    if b==a: won=True
    mult=1.8
    if not won:
        rs=g["round"]; record_game(uid,game,g["stake"],"loss",0,0,rs["round_hash"],rs["server_seed"],{"from":current,"to":nxt,"choice":action}); bot_active_games.pop(uid,None); await callback.message.answer(f"{REF_GAMES[game]}\n{current} → {nxt}\n\n❌ Проигрыш",reply_markup=_result_keyboard(game)); await callback.answer(); return
    g["card"]=nxt; g["wins"]=g.get("wins",0)+1; mult=round(1.8**g["wins"],4)
    if g["wins"]>=3:
        payout=_ref_finish(uid,game,g["stake"],True,mult,g["round"],{"wins":g["wins"]}); bot_active_games.pop(uid,None); await callback.message.answer(f"{REF_GAMES[game]}\n{current} → {nxt}\n\n🎉 Выигрыш: <b>{payout} ₽</b> · x{mult:.2f}",reply_markup=_result_keyboard(game)); await callback.answer(); return
    await callback.message.answer(f"{REF_GAMES[game]}\n{current} → <b>{nxt}</b> · верно!\nТекущий cashout: <b>x{mult:.2f}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬆️ Выше",callback_data=f"refhl:{game}:higher"),InlineKeyboardButton(text="⬇️ Ниже",callback_data=f"refhl:{game}:lower")],[InlineKeyboardButton(text=f"💰 Забрать x{mult:.2f}",callback_data=f"refhlcash:{game}")]])); await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("refhlcash:"))
async def reference_hilo_cashout(callback: CallbackQuery):
    uid=callback.from_user.id; game=callback.data.split(":")[1]; g=bot_active_games.get(uid)
    if not g or g.get("type")!=game: await callback.answer("Игра не найдена",show_alert=True); return
    mult=round(1.8**g.get("wins",1),4); payout=_ref_finish(uid,game,g["stake"],True,mult,g["round"],{"wins":g.get("wins",1)}); bot_active_games.pop(uid,None)
    await callback.message.answer(f"💰 Cash Out · <b>x{mult:.2f}</b>\nВыигрыш: <b>{payout} ₽</b>",reply_markup=_result_keyboard(game)); await callback.answer()


@dp.callback_query(lambda c: c.data and c.data.startswith("refbj:"))
async def reference_blackjack(callback: CallbackQuery):
    uid=callback.from_user.id; action=callback.data.split(":")[1]; g=bot_active_games.get(uid)
    if not g or g.get("type")!="blackjack_ref": await callback.answer("Игра не найдена",show_alert=True); return
    if action=="hit":
        g["player"].append(g["deck"].pop(0)); value=hv(g["player"])
        if value>21:
            rs=g["round"]; record_game(uid,"blackjack",g["stake"],"loss",0,0,rs["round_hash"],rs["server_seed"],{"player":g["player"],"dealer":g["dealer"]}); bot_active_games.pop(uid,None); await callback.message.answer(f"🃏 <b>Blackjack</b>\nВаши карты: {_cards_text(g['player'])} = <b>{value}</b>\n\n❌ Перебор",reply_markup=_result_keyboard("blackjack")); await callback.answer(); return
        await callback.message.edit_text(f"🃏 <b>Blackjack</b>\nВаши карты: {_cards_text(g['player'])} = <b>{value}</b>\nДилер: <b>{g['dealer'][0]} ❓</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Ещё",callback_data="refbj:hit"),InlineKeyboardButton(text="✋ Стоп",callback_data="refbj:stand")]])); await callback.answer(); return
    while hv(g["dealer"])<17: g["dealer"].append(g["deck"].pop(0))
    pv=hv(g["player"]); dv=hv(g["dealer"]); won=pv>dv or dv>21; tie=pv==dv; mult=1.95 if won else (1.0 if tie else 0)
    if tie: payout=_ref_finish(uid,"blackjack",g["stake"],True,1.0,g["round"],{"player":g["player"],"dealer":g["dealer"]})
    else: payout=_ref_finish(uid,"blackjack",g["stake"],won,mult,g["round"],{"player":g["player"],"dealer":g["dealer"]})
    bot_active_games.pop(uid,None); result="🤝 Возврат ставки" if tie else (f"🎉 Выигрыш: <b>{payout} ₽</b>" if won else "❌ Проигрыш")
    await callback.message.answer(f"🃏 <b>Blackjack</b>\nВы: {_cards_text(g['player'])} = <b>{pv}</b>\nДилер: {_cards_text(g['dealer'])} = <b>{dv}</b>\n\n{result}",reply_markup=_result_keyboard("blackjack")); await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("admin:"))
async def admin_callbacks(callback: CallbackQuery):
    uid=callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Доступ запрещен", show_alert=True); return
    parts=callback.data.split(":",2); action=parts[1]
    if action=="home":
        text=("╭────────────────────╮\n       🛠 | ADMIN PANEL\n╰────────────────────╯\n\n"
              "Панель бота синхронизирована с базой Mini App.\n"
              "Баланс и профили общие для обоих интерфейсов.")
        markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи",callback_data="admin:users"), InlineKeyboardButton(text="📊 Активность",callback_data="admin:activity")],
            [InlineKeyboardButton(text="💰 Изменить баланс",callback_data="admin:adjust")],
            [InlineKeyboardButton(text="📝 Логи",callback_data="admin:logs")],
            [InlineKeyboardButton(text="💳 Пополнения",callback_data="admin:payments"), InlineKeyboardButton(text="💸 Выводы",callback_data="admin:withdrawals")],
            [InlineKeyboardButton(text="⬅️ Профиль",callback_data="menu:profile")]
        ])
    elif action=="users":
        rows=get_all_users(25)
        text="👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n" + ("\n".join(f"{r.get('username') or 'без username'} · <code>{r['user_id']}</code> · <b>{float(r['balance']):.2f} ₽</b>" for r in rows) or "—")
        buttons=[]
        for r in rows[:20]:
            label=("@"+str(r['username'])) if r.get('username') else str(r['user_id'])
            buttons.append([InlineKeyboardButton(text=f"👤 {label}",callback_data=f"admin:user:{r['user_id']}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Admin",callback_data="admin:home")])
        markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    elif action=="user" and len(parts)>2:
        try: target=int(parts[2])
        except ValueError: await callback.answer("Некорректный ID",show_alert=True); return
        profile=get_user_profile(target)
        if not profile: await callback.answer("Пользователь не найден",show_alert=True); return
        stats=profile['stats']
        entries=get_user_ledger(target,20)
        text=(f"👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\nTelegram ID: <code>{profile['telegram_id']}</code>\n"
              f"Username: @{profile.get('username') or '—'}\nБаланс: <b>{profile['balance']:.2f} ₽</b>\n\n"
              f"Игры: {stats['games']} · Победы: {stats['wins']} · Поражения: {stats['losses']}\n"
              f"Winrate: {stats['winrate']}%\nОборот: {stats['turnover']} ₽\nВыиграно: {stats['payouts']} ₽\nMax Win: {stats['max_win']} ₽\n\n"
              "<b>Последние операции</b>\n" + ("\n".join(f"#{e['id']} · {float(e['amount']):+.2f} ₽ · {e['reason']}" for e in entries) or "—"))
        markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰 Изменить баланс",callback_data=f"admin:adjust:{target}")],[InlineKeyboardButton(text="⬅️ Пользователи",callback_data="admin:users")]])
    elif action=="activity":
        rows=get_ledger_activity(40)
        text="📊 <b>АКТИВНОСТЬ / LEDGER</b>\n\n"+("\n".join(f"#{r['id']} · {r.get('username') or r['user_id']} · <b>{float(r['amount']):+.2f} ₽</b> · {r['reason']}" for r in rows) or "—")
        markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin",callback_data="admin:home")]])
    elif action=="logs":
        rows=get_audit_logs(40); text="📝 <b>ЛОГИ</b>\n\n"+("\n".join(f"#{r['id']} · {r.get('user_id','—')} · {r['action']} · {r['details']}" for r in rows) or "—"); markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin",callback_data="admin:home")]])
    elif action=="payments":
        rows=get_all_payments(30); text="💳 <b>ПОПОЛНЕНИЯ</b>\n\n"+("\n".join(f"#{r['id']} · {r['user_id']} · {float(r['amount_rub']):.2f} ₽ · {r['status']}" for r in rows) or "—"); markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin",callback_data="admin:home")]])
    elif action=="withdrawals":
        rows=__import__('database').get_pending_withdrawals(30); text="💸 <b>ВЫВОДЫ</b>\n\n"+("\n".join(f"#{r['id']} · {r['user_id']} · {float(r['amount_rub']):.2f} ₽ · {r['status']}" for r in rows) or "—"); markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin",callback_data="admin:home")]])
    elif action=="adjust":
        target=parts[2] if len(parts)>2 else ""
        if target:
            bot_sessions[uid]={"step":"admin_amount","target":int(target)}
            await callback.message.answer(f"Введите изменение баланса для <code>{target}</code>. Например: <b>+500</b> или <b>-500</b>.")
            await callback.answer(); return
        bot_sessions[uid]={"step":"admin_target"}
        await callback.message.answer("Введите Telegram ID пользователя.")
        await callback.answer(); return
    else:
        await callback.answer("Неизвестный раздел",show_alert=True); return
    await _edit_menu(callback,text,markup); await callback.answer()

# ============================================================
# Telegram bot: Upgrader
# ============================================================

def upgrader_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="x2", callback_data="upg:x2"), InlineKeyboardButton(text="x5", callback_data="upg:x5"), InlineKeyboardButton(text="x10", callback_data="upg:x10")],
        [InlineKeyboardButton(text="35%", callback_data="upg:p35"), InlineKeyboardButton(text="70%", callback_data="upg:p70")],
        [InlineKeyboardButton(text="Указать 1–80%", callback_data="upg:custom")],
    ])

@dp.message(Command("upgrade"))
async def upgrade_command(message: Message):
    if not message.from_user: return
    uid=message.from_user.id
    ensure_user(uid)
    upgrade_sessions[uid]={"step":"amount"}
    await message.answer("⚡ <b>UPGRADER</b>\n\nОтправьте сумму ставки одним сообщением.\nНапример: <b>100</b>")

@dp.message()
async def upgrade_message_router(message: Message):
    if not message.from_user: return
    uid=message.from_user.id
    session=bot_sessions.get(uid)
    text=str(message.text or '').strip()
    if text in {"🤡 Play & Win", "Play & Win"}:
        await message.answer(_games_text(), reply_markup=_games_keyboard())
        return
    if text in {"🧳 Кошелёк", "Кошелёк", "💰 Кошелек", "Кошелек"}:
        await message.answer(_wallet_text(uid), reply_markup=_wallet_keyboard())
        return
    if text in {"💵 Профиль", "Профиль"}:
        await message.answer(_profile_text(uid), reply_markup=_profile_keyboard(uid))
        return
    if session:
        if session.get("step")=="deposit_amount":
            try: amount=float(text.replace(',','.').replace(' ',''))
            except ValueError: amount=0
            if amount<=0: await message.answer("Введите положительную сумму в USDT."); return
            try:
                inv=await create_invoice(uid, amount)
                if inv.get("pay_url"):
                    await message.answer(f"💳 Счет Crypto Pay на {amount:g} USDT:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Оплатить через CryptoBot", url=inv["pay_url"])]]))
                else:
                    await message.answer("Crypto Pay не настроен: добавьте CRYPTOBOT_TOKEN.")
            except Exception as e:
                await message.answer(f"Ошибка создания счета: {e}")
            bot_sessions.pop(uid,None); return
        if session.get("step")=="withdraw_amount":
            try: amount=int(float(text.replace(',','.').replace(' ','').replace('₽','')))
            except ValueError: amount=0
            if amount<=0: await message.answer("Введите сумму в ₽."); return
            bot_sessions[uid]={"step":"withdraw_details","amount":amount}
            await message.answer("Отправьте реквизиты/данные выплаты. Заявка будет видна в ADMIN PANEL.")
            return
        if session.get("step")=="withdraw_details":
            amount=int(session["amount"]); result=create_withdrawal(uid,amount,text)
            if result is None: await message.answer("Не удалось создать заявку: проверьте баланс и сумму."); bot_sessions.pop(uid,None); return
            log_event(uid,"withdrawal_created",f"id={result['id']} amount={amount}")
            await message.answer(f"Заявка на вывод #{result['id']} создана на {amount} ₽.")
            bot_sessions.pop(uid,None); return

    if session and session.get("step") in {"slot_amount","mines_amount","dice_amount"}:
        try: amount=int(float(text.replace(',','.').replace(' ','').replace('₽','')))
        except ValueError: amount=0
        if not 10<=amount<=5000: await message.answer("Сумма ставки должна быть от <b>10 ₽</b> до <b>5000 ₽</b>."); return
        if session["step"]=="slot_amount":
            session.update({"step":"slot_confirm","stake":amount}); await message.answer(f"<tg-emoji emoji-id='5384509325429463744'>🎰</tg-emoji> SLOTS\n\n💎 Ставка: <b>{amount} ₽</b>\n\nПодтвердить ставку?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подтвердить ставку",callback_data="slotconfirm:yes"),InlineKeyboardButton(text="Отмена",callback_data="slotconfirm:cancel")]]))
        elif session["step"]=="mines_amount":
            session.update({"step":"mines_count","stake":amount}); rows=[[InlineKeyboardButton(text=str(a),callback_data=f"mines:count:{a}") for a in range(2,14)],[InlineKeyboardButton(text=str(a),callback_data=f"mines:count:{a}") for a in range(14,25)]]; await message.answer(f"<tg-emoji emoji-id='5280569974404966639'>💣</tg-emoji> MINES\n\n💎 Ставка: <b>{amount} ₽</b>\n\nВыберите количество бомб:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        else:
            session.update({"step":"dice_confirm","stake":amount}); await message.answer(f"🎲 DICE\n\nСтавка: <b>{amount} ₽</b>\nРежим: {'один бросок' if session['mode']=='one' else 'два броска'}\nВыбор: <b>{session['bet']}</b>\n\nПодтвердить ставку?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подтвердить ставку",callback_data="diceconfirm:yes"),InlineKeyboardButton(text="Отмена",callback_data="diceconfirm:no")]]))
        return

    if session and session.get("step")=="admin_target":
        if not is_admin(uid): bot_sessions.pop(uid,None); return
        try: target=int(text)
        except ValueError: await message.answer("ID должен быть числом."); return
        bot_sessions[uid]={"step":"admin_amount","target":target}
        await message.answer("Введите изменение баланса в ₽. Например: <b>+500</b> или <b>-500</b>.")
        return
    if session and session.get("step")=="admin_amount":
        if not is_admin(uid): bot_sessions.pop(uid,None); return
        try: amount=int(text.replace("₽","").replace(" ",""))
        except ValueError: await message.answer("Введите целое число со знаком."); return
        target=int(session["target"]); ensure_user(target); new_balance=change_balance(target,amount)
        log_event(uid,"admin_balance_adjust",f"target={target} amount={amount}")
        log_event(target,"admin_balance_changed",f"amount={amount}")
        bot_sessions.pop(uid,None)
        await message.answer(f"Баланс пользователя <code>{target}</code> изменен на {amount:+d} ₽. Новый баланс: <b>{new_balance} ₽</b>.")
        return

    if session and session.get("step") == "ref_amount":
        try:
            amount=int(float(text.replace(',','.').replace(' ','').replace('₽','')))
        except ValueError:
            amount=0
        if not 10 <= amount <= 5000:
            await message.answer("Ставка должна быть от 10 до 5000 ₽.")
            return
        game=session["game"]
        session.update({"step":"ref_options","stake":amount})
        await _show_ref_options(message, uid, game, amount)
        return

    if session and session.get("step") == "ref_keno_numbers":
        parts=text.replace(',',' ').split()
        try: nums=[int(x) for x in parts]
        except ValueError: nums=[]
        if len(nums)!=5 or len(set(nums))!=5 or any(x<1 or x>40 for x in nums):
            await message.answer("Нужно ровно 5 разных чисел от 1 до 40. Например: 3 7 12 21 38")
            return
        stake=int(session["stake"])
        if not subtract_balance(uid,stake,"game_keno_bet"):
            bot_sessions.pop(uid,None); await message.answer("Недостаточно средств на балансе."); return
        rs=new_round("keno",uid); draw=[]; available=list(range(1,41))
        for i in range(5):
            j=pf_index(rs,"keno",len(available),i); draw.append(available.pop(j))
        hits=len(set(nums)&set(draw)); pays={0:0,1:0,2:1.0,3:2.5,4:8.0,5:20.0}; mult=pays[hits]; payout=_ref_finish(uid,"keno",stake,mult>0,mult,rs,{"numbers":nums,"draw":draw,"hits":hits}); bot_sessions.pop(uid,None)
        await message.answer(f"🔢 <b>Keno</b>\nВаши: <code>{' '.join(map(str,sorted(nums)))}</code>\nТираж: <code>{' '.join(map(str,sorted(draw)))}</code>\nСовпадений: <b>{hits}</b>\n\n"+(f"🎉 Выигрыш: <b>{payout} ₽</b> · x{mult:.2f}" if payout else "❌ Проигрыш"),reply_markup=_result_keyboard("keno"))
        return

    if uid not in upgrade_sessions:
        return
    s=upgrade_sessions[uid]
    text=str(message.text or '').strip()
    if s.get("step")=="amount":
        try:
            amount=float(text.replace(',','.').replace(' ',''))
            if amount<=0 or amount>1_000_000: raise ValueError
        except ValueError:
            await message.answer("Укажите сумму числом, например <b>100</b>."); return
        s["stake"]=int(round(amount)); s["step"]="option"
        await message.answer("Выберите коэффициент или шанс выигрыша:", reply_markup=upgrader_keyboard()); return
    if s.get("step")=="custom":
        try: pct=float(text.replace(',','.').replace(' ',''))
        except ValueError: pct=0
        if not 1<=pct<=80: await message.answer("Процент должен быть от 1 до 80."); return
        s["pct"]=pct; s["mult"]=(1-UPGRADE_HOUSE_EDGE)/(pct/100)
        await run_upgrade_bot(message, uid)

@dp.callback_query(lambda c: c.data and c.data.startswith("upg:"))
async def upgrade_choice(callback: CallbackQuery):
    uid=callback.from_user.id; s=upgrade_sessions.get(uid)
    if not s or "stake" not in s:
        await callback.answer("Сессия не найдена. Нажмите /upgrade", show_alert=True); return
    choice=callback.data.split(":",1)[1]
    if choice=="custom":
        s["step"]="custom"
        await callback.message.answer("Введите шанс выигрыша от <b>1</b> до <b>80</b> (в процентах).")
        await callback.answer(); return
    if choice.startswith("x"):
        mult=float(choice[1:]); pct=min(80.0, (1-UPGRADE_HOUSE_EDGE)/mult*100); s["mult"]=mult; s["pct"]=pct
    else:
        pct=float(choice[1:]); s["pct"]=pct; s["mult"]=(1-UPGRADE_HOUSE_EDGE)/(pct/100)
    await run_upgrade_bot(callback.message, uid)
    await callback.answer()

async def run_upgrade_bot(message: Message, uid: int):
    s=upgrade_sessions.get(uid,{}); stake=int(s.get("stake",0)); pct=float(s.get("pct",0)); mult=float(s.get("mult",0))
    if not subtract_balance(uid,stake):
        await message.answer("Недостаточно средств на балансе."); upgrade_sessions.pop(uid,None); return
    rs=new_round("upgrader",uid); roll=pf_unit(rs,"upgrade"); won=roll<pct/100
    payout=int(round(stake*mult)) if won else 0
    if payout: change_balance(uid,payout, f"game_payout:{game}" if "game" in locals() else "game_payout")
    record_game(uid,"upgrader",stake,"win" if won else "loss",mult if won else 0,payout,rs["round_hash"],rs["server_seed"])
    log_event(uid, "game_upgrader", f"stake={stake} result={'win' if won else 'loss'} payout={payout}")
    await message.answer(
        f"⚡ <b>UPGRADER</b>\nСтавка: <b>{stake} ₽</b>\nШанс: <b>{pct:.2f}%</b>\nКоэффициент: <b>x{mult:.2f}</b>\nХэш раунда: <code>{rs['round_hash']}</code>"
    )
    if UPGRADE_GIF.exists():
        await message.answer_animation(FSInputFile(UPGRADE_GIF), caption="Прокрутка…")
    await message.answer(
        (f"❄️ <b>УСПЕХ</b>\nВыигрыш: <b>{payout} ₽</b>\nРолл: {roll*100:.4f}%" if won else f"▫️ <b>НЕУДАЧА</b>\nРолл: {roll*100:.4f}%" ) +
        f"\n\nПроверка: SHA256(server_seed) =\n<code>{rs['round_hash']}</code>\nServer seed: <code>{rs['server_seed']}</code>"
    )
    upgrade_sessions.pop(uid,None)

@app.post(WEBHOOK_PATH)
async def webhook(request:Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token")!=WEBHOOK_SECRET:
        return JSONResponse({"ok":False},status_code=403)
    try:
        update=Update.model_validate(await request.json())
        await dp.feed_update(bot,update)
        return {"ok":True}
    except Exception as e:
        return JSONResponse({"ok":False,"error":str(e)},status_code=500)


@app.on_event("startup")
async def startup():
    init_db()


@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()


if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")))
