import sqlite3
from pathlib import Path


DB_PATH = Path("casino.db")


# =========================================================
# CONNECTION
# =========================================================

def get_connection():
    connection = sqlite3.connect(DB_PATH)

    connection.row_factory = sqlite3.Row

    return connection


# =========================================================
# INIT DATABASE
# =========================================================

def init_db():

    connection = get_connection()

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

    connection.commit()

    connection.close()


# =========================================================
# USER
# =========================================================

def ensure_user(user_id: int):

    connection = get_connection()

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

    connection.close()


# =========================================================
# BALANCE
# =========================================================

def get_balance(user_id: int) -> int:

    connection = get_connection()

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

        balance = 1000

    else:

        balance = row["balance"]

    connection.close()

    return balance


def change_balance(
    user_id: int,
    amount: int
) -> int:

    ensure_user(user_id)

    connection = get_connection()

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

    connection.commit()

    row = connection.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    balance = row["balance"]

    connection.close()

    return balance


def subtract_balance(
    user_id: int,
    amount: int
) -> bool:

    ensure_user(user_id)

    connection = get_connection()

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

    connection.commit()

    success = cursor.rowcount == 1

    connection.close()

    return success


# =========================================================
# USER STATS
# =========================================================

def get_user_stats(user_id: int):

    ensure_user(user_id)

    connection = get_connection()

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

    connection.close()

    return dict(row)


# =========================================================
# RECORD GAME
# =========================================================

def record_game(
    user_id: int,
    game: str,
    stake: int,
    result: str,
    multiplier: float = 0,
    payout: int = 0
):

    ensure_user(user_id)

    connection = get_connection()

    # -----------------------------------------
    # USER STATISTICS
    # -----------------------------------------

    games_played = 1

    wins = 1 if result == "win" else 0

    losses = 1 if result == "loss" else 0

    connection.execute(
        """
        UPDATE users
        SET
            games_played = games_played + ?,
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
            games_played,
            wins,
            losses,
            stake,
            payout if result == "win" else 0,
            payout if result == "win" else 0,
            user_id
        )
    )

    # -----------------------------------------
    # GAME HISTORY
    # -----------------------------------------

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

    connection.close()


# =========================================================
# GAME HISTORY
# =========================================================

def get_game_history(
    user_id: int,
    limit: int = 10
):

    ensure_user(user_id)

    connection = get_connection()

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

    connection.close()

    return [
        dict(row)
        for row in rows
    ]
