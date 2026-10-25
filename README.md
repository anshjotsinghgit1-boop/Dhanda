# Dhanda — Empire Century Telegram Bot

A text-only Telegram business empire game MVP built with Python, aiogram 3, and PostgreSQL.

## Features in this starter
- Telegram `/start` onboarding and inline-button menu
- Persistent player profiles and cash balances
- Passive business production with an 8-hour offline cap
- Collect income and upgrade your business
- Employee income sharing rule: 5% of eligible employee income is deducted and credited to their boss
- Seven-day season metadata and a foundation for seasonal rankings

This is an MVP foundation, not a production-ready clone. Season settlement, all 54 business levels, clubs, wars, assets, gold exchange, industrial park, and permanent reward inventory need further implementation and testing.

## Run locally
1. Use Python 3.11+ and PostgreSQL.
2. Create a database and apply `schema.sql`.
3. Copy `.env.example` to `.env` and fill in `BOT_TOKEN` and `DATABASE_URL`.
4. Install dependencies: `pip install -r requirements.txt`.
5. Start the bot: `python -m app`.

Never commit real bot tokens or database credentials.
