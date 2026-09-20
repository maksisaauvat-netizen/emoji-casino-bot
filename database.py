import sqlite3
from pathlib import Path


DB_PATH = Path("casino.db")


def get_connection():
    connection = sqlite3.connect(
        DB_PATH,
        timeout=15.0
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA journal_mode=WAL"
    )

    connection.execute(
        "PRAGMA busy_timeout=15000"
    )

    connection.execute(
        "PRAGMA synchronous=NORMAL"
    )

    return connection


def init_db():
    connection = get_connection()

    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                games_played INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                total_bet INTEGER NOT NULL DEFAULT 0,
                total_won INTEGER NOT NULL DEFAULT 0,
                biggest_win INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                stake INTEGER NOT NULL DEFAULT 0,
                result TEXT NOT NULL,
                multiplier REAL NOT NULL DEFAULT 0,
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                amount_usdt REAL NOT NULL DEFAULT 0,
                amount_rub INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'paid',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_rub INTEGER NOT NULL,
                method TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                admin_id INTEGER
            )
            """
        )

        # -------------------------------------------------
        # ВАЖНО:
        # Старые пользователи сохраняют свои реальные балансы.
        #
        # Новые пользователи теперь создаются с 0 ₽.
        # Стартовые 1000 ₽ выдаются только через ensure_user()
        # при первом /start.
        # -------------------------------------------------

        connection.commit()

    finally:
        connection.close()


def ensure_user(user_id: int) -> bool:
    """
    Создаёт пользователя только один раз.

    Возвращает:
        True  -> пользователь создан впервые
        False -> пользователь уже существовал
    """

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO users (
                user_id,
                balance
            )
            VALUES (?, 1000)
            """,
            (user_id,)
        )

        connection.commit()

        return cursor.rowcount == 1

    finally:
        connection.close()


def user_exists(user_id: int) -> bool:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        return row is not None

    finally:
        connection.close()


def get_balance(user_id: int) -> int:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if row is None:
            return 0

        return row["balance"]

    finally:
        connection.close()


def change_balance(
    user_id: int,
    amount: int
) -> int:

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                user_id,
                balance
            )
            VALUES (?, 0)
            """,
            (user_id,)
        )

        connection.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        row = connection.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        connection.commit()

        return row["balance"]

    finally:
        connection.close()


def subtract_balance(
    user_id: int,
    amount: int
) -> bool:

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
              AND balance >= ?
            """,
            (
                amount,
                user_id,
                amount
            )
        )

        success = cursor.rowcount == 1

        connection.commit()

        return success

    finally:
        connection.close()


def get_user_stats(user_id: int):

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                user_id,
                balance,
                games_played,
                wins,
                losses,
                total_bet,
                total_won,
                biggest_win
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if row is None:
            return {
                "user_id": user_id,
                "balance": 0,
                "games_played": 0,
                "wins": 0,
                "losses": 0,
                "total_bet": 0,
                "total_won": 0,
                "biggest_win": 0
            }

        return dict(row)

    finally:
        connection.close()


def record_game(
    user_id: int,
    game: str,
    stake: int,
    result: str,
    multiplier: float = 0,
    payout: int = 0
):

    connection = get_connection()

    try:
        wins = (
            1
            if result == "win"
            else 0
        )

        losses = (
            1
            if result == "loss"
            else 0
        )

        win_amount = (
            payout
            if result == "win"
            else 0
        )

        connection.execute(
            """
            UPDATE users
            SET
                games_played = games_played + 1,
                wins = wins + ?,
                losses = losses + ?,
                total_bet = total_bet + ?,
                total_won = total_won + ?,
                biggest_win = MAX(
                    biggest_win,
                    ?
                )
            WHERE user_id = ?
            """,
            (
                wins,
                losses,
                stake,
                win_amount,
                win_amount,
                user_id
            )
        )

        connection.execute(
            """
            INSERT INTO game_history (
                user_id,
                game,
                stake,
                result,
                multiplier,
                payout
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                game,
                stake,
                result,
                multiplier,
                payout
            )
        )

        connection.commit()

    finally:
        connection.close()


def get_game_history(
    user_id: int,
    limit: int = 10
):

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                game,
                stake,
                result,
                multiplier,
                payout,
                created_at
            FROM game_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_id,
                limit
            )
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


# =========================================================
# PAYMENTS
# =========================================================

def payment_exists(
    invoice_id: int
) -> bool:

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT id
            FROM payments
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        ).fetchone()

        return row is not None

    finally:
        connection.close()


def add_payment(
    invoice_id: int,
    user_id: int,
    amount_usdt: float,
    amount_rub: int
) -> bool:

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO payments (
                invoice_id,
                user_id,
                amount_usdt,
                amount_rub,
                status
            )
            VALUES (?, ?, ?, ?, 'paid')
            """,
            (
                invoice_id,
                user_id,
                amount_usdt,
                amount_rub
            )
        )

        connection.commit()

        return cursor.rowcount == 1

    finally:
        connection.close()


def process_payment(
    invoice_id: int,
    user_id: int,
    amount_usdt: float,
    amount_rub: int
):

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        existing = connection.execute(
            """
            SELECT id
            FROM payments
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        ).fetchone()

        if existing is not None:
            connection.rollback()
            return None

        connection.execute(
            """
            INSERT INTO payments (
                invoice_id,
                user_id,
                amount_usdt,
                amount_rub,
                status
            )
            VALUES (?, ?, ?, ?, 'paid')
            """,
            (
                invoice_id,
                user_id,
                amount_usdt,
                amount_rub
            )
        )

        # Пользователь должен существовать.
        # Если нет — создаём с 0, НЕ с 1000.
        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                user_id,
                balance
            )
            VALUES (?, 0)
            """,
            (user_id,)
        )

        connection.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (
                amount_rub,
                user_id
            )
        )

        row = connection.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        new_balance = row["balance"]

        connection.commit()

        return {
            "user_id": user_id,
            "invoice_id": invoice_id,
            "amount_usdt": amount_usdt,
            "amount_rub": amount_rub,
            "balance": new_balance
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_payment(
    invoice_id: int
):

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                invoice_id,
                user_id,
                amount_usdt,
                amount_rub,
                status,
                created_at
            FROM payments
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def get_payment_history(
    user_id: int,
    limit: int = 20
):

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                invoice_id,
                amount_usdt,
                amount_rub,
                status,
                created_at
            FROM payments
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_id,
                limit
            )
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


# =========================================================
# WITHDRAWALS
# =========================================================

def create_withdrawal(
    user_id: int,
    amount_rub: int,
    method: str,
    destination: str
):

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        # Проверяем баланс внутри той же транзакции.
        cursor = connection.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
              AND balance >= ?
            """,
            (
                amount_rub,
                user_id,
                amount_rub
            )
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        cursor = connection.execute(
            """
            INSERT INTO withdrawals (
                user_id,
                amount_rub,
                method,
                destination,
                status
            )
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                user_id,
                amount_rub,
                method,
                destination
            )
        )

        withdrawal_id = cursor.lastrowid

        connection.commit()

        return {
            "id": withdrawal_id,
            "user_id": user_id,
            "amount_rub": amount_rub,
            "method": method,
            "destination": destination,
            "status": "pending"
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_withdrawal(
    withdrawal_id: int
):

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                method,
                destination,
                status,
                created_at,
                processed_at,
                admin_id
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def get_withdrawals(
    status: str = "pending",
    limit: int = 20
):

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                method,
                destination,
                status,
                created_at,
                processed_at,
                admin_id
            FROM withdrawals
            WHERE status = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (
                status,
                limit
            )
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def approve_withdrawal(
    withdrawal_id: int,
    admin_id: int
):

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                status
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        if row is None:
            connection.rollback()
            return None

        if row["status"] != "pending":
            connection.rollback()
            return None

        connection.execute(
            """
            UPDATE withdrawals
            SET
                status = 'approved',
                processed_at = CURRENT_TIMESTAMP,
                admin_id = ?
            WHERE id = ?
              AND status = 'pending'
            """,
            (
                admin_id,
                withdrawal_id
            )
        )

        connection.commit()

        return dict(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def reject_withdrawal(
    withdrawal_id: int,
    admin_id: int
):

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                status
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        if row is None:
            connection.rollback()
            return None

        if row["status"] != "pending":
            connection.rollback()
            return None

        # Возвращаем деньги пользователю.
        connection.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (
                row["amount_rub"],
                row["user_id"]
            )
        )

        connection.execute(
            """
            UPDATE withdrawals
            SET
                status = 'rejected',
                processed_at = CURRENT_TIMESTAMP,
                admin_id = ?
            WHERE id = ?
              AND status = 'pending'
            """,
            (
                admin_id,
                withdrawal_id
            )
        )

        connection.commit()

        return dict(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_user_withdrawals(
    user_id: int,
    limit: int = 20
):

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                amount_rub,
                method,
                destination,
                status,
                created_at,
                processed_at
            FROM withdrawals
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_id,
                limit
            )
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()
