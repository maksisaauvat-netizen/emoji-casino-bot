import sqlite3
from pathlib import Path


DB_PATH = Path("casino.db")


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_connection()

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 1000
        )
        """
    )

    connection.commit()
    connection.close()


def get_balance(user_id: int) -> int:
    connection = get_connection()

    row = connection.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if row is None:
        connection.execute(
            "INSERT INTO users (user_id, balance) VALUES (?, ?)",
            (user_id, 1000)
        )
        connection.commit()
        balance = 1000
    else:
        balance = row["balance"]

    connection.close()
    return balance


def change_balance(user_id: int, amount: int) -> int:
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO users (user_id, balance)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET balance = balance + excluded.balance
        """,
        (user_id, amount)
    )

    connection.commit()

    row = connection.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    balance = row["balance"]

    connection.close()
    return balance


def subtract_balance(user_id: int, amount: int) -> bool:
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE users
        SET balance = balance - ?
        WHERE user_id = ?
          AND balance >= ?
        """,
        (amount, user_id, amount)
    )

    connection.commit()

    success = cursor.rowcount == 1

    connection.close()
    return success
