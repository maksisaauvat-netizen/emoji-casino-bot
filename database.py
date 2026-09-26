"""Database adapter shared with the existing Mini App.

When DATABASE_URL is set, the bot uses the same PostgreSQL database as the
NestJS/Prisma application. The bot never keeps a second balance: balance is
always the sum of the application's LedgerEntry rows.

A small set of bot-owned tables is created in that same database for bot game
history, payments, withdrawals and audit logs. The application code does not
need to change to use these tables.

For local legacy development, if DATABASE_URL is absent, the original SQLite
storage is retained as a fallback.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_LOCK = threading.RLock()

if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row

DB_PATH = Path(os.getenv("DATABASE_PATH", str(Path(__file__).with_name("resonant.sqlite3"))) )


def _pg_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _sqlite_conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _is_pg() -> bool:
    return bool(DATABASE_URL)


def init_db() -> None:
    if not _is_pg():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, _sqlite_conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance_rub INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS games (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, game TEXT NOT NULL, stake INTEGER NOT NULL, result TEXT NOT NULL, multiplier REAL NOT NULL DEFAULT 0, payout INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, round_hash TEXT, server_seed TEXT);
            CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, invoice_id INTEGER NOT NULL UNIQUE, amount_usdt REAL NOT NULL, amount_rub INTEGER NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, paid_at INTEGER);
            CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount_rub INTEGER NOT NULL, payout_details TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_games_user ON games(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id, id DESC);
            """)
        return

    with _LOCK, _pg_conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS bot_games (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
            game TEXT NOT NULL,
            stake NUMERIC(18,2) NOT NULL,
            result TEXT NOT NULL,
            multiplier NUMERIC(18,6) NOT NULL DEFAULT 0,
            payout NUMERIC(18,2) NOT NULL DEFAULT 0,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            round_hash TEXT,
            server_seed TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_bot_games_user ON bot_games(user_id, id DESC);
        CREATE TABLE IF NOT EXISTS bot_payments (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
            invoice_id BIGINT NOT NULL UNIQUE,
            amount_usdt NUMERIC(18,6) NOT NULL,
            amount_rub NUMERIC(18,2) NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            paid_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS bot_withdrawals (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
            amount_rub NUMERIC(18,2) NOT NULL,
            payout_details TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_bot_withdrawals_status ON bot_withdrawals(status, id);
        CREATE TABLE IF NOT EXISTS bot_audit_logs (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES "User"(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_bot_audit_logs_user ON bot_audit_logs(user_id, id DESC);
        """)


def _pg_user_id(c, telegram_id: int, username: str | None = None) -> int:
    tid = str(int(telegram_id))
    row = c.execute('SELECT id FROM "User" WHERE "telegramId"=%s', (tid,)).fetchone()
    if row:
        if username is not None:
            c.execute('UPDATE "User" SET "username"=%s WHERE id=%s', (username, row['id']))
        return int(row['id'])
    row = c.execute(
        'INSERT INTO "User" ("telegramId", "username") VALUES (%s,%s) RETURNING id',
        (tid, username),
    ).fetchone()
    return int(row['id'])


def ensure_user(user_id: int, username: str | None = None) -> None:
    now = int(time.time())
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            _pg_user_id(c, user_id, username)
        return
    with _LOCK, _sqlite_conn() as c:
        c.execute('INSERT OR IGNORE INTO users(user_id,created_at,updated_at) VALUES (?,?,?)', (int(user_id), now, now))


def sync_profile(user_id: int, username: str | None = None) -> None:
    ensure_user(user_id, username)


def get_balance(user_id: int) -> int:
    ensure_user(user_id)
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid = _pg_user_id(c, user_id)
            row = c.execute('SELECT COALESCE(SUM("amount"),0) AS balance FROM "LedgerEntry" WHERE "userId"=%s', (uid,)).fetchone()
            return int(round(float(row['balance'] or 0)))
    with _LOCK, _sqlite_conn() as c:
        row = c.execute('SELECT balance_rub FROM users WHERE user_id=?', (int(user_id),)).fetchone()
        return int(row[0] if row else 0)


def change_balance(user_id: int, amount: int, reason: str = 'bot_balance_change') -> int:
    amount = int(amount)
    if amount == 0:
        return get_balance(user_id)
    ensure_user(user_id)
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid = _pg_user_id(c, user_id)
            c.execute('SELECT id FROM "User" WHERE id=%s FOR UPDATE', (uid,))
            row = c.execute('SELECT COALESCE(SUM("amount"),0) AS balance FROM "LedgerEntry" WHERE "userId"=%s', (uid,)).fetchone()
            current = float(row['balance'] or 0)
            if current + amount < -0.000001:
                raise ValueError('Insufficient player balance')
            c.execute('INSERT INTO "LedgerEntry" ("userId","amount","reason") VALUES (%s,%s,%s)', (uid, f'{amount:.2f}', reason))
            row = c.execute('SELECT COALESCE(SUM("amount"),0) AS balance FROM "LedgerEntry" WHERE "userId"=%s', (uid,)).fetchone()
            return int(round(float(row['balance'] or 0)))
    with _LOCK, _sqlite_conn() as c:
        cur = c.execute('UPDATE users SET balance_rub=balance_rub+?,updated_at=? WHERE user_id=? AND balance_rub+?>=0', (amount, int(time.time()), int(user_id), amount))
        if cur.rowcount != 1:
            raise ValueError('Insufficient player balance')
        return get_balance(user_id)


def subtract_balance(user_id: int, amount: int, reason: str = 'game_bet') -> bool:
    amount = int(amount)
    if amount <= 0:
        return False
    try:
        change_balance(user_id, -amount, reason)
        return True
    except ValueError:
        return False


def _pg_game_user_id(c, telegram_id: int) -> int:
    return _pg_user_id(c, telegram_id)


def get_user_stats(user_id: int) -> dict:
    ensure_user(user_id)
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid = _pg_game_user_id(c, user_id)
            row = c.execute('''SELECT COUNT(*) games, COUNT(*) FILTER (WHERE result='win') wins, COALESCE(SUM(stake),0) turnover, COALESCE(SUM(payout),0) payouts, COALESCE(MAX(payout),0) max_win FROM bot_games WHERE user_id=%s''', (uid,)).fetchone()
            games = int(row['games'] or 0); wins = int(row['wins'] or 0)
            return {'games': games, 'wins': wins, 'losses': games-wins, 'winrate': round(wins/games*100,1) if games else 0, 'turnover': int(round(float(row['turnover'] or 0))), 'payouts': int(round(float(row['payouts'] or 0))), 'max_win': int(round(float(row['max_win'] or 0)))}
    with _LOCK, _sqlite_conn() as c:
        row = c.execute("SELECT COUNT(*) games,SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) wins,COALESCE(SUM(stake),0) turnover,COALESCE(SUM(payout),0) payouts,COALESCE(MAX(payout),0) max_win FROM games WHERE user_id=?", (int(user_id),)).fetchone()
        games=int(row[0] or 0); wins=int(row[1] or 0)
        return {'games':games,'wins':wins,'losses':games-wins,'winrate':round(wins/games*100,1) if games else 0,'turnover':int(row[2] or 0),'payouts':int(row[3] or 0),'max_win':int(row[4] or 0)}


def record_game(user_id: int, game: str, stake: int, result: str, multiplier: float, payout: int, round_hash: str='', server_seed: str='', details: dict | None = None) -> int:
    ensure_user(user_id)
    if _is_pg():
        import json
        with _LOCK, _pg_conn() as c:
            uid=_pg_game_user_id(c,user_id)
            row=c.execute('''INSERT INTO bot_games(user_id,game,stake,result,multiplier,payout,details,round_hash,server_seed) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING id''', (uid,str(game),stake,str(result),multiplier,payout,json.dumps(details or {}),round_hash or '',server_seed or '')).fetchone()
            return int(row['id'])
    with _LOCK, _sqlite_conn() as c:
        cur=c.execute('INSERT INTO games(user_id,game,stake,result,multiplier,payout,created_at,round_hash,server_seed) VALUES (?,?,?,?,?,?,?,?,?)',(int(user_id),str(game),int(stake),str(result),float(multiplier),int(payout),int(time.time()),round_hash or '',server_seed or ''))
        return int(cur.lastrowid)


def _rows_pg(sql: str, args=()):
    with _LOCK, _pg_conn() as c:
        return [dict(r) for r in c.execute(sql,args).fetchall()]


def get_game_history(user_id:int, limit:int=10):
    if _is_pg():
        uid=None
        with _LOCK, _pg_conn() as c: uid=_pg_user_id(c,user_id); rows=c.execute('SELECT id,%s::bigint AS user_id,game,stake,result,multiplier,payout,EXTRACT(EPOCH FROM created_at)::bigint AS created_at,round_hash,server_seed FROM bot_games WHERE user_id=%s ORDER BY id DESC LIMIT %s',(int(user_id),uid,int(limit))).fetchall()
        return [dict(r) for r in rows]
    with _LOCK, _sqlite_conn() as c: return [dict(r) for r in c.execute('SELECT id,user_id,game,stake,result,multiplier,payout,created_at,round_hash,server_seed FROM games WHERE user_id=? ORDER BY id DESC LIMIT ?', (int(user_id),int(limit))).fetchall()]


def get_payment_history(user_id:int, limit:int=10):
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid=_pg_user_id(c,user_id); rows=c.execute('SELECT id,%s::bigint AS user_id,invoice_id,amount_usdt,amount_rub,status,EXTRACT(EPOCH FROM created_at)::bigint AS created_at,EXTRACT(EPOCH FROM paid_at)::bigint AS paid_at FROM bot_payments WHERE user_id=%s ORDER BY id DESC LIMIT %s',(int(user_id),uid,int(limit))).fetchall(); return [dict(r) for r in rows]
    with _LOCK, _sqlite_conn() as c: return [dict(r) for r in c.execute('SELECT id,user_id,invoice_id,amount_usdt,amount_rub,status,created_at,paid_at FROM payments WHERE user_id=? ORDER BY id DESC LIMIT ?', (int(user_id),int(limit))).fetchall()]


def create_payment(user_id:int, invoice_id:int, amount_usdt:float, amount_rub:int, status:str='active')->dict:
    ensure_user(user_id)
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid=_pg_user_id(c,user_id)
            row=c.execute('''INSERT INTO bot_payments(user_id,invoice_id,amount_usdt,amount_rub,status) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(invoice_id) DO UPDATE SET status=EXCLUDED.status RETURNING id,user_id,invoice_id,amount_usdt,amount_rub,status,EXTRACT(EPOCH FROM created_at)::bigint AS created_at,EXTRACT(EPOCH FROM paid_at)::bigint AS paid_at''',(uid,invoice_id,amount_usdt,amount_rub,status)).fetchone(); return dict(row)
    with _LOCK, _sqlite_conn() as c:
        now=int(time.time()); c.execute('INSERT INTO payments(user_id,invoice_id,amount_usdt,amount_rub,status,created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(invoice_id) DO UPDATE SET status=excluded.status',(int(user_id),invoice_id,amount_usdt,amount_rub,status,now)); return dict(c.execute('SELECT * FROM payments WHERE invoice_id=?',(invoice_id,)).fetchone())


def mark_payment_paid(invoice_id:int)->Optional[dict]:
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            row=c.execute('SELECT * FROM bot_payments WHERE invoice_id=%s FOR UPDATE',(invoice_id,)).fetchone()
            if not row: return None
            if row['status'] == 'paid': return dict(row)
            c.execute("UPDATE bot_payments SET status='paid',paid_at=NOW() WHERE invoice_id=%s",(invoice_id,))
            c.execute('INSERT INTO "LedgerEntry" ("userId","amount","reason") VALUES (%s,%s,%s)',(row['user_id'],row['amount_rub'],'crypto_pay_deposit'))
            row=c.execute('SELECT * FROM bot_payments WHERE invoice_id=%s',(invoice_id,)).fetchone(); return dict(row)
    with _LOCK, _sqlite_conn() as c:
        row=c.execute('SELECT * FROM payments WHERE invoice_id=?',(invoice_id,)).fetchone()
        if not row:return None
        if row['status']=='paid':return dict(row)
        now=int(time.time()); c.execute("UPDATE payments SET status='paid',paid_at=? WHERE invoice_id=?",(now,invoice_id)); c.execute('UPDATE users SET balance_rub=balance_rub+?,updated_at=? WHERE user_id=?',(int(row['amount_rub']),now,int(row['user_id']))); return dict(c.execute('SELECT * FROM payments WHERE invoice_id=?',(invoice_id,)).fetchone())


def create_withdrawal(user_id:int, amount_rub:int, payout_details:str):
    amount_rub=int(amount_rub)
    if amount_rub<=0 or not str(payout_details).strip(): return None
    if not subtract_balance(user_id, amount_rub, 'withdrawal_reserve'): return None
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid=_pg_user_id(c,user_id)
            row=c.execute('INSERT INTO bot_withdrawals(user_id,amount_rub,payout_details,status) VALUES (%s,%s,%s,%s) RETURNING id,user_id,amount_rub,payout_details,status,EXTRACT(EPOCH FROM created_at)::bigint AS created_at,EXTRACT(EPOCH FROM updated_at)::bigint AS updated_at',(uid,amount_rub,payout_details.strip(),'pending')).fetchone(); return dict(row)
    with _LOCK, _sqlite_conn() as c:
        now=int(time.time()); cur=c.execute('INSERT INTO withdrawals(user_id,amount_rub,payout_details,status,created_at,updated_at) VALUES (?,?,?,?,?,?)',(int(user_id),amount_rub,payout_details.strip(),'pending',now,now)); return dict(c.execute('SELECT * FROM withdrawals WHERE id=?',(cur.lastrowid,)).fetchone())


def get_withdrawal(withdrawal_id:int):
    if _is_pg():
        rows=_rows_pg('SELECT id,user_id,amount_rub,payout_details,status,EXTRACT(EPOCH FROM created_at)::bigint AS created_at,EXTRACT(EPOCH FROM updated_at)::bigint AS updated_at FROM bot_withdrawals WHERE id=%s',(withdrawal_id,)); return rows[0] if rows else None
    with _LOCK,_sqlite_conn() as c: row=c.execute('SELECT * FROM withdrawals WHERE id=?',(withdrawal_id,)).fetchone(); return dict(row) if row else None


def get_pending_withdrawals(limit:int=20):
    if _is_pg(): return _rows_pg('SELECT w.id,u."telegramId" AS user_id,u.username,w.amount_rub,w.payout_details,w.status,EXTRACT(EPOCH FROM w.created_at)::bigint AS created_at FROM bot_withdrawals w JOIN "User" u ON u.id=w.user_id WHERE w.status=\'pending\' ORDER BY w.id ASC LIMIT %s',(limit,))
    with _LOCK,_sqlite_conn() as c:return [dict(r) for r in c.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id ASC LIMIT ?",(limit,)).fetchall()]


def get_withdrawal_history(user_id:int, limit:int=20):
    if _is_pg():
        with _LOCK,_pg_conn() as c:
            uid=_pg_user_id(c,user_id); return [dict(r) for r in c.execute('SELECT id,%s::bigint AS user_id,amount_rub,payout_details,status,EXTRACT(EPOCH FROM created_at)::bigint AS created_at,EXTRACT(EPOCH FROM updated_at)::bigint AS updated_at FROM bot_withdrawals WHERE user_id=%s ORDER BY id DESC LIMIT %s',(int(user_id),uid,limit)).fetchall()]
    with _LOCK,_sqlite_conn() as c:return [dict(r) for r in c.execute('SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT ?',(int(user_id),limit)).fetchall()]


def approve_withdrawal(withdrawal_id:int):
    if _is_pg():
        with _LOCK,_pg_conn() as c:
            row=c.execute("UPDATE bot_withdrawals SET status='approved',updated_at=NOW() WHERE id=%s AND status='pending' RETURNING *",(withdrawal_id,)).fetchone(); return dict(row) if row else None
    with _LOCK,_sqlite_conn() as c:
        now=int(time.time()); cur=c.execute("UPDATE withdrawals SET status='approved',updated_at=? WHERE id=? AND status='pending'",(now,withdrawal_id)); row=c.execute('SELECT * FROM withdrawals WHERE id=?',(withdrawal_id,)).fetchone(); return dict(row) if cur.rowcount else None


def reject_withdrawal(withdrawal_id:int):
    row=get_withdrawal(withdrawal_id)
    if not row or row['status'] not in ('pending','approved'): return None
    # Reserved balance is returned to the common application ledger.
    tg=int(row['user_id'])
    change_balance(tg,int(row['amount_rub']),'withdrawal_rejected_refund')
    if _is_pg():
        with _LOCK,_pg_conn() as c:
            c.execute("UPDATE bot_withdrawals SET status='rejected',updated_at=NOW() WHERE id=%s",(withdrawal_id,)); return get_withdrawal(withdrawal_id)
    with _LOCK,_sqlite_conn() as c:
        now=int(time.time()); c.execute("UPDATE withdrawals SET status='rejected',updated_at=? WHERE id=?",(now,withdrawal_id)); return get_withdrawal(withdrawal_id)


def complete_withdrawal(withdrawal_id:int):
    if _is_pg():
        with _LOCK,_pg_conn() as c:
            row=c.execute("UPDATE bot_withdrawals SET status='paid',updated_at=NOW() WHERE id=%s AND status='approved' RETURNING *",(withdrawal_id,)).fetchone(); return dict(row) if row else None
    with _LOCK,_sqlite_conn() as c:
        now=int(time.time()); cur=c.execute("UPDATE withdrawals SET status='paid',updated_at=? WHERE id=? AND status='approved'",(now,withdrawal_id)); row=c.execute('SELECT * FROM withdrawals WHERE id=?',(withdrawal_id,)).fetchone(); return dict(row) if cur.rowcount else None


def log_event(user_id:int|None, action:str, details:str='')->None:
    if _is_pg():
        with _LOCK,_pg_conn() as c:
            uid=_pg_user_id(c,user_id) if user_id is not None else None
            c.execute('INSERT INTO bot_audit_logs(user_id,action,details) VALUES (%s,%s,%s)',(uid,str(action),str(details))); return
    with _LOCK,_sqlite_conn() as c:c.execute('INSERT INTO audit_logs(user_id,action,details,created_at) VALUES (?,?,?,?)',(None if user_id is None else int(user_id),str(action),str(details),int(time.time())))


def get_audit_logs(limit:int=50):
    if _is_pg(): return _rows_pg('SELECT l.id,COALESCE(u."telegramId",\'\') AS user_id,u.username,l.action,l.details,EXTRACT(EPOCH FROM l.created_at)::bigint AS created_at FROM bot_audit_logs l LEFT JOIN "User" u ON u.id=l.user_id ORDER BY l.id DESC LIMIT %s',(limit,))
    with _LOCK,_sqlite_conn() as c:return [dict(r) for r in c.execute('SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?',(limit,)).fetchall()]


def get_all_users(limit:int=100):
    if _is_pg(): return _rows_pg('''SELECT u.id AS app_user_id,u."telegramId" AS user_id,u.username,u."createdAt" AS created_at,u."lastBet" AS last_bet,COALESCE((SELECT SUM(l."amount") FROM "LedgerEntry" l WHERE l."userId"=u.id),0) AS balance FROM "User" u ORDER BY u."createdAt" DESC LIMIT %s''',(limit,))
    with _LOCK,_sqlite_conn() as c:return [dict(r) for r in c.execute('SELECT user_id,balance_rub,created_at,updated_at FROM users ORDER BY updated_at DESC LIMIT ?',(limit,)).fetchall()]


def get_all_payments(limit:int=50):
    if _is_pg(): return _rows_pg('SELECT p.id,u."telegramId" AS user_id,u.username,p.invoice_id,p.amount_usdt,p.amount_rub,p.status,EXTRACT(EPOCH FROM p.created_at)::bigint AS created_at,EXTRACT(EPOCH FROM p.paid_at)::bigint AS paid_at FROM bot_payments p JOIN "User" u ON u.id=p.user_id ORDER BY p.id DESC LIMIT %s',(limit,))
    with _LOCK,_sqlite_conn() as c:return [dict(r) for r in c.execute('SELECT * FROM payments ORDER BY id DESC LIMIT ?',(limit,)).fetchall()]


def get_user_ledger(telegram_id: int, limit: int = 100):
    if _is_pg():
        with _LOCK, _pg_conn() as c:
            uid = _pg_user_id(c, telegram_id)
            rows = c.execute('SELECT l.id,l."amount" AS amount,l."reason" AS reason,EXTRACT(EPOCH FROM l."createdAt")::bigint AS created_at FROM "LedgerEntry" l WHERE l."userId"=%s ORDER BY l.id DESC LIMIT %s', (uid, int(limit))).fetchall()
            return [dict(r) for r in rows]
    return []


def get_ledger_activity(limit: int = 200):
    if _is_pg():
        return _rows_pg('SELECT l.id,u."telegramId" AS user_id,u.username,l."amount" AS amount,l."reason" AS reason,EXTRACT(EPOCH FROM l."createdAt")::bigint AS created_at FROM "LedgerEntry" l JOIN "User" u ON u.id=l."userId" ORDER BY l.id DESC LIMIT %s', (int(limit),))
    with _LOCK, _sqlite_conn() as c:
        return [dict(r) for r in c.execute("SELECT id,user_id,balance_rub AS amount,'legacy' AS reason,created_at FROM users ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]


def get_user_profile(telegram_id:int):
    if _is_pg():
        with _LOCK,_pg_conn() as c:
            row=c.execute('''SELECT u.id,u."telegramId" AS telegram_id,u.username,u."createdAt" AS created_at,COALESCE((SELECT SUM(l."amount") FROM "LedgerEntry" l WHERE l."userId"=u.id),0) AS balance FROM "User" u WHERE u."telegramId"=%s''',(str(telegram_id),)).fetchone();
            if not row:return None
            profile=dict(row); profile['balance']=float(profile['balance'] or 0); profile['stats']=get_user_stats(telegram_id); return profile
    return {'telegram_id':telegram_id,'balance':get_balance(telegram_id),'stats':get_user_stats(telegram_id)}
