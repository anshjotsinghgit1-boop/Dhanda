# EMPIRE CENTURY

A text-first Telegram empire simulator built with Python, aiogram 3, and **local SQLite storage**. The bot can run directly in Termux on Android; it does not require PostgreSQL or a hosted database.

## Run locally in Termux

1. Install Python and Git in Termux: `pkg install python git`.
2. Clone or update this repository, then enter its folder.
3. Create and activate a virtual environment:
   ```sh
   python -m venv .venv
   source .venv/bin/activate
   ```
4. Install Python dependencies:
   ```sh
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
5. Create your private environment file:
   ```sh
   cp .env.example .env
   nano .env
   ```
   Replace `BOT_TOKEN=replace_me` with the token from BotFather. Keep this file private and never commit it.
6. Start the bot:
   ```sh
   python -m app
   ```

The local database is created automatically at `data/dhanda.sqlite3`. The `data/` directory is local runtime data and should not be committed. Keep Termux allowed to run in the background if you want the bot to stay online; Android may still stop background processes.

## Core game loop

- Start with 1,000 cash and build a business through 54 levels.
- Collect passive income (maximum 8 hours per collection) and reinvest in upgrades.
- Every season lasts seven days. Settlement snapshots rankings and resets temporary cash/business progress.
- Gold exchange, collectible assets, stocks, industrial buildings, clubs, employee challenges, business wars, and season rewards are part of the game.
- Employees pay a 5% share of eligible collected income to their boss.

## Group mining

- Group chats are reserved for mining; use the bot in private chat for the rest of the game.
- Use `/miningwar` in a group to register it for scheduled mining events.
- Timed mining events and the club battle queue are an initial MVP and still need live end-to-end testing.

## Commands

- `/start`, `/empire`, `/collect`, `/ranking`
- `/assetshop`, `/buyasset sports_car`, `/inventory`
- `/gold buy 2`, `/gold sell 1`
- `/stocks`, `/stock buy ECOR 10`, `/stock sell ECOR 2`
- `/industry`, `/buildindustry workshop`
- `/club`, `/club create Empire Crew | EC`, `/club join EC`, `/donate 1000`
- `/hire TELEGRAM_ID`, `/hireaccept CHALLENGE_ID`, `/war TELEGRAM_ID`
- `/help`

## Local data and limitations

- The SQLite database lives at `data/dhanda.sqlite3`; back it up if you want to preserve game data.
- SQLite schema setup runs automatically on startup from `schema.sql` and `migrations/*.sql`.
- This is a local compatibility conversion from PostgreSQL SQL to SQLite, so first startup and each gameplay feature must be tested on-device. Do not assume every advanced SQL path works until it has been exercised.
- The bot token belongs only in your local `.env`, never in GitHub.
