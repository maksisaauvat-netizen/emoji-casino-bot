# Telegram Bot — reference version + Mini App synchronization

## What changed

The Telegram bot is now the primary place for the games shown in the supplied reference video. The existing Mini App source is intentionally not modified by this project.

### Games in the bot

- Mines
- Tower
- КНБ
- Keno
- Plinko
- Even
- Сектор
- Дуэль
- Больше-Меньше
- Hi-Lo
- Пенальти
- Blackjack
- Baccarat

The bot keeps server-side game results and uses the existing provably-fair round hash mechanism.

## Shared database

Set `DATABASE_URL` to the **same PostgreSQL connection string used by the Mini App API**.

The bot then uses the application's existing tables:

- `User`
- `LedgerEntry`

Therefore:

- Telegram ID is the same user identity in both systems.
- Username is synchronized into `User.username`.
- Balance is read from `LedgerEntry` — there is no second bot balance.
- Admin balance changes made from the Mini App are visible in the bot.
- Balance changes made from the bot are visible in the Mini App.

The bot creates only its own additional tables in the same database:

- `bot_games`
- `bot_payments`
- `bot_withdrawals`
- `bot_audit_logs`

No Mini App source file is required to be changed for this synchronization.

## Admin panel

The Telegram bot admin panel mirrors the Mini App admin capabilities:

- users list
- individual player profile
- Telegram ID / Mini App User ID / username
- current shared balance
- last Ledger operations
- balance credit/debit
- global Ledger activity
- audit logs
- payments
- withdrawals

Use the same `ADMIN_TELEGRAM_IDS` value as the Mini App API. `ADMIN_IDS` remains supported for backwards compatibility.

## Run

```bash
pip install -r requirements.txt
python bot.py
```

The first startup with `DATABASE_URL` creates the bot-owned tables automatically.
