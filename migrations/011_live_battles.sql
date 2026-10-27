-- Live, server-authoritative club battle series and mining team rounds.
CREATE TABLE IF NOT EXISTS club_battle_series (
  id INTEGER PRIMARY KEY,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  opponent_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  match_number SMALLINT NOT NULL CHECK(match_number IN (1,2)),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','won','lost')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(player_id, match_number),
  CHECK(player_id <> opponent_id)
);
CREATE TABLE IF NOT EXISTS club_live_matches (
  id INTEGER PRIMARY KEY,
  player_a BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  player_b BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  round_number SMALLINT NOT NULL DEFAULT 1 CHECK(round_number BETWEEN 1 AND 3),
  wins_a SMALLINT NOT NULL DEFAULT 0,
  wins_b SMALLINT NOT NULL DEFAULT 0,
  deadline_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '15 seconds'),
  layout_a TEXT NOT NULL,
  layout_b TEXT NOT NULL,
  picked_a INTEGER,
  picked_b INTEGER,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','finished')),
  winner_id BIGINT REFERENCES players(telegram_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  CHECK(player_a <> player_b)
);
CREATE TABLE IF NOT EXISTS club_live_rounds (
  match_id BIGINT NOT NULL REFERENCES club_live_matches(id) ON DELETE CASCADE,
  round_number SMALLINT NOT NULL,
  player_a_kind TEXT,
  player_b_kind TEXT,
  winner_id BIGINT REFERENCES players(telegram_id),
  PRIMARY KEY(match_id,round_number)
);
CREATE TABLE IF NOT EXISTS mining_war_matchups (
  id INTEGER PRIMARY KEY,
  war_id BIGINT NOT NULL REFERENCES group_mining_wars(id) ON DELETE CASCADE,
  matchup_number SMALLINT NOT NULL CHECK(matchup_number BETWEEN 1 AND 4),
  team_a_wins SMALLINT NOT NULL DEFAULT 0,
  team_b_wins SMALLINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','finished')),
  deadline_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '15 seconds'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(war_id,matchup_number)
);
