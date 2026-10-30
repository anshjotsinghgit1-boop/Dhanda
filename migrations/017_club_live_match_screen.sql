-- Persist the single editable Telegram match screen and countdown state.
ALTER TABLE club_competition_matches ADD COLUMN message_id BIGINT;
ALTER TABLE club_competition_matches ADD COLUMN countdown_mark INTEGER NOT NULL DEFAULT -1;
