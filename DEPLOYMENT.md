# Deployment checklist

## Required services
- A Telegram bot token from BotFather
- PostgreSQL database
- A host that can run a persistent Python process or Docker container

## Database setup — when you are ready
Apply these files in order:
1. `schema.sql`
2. `migrations/002_seasons.sql`
3. `migrations/003_full_economy.sql`
4. `migrations/004_employees_market.sql`

The bot now imports the season, asset, club, employee, stock and business-war modules. Do not start it against a database that is missing the corresponding tables and columns. SQL has been committed to GitHub but has **not** been run against your PostgreSQL database.

## Environment
Set `BOT_TOKEN` and `DATABASE_URL` from your host's secret/environment-variable settings. Do not upload `.env` to GitHub.

## Run
Install `requirements.txt`, then run `python -m app`. For Docker, build the image and pass the two environment variables at runtime.

## Current mechanics
- Seven-day season scheduler snapshots net-worth rankings, marks the top 50 eligible, grants a unique permanent inventory reward, resets cash to 1,000 and business level to 1, and preserves reputation and permanent assets.
- Net worth includes cash, stocks, gold grams × 10 and asset value; permanent asset valuation is capped at 25,000 in aggregate.
- Passive income is capped at eight hours. Employee share is 5% of eligible collected income.
- Gold exchange, asset shop/inventory, industrial buildings, stock trades, clubs/treasury donations, recruitment challenges and business-war resolution are wired into Telegram commands.

## Still required before public launch
- Run all migrations against a staging PostgreSQL database and exercise every command end-to-end.
- Add a real migration runner, rate limits, monitoring, backups, and admin tooling.
- Complete timed club matchmaking, level-specific economic balancing, full stock price updates, business-war protection/cooldowns, freeze/unfreeze mechanics, and industrial park season pausing/resume.
- Add automated unit/integration tests and confirm GitHub Actions succeeds.
- Review the reward economy and edge cases before public release.

This is a development build. The code is committed to `main`, but live Telegram and PostgreSQL behavior has not been verified.
