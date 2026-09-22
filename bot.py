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
from pydantic import BaseModel, Field

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, CallbackQuery, FSInputFile

from admin import is_admin
from database import (
    init_db, ensure_user, get_balance, change_balance, subtract_balance,
    get_user_stats, get_game_history, get_payment_history,
    get_withdrawal_history, create_withdrawal, record_game,
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
active_games: dict[int, dict] = {}

GAME_NAMES = {"slot", "x50", "crash", "blackjack", "mines", "upgrader", "slot_buy"}
RNG = random.SystemRandom()
UPGRADE_HOUSE_EDGE = float(os.getenv("UPGRADE_HOUSE_EDGE", "0.04"))
UPGRADE_GIF = Path(os.getenv("UPGRADE_GIF", str(Path(__file__).with_name("assets").joinpath("upgrader_spin.gif"))))
upgrade_sessions: dict[int, dict] = {}



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

X50 = ["x2", "x3", "x5", "x50"]
X50_MULT = {"x2": 2, "x3": 3, "x5": 5, "x50": 50}
X50_WEIGHTS = [54, 30, 12, 1]  # configurable; target Mini App can be tuned


# ============================================================
# CRASH
# ============================================================

def crash_point(round_state=None):
    u = pf_unit(round_state, "crash") if round_state else RNG.random()
    return round(max(1.0, min(1000.0, 0.97 / max(1e-12, 1-u))), 2)


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
    return round(0.97/p, 4)


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
        {"id":"slot","name":"SLOT","icon":"🎰"},
        {"id":"x50","name":"x50","icon":"🎡"},
        {"id":"crash","name":"CRASH","icon":"🚀"},
        {"id":"blackjack","name":"Blackjack","icon":"🃏"},
        {"id":"mines","name":"Mines","icon":"💣"},
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
            change_balance(uid,stake); raise HTTPException(400,"Выберите x2, x3, x5 или x50")
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
        if payout: change_balance(uid,payout)
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
        result=g["result"]; won=result==g["selected"]
        return finish(uid,"x50",g["stake"],won,X50_MULT[result] if won else 0,
                      {"selected":g["selected"],"result":result,"round_seconds":g["round_seconds"]},
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


def start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Открыть Resonant Casino",
                              web_app=WebAppInfo(url=WEBAPP_URL))]
    ])


@dp.message(CommandStart())
async def start_handler(message: Message):
    if message.from_user: ensure_user(message.from_user.id)
    await message.answer(
        "🎰 <b>RESONANT CASINO</b>\n\n"
        "SLOT · x50 · CRASH · Blackjack · Mines\n\n"
        "Откройте Mini App.\n\n⚡ Апгрейдер: /upgrade",
        reply_markup=start_keyboard())


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
    if not message.from_user or message.from_user.id not in upgrade_sessions: return
    uid=message.from_user.id; s=upgrade_sessions[uid]
    text=str(message.text or '').strip()
    if s.get("step")=="amount":
        try:
            amount=float(text.replace(',','.').replace(' ',''))
            if amount<=0 or amount>1_000_000: raise ValueError
        except ValueError:
            await message.answer("Укажите сумму числом, например <b>100</b>.")
            return
        s["stake"]=int(round(amount)); s["step"]="option"
        await message.answer("Выберите коэффициент или шанс выигрыша:", reply_markup=upgrader_keyboard())
        return
    if s.get("step")=="custom":
        try: pct=float(text.replace(',','.').replace(' ',''))
        except ValueError: pct=0
        if not 1<=pct<=80:
            await message.answer("Процент должен быть от 1 до 80."); return
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
    if payout: change_balance(uid,payout)
    record_game(uid,"upgrader",stake,"win" if won else "loss",mult if won else 0,payout,rs["round_hash"],rs["server_seed"])
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
