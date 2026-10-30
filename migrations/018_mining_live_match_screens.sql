-- Persist one editable group message for each side of a mining matchup.
ALTER TABLE mining_team_war_opponents ADD COLUMN main_message_id BIGINT;
ALTER TABLE mining_team_war_opponents ADD COLUMN opponent_message_id BIGINT;
ALTER TABLE mining_team_war_opponents ADD COLUMN countdown_mark INTEGER NOT NULL DEFAULT -1;
