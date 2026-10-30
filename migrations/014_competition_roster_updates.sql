-- Track the four timed roster snapshots during a competition lobby.
ALTER TABLE club_competitions ADD COLUMN roster_updates_sent INTEGER NOT NULL DEFAULT 0;
