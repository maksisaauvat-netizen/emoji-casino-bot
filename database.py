import sqlite3
from pathlib import Path


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

    # Разрешаем одновременное чтение во время записи.
    connection.execute("PRAGMA journal_mode=WAL")

    # SQLite будет ждать освобождения базы вместо
    # немедленного "database is locked".
    connection.execute("PRAGMA busy_timeout=15000")

    # Более безопасная синхронизация записи.
    connection.execute("PRAGMA synchronous=NORMAL")

    return connection


# =========================================================
# INIT DATABASE
# =========================================================

def init_db():
    connection = get_connection()

    try:

        # =================================================
        # USERS
        # =================================================

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 1000,

                games_played INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,

                total_bet INTEGER NOT NULL DEFAULT 0,
                total_won INTEGER NOT NULL DEFAULT 0,

                biggest_win INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # =================================================
        # GAME HISTORY
        # =================================================

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

        # =================================================
        # PAYMENTS
        # =================================================

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

        connection.commit()

    finally:
        connection.close()


# =========================================================
# USERS
# =========================================================

def ensure_user(user_id: int):

    connection = get_connection()

    try:

        connection.execute(
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

            connection.execute(
                """
                INSERT INTO users (
                    user_id,
                    balance
                )
                VALUES (?, 1000)
                """,
                (user_id,)
            )

            connection.commit()

            return 1000

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
            VALUES (?, 1000)
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

        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                user_id,
                balance
            )
            VALUES (?, 1000)
            """,
            (user_id,)
        )

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
# USER STATISTICS
# =========================================================

def get_user_stats(user_id: int):

    connection = get_connection()

    try:

        connection.execute(
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

        return dict(row)

    finally:
        connection.close()


# =========================================================
# GAME HISTORY
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

        # Гарантируем наличие пользователя.
        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                user_id,
                balance
            )
            VALUES (?, 1000)
            """,
            (user_id,)
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

        connection.execute(
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
    Атомарно обрабатывает оплаченный invoice.

    Один invoice может быть зачислен только один раз.
    """

    connection = get_connection()

    try:

        # Ждём освобождения базы до 15 секунд.
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        # =================================================
        # ПРОВЕРЯЕМ ПОВТОРНЫЙ INVOICE
        # =================================================

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

        # =================================================
        # СОХРАНЯЕМ ПЛАТЁЖ
        # =================================================

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

        # =================================================
        # СОЗДАЁМ USER, ЕСЛИ ЕГО НЕТ
        # =================================================

        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                user_id,
                balance
            )
            VALUES (?, 1000)
            """,
            (user_id,)
        )

        # =================================================
        # НАЧИСЛЯЕМ БАЛАНС
        # =================================================

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

        # =================================================
        # ПОЛУЧАЕМ НОВЫЙ БАЛАНС
        # =================================================

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
