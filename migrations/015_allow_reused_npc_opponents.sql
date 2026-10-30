-- NPCs can face multiple human players in the same competition; each human still gets
-- exactly one match in slot 1 and one in slot 2.
DROP TABLE IF EXISTS club_competition_matches_new;
CREATE TABLE club_competition_matches_new (
 id INTEGER PRIMARY KEY,
 competition_id BIGINT NOT NULL REFERENCES club_competitions(id) ON DELETE CASCADE,
 player_a BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
 player_b BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
 match_number SMALLINT NOT NULL CHECK(match_number IN (1,2)),
 round_number SMALLINT NOT NULL DEFAULT 1 CHECK(round_number BETWEEN 1 AND 3),
 wins_a SMALLINT NOT NULL DEFAULT 0,
 wins_b SMALLINT NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','finished')),
 winner_id BIGINT REFERENCES players(telegram_id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 finished_at TIMESTAMPTZ,
 layout_a TEXT,
 layout_b TEXT,
 picked_a INTEGER,
 picked_b INTEGER,
 deadline_at TIMESTAMPTZ,
 CHECK(player_a<>player_b),
 UNIQUE(competition_id,player_a,match_number)
);
INSERT INTO club_competition_matches_new
 (id,competition_id,player_a,player_b,match_number,round_number,wins_a,wins_b,status,winner_id,
  created_at,finished_at,layout_a,layout_b,picked_a,picked_b,deadline_at)
 SELECT id,competition_id,player_a,player_b,match_number,round_number,wins_a,wins_b,status,winner_id,
  created_at,finished_at,layout_a,layout_b,picked_a,picked_b,deadline_at
 FROM club_competition_matches;
DROP TABLE club_competition_matches;
ALTER TABLE club_competition_matches_new RENAME TO club_competition_matches;
CREATE INDEX IF NOT EXISTS club_competition_matches_active_idx ON club_competition_matches(status,competition_id);
