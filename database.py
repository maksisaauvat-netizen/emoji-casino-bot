import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.getenv("DATABASE_PATH", str(Path(__file__).with_name("resonant.sqlite3"))))
_LOCK = threading.RLock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance_rub INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            stake INTEGER NOT NULL,
            result TEXT NOT NULL,
            multiplier REAL NOT NULL DEFAULT 0,
            payout INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL UNIQUE,
            amount_usdt REAL NOT NULL,
            amount_rub INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            paid_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_rub INTEGER NOT NULL,
            payout_details TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_games_user ON games(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id, id DESC);
        """)


def ensure_user(user_id: int) -> None:
    now = int(time.time())
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO users(user_id, created_at, updated_at) VALUES (?, ?, ?)",
            (int(user_id), now, now),
        )


def get_balance(user_id: int) -> int:
    ensure_user(user_id)
    with _LOCK, _conn() as c:
        row = c.execute("SELECT balance_rub FROM users WHERE user_id=?", (int(user_id),)).fetchone()
        return int(row[0] if row else 0)


def change_balance(user_id: int, amount: int) -> int:
    ensure_user(user_id)
    with _LOCK, _conn() as c:
        c.execute("UPDATE users SET balance_rub=balance_rub+?, updated_at=? WHERE user_id=?", (int(amount), int(time.time()), int(user_id)))
        row = c.execute("SELECT balance_rub FROM users WHERE user_id=?", (int(user_id),)).fetchone()
        return int(row[0])


def subtract_balance(user_id: int, amount: int) -> bool:
    amount = int(amount)
    if amount <= 0:
        return False
    ensure_user(user_id)
    with _LOCK, _conn() as c:
        cur = c.execute(
            "UPDATE users SET balance_rub=balance_rub-?, updated_at=? WHERE user_id=? AND balance_rub>=?",
            (amount, int(time.time()), int(user_id), amount),
        )
        return cur.rowcount == 1


def get_user_stats(user_id: int) -> dict:
    ensure_user(user_id)
    with _LOCK, _conn() as c:
        row = c.execute("""
            SELECT COUNT(*) games,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) wins,
                   COALESCE(SUM(stake),0) turnover,
                   COALESCE(SUM(payout),0) payouts
            FROM games WHERE user_id=?
        """, (int(user_id),)).fetchone()
        games = int(row[0] or 0)
        wins = int(row[1] or 0)
        return {
            "games": games,
            "wins": wins,
            "losses": games - wins,
            "winrate": round((wins / games * 100) if games else 0, 1),
            "turnover": int(row[2] or 0),
            "payouts": int(row[3] or 0),
        }


def record_game(user_id: int, game: str, stake: int, result: str, multiplier: float, payout: int) -> int:
    with _LOCK, _conn() as c:
        cur = c.execute(
            "INSERT INTO games(user_id,game,stake,result,multiplier,payout,created_at) VALUES (?,?,?,?,?,?,?)",
            (int(user_id), str(game), int(stake), str(result), float(multiplier), int(payout), int(time.time())),
        )
        return int(cur.lastrowid)


def _rows(sql: str, args=()):
    with _LOCK, _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def get_game_history(user_id: int, limit: int = 10):
    return _rows("SELECT id,user_id,game,stake,result,multiplier,payout,created_at FROM games WHERE user_id=? ORDER BY id DESC LIMIT ?", (int(user_id), int(limit)))


def get_payment_history(user_id: int, limit: int = 10):
    return _rows("SELECT id,user_id,invoice_id,amount_usdt,amount_rub,status,created_at,paid_at FROM payments WHERE user_id=? ORDER BY id DESC LIMIT ?", (int(user_id), int(limit)))


def create_payment(user_id: int, invoice_id: int, amount_usdt: float, amount_rub: int, status: str = "active") -> dict:
    now = int(time.time())
    with _LOCK, _conn() as c:
        c.execute("""
            INSERT INTO payments(user_id,invoice_id,amount_usdt,amount_rub,status,created_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(invoice_id) DO UPDATE SET status=excluded.status
        """, (int(user_id), int(invoice_id), float(amount_usdt), int(amount_rub), status, now))
        row = c.execute("SELECT * FROM payments WHERE invoice_id=?", (int(invoice_id),)).fetchone()
        return dict(row)


def mark_payment_paid(invoice_id: int) -> Optional[dict]:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM payments WHERE invoice_id=?", (int(invoice_id),)).fetchone()
        if not row:
            return None
        if row["status"] == "paid":
            return dict(row)
        now = int(time.time())
        c.execute("UPDATE payments SET status='paid', paid_at=? WHERE invoice_id=?", (now, int(invoice_id)))
        c.execute("UPDATE users SET balance_rub=balance_rub+?, updated_at=? WHERE user_id=?", (int(row["amount_rub"]), now, int(row["user_id"])))
        row = c.execute("SELECT * FROM payments WHERE invoice_id=?", (int(invoice_id),)).fetchone()
        return dict(row)


def get_withdrawal(withdrawal_id: int):
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM withdrawals WHERE id=?", (int(withdrawal_id),)).fetchone()
        return dict(row) if row else None


def get_pending_withdrawals(limit: int = 20):
    return _rows("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id ASC LIMIT ?", (int(limit),))


def get_withdrawal_history(user_id: int, limit: int = 20):
    return _rows("SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT ?", (int(user_id), int(limit)))


def create_withdrawal(user_id: int, amount_rub: int, payout_details: str):
    amount_rub = int(amount_rub)
    if amount_rub <= 0 or not str(payout_details).strip():
        return None
    ensure_user(user_id)
    now = int(time.time())
    with _LOCK, _conn() as c:
        cur = c.execute("UPDATE users SET balance_rub=balance_rub-?, updated_at=? WHERE user_id=? AND balance_rub>=?", (amount_rub, now, int(user_id), amount_rub))
        if cur.rowcount != 1:
            return None
        cur = c.execute("INSERT INTO withdrawals(user_id,amount_rub,payout_details,status,created_at,updated_at) VALUES (?,?,?,?,?,?)", (int(user_id), amount_rub, str(payout_details).strip(), 'pending', now, now))
        row = c.execute("SELECT * FROM withdrawals WHERE id=?", (int(cur.lastrowid),)).fetchone()
        return dict(row)


def approve_withdrawal(withdrawal_id: int):
    now = int(time.time())
    with _LOCK, _conn() as c:
        cur = c.execute("UPDATE withdrawals SET status='approved', updated_at=? WHERE id=? AND status='pending'", (now, int(withdrawal_id)))
        if cur.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM withdrawals WHERE id=?", (int(withdrawal_id),)).fetchone()
        return dict(row)


def reject_withdrawal(withdrawal_id: int):
    now = int(time.time())
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM withdrawals WHERE id=?", (int(withdrawal_id),)).fetchone()
        if not row or row["status"] not in ("pending", "approved"):
            return None
        c.execute("UPDATE users SET balance_rub=balance_rub+?, updated_at=? WHERE user_id=?", (int(row["amount_rub"]), now, int(row["user_id"])))
        c.execute("UPDATE withdrawals SET status='rejected', updated_at=? WHERE id=?", (now, int(withdrawal_id)))
        row = c.execute("SELECT * FROM withdrawals WHERE id=?", (int(withdrawal_id),)).fetchone()
        return dict(row)


def complete_withdrawal(withdrawal_id: int):
    now = int(time.time())
    with _LOCK, _conn() as c:
        cur = c.execute("UPDATE withdrawals SET status='paid', updated_at=? WHERE id=? AND status='approved'", (now, int(withdrawal_id)))
        if cur.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM withdrawals WHERE id=?", (int(withdrawal_id),)).fetchone()
        return dict(row)
