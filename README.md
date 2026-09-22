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
