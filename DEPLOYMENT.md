# Deployment checklist

## Required services
- A Telegram bot token from BotFather
- PostgreSQL database
- A host that can run a persistent Python process or Docker container

## Database setup
1. Run `schema.sql` against the target database once.
2. Run `migrations/002_seasons.sql` after `schema.sql`; the bot's season scheduler requires these tables.
3. Keep the database URL private.

## Environment
Set `BOT_TOKEN` and `DATABASE_URL` from your host's secret/environment-variable settings. Do not upload `.env` to GitHub.

## Run
Install `requirements.txt`, then run `python -m app`. For Docker, build the image and pass the two environment variables at runtime.

## Current season rollover
The bot checks the seven-day season deadline every 30 seconds. It snapshots a cash-based provisional ranking, records top-50 reward eligibility, resets cash to 1,000 and business level to 1, and preserves reputation. The full ranking must later include gold, stocks and asset valuation before this can be considered final game logic. See `SEASONS.md`.

## Before public launch
- Add a versioned migration runner instead of relying on manual SQL application.
- Test seven-day settlement and reset rules against a staging database.
- Add rate limiting, error monitoring, database backups, and admin tools.
- Test concurrent income collection and employee hiring with multiple users.
- Complete and test assets, gold exchange, all 54 level balance values, clubs, battles, permanent rewards, and the industrial park.

The current repository is a development MVP; do not treat it as a finished production game yet.
