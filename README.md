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

## Group mining
- Group chats are reserved for mining only; all other empire commands and non-mining buttons are blocked in groups. Use the bot in a private chat for the rest of the game.
- Use `/miningwar` to open the group's one active mining lobby. Everyone joins the same pool with the **JOIN MINING** inline button.
- Press **START MINING** when ready. With 3–4 applicants, the top 3 by net worth are selected; with 5 or more, the top 5 are selected. At least 3 applicants are required.
- Net worth is calculated from cash, stocks, gold, and asset valuation. Refresh and cancel are available as mining-only inline buttons.
- Each player must first use `/start` with the bot in a private chat so their game profile exists.

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
