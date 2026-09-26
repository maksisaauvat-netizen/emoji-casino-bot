# Telegram Bot — reference games + shared Mini App data

## Scope

This package changes **only the Telegram bot**. The Mini App source from `lobby.zip` is not modified and is not included here.

The bot is connected to the same PostgreSQL database used by the Mini App API.

## Shared application data

When `DATABASE_URL` points to the same PostgreSQL database as the Mini App, the bot uses the existing application tables:

- `User`
- `LedgerEntry`

This means the following are shared:

- Telegram identity (`User.telegramId`)
- username (`User.username`)
- application user ID (`User.id`)
- profile creation date
- `lastBet`
- balance (sum of `LedgerEntry.amount`)
- admin balance adjustments
- all ledger history

The bot does **not** maintain a second production balance.

The bot creates only these bot-owned tables in the same database:

- `bot_games`
- `bot_payments`
- `bot_withdrawals`
- `bot_audit_logs`

## Reference games in the bot

- 💣 Mines
- 🗼 Tower
- ✊ КНБ
- 🔢 Keno
- 🃏 Blackjack
- 🃏 Baccarat
- 🔻 Plinko
- ⚖️ Even
- 🎡 Сектор
- ⚔️ Дуэль
- ↕️ Больше-Меньше
- 🏹 Hi-Lo
- 🥅 Пенальти

Game results are generated on the server and use the bot's provably-fair round seed/hash mechanism. Stakes and payouts go through the shared application ledger.

## Admin panel in the bot

The bot admin panel includes the capabilities present in the Mini App admin panel:

- players list
- player profile
- App User ID
- Telegram ID
- username
- current shared balance
- ledger history for a player
- credit/debit balance
- global ledger activity

It also exposes the bot's additional operational sections:

- audit logs
- payments
- withdrawals

Use the same administrator Telegram IDs as the API:

```env
ADMIN_TELEGRAM_IDS=123456789,987654321
```

`ADMIN_IDS` remains supported for compatibility.

## Production configuration

The critical setting is:

```env
DATABASE_URL=<the exact same PostgreSQL URL used by the Mini App API>
```

Do not point the bot at a separate production database if synchronization is required.

Other required settings remain the bot's normal settings, including:

```env
BOT_TOKEN=...
```

## Run

```bash
pip install -r requirements.txt
python bot.py
```

On first startup with `DATABASE_URL`, the bot creates its own `bot_*` tables automatically. It does not alter the Mini App Prisma schema.

## Verification

Before production, verify with one test Telegram account:

1. Change balance in the Mini App admin.
2. Open the bot profile and confirm the same balance.
3. Place a bot game bet and confirm the Ledger balance changed.
4. Open the Mini App and confirm the same new balance.
5. Change username in Telegram and reopen the bot; `User.username` should update.
6. Open the Mini App admin and confirm the same user/profile and Ledger entries.
