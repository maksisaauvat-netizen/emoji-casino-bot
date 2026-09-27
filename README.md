# Resonant Games — 5 modes

Версия Mini App без меню кейсов и без старых игровых режимов. Интерфейс SLOT и x50 переработан под визуальный стиль Resonant Casino по предоставленным записям экрана.

## Режимы

- SLOT
- x50
- CRASH
- Blackjack
- Mines

Сервер является источником истины: RNG и активное состояние игры находятся в `bot.py`, клиент не получает crash-point заранее.

## Запуск

1. Установить зависимости:
   `pip install -r requirements.txt`
2. Заполнить `.env`:
   - `BOT_TOKEN`
   - `BASE_URL`
   - `WEBAPP_URL`
   - `WEBHOOK_SECRET`
3. Запустить:
   `python bot.py`

## Важно

Механика x50 в этой версии сделана как классическое колесо с зонами x2/x3/x5/x50. Точные веса/сектора можно подогнать под фактическую механику Rakes после получения скриншотов/записи экрана.

CRASH использует серверный crash-point и серверную проверку cashout. Для production желательно вынести активные раунды в Redis/БД, чтобы состояние не терялось при рестарте процесса.


## UI v3

SLOT получил 5×3, 16 линий, последовательную остановку барабанов, подсветку выигрышных позиций, Wild/Scatter/Free Spins и раскрываемую таблицу выплат.

x50 получил дуговое колесо, 16-секундный countdown, четыре исхода x2/x3/x5/x50 и отдельную анимацию остановки.

Визуальные элементы переработаны под Resonant Casino; логотипы и защищённые ассеты исходного приложения не копируются.


## v4 — Upgrader + Provably Fair Round Hash

- Added **Upgrader** to the Mini App and Telegram bot.
- Presets: **x2 / x5 / x10**, **35% / 70%**, and custom **1–80%** chance.
- The Mini App uses an ice-blue win zone and an animated pointer.
- The bot supports `/upgrade`, amount input, inline choice buttons, and a local `upgrader_spin.gif` animation.
- Every game round receives a SHA-256 **round hash** before the result. After completion the server seed is revealed so the user can verify `SHA256(server_seed) == round_hash`.
- Round metadata is stored in `games` and returned in history. Existing SQLite databases are migrated automatically.
- The existing `REAL_ECONOMY` switch remains unchanged; keep it disabled while testing.


## Что добавлено в этой версии

- `/start` теперь отправляет исходное изображение Resonant Casino из `start.jpg` и не меняет его при навигации по inline-кнопкам.
- Бот-меню: `Профиль`, `Кошелек`, `Бонусы`, `Играть`, `Помощь`.
- Профиль с ID, балансом, играми, победами, поражениями, winrate, оборотом, выигрышами и MAX WIN.
- История игр, история пополнений/выводов и реферальный экран.
- `ADMIN PANEL` доступен только Telegram ID из `ADMIN_IDS`.
- В админ-панели доступны логи, пользователи, пополнения, заявки на вывод и изменение баланса.
- Mini App получил нижнюю навигацию: Меню / Главная / Кошелек / Бонусы / Профиль.
- Добавлены страницы профиля, кошелька и истории, а также боковое меню.
- Состояние баланса и статистики берется из общей SQLite БД, поэтому бот и Mini App используют одни данные.
- Добавлен `audit_logs` для синхронного логирования.
- Стартовый баннер приложения сделан в стиле Resonant Casino; логотип можно заменить позже.
- X50 расширен вариантом `💎 Diamond` с выбором 1 из 9 ячеек: x5 ×3, x7 ×3, x10 ×2, x25 ×1.
- CRASH получил визуальную ракету и 💥 при достижении серверного crash point.
- Для CRASH/Mines/Upgrader использован параметр house edge 2% (RTP 98% для этих математических схем).
- `Hash round` / server seed сохраняются и раскрываются после завершения раунда.
- Upgrader в боте продолжает использовать GIF из `upgrader_spin.gif`.

### Важно перед запуском

1. Заполните `.env`: `BOT_TOKEN`, `BASE_URL`, `WEBHOOK_SECRET`, `ADMIN_IDS`.
2. Для Crypto Pay задайте `CRYPTOBOT_TOKEN`.
3. `START_IMAGE=./start.jpg` уже добавлен.
4. `HELP_USERNAME=narotan7`.
5. Для production используйте `REAL_ECONOMY=true` только после проверки платежной/юридической конфигурации. Без `CRYPTOBOT_TOKEN` реальные платежи блокируются.
6. В текущей реализации пополнение через Crypto Pay создается как invoice. Вывод резервирует средства и выполняет Crypto Pay transfer с идемпотентным `spend_id`; незавершённые операции автоматически сверяются через `getTransfers`.

## Обновления в этой версии
- ADMIN PANEL в профиле Mini App: выдача/снятие баланса и просмотр audit-логов.
- ADMIN PANEL в профиле Telegram-бота: выдача/снятие баланса, пользователи, платежи, выводы и логи.
- Экран «Играть» в боте изменён на `🎰 GAMES` с кнопкой «🎰 • Играть в приложении» и отдельными режимами.
- `SLOTS` работает непосредственно в боте: ставка $0.10–$5000, подтверждение, 3 символа и заданная таблица выплат.
- `MINES` работает непосредственно в боте: ставка $0.10–$5000, выбор 2–24 мин, поле 5×5, cashout.
- Добавлен `🎲 DICE`: один/два броска и заданные варианты ставок, лимит $0.10–$5000.
- Для игровых раундов бота сохраняются SHA-256 hash и server seed в истории.


## Release candidate

- Единый USD Ledger с Mini App.
- Crypto Pay deposit/withdraw.
- Публичный лог ставок в игровом чате.
- Провайдерные операции идемпотентны и сверяются после сбоев.
- Минимальный депозит $0.10, минимальный вывод $1.00.
- Production требует `DATABASE_URL`, `BOT_TOKEN`, стабильный `WEBHOOK_SECRET`, `CRYPTOBOT_TOKEN`, `GAME_CHAT_ID` и `REQUIRED_CHANNEL_ID`.

## Images
The Mini App serves images directly from the project root. No `assets/` directory is required. Keep `start.jpg` and `upgrader_spin.gif` next to `bot.py`.


### Premium custom emoji
The bot uses Telegram custom emoji entities for the supplied IDs. The Mini App displays the same IDs through the `/custom-emoji/{id}` proxy; no `assets/` folder is required. Inline keyboard button labels keep ordinary Unicode emoji because Telegram does not support message entities inside button text.

## USD wallet + public game log

- The common wallet currency is **USD ($)** and the bot uses the same PostgreSQL `LedgerEntry` balance as the Mini App.
- CryptoBot / Crypto Pay is used for deposits in USDT at a 1:1 internal USD rate.
- Minimum deposit: **$0.10**.
- Minimum withdrawal: **$1.00**.
- With `CRYPTOBOT_AUTO_PAYOUT=true`, withdrawals are sent to the user's CryptoBot account via Crypto Pay transfer; failed payouts are refunded to the shared ledger.
- The public game-history chat is configured with `GAME_CHAT_ID` or by an admin running `/setlogchat` inside the target group.
- The bot displays the total number of users from the shared `User` table.
- Reference-game coefficients use a default **7.5% house edge** where the underlying probability is known; `HOUSE_EDGE` can be adjusted for the probability-based modes.

### CryptoBot setup

Create a Crypto Pay API token through `@CryptoBot`, put it into `CRYPTOBOT_TOKEN`, and make sure the bot account can use the configured Crypto Pay balance for transfers. Crypto Pay supports invoice-based crypto payments and transfers to users. See the official CryptoBot documentation for current API/limits. 
