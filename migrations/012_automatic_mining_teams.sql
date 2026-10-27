-- Automatic cross-group mining teams and four-opponent wars.
CREATE TABLE IF NOT EXISTS mining_teams (
  id BIGSERIAL PRIMARY KEY,
  event_id BIGINT NOT NULL UNIQUE REFERENCES timed_mining_events(id) ON DELETE CASCADE,
  chat_id BIGINT NOT NULL,
  team_size SMALLINT NOT NULL CHECK(team_size IN (3,5)),
  status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','assigned','finished')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS mining_team_players (
  team_id BIGINT NOT NULL REFERENCES mining_teams(id) ON DELETE CASCADE,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  roster_position SMALLINT NOT NULL,
  base_worth BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY(team_id,player_id),
  UNIQUE(team_id,roster_position)
);
CREATE TABLE IF NOT EXISTS mining_team_wars (
  id BIGSERIAL PRIMARY KEY,
  main_team_id BIGINT NOT NULL REFERENCES mining_teams(id),
  status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','active','won','lost','cancelled')),
  current_matchup SMALLINT NOT NULL DEFAULT 1 CHECK(current_matchup BETWEEN 1 AND 4),
  main_wins SMALLINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS mining_team_war_opponents (
  war_id BIGINT NOT NULL REFERENCES mining_team_wars(id) ON DELETE CASCADE,
  matchup_number SMALLINT NOT NULL CHECK(matchup_number BETWEEN 1 AND 4),
  opponent_team_id BIGINT NOT NULL REFERENCES mining_teams(id),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','won','lost','draw')),
  deadline_at TIMESTAMPTZ,
  PRIMARY KEY(war_id,matchup_number),
  UNIQUE(war_id,opponent_team_id)
);
CREATE TABLE IF NOT EXISTS mining_team_picks (
  war_id BIGINT NOT NULL,
  matchup_number SMALLINT NOT NULL,
  player_id BIGINT NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
  box_number SMALLINT NOT NULL CHECK(box_number BETWEEN 1 AND 9),
  box_kind TEXT NOT NULL CHECK(box_kind IN ('money','normal','empty')),
  temporary_worth BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(war_id,matchup_number,player_id),
  FOREIGN KEY(war_id,matchup_number) REFERENCES mining_team_war_opponents(war_id,matchup_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS mining_teams_waiting_idx ON mining_teams(status,team_size,created_at);
CREATE INDEX IF NOT EXISTS mining_team_wars_active_idx ON mining_team_wars(status);
