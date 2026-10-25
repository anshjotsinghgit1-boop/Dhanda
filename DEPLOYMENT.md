# Deployment checklist

## Required services
- A Telegram bot token from BotFather
- PostgreSQL database
- A host that can run a persistent Python process or Docker container

## Database setup
Run `schema.sql` against the target database once, using a database administrator or migration tool. Keep the database URL private.

## Environment
Set `BOT_TOKEN` and `DATABASE_URL` from your host's secret/environment-variable settings. Do not upload `.env` to GitHub.

## Run
Install `requirements.txt`, then run `python -m app`. For Docker, build the image and pass the two environment variables at runtime.

## Before public launch
- Add a migration system instead of relying on a one-time SQL file.
- Implement and test seven-day season settlement and reset rules.
- Add rate limiting, error monitoring, database backups, and admin tools.
- Test concurrent income collection and employee hiring with multiple users.
- Complete and test assets, gold exchange, all 54 level balance values, clubs, battles, permanent rewards, and the industrial park.

The current repository is a development MVP; do not treat it as a finished production game yet.
