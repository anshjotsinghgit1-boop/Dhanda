# EMPIRE CENTURY

A text-first Telegram empire simulator built with Python, aiogram 3 and PostgreSQL.

## Core game loop
- Start with 1,000 cash and build a business through 54 levels.
- Collect passive income (maximum 8 hours per collection) and reinvest in upgrades.
- Every season lasts exactly seven days. Settlement snapshots the Fosbu ranking, resets temporary cash/business progress and employee relationships, and preserves reputation and eligible permanent assets.
- Gold exchange: 1 gram costs 1,000 cash and contributes 10 net worth.
- Collectible assets add catalog net-worth value and can be bought from the asset shop.
- Stocks can be bought and sold using the current market quote; stock value contributes to net worth.
- Industrial buildings generate reputation when settled and unlock at selected business levels.
- Clubs support creation, joining and treasury donations.
- Business wars compare net worth, with asset/stock/cash tie-breakers; battle determination affects score.
- Board of Directors recruiting unlocks at level 7. A boss starts with three employee slots; VIP level 5 adds two. Recruiting requires the target to accept. Employees pay a 5% share of eligible collected income to their boss.
- Top 50 season finishers are marked for permanent reward eligibility and receive a unique permanent reward asset.

## Group mining wars
- In any Telegram group, use `/miningwar 3` or `/miningwar 5` to open the group's only active mining war.
- Players register for Team 1 or Team 2 with inline buttons. Each player must first use `/start` with the bot.
- Teams can have multiple applicants; when the creator presses **FIGHT**, the highest-net-worth 3 or 5 applicants on each side qualify. Combined selected-player net worth decides the winner, with top individual net worth and reputation as tie-breakers.
- Use `/miningstatus` to refresh the group board. The creator can cancel the lobby before the fight.

## Commands
- `/start`, `/empire`, `/collect`, `/ranking`
- `/assetshop`, `/buyasset sports_car`, `/inventory`
- `/gold buy 2`, `/gold sell 1`
- `/stocks`, `/stock buy ECOR 10`, `/stock sell ECOR 2`
- `/industry`, `/buildindustry workshop`
- `/club`, `/club create Empire Crew | EC`, `/club join EC`, `/donate 1000`
- `/hire TELEGRAM_ID`, `/hireaccept CHALLENGE_ID`, `/war TELEGRAM_ID`
- `/help`

## Setup (when ready)
1. Create a Telegram bot with BotFather.
2. Create a PostgreSQL database.
3. Apply `schema.sql`, then `migrations/002_seasons.sql`, `migrations/003_full_economy.sql`, `migrations/004_employees_market.sql`, and `migrations/005_group_mining_wars.sql`, in order.
4. Set `BOT_TOKEN` and `DATABASE_URL` in the runtime environment.
5. Install requirements and run `python -m app`.

Do not run the bot until all migrations are applied. Keep credentials out of Git. This project is actively being built; live database and Telegram behavior still need staging tests before public launch.
