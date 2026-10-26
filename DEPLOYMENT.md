# Local Termux run guide

This project is configured to use a local SQLite file for the current Termux build. No PostgreSQL server or hosted database is required.

1. Install Termux packages: `pkg install python git`
2. In the repository: `python -m venv .venv && source .venv/bin/activate`
3. Install dependencies: `python -m pip install -r requirements.txt`
4. Copy and edit environment settings: `cp .env.example .env && nano .env`
5. Set `BOT_TOKEN` from BotFather. Keep it secret.
6. Run: `python -m app`

The database file is created at `data/dhanda.sqlite3` automatically. Back up that file to preserve local game progress. Android battery/background restrictions can stop Termux and therefore stop the bot.

The SQLite adapter is a compatibility conversion; test the bot on-device before relying on all game modules.
