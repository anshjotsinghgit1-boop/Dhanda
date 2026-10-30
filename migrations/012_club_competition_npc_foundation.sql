-- Foundation for level-specific system clubs and persistent NPC game characters.
ALTER TABLE players ADD COLUMN is_npc BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE players ADD COLUMN npc_key TEXT;
ALTER TABLE players ADD COLUMN club_completed_level INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS players_npc_key_unique ON players(npc_key) WHERE npc_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS players_level_npc_idx ON players(business_level,is_npc);

CREATE TABLE IF NOT EXISTS club_competitions (
 id INTEGER PRIMARY KEY, business_level INTEGER NOT NULL CHECK(business_level BETWEEN 12 AND 53),
 status TEXT NOT NULL DEFAULT 'joining' CHECK(status IN ('joining','running','finished','cancelled')),
 opens_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), closes_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS club_competitions_status_idx ON club_competitions(status,closes_at);
CREATE TABLE IF NOT EXISTS club_competition_participants (
 competition_id BIGINT NOT NULL REFERENCES club_competitions(id) ON DELETE CASCADE,
 player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
 joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), completed_matches INTEGER NOT NULL DEFAULT 0,
 matches_won INTEGER NOT NULL DEFAULT 0, passed BOOLEAN,
 PRIMARY KEY(competition_id,player_id)
);
CREATE INDEX IF NOT EXISTS club_competition_participants_player_idx ON club_competition_participants(player_id,competition_id);
CREATE TABLE IF NOT EXISTS club_competition_matches (
 id INTEGER PRIMARY KEY, competition_id BIGINT NOT NULL REFERENCES club_competitions(id) ON DELETE CASCADE,
 player_a BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
 player_b BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
 match_number SMALLINT NOT NULL CHECK(match_number IN (1,2)),
 round_number SMALLINT NOT NULL DEFAULT 1 CHECK(round_number BETWEEN 1 AND 3),
 wins_a SMALLINT NOT NULL DEFAULT 0, wins_b SMALLINT NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','finished')),
 winner_id BIGINT REFERENCES players(telegram_id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 finished_at TIMESTAMPTZ, CHECK(player_a<>player_b),
 UNIQUE(competition_id,player_a,match_number), UNIQUE(competition_id,player_b,match_number)
);
CREATE INDEX IF NOT EXISTS club_competition_matches_active_idx ON club_competition_matches(status,competition_id);
