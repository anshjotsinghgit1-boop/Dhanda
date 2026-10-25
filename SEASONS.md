# Season rollover migration

Apply `migrations/002_seasons.sql` to the PostgreSQL database after `schema.sql` and before starting the bot with the season scheduler.

## Current rollover behavior
- Checks the active season every 30 seconds; the database controls the deadline.
- Takes a one-time final snapshot ordered by cash, then business level, then reputation.
- Records the top 50 as eligible and creates a permanent reward inventory record for each eligible player.
- Marks the old season settled and starts the next seven-day season.
- Resets temporary cash to 1,000 and business level to 1; preserves reputation.
- Clears employee relationships at rollover.

## Important limitations
The complete game rules include net worth from cash, gold, stocks and assets. Those systems are not implemented yet, so this MVP's season ranking uses cash as a temporary placeholder, not the final Fosbu ranking. The permanent reward row is an inventory placeholder; replace its label/code with the actual reward catalogue before public launch. If the game should start at zero cash rather than 1,000 after each reset, change the configured reset amount intentionally.
