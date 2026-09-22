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
- The bot supports `/upgrade`, amount input, inline choice buttons, and a local `assets/upgrader_spin.gif` animation.
- Every game round receives a SHA-256 **round hash** before the result. After completion the server seed is revealed so the user can verify `SHA256(server_seed) == round_hash`.
- Round metadata is stored in `games` and returned in history. Existing SQLite databases are migrated automatically.
- The existing `REAL_ECONOMY` switch remains unchanged; keep it disabled while testing.


## Что добавлено в этой версии

- `/start` теперь отправляет исходное изображение Resonant Casino из `assets/start.jpg` и не меняет его при навигации по inline-кнопкам.
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
- Upgrader в боте продолжает использовать GIF из `assets/upgrader_spin.gif`.

### Важно перед запуском

1. Заполните `.env`: `BOT_TOKEN`, `BASE_URL`, `WEBHOOK_SECRET`, `ADMIN_IDS`.
2. Для Crypto Pay задайте `CRYPTOBOT_TOKEN`.
3. `START_IMAGE=./assets/start.jpg` уже добавлен.
4. `HELP_USERNAME=narotan7`.
5. Для реальной экономики оставляйте `REAL_ECONOMY=false`, пока не проведете тестирование и не проверите юридические/платежные требования.
6. В текущей реализации пополнение через Crypto Pay создается как invoice. Вывод создает заявку и резервирует средства в БД; фактическая выплата требует обработки администратором. Автоматическая Crypto Pay payout-схема отдельно не включена.

## Обновления в этой версии
- ADMIN PANEL в профиле Mini App: выдача/снятие баланса и просмотр audit-логов.
- ADMIN PANEL в профиле Telegram-бота: выдача/снятие баланса, пользователи, платежи, выводы и логи.
- Экран «Играть» в боте изменён на `🎰 GAMES` с кнопкой «🎰 • Играть в приложении» и отдельными режимами.
- `SLOTS` работает непосредственно в боте: ставка 10–5000 ₽, подтверждение, 3 символа и заданная таблица выплат.
- `MINES` работает непосредственно в боте: ставка 10–5000 ₽, выбор 2–24 мин, поле 5×5, cashout.
- Добавлен `🎲 DICE`: один/два броска и заданные варианты ставок, лимит 10–5000 ₽.
- Для игровых раундов бота сохраняются SHA-256 hash и server seed в истории.


## Resonant Casino v3 — схема

Версия собрана по последней схеме интерфейса:

- Telegram Bot: `/start` → Profile / Wallet / Bonuses / Games / Help.
- Games: SLOTS, MINES, DICE, CRASH, x50, Upgrader.
- SLOTS и MINES работают непосредственно в боте; DICE также полностью реализован в боте.
- Mini App: главное лобби с баннером Resonant Casino, балансом, `+`, аватаром, боковым меню и нижней навигацией.
- Mini App Profile содержит статистику, истории игр/пополнений/выводов и ADMIN PANEL для администраторов.
- ADMIN PANEL в боте и Mini App используют общую SQLite БД и audit logs.
- `/assets/start.jpg` подключён как стартовый/лобби-баннер.
- Проверьте `ADMIN_IDS`, `BOT_TOKEN`, `BASE_URL`, `WEBAPP_URL`, `CRYPTOBOT_TOKEN` перед запуском.
