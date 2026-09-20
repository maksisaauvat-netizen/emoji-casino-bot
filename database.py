import sqlite3
from pathlib import Path


# =========================================================
# CONFIG
# =========================================================

DB_PATH = Path("casino.db")


# =========================================================
# CONNECTION
# =========================================================

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


# =========================================================
# INIT DATABASE
# =========================================================

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
                payout_details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
            """
        )

        connection.commit()

    finally:
        connection.close()


# =========================================================
# USERS
# =========================================================

def ensure_user(user_id: int):
    """
    Создаёт пользователя только если его ещё нет.

    Новый пользователь получает 0 ₽.
    Существующий баланс не изменяется.
    """

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

        connection.commit()

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


# =========================================================
# BALANCE
# =========================================================

def get_balance(user_id: int) -> int:
    """
    Только читает баланс.
    Ничего автоматически не начисляет.
    """

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

        return int(row["balance"])

    finally:
        connection.close()


def change_balance(
    user_id: int,
    amount: int
) -> int:
    """
    Изменяет баланс пользователя на amount.

    amount > 0  -> пополнение
    amount < 0  -> списание
    """

    connection = get_connection()

    try:
        cursor = connection.execute(
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

        if cursor.rowcount != 1:
            connection.rollback()

            raise ValueError(
                "User is not registered"
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

        return int(row["balance"])

    finally:
        connection.close()


def subtract_balance(
    user_id: int,
    amount: int
) -> bool:
    """
    Безопасно списывает сумму только если
    на балансе достаточно средств.
    """

    if amount <= 0:
        return False

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


# =========================================================
# USER STATS
# =========================================================

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
                "biggest_win": 0,
            }

        return dict(row)

    finally:
        connection.close()


# =========================================================
# GAMES
# =========================================================

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
        user = connection.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if user is None:
            raise ValueError(
                "User is not registered"
            )

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
    """
    Атомарно:
    1. Проверяет пользователя.
    2. Проверяет, не обработан ли invoice.
    3. Записывает платёж.
    4. Начисляет деньги.
    """

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        user = connection.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if user is None:
            connection.rollback()

            raise ValueError(
                "User is not registered"
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

        new_balance = int(
            row["balance"]
        )

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
    payout_details: str
):
    """
    Создаёт заявку на вывод.

    Деньги сразу резервируются:
    баланс пользователя уменьшается,
    а сумма записывается в withdrawals.

    При отклонении заявки деньги возвращаются.
    """

    if amount_rub <= 0:
        raise ValueError(
            "Withdrawal amount must be positive"
        )

    if not payout_details.strip():
        raise ValueError(
            "Payout details are required"
        )

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        user = connection.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if user is None:
            connection.rollback()

            raise ValueError(
                "User is not registered"
            )

        if user["balance"] < amount_rub:
            connection.rollback()
            return None

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
                payout_details,
                status
            )
            VALUES (?, ?, ?, 'pending')
            """,
            (
                user_id,
                amount_rub,
                payout_details.strip()
            )
        )

        withdrawal_id = cursor.lastrowid

        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                payout_details,
                status,
                admin_note,
                created_at,
                processed_at
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        connection.commit()

        return dict(row)

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
                payout_details,
                status,
                admin_note,
                created_at,
                processed_at
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


def get_pending_withdrawals(
    limit: int = 20
):
    """
    Возвращает только заявки со статусом pending.
    """

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                payout_details,
                status,
                admin_note,
                created_at,
                processed_at
            FROM withdrawals
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        connection.close()


def approve_withdrawal(
    withdrawal_id: int
):
    """
    pending -> approved

    Деньги уже зарезервированы.
    При подтверждении баланс не меняется.
    """

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = connection.execute(
            """
            UPDATE withdrawals
            SET
                status = 'approved',
                processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'pending'
            """,
            (withdrawal_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                payout_details,
                status,
                admin_note,
                created_at,
                processed_at
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        connection.commit()

        return dict(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def complete_withdrawal(
    withdrawal_id: int
):
    """
    approved -> paid

    Используется после того,
    как администратор реально отправил выплату.

    Баланс пользователя НЕ меняется,
    потому что деньги были списаны
    при создании заявки.
    """

    connection = get_connection()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = connection.execute(
            """
            UPDATE withdrawals
            SET
                status = 'paid',
                processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'approved'
            """,
            (withdrawal_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

        row = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                payout_details,
                status,
                admin_note,
                created_at,
                processed_at
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        connection.commit()

        return dict(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def reject_withdrawal(
    withdrawal_id: int
):
    """
    pending -> rejected

    Зарезервированные деньги
    возвращаются пользователю.
    """

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

        cursor = connection.execute(
            """
            UPDATE withdrawals
            SET
                status = 'rejected',
                processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'pending'
            """,
            (withdrawal_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return None

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

        result = connection.execute(
            """
            SELECT
                id,
                user_id,
                amount_rub,
                payout_details,
                status,
                admin_note,
                created_at,
                processed_at
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,)
        ).fetchone()

        connection.commit()

        return dict(result)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_withdrawal_history(
    user_id: int,
    limit: int = 20
):
    """
    История выводов конкретного пользователя.
    """

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                amount_rub,
                payout_details,
                status,
                admin_note,
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
