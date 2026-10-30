-- Persist each hourly IST competition slot so restarts cannot duplicate it,
-- while allowing a new hourly competition even if an earlier one is still running.
ALTER TABLE club_competitions ADD COLUMN schedule_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS club_competitions_level_schedule_unique
    ON club_competitions(business_level, schedule_key);
